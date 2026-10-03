from __future__ import annotations

from e400plus.protocol import Metrics, ShowMask
from e400plus.sensors import MetricsCache


def test_metrics_cache_refreshes_once_per_second(monkeypatch):
    calls = 0
    clock = 10.0

    def sample(**_kwargs):
        nonlocal calls
        calls += 1
        return Metrics(cpu_temp_c=float(calls), cpu_usage=float(calls))

    monkeypatch.setattr("e400plus.sensors._collect_metrics", sample)
    monkeypatch.setattr("e400plus.sensors.time.monotonic", lambda: clock)
    cache = MetricsCache()

    first = cache.get(
        celsius=True,
        show=ShowMask.CPU_TEMP,
        cpu_temp_sensor=None,
        gpu_temp_sensor=None,
    )
    clock += 0.99
    second = cache.get(
        celsius=False,
        show=ShowMask.GPU_USAGE,
        cpu_temp_sensor=None,
        gpu_temp_sensor=None,
    )
    clock += 0.01
    third = cache.get(
        celsius=True,
        show=ShowMask.DEFAULT,
        cpu_temp_sensor=None,
        gpu_temp_sensor=None,
    )

    assert calls == 2
    assert (first.cpu_temp_c, second.cpu_temp_c, third.cpu_temp_c) == (1.0, 1.0, 2.0)
    assert second.celsius is False
    assert second.show == ShowMask.GPU_USAGE


def test_metrics_cache_refreshes_when_sensor_selection_changes(monkeypatch):
    calls = 0

    def sample(**_kwargs):
        nonlocal calls
        calls += 1
        return Metrics(cpu_temp_c=float(calls))

    monkeypatch.setattr("e400plus.sensors._collect_metrics", sample)
    cache = MetricsCache()

    first = cache.get(
        celsius=True,
        show=ShowMask.DEFAULT,
        cpu_temp_sensor="package",
        gpu_temp_sensor=None,
    )
    second = cache.get(
        celsius=True,
        show=ShowMask.DEFAULT,
        cpu_temp_sensor="tctl",
        gpu_temp_sensor=None,
    )

    assert (first.cpu_temp_c, second.cpu_temp_c) == (1.0, 2.0)


def test_metrics_cache_honors_configured_duration(monkeypatch):
    calls = 0
    clock = 0.0

    def sample(**_kwargs):
        nonlocal calls
        calls += 1
        return Metrics(cpu_temp_c=float(calls))

    monkeypatch.setattr("e400plus.sensors._collect_metrics", sample)
    monkeypatch.setattr("e400plus.sensors.time.monotonic", lambda: clock)
    cache = MetricsCache()

    cache.get(
        celsius=True,
        show=ShowMask.DEFAULT,
        cpu_temp_sensor=None,
        gpu_temp_sensor=None,
        ttl_seconds=0.25,
    )
    clock += 0.25
    cache.get(
        celsius=True,
        show=ShowMask.DEFAULT,
        cpu_temp_sensor=None,
        gpu_temp_sensor=None,
        ttl_seconds=0.25,
    )

    assert calls == 2
