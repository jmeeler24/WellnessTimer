"""Windows autostart helper.

Writes/removes an entry under HKCU\\Software\\Microsoft\\Windows\\
CurrentVersion\\Run pointing at the running executable.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path


log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "WellnessTimer"


def _executable_command() -> str:
    """Quoted command to launch the app at login.

    When frozen by PyInstaller, sys.executable is the .exe itself. When
    running from source, we launch python with main.py.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    script = Path(__file__).resolve().parent / "main.py"
    return f'"{sys.executable}" "{script}"'


def is_enabled() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError as e:
        log.warning("Failed to read autostart key: %s", e)
        return False


def enable() -> bool:
    if not sys.platform.startswith("win"):
        log.info("Autostart only supported on Windows; skipping")
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(
                key, VALUE_NAME, 0, winreg.REG_SZ, _executable_command()
            )
        return True
    except OSError as e:
        log.error("Failed to enable autostart: %s", e)
        return False


def disable() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
        return True
    except OSError as e:
        log.error("Failed to disable autostart: %s", e)
        return False


def sync(desired: bool) -> bool:
    """Reconcile registry state to match `desired`."""
    current = is_enabled()
    if desired == current:
        return True
    return enable() if desired else disable()
