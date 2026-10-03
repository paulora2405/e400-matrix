from __future__ import annotations

from argparse import Namespace

from e400plus import cli
from e400plus.config import Config
from e400plus.protocol import Metrics


class _Device:
    def __init__(self, fail_write: bool = False) -> None:
        self.fail_write = fail_write
        self.closed = False
        self.shutdown_called = False

    def push(self, _metrics: Metrics) -> int:
        if self.fail_write:
            raise OSError("HID write failed (-1)")
        return 65

    def shutdown(self) -> int:
        self.shutdown_called = True
        return 65

    def close(self) -> None:
        self.closed = True


def test_daemon_reopens_device_after_write_failure(monkeypatch):
    first = _Device(fail_write=True)
    second = _Device()
    devices = iter([first, second])

    monkeypatch.setattr(cli, "load_config", lambda _path: Config(interval_ms=100))
    monkeypatch.setattr(cli, "open_device", lambda **_kwargs: next(devices))
    monkeypatch.setattr(cli, "_metrics_from_args", lambda *_args: Metrics())

    sleeps = 0

    def sleep(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", sleep)
    args = Namespace(
        config=None,
        mock=False,
        interval=None,
        demo=False,
        path=None,
        verbose=False,
    )

    assert cli._cmd_daemon(args) == 0
    assert first.closed is True
    assert second.shutdown_called is True
    assert second.closed is True
