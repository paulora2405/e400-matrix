"""HID transport for the E400 / E400 Plus matrix display."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

from . import PRODUCT_ID, VENDOR_ID
from .protocol import REPORT_PAYLOAD_LEN, build_shutdown_payload, build_stats_payload, Metrics


@dataclass
class DeviceInfo:
    path: str
    vendor_id: int
    product_id: int
    manufacturer: str = ""
    product: str = ""
    serial: str = ""
    interface: int | None = None

    @property
    def id_str(self) -> str:
        return f"{self.vendor_id:04x}:{self.product_id:04x}"


class MockDevice:
    """In-memory sink so the CLI/UI can be exercised without hardware."""

    def __init__(self) -> None:
        self.closed = False
        self.last: bytes | None = None
        self.writes: list[bytes] = []

    def write_payload(self, payload: bytes) -> int:
        if self.closed:
            raise RuntimeError("mock device closed")
        if len(payload) != REPORT_PAYLOAD_LEN:
            raise ValueError(f"expected {REPORT_PAYLOAD_LEN} bytes, got {len(payload)}")
        frame = bytes([0x00]) + payload  # report ID 0
        self.last = frame
        self.writes.append(frame)
        return len(frame)

    def push(self, metrics: Metrics) -> int:
        return self.write_payload(build_stats_payload(metrics))

    def shutdown(self) -> int:
        return self.write_payload(build_shutdown_payload())

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "MockDevice":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class E400Device:
    """Talk to the cooler over hidapi (Linux hidraw)."""

    def __init__(self, path: Optional[str] = None, report_id: int = 0) -> None:
        try:
            import hid  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "hidapi is required. Install system libhidapi and `pip install hidapi`."
            ) from exc

        self._hid = hid
        self.report_id = report_id
        self._dev = hid.device()
        if path:
            self._dev.open_path(path.encode() if isinstance(path, str) else path)
        else:
            self._dev.open(VENDOR_ID, PRODUCT_ID)
        self._dev.set_nonblocking(1)

    @staticmethod
    def list_devices() -> list[DeviceInfo]:
        try:
            import hid  # type: ignore
        except ImportError:
            return []
        out: list[DeviceInfo] = []
        for d in hid.enumerate(VENDOR_ID, PRODUCT_ID):
            out.append(
                DeviceInfo(
                    path=d.get("path", b"").decode(errors="replace")
                    if isinstance(d.get("path"), (bytes, bytearray))
                    else str(d.get("path", "")),
                    vendor_id=int(d.get("vendor_id", 0)),
                    product_id=int(d.get("product_id", 0)),
                    manufacturer=d.get("manufacturer_string") or "",
                    product=d.get("product_string") or "",
                    serial=d.get("serial_number") or "",
                    interface=d.get("interface_number"),
                )
            )
        return out

    def write_payload(self, payload: bytes) -> int:
        if len(payload) != REPORT_PAYLOAD_LEN:
            raise ValueError(f"expected {REPORT_PAYLOAD_LEN} bytes, got {len(payload)}")
        # Windows CyUSB path: DataBuf[0]=report ID, DataBuf[1:]=payload
        frame = bytes([self.report_id & 0xFF]) + payload
        written = self._dev.write(frame)
        if written < 0:
            raise OSError(f"HID write failed ({written})")
        return written

    def push(self, metrics: Metrics) -> int:
        return self.write_payload(build_stats_payload(metrics))

    def shutdown(self) -> int:
        return self.write_payload(build_shutdown_payload())

    def close(self) -> None:
        try:
            self._dev.close()
        except Exception:
            pass

    def __enter__(self) -> "E400Device":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def open_device(*, mock: bool = False, path: Optional[str] = None) -> E400Device | MockDevice:
    if mock:
        print("using mock device (no hardware)", file=sys.stderr)
        return MockDevice()
    devices = E400Device.list_devices()
    if not devices and path is None:
        raise FileNotFoundError(
            f"no E400 display found (expected USB {VENDOR_ID:04x}:{PRODUCT_ID:04x}). "
            "Pass --mock to dry-run, or check `lsusb` / udev rules."
        )
    return E400Device(path=path)
