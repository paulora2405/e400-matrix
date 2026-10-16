from __future__ import annotations

from e400plus import probe
from e400plus.device import MockDevice
from e400plus.protocol import HEADER, SHUTDOWN_CMD


def _no_sleep(monkeypatch):
    monkeypatch.setattr(probe.time, "sleep", lambda _s: None)
    ticks = iter(range(10_000))
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(ticks) * 0.1)


def test_command_payload_sets_only_the_command_byte():
    payload = probe.command_payload(0x0F)
    assert len(payload) == 64
    assert payload[1] == 0x0F
    assert sum(payload) == 0x0F


def test_shutdown_experiment_ends_with_exit_frame(monkeypatch):
    _no_sleep(monkeypatch)
    dev = MockDevice()
    probe.run_shutdown(dev, quiet_s=1, warmup_s=1)
    *stats, last = dev.writes
    assert stats and all(tuple(f[1:4]) == HEADER for f in stats)
    assert last[2] == SHUTDOWN_CMD


def test_silence_experiment_reports_each_gap(monkeypatch):
    _no_sleep(monkeypatch)
    answers = iter(["n", "y"])
    results = probe.run_silence(MockDevice(), [0.5, 2], warmup_s=1, ask=lambda _p: next(answers))
    assert results == [(0.5, False), (2, True)]


def test_interval_experiment_streams_at_each_period(monkeypatch):
    _no_sleep(monkeypatch)
    answers = iter(["n", "y"])
    dev = MockDevice()
    results = probe.run_interval(dev, [0.1, 0.4], seconds=1, ask=lambda _p: next(answers))
    assert results == [(0.1, False), (0.4, True)]
    assert dev.writes
