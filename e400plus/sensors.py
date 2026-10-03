"""Read host sensors for the E400 matrix (Linux sysfs + psutil)."""

from __future__ import annotations

import glob
import os
import re
import threading
import time
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional

from .protocol import Metrics, ShowMask


@dataclass
class SensorReading:
    label: str
    path: str
    value: float
    unit: str = ""


def _read_float(path: str) -> Optional[float]:
    try:
        raw = Path(path).read_text().strip()
        return float(raw)
    except (OSError, ValueError):
        return None


def list_hwmon_temps() -> list[SensorReading]:
    out: list[SensorReading] = []
    for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = Path(hw, "name").read_text().strip() if Path(hw, "name").exists() else Path(hw).name
        for input_path in sorted(glob.glob(f"{hw}/temp*_input")):
            idx = re.search(r"temp(\d+)_input", input_path)
            n = idx.group(1) if idx else "?"
            label_path = f"{hw}/temp{n}_label"
            label = Path(label_path).read_text().strip() if Path(label_path).exists() else f"temp{n}"
            val = _read_float(input_path)
            if val is None:
                continue
            out.append(SensorReading(f"{name}/{label}", input_path, val / 1000.0, "C"))
    return out


def _pick_cpu_temp(temps: list[SensorReading], prefer: Optional[str] = None) -> float:
    if prefer:
        for t in temps:
            if prefer.lower() in t.label.lower() or prefer in t.path:
                return t.value
    # Prefer package / Tctl / CPU-ish labels.
    for key in ("tctl", "package", "cpu", "core"):
        for t in temps:
            if key in t.label.lower():
                return t.value
    return temps[0].value if temps else 0.0


def _pick_gpu_temp(temps: list[SensorReading], prefer: Optional[str] = None) -> float:
    if prefer:
        for t in temps:
            if prefer.lower() in t.label.lower() or prefer in t.path:
                return t.value
    for key in ("edge", "junction", "gpu", "amdgpu", "nouveau"):
        for t in temps:
            if key in t.label.lower() or key in t.path:
                return t.value
    return 0.0


def _cpu_freq_mhz() -> float:
    try:
        import psutil

        freq = psutil.cpu_freq()
        if freq and freq.current:
            return float(freq.current)
    except Exception:
        pass
    vals = []
    for p in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq"):
        v = _read_float(p)
        if v is not None:
            vals.append(v / 1000.0)  # kHz → MHz
    return sum(vals) / len(vals) if vals else 0.0


def _cpu_power_w() -> float:
    # Intel RAPL
    for energy in glob.glob("/sys/class/powercap/intel-rapl:0/energy_uj"):
        # instantaneous power needs a delta; skip for now and try hwmon
        break
    for path in glob.glob("/sys/class/hwmon/hwmon*/power*_input"):
        name = Path(path).parent.joinpath("name")
        chip = name.read_text().strip() if name.exists() else ""
        if chip in {"coretemp", "k10temp", "zenpower"}:
            continue
        v = _read_float(path)
        if v is not None and v > 0:
            return v / 1_000_000.0
    return 0.0


METRICS_CACHE_SECONDS = 1.0


def _collect_metrics(
    *,
    cpu_temp_sensor: Optional[str] = None,
    gpu_temp_sensor: Optional[str] = None,
) -> Metrics:
    import psutil

    temps = list_hwmon_temps()
    cpu_temp = _pick_cpu_temp(temps, cpu_temp_sensor)
    gpu_temp = _pick_gpu_temp(temps, gpu_temp_sensor)
    vm = psutil.virtual_memory()

    return Metrics(
        cpu_temp_c=cpu_temp,
        cpu_usage=float(psutil.cpu_percent(interval=0.05)),
        cpu_power_w=_cpu_power_w(),
        cpu_freq_mhz=_cpu_freq_mhz(),
        cpu_voltage=0.0,
        gpu_temp_c=gpu_temp,
        gpu_usage=0.0,
        gpu_power_w=0.0,
        gpu_freq_mhz=0.0,
        fan_rpm=0.0,
        water_rpm=0.0,
        ram_usage=float(vm.percent),
    )


class MetricsCache:
    """Cache a hardware metrics snapshot for a fixed duration.

    Frame settings such as temperature unit and display mask are intentionally
    applied after the lookup: they describe a frame, not a hardware sample.
    """

    def __init__(self, ttl_seconds: float = METRICS_CACHE_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._cached_at: float | None = None
        self._cached_key: tuple[Optional[str], Optional[str]] | None = None
        self._cached_metrics: Metrics | None = None

    def get(
        self,
        *,
        celsius: bool,
        show: ShowMask,
        cpu_temp_sensor: Optional[str],
        gpu_temp_sensor: Optional[str],
        ttl_seconds: float | None = None,
    ) -> Metrics:
        key = (cpu_temp_sensor, gpu_temp_sensor)
        now = time.monotonic()
        ttl = self.ttl_seconds if ttl_seconds is None else max(ttl_seconds, 0.0)
        with self._lock:
            if (
                self._cached_metrics is None
                or self._cached_key != key
                or self._cached_at is None
                or now - self._cached_at >= ttl
            ):
                self._cached_metrics = _collect_metrics(
                    cpu_temp_sensor=cpu_temp_sensor,
                    gpu_temp_sensor=gpu_temp_sensor,
                )
                self._cached_key = key
                # Start the next one-second window once sampling completes.
                self._cached_at = time.monotonic()

            # Callers can safely set per-frame fields without mutating the
            # cached snapshot used by the next frame.
            return replace(
                self._cached_metrics,
                celsius=celsius,
                show=show,
                when=datetime.now(),
            )


_metrics_cache = MetricsCache()


def collect_metrics(
    *,
    celsius: bool = True,
    show: ShowMask = ShowMask.DEFAULT,
    cpu_temp_sensor: Optional[str] = None,
    gpu_temp_sensor: Optional[str] = None,
    cache_seconds: float = METRICS_CACHE_SECONDS,
) -> Metrics:
    """Return host metrics, refreshing the snapshot after ``cache_seconds``."""
    return _metrics_cache.get(
        celsius=celsius,
        show=show,
        cpu_temp_sensor=cpu_temp_sensor,
        gpu_temp_sensor=gpu_temp_sensor,
        ttl_seconds=cache_seconds,
    )


def demo_metrics(tick: int = 0) -> Metrics:
    """Synthetic values for mock / UI preview."""
    base = 40 + (tick % 30)
    return Metrics(
        cpu_temp_c=base + 0.3,
        cpu_usage=35 + (tick % 50),
        cpu_power_w=65.4,
        cpu_freq_mhz=3800 + (tick % 200),
        cpu_voltage=1.21,
        gpu_temp_c=base - 5 + 0.7,
        gpu_usage=20 + (tick % 40),
        gpu_power_w=48.2,
        gpu_freq_mhz=1800,
        fan_rpm=1200 + tick * 3,
        water_rpm=0,
        ram_usage=42.0,
        celsius=True,
        show=ShowMask.DEFAULT,
    )
