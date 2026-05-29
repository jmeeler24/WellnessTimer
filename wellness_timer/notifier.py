"""Toast notification wrapper.

The primary backend talks to the Windows toast APIs directly through the
`winrt` projection. Going direct (rather than via a convenience wrapper)
lets us set each toast's ``expiration_time``, so a reminder removes itself
from the Action Center after a few minutes instead of lingering in the
notification list until manually cleared. Falls back to winotify (no
expiration control) if winrt is unavailable, then a no-op stub on
non-Windows hosts so dev hosts don't crash.

Notifications are fire-and-forget: no action buttons. Background-activation
callbacks (the only way to get an in-process click handler) require the app
to be registered as a Toast Notification Activator with a Start Menu
shortcut + COM CLSID, which a single-file PyInstaller exe doesn't provide.
The tray menu's "Snooze All" covers the snooze use-case instead.
"""
from __future__ import annotations

import datetime
import logging
import xml.sax.saxutils as xml_utils
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)

# How long a reminder lingers in the Action Center before Windows removes
# it. Wellness nudges are time-sensitive — a stale one has no value — so we
# let them self-clean rather than accumulate in the notification list.
ACTION_CENTER_TTL = datetime.timedelta(minutes=5)


class Notifier:
    """Send native Windows toast notifications."""

    def __init__(self, app_id: str, icon_path: Optional[Path] = None):
        self.app_id = app_id
        self.icon_path = str(icon_path) if icon_path and icon_path.exists() else None
        self._backend = self._pick_backend()
        log.info("Notifier backend: %s", self._backend)

    def _pick_backend(self) -> str:
        try:
            import winrt.windows.ui.notifications  # noqa: F401
            return "winrt"
        except ImportError:
            pass
        try:
            import winotify  # noqa: F401
            return "winotify"
        except ImportError:
            pass
        return "stub"

    def notify(self, title: str, message: str) -> None:
        """Show a toast and return immediately."""
        try:
            if self._backend == "winrt":
                self._notify_winrt(title, message)
            elif self._backend == "winotify":
                self._notify_winotify(title, message)
            else:
                log.info("[STUB notification] %s — %s", title, message)
        except Exception as e:
            # Never let notification failures crash the scheduler.
            log.exception("Failed to send notification: %s", e)

    def _notify_winrt(self, title: str, message: str) -> None:
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import (
            ToastNotification,
            ToastNotificationManager,
        )

        document = XmlDocument()
        document.load_xml(self._build_xml(title, message))

        toast = ToastNotification(document)
        # Auto-remove from the Action Center after the TTL elapses.
        toast.expiration_time = (
            datetime.datetime.now(datetime.timezone.utc) + ACTION_CENTER_TTL
        )

        notifier = ToastNotificationManager.create_toast_notifier_with_id(
            self.app_id
        )
        notifier.show(toast)

    def _build_xml(self, title: str, message: str) -> str:
        # The root activationType/launch/scenario attributes are required for
        # Windows to show the toast as a *banner*. Without a launch arg the
        # OS treats the toast as non-actionable and delivers it silently to
        # the Action Center with no banner. (launch="http:" is a benign
        # no-op target; the toast has no clickable actions of its own.)
        title_x = xml_utils.escape(title)
        message_x = xml_utils.escape(message)
        image = ""
        if self.icon_path:
            src = xml_utils.quoteattr(self.icon_path)
            image = (f'<image placement="appLogoOverride" hint-crop="circle" '
                     f'src={src}/>')
        return (
            '<toast activationType="protocol" launch="http:" scenario="default">'
            '<visual><binding template="ToastGeneric">'
            f'{image}'
            f'<text>{title_x}</text>'
            f'<text>{message_x}</text>'
            '</binding></visual>'
            '</toast>'
        )

    def _notify_winotify(self, title: str, message: str) -> None:
        from winotify import Notification, audio

        toast = Notification(
            app_id=self.app_id,
            title=title,
            msg=message,
            icon=self.icon_path or "",
        )
        toast.set_audio(audio.Default, loop=False)
        toast.show()
