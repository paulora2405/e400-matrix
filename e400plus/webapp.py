"""Minimal FastAPI control panel for e400plus."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import PRODUCT_ID, VENDOR_ID, __version__
from .config import Config, save_config
from .device import E400Device, MockDevice, open_device
from .protocol import Metrics, ShowMask, build_stats_payload, describe_payload
from .sensors import collect_metrics, demo_metrics, list_hwmon_temps

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


class Status(BaseModel):
    connected: bool
    mock: bool
    version: str
    vendor_id: str
    product_id: str
    last_push: Optional[str] = None
    last_describe: Optional[str] = None
    metrics: Optional[dict[str, Any]] = None
    daemon_running: bool = False
    error: Optional[str] = None


class PushRequest(BaseModel):
    demo: bool = False
    cpu_temp: Optional[float] = None
    cpu_usage: Optional[float] = None
    celsius: bool = True
    show_cpu_temp: bool = True
    show_cpu_usage: bool = True
    show_gpu_temp: bool = True
    show_gpu_usage: bool = True


class DaemonRequest(BaseModel):
    enabled: bool
    interval_ms: int = Field(500, ge=100, le=5000)
    demo: bool = False
    celsius: bool = True


class ControlState:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.lock = threading.Lock()
        self.daemon_thread: Optional[threading.Thread] = None
        self.daemon_stop = threading.Event()
        self.last_push: Optional[str] = None
        self.last_describe: Optional[str] = None
        self.last_metrics: Optional[Metrics] = None
        self.error: Optional[str] = None
        self.tick = 0

    def show_mask(self, req: PushRequest | DaemonRequest | None = None) -> ShowMask:
        if isinstance(req, PushRequest):
            mask = ShowMask.NONE
            if req.show_cpu_temp:
                mask |= ShowMask.CPU_TEMP
            if req.show_cpu_usage:
                mask |= ShowMask.CPU_USAGE
            if req.show_gpu_temp:
                mask |= ShowMask.GPU_TEMP
            if req.show_gpu_usage:
                mask |= ShowMask.GPU_USAGE
            return mask or ShowMask.CPU_TEMP
        return self.cfg.show_mask

    def build_metrics(self, *, demo: bool, overrides: Optional[PushRequest] = None) -> Metrics:
        if demo or self.cfg.mock:
            m = demo_metrics(self.tick)
        else:
            m = collect_metrics(
                celsius=self.cfg.celsius,
                show=self.cfg.show_mask,
                cpu_temp_sensor=self.cfg.cpu_temp_sensor,
                gpu_temp_sensor=self.cfg.gpu_temp_sensor,
                cache_seconds=self.cfg.metrics_cache_ms / 1000.0,
            )
        if overrides:
            m.celsius = overrides.celsius
            m.show = self.show_mask(overrides)
            if overrides.cpu_temp is not None:
                m.cpu_temp_c = overrides.cpu_temp
            if overrides.cpu_usage is not None:
                m.cpu_usage = overrides.cpu_usage
        else:
            m.celsius = self.cfg.celsius
            m.show = self.cfg.show_mask
        m.when = datetime.now()
        return m

    def push_once(self, *, demo: bool = False, overrides: Optional[PushRequest] = None) -> Metrics:
        m = self.build_metrics(demo=demo, overrides=overrides)
        payload = build_stats_payload(m)
        with open_device(mock=self.cfg.mock, path=self.cfg.device_path) as dev:
            dev.push(m)
        self.last_push = datetime.now().isoformat(timespec="seconds")
        self.last_describe = describe_payload(payload)
        self.last_metrics = m
        self.error = None
        self.tick += 1
        return m


def create_app(cfg: Config | None = None) -> FastAPI:
    state = ControlState(cfg or Config(mock=True))
    app = FastAPI(title="e400plus", version=__version__)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html_path = STATIC_DIR / "index.html"
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/status", response_model=Status)
    def status() -> Status:
        devices = E400Device.list_devices()
        connected = bool(devices) or state.cfg.mock
        metrics = None
        if state.last_metrics:
            m = state.last_metrics
            metrics = {
                "cpu_temp_c": m.cpu_temp_c,
                "cpu_usage": m.cpu_usage,
                "gpu_temp_c": m.gpu_temp_c,
                "gpu_usage": m.gpu_usage,
                "ram_usage": m.ram_usage,
                "celsius": m.celsius,
                "show": int(m.show),
            }
        return Status(
            connected=connected,
            mock=state.cfg.mock,
            version=__version__,
            vendor_id=f"{VENDOR_ID:04x}",
            product_id=f"{PRODUCT_ID:04x}",
            last_push=state.last_push,
            last_describe=state.last_describe,
            metrics=metrics,
            daemon_running=state.daemon_thread is not None and state.daemon_thread.is_alive(),
            error=state.error,
        )

    @app.get("/api/sensors")
    def sensors() -> dict[str, Any]:
        temps = [
            {"label": t.label, "path": t.path, "value": t.value, "unit": t.unit}
            for t in list_hwmon_temps()
        ]
        devices = [
            {"path": d.path, "id": d.id_str, "product": d.product, "manufacturer": d.manufacturer}
            for d in E400Device.list_devices()
        ]
        return {"temps": temps, "devices": devices}

    @app.post("/api/push")
    def push(req: PushRequest) -> dict[str, Any]:
        try:
            with state.lock:
                m = state.push_once(demo=req.demo or state.cfg.mock, overrides=req)
            return {
                "ok": True,
                "describe": state.last_describe,
                "metrics": {
                    "cpu_temp_c": m.cpu_temp_c,
                    "cpu_usage": m.cpu_usage,
                    "gpu_temp_c": m.gpu_temp_c,
                },
            }
        except Exception as exc:
            state.error = str(exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _daemon_loop(interval_ms: int, demo: bool) -> None:
        while not state.daemon_stop.is_set():
            try:
                with state.lock:
                    state.push_once(demo=demo or state.cfg.mock)
            except Exception as exc:
                state.error = str(exc)
            state.daemon_stop.wait(interval_ms / 1000.0)

    @app.post("/api/daemon")
    def daemon(req: DaemonRequest) -> dict[str, Any]:
        state.cfg.celsius = req.celsius
        state.cfg.interval_ms = req.interval_ms
        if req.enabled:
            if state.daemon_thread and state.daemon_thread.is_alive():
                return {"ok": True, "running": True}
            state.daemon_stop.clear()
            state.daemon_thread = threading.Thread(
                target=_daemon_loop,
                args=(req.interval_ms, req.demo),
                daemon=True,
                name="e400plus-daemon",
            )
            state.daemon_thread.start()
            return {"ok": True, "running": True}
        state.daemon_stop.set()
        if state.daemon_thread:
            state.daemon_thread.join(timeout=2.0)
            state.daemon_thread = None
        try:
            with open_device(mock=state.cfg.mock, path=state.cfg.device_path) as dev:
                if isinstance(dev, (E400Device, MockDevice)):
                    dev.shutdown()
        except Exception:
            pass
        return {"ok": True, "running": False}

    @app.post("/api/config")
    def write_config(req: PushRequest) -> dict[str, Any]:
        state.cfg.celsius = req.celsius
        state.cfg.show_cpu_temp = req.show_cpu_temp
        state.cfg.show_cpu_usage = req.show_cpu_usage
        state.cfg.show_gpu_temp = req.show_gpu_temp
        state.cfg.show_gpu_usage = req.show_gpu_usage
        path = save_config(state.cfg)
        return {"ok": True, "path": str(path), "config": state.cfg.to_dict()}

    return app
