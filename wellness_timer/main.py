"""Entry point: tray icon, scheduler wiring, lifecycle.

Threading model:
- Tk's mainloop runs on the process's main thread. All Tk/UI work
  (Settings window, About dialog, message boxes) happens there.
- pystray.Icon runs on a worker thread. Menu callbacks fire on that
  thread and marshal UI work back to the main thread via root.after().
This is the only safe arrangement for pystray + Tk in the same process.
"""
from __future__ import annotations

import logging
import sys
import threading
import tkinter as tk
from pathlib import Path
from typing import Optional


# Make `python main.py` work both as a script and as a package module.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from wellness_timer import autostart, config as cfg_mod, lock_state
    from wellness_timer.notifier import Notifier
    from wellness_timer.scheduler import Scheduler, GLOBAL_SNOOZE_SECONDS
    from wellness_timer.settings_ui import SettingsWindow
else:
    from . import autostart, config as cfg_mod, lock_state
    from .notifier import Notifier
    from .scheduler import Scheduler, GLOBAL_SNOOZE_SECONDS
    from .settings_ui import SettingsWindow


# Used verbatim as the toast notification header text. Windows ignores
# registry-based AppUserModelId display registration for unpackaged apps,
# so the AppID itself has to be human-readable.
APP_ID = "Wellness Timer"
APP_TITLE = "Wellness Timer"
APP_VERSION = "0.1.0"
GITHUB_URL = "https://github.com/jmeeler24/WellnessTimer"

log = logging.getLogger("wellness_timer")


def _asset_path(filename: str) -> Path:
    """Resolve a bundled asset whether running from source or frozen."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent
    return base / "assets" / filename


def _icon_image():
    """Return a PIL.Image for the tray icon. Falls back to a generated
    placeholder if the bundled .ico cannot be loaded."""
    from PIL import Image, ImageDraw

    ico = _asset_path("icon.ico")
    if ico.exists():
        try:
            return Image.open(ico)
        except Exception:
            log.exception("Failed to load %s; using generated icon", ico)

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((12, 20, 52, 60), fill=(48, 140, 220, 255))
    d.polygon([(32, 4), (20, 28), (44, 28)], fill=(48, 140, 220, 255))
    return img


class App:
    def __init__(self) -> None:
        self._config = cfg_mod.load_config()
        self._notifier = Notifier(APP_ID, _asset_path("icon.ico"))
        self._scheduler = Scheduler(self._on_timer_fire)
        self._tray = None  # pystray.Icon, created in run()
        self._tray_thread: Optional[threading.Thread] = None
        self._root: Optional[tk.Tk] = None
        self._settings: Optional[SettingsWindow] = None

        autostart.sync(self._config.start_at_login)
        # Start the lock-state listener now so we don't miss an early
        # lock event during the first timer interval.
        lock_state.start()

    # ---- scheduler callbacks ----------------------------------------

    def _on_timer_fire(self, timer_cfg: cfg_mod.TimerConfig) -> None:
        # Suppress while the screen is locked so reminders don't pile up and
        # arrive all at once on return. The timer keeps its normal cadence;
        # the next fire after unlock just shows normally.
        if lock_state.is_locked():
            log.info("Locked — suppressing: %s", timer_cfg.name)
            return
        log.info("Firing: %s", timer_cfg.name)
        self._notifier.notify(title=timer_cfg.name, message=timer_cfg.message)

    # ---- config plumbing --------------------------------------------

    def _apply_new_config(self, new_cfg: cfg_mod.AppConfig) -> None:
        cfg_mod.save_config(new_cfg)
        self._config = new_cfg
        autostart.sync(new_cfg.start_at_login)
        self._scheduler.apply(new_cfg.timers, new_cfg.global_enabled)
        self._refresh_menu()

    # ---- tray menu callbacks (fire on pystray's worker thread) ------
    # UI-touching callbacks must marshal to the Tk main thread.

    def _show_settings(self, _icon=None, _item=None) -> None:
        if self._root is not None and self._settings is not None:
            self._root.after(0, lambda: self._settings.open(self._config))

    def _toggle_pause(self, _icon=None, _item=None) -> None:
        # Scheduler is thread-safe; no need to marshal to main.
        if self._scheduler.paused:
            self._scheduler.apply(self._config.timers, True)
        else:
            self._scheduler.pause()
        self._refresh_menu()

    def _snooze_all(self, _icon=None, _item=None) -> None:
        self._scheduler.snooze_all(GLOBAL_SNOOZE_SECONDS)

    def _show_about(self, _icon=None, _item=None) -> None:
        if self._root is not None:
            self._root.after(0, self._show_about_dialog)

    def _show_about_dialog(self) -> None:
        # Custom Toplevel instead of messagebox.showinfo so the GitHub URL
        # can render as a real clickable hyperlink. Uses the system default
        # UI font everywhere for consistent sizing — only weight (bold on
        # the title) and underline (on the link) vary.
        import webbrowser
        from tkinter import font as tkfont, ttk

        try:
            dlg = tk.Toplevel(self._root)
            dlg.title(APP_TITLE)
            dlg.resizable(False, False)

            default = tkfont.nametofont("TkDefaultFont")
            bold = default.copy()
            bold.configure(weight="bold")
            link_font = default.copy()
            link_font.configure(underline=True)

            frame = ttk.Frame(dlg, padding=16)
            frame.pack()

            ttk.Label(frame, text=APP_TITLE, font=bold).pack(anchor=tk.W)
            ttk.Label(frame,
                      text="Lightweight wellness reminders for Windows."
                      ).pack(anchor=tk.W, pady=(2, 8))
            ttk.Label(frame, text=f"Version: {APP_VERSION}").pack(anchor=tk.W)

            link = ttk.Label(frame, text=GITHUB_URL, font=link_font,
                             foreground="#1a6dd1", cursor="hand2")
            link.pack(anchor=tk.W)
            link.bind("<Button-1>",
                      lambda _e: webbrowser.open_new_tab(GITHUB_URL))

            ttk.Label(frame,
                      text=f"Config: {cfg_mod.config_path()}").pack(anchor=tk.W)

            ttk.Button(frame, text="Close",
                       command=dlg.destroy).pack(pady=(12, 0))
            dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
            # Ensure the dialog is up-front even when the hidden root would
            # otherwise leave it buried.
            dlg.lift()
            dlg.after(50, dlg.focus_force)
        except Exception:
            log.exception("Failed to show About dialog")

    def _quit(self, _icon=None, _item=None) -> None:
        if self._root is not None:
            self._root.after(0, self._shutdown_on_main)

    def _shutdown_on_main(self) -> None:
        log.info("Shutting down")
        self._scheduler.stop()
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                log.exception("Tray stop failed")
        if self._root is not None:
            self._root.quit()

    # ---- tray construction ------------------------------------------

    def _build_menu(self):
        import pystray
        pause_label = "Resume All" if self._scheduler.paused else "Pause All"
        return pystray.Menu(
            pystray.MenuItem("Show Settings", self._show_settings, default=True),
            pystray.MenuItem(pause_label, self._toggle_pause),
            pystray.MenuItem("Snooze All (15 min)", self._snooze_all),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("About", self._show_about),
            pystray.MenuItem("Quit", self._quit),
        )

    def _refresh_menu(self) -> None:
        if self._tray is not None:
            self._tray.menu = self._build_menu()
            try:
                self._tray.update_menu()
            except Exception:
                pass

    def run(self) -> None:
        import pystray

        # Tk root lives on the main thread; all UI work marshals here.
        # The root stays hidden — visible windows are Toplevels parented to it.
        self._root = tk.Tk()
        self._root.withdraw()
        self._settings = SettingsWindow(self._root,
                                        on_save=self._apply_new_config)

        self._scheduler.apply(self._config.timers, self._config.global_enabled)

        self._tray = pystray.Icon(
            name=APP_ID,
            icon=_icon_image(),
            title=APP_TITLE,
            menu=self._build_menu(),
        )

        self._tray_thread = threading.Thread(
            target=self._tray.run, name="TrayIcon", daemon=True
        )
        self._tray_thread.start()

        try:
            self._root.mainloop()
        finally:
            self._scheduler.stop()
            if self._tray is not None:
                try:
                    self._tray.stop()
                except Exception:
                    pass
            try:
                self._root.destroy()
            except Exception:
                pass


def _setup_logging() -> None:
    log_dir = cfg_mod._config_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "wellness_timer.log",
                                      encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main() -> int:
    _setup_logging()
    try:
        App().run()
    except KeyboardInterrupt:
        return 0
    except Exception:
        log.exception("Fatal error")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
