"""Persistent configuration for DeepCool Control."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

APP_ID = "io.github.deepcool.Control"
APP_NAME = "DeepCool Control"
VERSION = "1.2.0"
LIGHTING_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
DEFAULT_LIGHTING_COLOR = "#22D3EE"

ACCENTS: dict[str, tuple[str, str]] = {
    # name: (primary, soft background tint)
    "cyan": ("#22d3ee", "rgba(34, 211, 238, 0.16)"),
    "violet": ("#a78bfa", "rgba(167, 139, 250, 0.16)"),
    "emerald": ("#34d399", "rgba(52, 211, 153, 0.16)"),
    "amber": ("#fbbf24", "rgba(251, 191, 36, 0.16)"),
    "rose": ("#fb7185", "rgba(251, 113, 133, 0.16)"),
    "blue": ("#60a5fa", "rgba(96, 165, 250, 0.16)"),
}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "deepcool-control"


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass
class Config:
    primary: str = "cpu_temp"
    secondary: str = "gpu_temp"
    fahrenheit: bool = False
    interval_ms: int = 1000
    auto_cycle_s: int = 10
    cpu_sensor: str = ""
    gpu_sensor: str = ""
    accent: str = "cyan"
    animations: bool = True
    autostart: bool = False
    service: bool = False
    color_scheme: str = "system"
    lighting_device: str = ""
    lighting_zone: str = ""
    lighting_color: str = DEFAULT_LIGHTING_COLOR
    lighting_mode: str = "Direct"
    lighting_brightness: int = 100

    def validate(self) -> "Config":
        if self.primary not in ("cpu_temp", "cpu_usage", "auto"):
            self.primary = "cpu_temp"
        if self.secondary not in ("gpu_temp", "gpu_usage", "auto", "off"):
            self.secondary = "gpu_temp"
        self.interval_ms = max(250, min(5000, int(self.interval_ms)))
        self.auto_cycle_s = max(3, min(120, int(self.auto_cycle_s)))
        if self.accent not in ACCENTS:
            self.accent = "cyan"
        if self.color_scheme not in ("system", "light", "dark"):
            self.color_scheme = "system"
        self.lighting_device = str(self.lighting_device or "").strip()
        self.lighting_zone = str(self.lighting_zone or "").strip()
        if not isinstance(self.lighting_color, str) or not LIGHTING_COLOR_RE.fullmatch(
            self.lighting_color
        ):
            self.lighting_color = DEFAULT_LIGHTING_COLOR
        else:
            self.lighting_color = self.lighting_color.upper()
        self.lighting_mode = str(self.lighting_mode or "Direct").strip() or "Direct"
        try:
            self.lighting_brightness = int(self.lighting_brightness)
        except (TypeError, ValueError):
            self.lighting_brightness = 100
        self.lighting_brightness = max(0, min(100, self.lighting_brightness))
        return self

    @property
    def accent_color(self) -> str:
        return ACCENTS[self.accent][0]

    @property
    def accent_soft(self) -> str:
        return ACCENTS[self.accent][1]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Config":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known}).validate()

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_path()
        try:
            with path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                raise ValueError("configuration root is not an object")
            return cls.from_dict(raw)
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError, TypeError):
            # A broken config must never prevent the app from starting.
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=".config-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
