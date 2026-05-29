"""Configuration load/save with defaults.

Config lives at %APPDATA%\\WellnessTimer\\config.json on Windows. On
non-Windows hosts (used for dev/testing) we fall back to ~/.wellness_timer.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


APP_NAME = "WellnessTimer"
CONFIG_FILENAME = "config.json"


def _config_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    # Dev fallback (mac/linux)
    return Path.home() / f".{APP_NAME.lower()}"


def config_path() -> Path:
    return _config_dir() / CONFIG_FILENAME


@dataclass
class TimerConfig:
    """A single wellness timer."""
    name: str
    interval_minutes: int
    message: str
    enabled: bool = True

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Timer name cannot be empty")
        if not isinstance(self.interval_minutes, int) or self.interval_minutes <= 0:
            raise ValueError("Interval must be a positive integer (minutes)")
        if self.message is None:
            raise ValueError("Message cannot be None")


@dataclass
class AppConfig:
    """Top-level application configuration."""
    timers: list[TimerConfig] = field(default_factory=list)
    global_enabled: bool = True
    start_at_login: bool = False
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "global_enabled": self.global_enabled,
            "start_at_login": self.start_at_login,
            "timers": [asdict(t) for t in self.timers],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppConfig":
        timers_raw = raw.get("timers") or []
        timers: list[TimerConfig] = []
        for entry in timers_raw:
            try:
                timers.append(
                    TimerConfig(
                        name=str(entry["name"]),
                        interval_minutes=int(entry["interval_minutes"]),
                        message=str(entry.get("message", "")),
                        enabled=bool(entry.get("enabled", True)),
                    )
                )
            except (KeyError, TypeError, ValueError):
                # Skip malformed entries rather than abort whole load.
                continue
        return cls(
            timers=timers,
            global_enabled=bool(raw.get("global_enabled", True)),
            start_at_login=bool(raw.get("start_at_login", False)),
            schema_version=int(raw.get("schema_version", 1)),
        )


def default_config() -> AppConfig:
    return AppConfig(
        timers=[
            TimerConfig("Hydration Reminder", 45, "Time to drink some water 💧"),
            TimerConfig("Posture Change", 50, "Switch between sitting and standing 🪑"),
            TimerConfig("Movement Break", 60, "Get up and move for 2 minutes 🚶"),
            TimerConfig("20-20-20 Eye Rule", 20,
                        "Look at something 20 feet away for 20 seconds 👀"),
        ],
        global_enabled=True,
        start_at_login=False,
    )


_save_lock = threading.Lock()


def load_config() -> AppConfig:
    """Load config from disk, creating defaults if missing or corrupt."""
    path = config_path()
    if not path.exists():
        cfg = default_config()
        save_config(cfg)
        return cfg
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return AppConfig.from_dict(raw)
    except (json.JSONDecodeError, OSError):
        # Corrupt config — back it up and write fresh defaults.
        try:
            path.rename(path.with_suffix(".json.bak"))
        except OSError:
            pass
        cfg = default_config()
        save_config(cfg)
        return cfg


def save_config(cfg: AppConfig) -> None:
    """Atomically persist config to disk."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False)
    with _save_lock:
        # Atomic write: tmp file in same dir, then replace.
        fd, tmp_name = tempfile.mkstemp(
            prefix=".config-", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
