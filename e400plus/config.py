"""YAML / env config for e400plus."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from .protocol import ShowMask

DEFAULT_PATHS = (
    Path.home() / ".config" / "e400plus" / "config.yaml",
    Path("/etc/e400plus/config.yaml"),
)


@dataclass
class Config:
    celsius: bool = True
    interval_ms: int = 500
    show_cpu_temp: bool = True
    show_cpu_usage: bool = True
    show_gpu_temp: bool = True
    show_gpu_usage: bool = True
    cpu_temp_sensor: Optional[str] = None
    gpu_temp_sensor: Optional[str] = None
    device_path: Optional[str] = None
    mock: bool = False

    @property
    def show_mask(self) -> ShowMask:
        mask = ShowMask.NONE
        if self.show_cpu_temp:
            mask |= ShowMask.CPU_TEMP
        if self.show_cpu_usage:
            mask |= ShowMask.CPU_USAGE
        if self.show_gpu_temp:
            mask |= ShowMask.GPU_TEMP
        if self.show_gpu_usage:
            mask |= ShowMask.GPU_USAGE
        return mask or ShowMask.CPU_TEMP

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


def load_config(path: Optional[str | Path] = None) -> Config:
    paths: list[Path] = [Path(path)] if path else list(DEFAULT_PATHS)
    for p in paths:
        if p and p.is_file():
            with p.open() as fh:
                data = yaml.safe_load(fh) or {}
            return Config.from_dict(data)
    return Config()


def save_config(cfg: Config, path: Optional[str | Path] = None) -> Path:
    target = Path(path) if path else DEFAULT_PATHS[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w") as fh:
        yaml.safe_dump(cfg.to_dict(), fh, sort_keys=False)
    return target
