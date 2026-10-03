"""Command-line interface for e400plus."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

from . import PRODUCT_ID, VENDOR_ID, __version__
from .config import Config, load_config, save_config
from .device import E400Device, open_device
from .protocol import Metrics, ShowMask, build_stats_payload, describe_payload
from .sensors import collect_metrics, demo_metrics, list_hwmon_temps


def _cmd_detect(_: argparse.Namespace) -> int:
    devices = E400Device.list_devices()
    if not devices:
        print(f"no device with USB ID {VENDOR_ID:04x}:{PRODUCT_ID:04x}")
        print("tip: check `lsusb | grep -i 5131` and udev rules")
        return 1
    for d in devices:
        print(f"{d.id_str}  {d.path}")
        if d.manufacturer or d.product:
            print(f"  {d.manufacturer} {d.product}".rstrip())
        if d.serial:
            print(f"  serial={d.serial}")
    return 0


def _cmd_sensors(_: argparse.Namespace) -> int:
    temps = list_hwmon_temps()
    if not temps:
        print("no hwmon temperature sensors found")
    for t in temps:
        print(f"{t.value:6.1f} C  {t.label:32s}  {t.path}")
    m = collect_metrics()
    print("---")
    print(
        f"cpu={m.cpu_temp_c:.1f}C {m.cpu_usage:.0f}% "
        f"{m.cpu_freq_mhz:.0f}MHz  gpu={m.gpu_temp_c:.1f}C  ram={m.ram_usage:.0f}%"
    )
    return 0


def _metrics_from_args(args: argparse.Namespace, cfg: Config, tick: int = 0) -> Metrics:
    if getattr(args, "demo", False) or cfg.mock:
        m = demo_metrics(tick)
    else:
        m = collect_metrics(
            celsius=cfg.celsius,
            show=cfg.show_mask,
            cpu_temp_sensor=cfg.cpu_temp_sensor,
            gpu_temp_sensor=cfg.gpu_temp_sensor,
            cache_seconds=cfg.metrics_cache_ms / 1000.0,
        )
    m.celsius = cfg.celsius
    m.show = cfg.show_mask
    m.when = datetime.now()
    if getattr(args, "cpu_temp", None) is not None:
        m.cpu_temp_c = float(args.cpu_temp)
    if getattr(args, "cpu_usage", None) is not None:
        m.cpu_usage = float(args.cpu_usage)
    return m


def _cmd_push(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.mock:
        cfg.mock = True
    m = _metrics_from_args(args, cfg)
    payload = build_stats_payload(m)
    if args.dump:
        print(describe_payload(payload))
        print(payload.hex(" "))
    with open_device(mock=cfg.mock, path=args.path or cfg.device_path) as dev:
        n = dev.push(m)
        print(f"wrote {n} bytes ({describe_payload(payload)})")
    return 0


def _cmd_daemon(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.mock:
        cfg.mock = True
    if args.interval:
        cfg.interval_ms = args.interval
    tick = 0
    print(
        f"e400plus daemon {__version__} — interval={cfg.interval_ms}ms "
        f"metrics-cache={cfg.metrics_cache_ms}ms "
        f"show=0x{int(cfg.show_mask):x} mock={cfg.mock}",
        flush=True,
    )
    try:
        with open_device(mock=cfg.mock, path=args.path or cfg.device_path) as dev:
            while True:
                m = _metrics_from_args(args, cfg, tick)
                try:
                    n = dev.push(m)
                    if args.verbose:
                        print(
                            f"[{datetime.now():%H:%M:%S}] wrote {n}  "
                            f"cpu={m.cpu_temp_c:.1f}C {m.cpu_usage:.0f}%",
                            flush=True,
                        )
                except OSError as exc:
                    print(f"write error: {exc}", file=sys.stderr, flush=True)
                    time.sleep(1.0)
                tick += 1
                time.sleep(max(cfg.interval_ms, 100) / 1000.0)
    except KeyboardInterrupt:
        print("stopping…", flush=True)
        try:
            with open_device(mock=cfg.mock, path=args.path or cfg.device_path) as dev:
                dev.shutdown()
        except Exception:
            pass
        return 0


def _cmd_encode(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    m = _metrics_from_args(args, cfg)
    payload = build_stats_payload(m)
    print(describe_payload(payload))
    if args.json:
        print(json.dumps({"hex": payload.hex(), "len": len(payload)}))
    else:
        print(payload.hex(" "))
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.show:
        print(json.dumps(cfg.to_dict(), indent=2))
        return 0
    if args.set_celsius is not None:
        cfg.celsius = args.set_celsius
    if args.show_mask:
        # e.g. cpu_temp,cpu_usage
        names = {s.strip().lower() for s in args.show_mask.split(",") if s.strip()}
        cfg.show_cpu_temp = "cpu_temp" in names
        cfg.show_cpu_usage = "cpu_usage" in names
        cfg.show_gpu_temp = "gpu_temp" in names
        cfg.show_gpu_usage = "gpu_usage" in names
    path = save_config(cfg, args.config)
    print(f"wrote {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="e400plus",
        description="Simple Linux control for the darkFlash E400 / E400 Plus matrix display",
    )
    p.add_argument("--version", action="version", version=f"e400plus {__version__}")
    p.add_argument("-c", "--config", help="config YAML path")
    p.add_argument("--mock", action="store_true", help="do not open real HID device")
    p.add_argument("--path", help="hidraw / hidapi device path")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("detect", help="list matching USB HID devices")
    s.set_defaults(func=_cmd_detect)

    s = sub.add_parser("sensors", help="list host temperature sensors")
    s.set_defaults(func=_cmd_sensors)

    s = sub.add_parser("push", help="send one stats frame")
    s.add_argument("--dump", action="store_true")
    s.add_argument("--demo", action="store_true", help="use synthetic metrics")
    s.add_argument("--mock", action="store_true", help="do not open real HID device")
    s.add_argument("--cpu-temp", type=float)
    s.add_argument("--cpu-usage", type=float)
    s.set_defaults(func=_cmd_push)

    s = sub.add_parser("daemon", help="stream metrics to the display")
    s.add_argument("--interval", type=int, help="milliseconds between frames")
    s.add_argument("--demo", action="store_true")
    s.add_argument("--mock", action="store_true")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=_cmd_daemon)

    s = sub.add_parser("encode", help="build a payload without opening the device")
    s.add_argument("--demo", action="store_true")
    s.add_argument("--json", action="store_true")
    s.add_argument("--cpu-temp", type=float)
    s.add_argument("--cpu-usage", type=float)
    s.set_defaults(func=_cmd_encode)

    s = sub.add_parser("config", help="show or write config")
    s.add_argument("--show", action="store_true")
    s.add_argument("--set-celsius", type=lambda x: x.lower() != "false", nargs="?", const=True)
    s.add_argument("--show-mask", help="comma list: cpu_temp,cpu_usage,gpu_temp,gpu_usage")
    s.set_defaults(func=_cmd_config)

    s = sub.add_parser("web", help="start the simple control UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=43127)
    s.add_argument("--mock", action="store_true")
    s.set_defaults(func=_cmd_web)
    return p


def _cmd_web(args: argparse.Namespace) -> int:
    import uvicorn

    from .webapp import create_app

    cfg = load_config(args.config)
    if args.mock:
        cfg.mock = True
    app = create_app(cfg)
    print(f"E400 Plus UI → http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
