"""Wire protocol for the darkFlash E400 / E400 Plus HID matrix display.

Recovered from the official Windows "darkFlash E400" app (CyUSB HID).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntFlag
from math import floor
from typing import Iterable

REPORT_PAYLOAD_LEN = 64
# Bytes [0]=0, [1]=1, [2]=2 identify a live stats frame; values follow.
HEADER = (0x00, 0x01, 0x02)
SHUTDOWN_CMD = 0x0F


class ShowMask(IntFlag):
    """Bitmask at SendValueArray[0x24] — which metrics the panel rotates."""

    NONE = 0
    CPU_TEMP = 1
    CPU_USAGE = 2
    GPU_TEMP = 4
    GPU_USAGE = 8
    DEFAULT = CPU_TEMP | CPU_USAGE | GPU_TEMP | GPU_USAGE


@dataclass
class Metrics:
    cpu_temp_c: float = 0.0
    cpu_usage: float = 0.0
    cpu_power_w: float = 0.0
    cpu_freq_mhz: float = 0.0
    cpu_voltage: float = 0.0
    gpu_temp_c: float = 0.0
    gpu_usage: float = 0.0
    gpu_power_w: float = 0.0
    gpu_freq_mhz: float = 0.0
    fan_rpm: float = 0.0
    water_rpm: float = 0.0
    ram_usage: float = 0.0
    celsius: bool = True
    show: ShowMask = ShowMask.DEFAULT
    when: datetime = field(default_factory=datetime.now)


def _split_int_frac(value: float) -> tuple[int, int]:
    whole = int(floor(value))
    # Avoid binary float noise so 0.70 → 70, not 69.
    frac = int(floor((value - whole) * 100.0 + 1e-6))
    return whole & 0xFF, frac & 0xFF


def _split_hundreds(value: float) -> tuple[int, int, int]:
    """Match vendor packing: lo2 = floor%100, frac*100, hundreds = floor//100."""
    whole = floor(value)
    hundreds = int(floor(whole / 100.0))
    lo2 = int(floor(whole % 100.0))
    frac = int(floor((value - whole) * 100.0 + 1e-6))
    return lo2 & 0xFF, frac & 0xFF, hundreds & 0xFF


def _split_freq(mhz: float) -> tuple[int, int]:
    whole = floor(mhz)
    return int(floor(whole / 100.0)) & 0xFF, int(floor(whole % 100.0)) & 0xFF


def build_value_array(m: Metrics) -> list[int]:
    """Build the 60-slot SendValueArray the Windows app pushes over HID."""
    arr = [0] * 60
    now = m.when

    cpu_i, cpu_f = _split_int_frac(m.cpu_temp_c if m.celsius else m.cpu_temp_c * 9 / 5 + 32)
    arr[0], arr[1] = cpu_i, cpu_f
    arr[2] = 0 if m.celsius else 1
    arr[3] = int(floor(m.cpu_usage)) & 0xFF

    cpu_lo, cpu_pf, cpu_hi = _split_hundreds(m.cpu_power_w)
    arr[4], arr[5], arr[0x1F] = cpu_lo, cpu_pf, cpu_hi

    arr[6], arr[7] = _split_freq(m.cpu_freq_mhz)

    # Vendor code drops the fractional volt and stores floor / floor*100;
    # the display expects integer + hundredths, so we send the sensible form.
    v_i, v_f = _split_int_frac(m.cpu_voltage)
    arr[8], arr[9] = v_i, v_f

    gpu_i, gpu_f = _split_int_frac(m.gpu_temp_c if m.celsius else m.gpu_temp_c * 9 / 5 + 32)
    arr[0x0A], arr[0x0B] = gpu_i, gpu_f
    arr[0x0C] = 0 if m.celsius else 1
    arr[0x0D] = int(floor(m.gpu_usage)) & 0xFF

    gpu_lo, gpu_pf, gpu_hi = _split_hundreds(m.gpu_power_w)
    arr[0x0E], arr[0x0F] = gpu_lo, gpu_pf
    # Vendor duplicates hundreds into 0x20..0x22.
    arr[0x20] = arr[0x21] = arr[0x22] = gpu_hi

    arr[0x10], arr[0x11] = _split_freq(m.gpu_freq_mhz)
    arr[0x12], arr[0x13] = _split_freq(m.fan_rpm)
    arr[0x14], arr[0x15] = _split_freq(m.water_rpm)

    year = f"{now.year:04d}"
    arr[0x16] = int(year[0:2])
    arr[0x17] = int(year[2:4])
    arr[0x18] = now.month
    arr[0x19] = now.day
    arr[0x1A] = now.hour
    arr[0x1B] = now.minute
    arr[0x1C] = now.second
    # Match .NET DayOfWeek: Sunday=0 … Saturday=6
    arr[0x1D] = (now.weekday() + 1) % 7
    arr[0x1E] = int(floor(m.ram_usage)) & 0xFF
    arr[0x24] = int(m.show) & 0xFF
    return arr


def build_stats_payload(m: Metrics) -> bytes:
    """64-byte HID payload (report ID is prepended by the transport)."""
    values = build_value_array(m)
    buf = bytearray(REPORT_PAYLOAD_LEN)
    buf[0], buf[1], buf[2] = HEADER
    for i, v in enumerate(values):
        buf[3 + i] = v & 0xFF
    return bytes(buf)


def build_shutdown_payload() -> bytes:
    """Tell the panel the host app is exiting (Windows FormClosing path)."""
    buf = bytearray(REPORT_PAYLOAD_LEN)
    buf[1] = SHUTDOWN_CMD
    return bytes(buf)


def describe_payload(payload: bytes | bytearray) -> str:
    if len(payload) < 3:
        return f"short payload ({len(payload)} bytes)"
    if payload[1] == SHUTDOWN_CMD and payload[0] == 0:
        return "shutdown (0x0F)"
    if tuple(payload[0:3]) == HEADER:
        vals = list(payload[3:])
        return (
            f"stats cpu={vals[0]}.{vals[1]:02d}° "
            f"({'C' if vals[2] == 0 else 'F'}) "
            f"usage={vals[3]}% "
            f"show=0x{vals[0x24]:02x}"
        )
    return "unknown frame: " + " ".join(f"{b:02x}" for b in payload[:16])


def frames_equal(a: Iterable[int], b: Iterable[int]) -> bool:
    return list(a) == list(b)
