"""Hardware experiments for the questions static analysis can't answer.

Each experiment keeps the panel alive with normal frames, changes exactly one
thing, then reports what it sent. Watch the display and note what it does.
Run with the daemon stopped: only one process can own the HID interface.
"""

from __future__ import annotations

import time
from typing import Callable

from .protocol import (
    REPORT_PAYLOAD_LEN,
    SHUTDOWN_CMD,
    Metrics,
    build_shutdown_payload,
    build_stats_payload,
)

FRAME_INTERVAL_S = 0.2  # the vendor app's send period


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def stream(dev, seconds: float, interval: float = FRAME_INTERVAL_S) -> None:
    """Send live stats frames for `seconds` at `interval`."""
    metrics = Metrics(cpu_temp_c=42.5, cpu_usage=17, gpu_temp_c=51, gpu_usage=9)
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        dev.write_payload(build_stats_payload(metrics))
        time.sleep(interval)


def command_payload(cmd: int) -> bytes:
    """A frame whose command byte (payload[1]) is `cmd`, everything else zero."""
    buf = bytearray(REPORT_PAYLOAD_LEN)
    buf[1] = cmd & 0xFF
    return bytes(buf)


def run_shutdown(dev, quiet_s: float = 10.0, warmup_s: float = 3.0) -> None:
    """Does the vendor's exit frame (0x0F) blank, hold, or do nothing?"""
    print(f"[{_stamp()}] streaming live frames for {warmup_s:g}s")
    stream(dev, warmup_s)
    dev.write_payload(build_shutdown_payload())
    print(f"[{_stamp()}] sent shutdown frame (cmd 0x{SHUTDOWN_CMD:02x}); now silent for {quiet_s:g}s")
    print("  watch: blank? last frame held? all-pixels default? how long until it changes?")
    time.sleep(quiet_s)
    print(f"[{_stamp()}] done")


def run_command(dev, cmd: int, quiet_s: float = 10.0, warmup_s: float = 3.0) -> None:
    """Send one frame with command byte `cmd`, then go silent."""
    print(f"[{_stamp()}] streaming live frames for {warmup_s:g}s")
    stream(dev, warmup_s)
    dev.write_payload(command_payload(cmd))
    print(f"[{_stamp()}] sent cmd 0x{cmd:02x}; now silent for {quiet_s:g}s")
    time.sleep(quiet_s)
    print(f"[{_stamp()}] done")


def run_interval(
    dev,
    periods_s: list[float],
    seconds: float = 6.0,
    ask: Callable[[str], str] = input,
) -> list[tuple[float, bool]]:
    """Find the longest steady send period that doesn't flash the default pattern."""
    results: list[tuple[float, bool]] = []
    for period in periods_s:
        print(f"[{_stamp()}] streaming at one frame every {period * 1000:g} ms for {seconds:g}s")
        stream(dev, seconds, interval=period)
        flicker = ask(f"  {period * 1000:g} ms: did the all-pixels pattern flash? [y/N] ").strip().lower() == "y"
        results.append((period, flicker))
    print("period_ms  flicker")
    for period, flicker in results:
        print(f"{period * 1000:9g}  {'yes' if flicker else 'no'}")
    return results


def run_silence(
    dev,
    gaps_s: list[float],
    warmup_s: float = 3.0,
    ask: Callable[[str], str] = input,
) -> list[tuple[float, bool]]:
    """Find the firmware watchdog: how long can the host stay silent?

    For each gap: stream, go silent for `gap`, resume streaming, then ask
    whether the panel flashed the all-pixels default pattern during the gap.
    """
    results: list[tuple[float, bool]] = []
    for gap in gaps_s:
        print(f"[{_stamp()}] streaming {warmup_s:g}s, then silent for {gap:g}s")
        stream(dev, warmup_s)
        time.sleep(gap)
        stream(dev, 2.0)
        reset = ask(f"  gap {gap:g}s: did the all-pixels pattern appear? [y/N] ").strip().lower() == "y"
        results.append((gap, reset))
    print("gap_s  default_pattern_seen")
    for gap, reset in results:
        print(f"{gap:5g}  {'yes' if reset else 'no'}")
    return results
