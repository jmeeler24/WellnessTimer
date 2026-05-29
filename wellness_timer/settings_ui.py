"""Tkinter settings window.

Lives as a Toplevel under the App's shared hidden Tk root. Must be operated
on the Tk main thread — callers are responsible for marshalling there
(e.g. via root.after()). Does NOT own a tk.Tk() instance or call mainloop().
"""
from __future__ import annotations

import copy
import logging
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from .config import AppConfig, TimerConfig


log = logging.getLogger(__name__)


class SettingsWindow:
    """Modeless settings dialog. Reuses the existing Toplevel if already open."""

    def __init__(self, parent: tk.Tk, on_save: Callable[[AppConfig], None]):
        self._parent = parent
        self._on_save = on_save
        self._window: Optional[tk.Toplevel] = None
        self._working: Optional[AppConfig] = None

        # Widgets bound to working state.
        self._tree: Optional[ttk.Treeview] = None
        self._global_var: Optional[tk.BooleanVar] = None
        self._autostart_var: Optional[tk.BooleanVar] = None

    # ---- public ------------------------------------------------------

    def open(self, config: AppConfig) -> None:
        """Show the settings window. Must run on the Tk main thread."""
        if self._window is not None:
            try:
                self._window.deiconify()
                self._window.lift()
                self._window.focus_force()
                return
            except tk.TclError:
                self._window = None

        self._working = copy.deepcopy(config)
        self._build()

    # ---- build -------------------------------------------------------

    def _build(self) -> None:
        win = tk.Toplevel(self._parent)
        self._window = win
        win.title("Wellness Timer — Settings")
        win.geometry("640x480")
        win.minsize(560, 400)

        main = ttk.Frame(win, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # Global toggles ------------------------------------------------
        toggles = ttk.Frame(main)
        toggles.pack(fill=tk.X, pady=(0, 8))

        self._global_var = tk.BooleanVar(value=self._working.global_enabled)
        ttk.Checkbutton(
            toggles, text="Enable all timers",
            variable=self._global_var,
        ).pack(side=tk.LEFT)

        self._autostart_var = tk.BooleanVar(value=self._working.start_at_login)
        ttk.Checkbutton(
            toggles, text="Start at Windows login",
            variable=self._autostart_var,
        ).pack(side=tk.LEFT, padx=16)

        # Timer list ---------------------------------------------------
        list_frame = ttk.LabelFrame(main, text="Timers", padding=8)
        list_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("name", "interval", "enabled", "message")
        tree = ttk.Treeview(list_frame, columns=columns, show="headings",
                            selectmode="browse")
        tree.heading("name", text="Name")
        tree.heading("interval", text="Every (min)")
        tree.heading("enabled", text="On")
        tree.heading("message", text="Message")
        tree.column("name", width=140, anchor=tk.W)
        tree.column("interval", width=80, anchor=tk.CENTER)
        tree.column("enabled", width=50, anchor=tk.CENTER)
        tree.column("message", width=280, anchor=tk.W)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=sb.set)
        tree.bind("<Double-1>", lambda _e: self._edit_selected())

        self._tree = tree
        self._refresh_tree()

        # Action buttons -----------------------------------------------
        actions = ttk.Frame(main)
        actions.pack(fill=tk.X, pady=8)
        ttk.Button(actions, text="Add…",
                   command=self._add_timer).pack(side=tk.LEFT)
        ttk.Button(actions, text="Edit…",
                   command=self._edit_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Delete",
                   command=self._delete_selected).pack(side=tk.LEFT)

        ttk.Button(actions, text="Cancel",
                   command=self._cancel).pack(side=tk.RIGHT)
        ttk.Button(actions, text="Save",
                   command=self._save).pack(side=tk.RIGHT, padx=4)

        win.protocol("WM_DELETE_WINDOW", self._cancel)
        win.after(50, lambda: win.focus_force())

    # ---- tree state --------------------------------------------------

    def _refresh_tree(self) -> None:
        assert self._tree is not None and self._working is not None
        for row in self._tree.get_children():
            self._tree.delete(row)
        for i, t in enumerate(self._working.timers):
            self._tree.insert(
                "", tk.END, iid=str(i),
                values=(t.name, t.interval_minutes,
                        "✓" if t.enabled else "—", t.message),
            )

    def _selected_index(self) -> Optional[int]:
        assert self._tree is not None
        sel = self._tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    # ---- timer CRUD --------------------------------------------------

    def _add_timer(self) -> None:
        assert self._working is not None
        result = _TimerEditor(self._window,
                              TimerConfig("New Timer", 30, "Reminder", True)).run()
        if result is not None:
            self._working.timers.append(result)
            self._refresh_tree()

    def _edit_selected(self) -> None:
        assert self._working is not None
        idx = self._selected_index()
        if idx is None or idx >= len(self._working.timers):
            return
        current = copy.deepcopy(self._working.timers[idx])
        result = _TimerEditor(self._window, current).run()
        if result is not None:
            self._working.timers[idx] = result
            self._refresh_tree()

    def _delete_selected(self) -> None:
        assert self._working is not None
        idx = self._selected_index()
        if idx is None or idx >= len(self._working.timers):
            return
        name = self._working.timers[idx].name
        if messagebox.askyesno("Delete timer",
                               f"Delete timer “{name}”?", parent=self._window):
            del self._working.timers[idx]
            self._refresh_tree()

    # ---- commit/cancel ----------------------------------------------

    def _save(self) -> None:
        assert self._working is not None
        try:
            for t in self._working.timers:
                t.validate()
        except ValueError as e:
            messagebox.showerror("Invalid timer", str(e), parent=self._window)
            return
        self._working.global_enabled = bool(self._global_var.get())
        self._working.start_at_login = bool(self._autostart_var.get())
        try:
            self._on_save(self._working)
        except Exception as e:
            log.exception("on_save raised")
            messagebox.showerror("Save failed", str(e), parent=self._window)
            return
        self._close()

    def _cancel(self) -> None:
        self._close()

    def _close(self) -> None:
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None


class _TimerEditor:
    """Modal editor for a single TimerConfig."""

    def __init__(self, parent: Optional[tk.Misc], initial: TimerConfig):
        self._parent = parent
        self._initial = initial
        self._result: Optional[TimerConfig] = None

    def run(self) -> Optional[TimerConfig]:
        dlg = tk.Toplevel(self._parent)
        dlg.title("Edit Timer")
        if self._parent is not None:
            dlg.transient(self._parent)
        dlg.grab_set()
        dlg.resizable(False, False)

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Name:").grid(row=0, column=0, sticky=tk.W, pady=4)
        name_var = tk.StringVar(value=self._initial.name)
        ttk.Entry(frm, textvariable=name_var, width=36).grid(
            row=0, column=1, sticky=tk.EW, pady=4)

        ttk.Label(frm, text="Interval (minutes):").grid(
            row=1, column=0, sticky=tk.W, pady=4)
        interval_var = tk.StringVar(value=str(self._initial.interval_minutes))
        ttk.Entry(frm, textvariable=interval_var, width=10).grid(
            row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frm, text="Message:").grid(
            row=2, column=0, sticky=tk.NW, pady=4)
        msg_text = tk.Text(frm, width=36, height=4, wrap=tk.WORD)
        msg_text.grid(row=2, column=1, sticky=tk.EW, pady=4)
        msg_text.insert("1.0", self._initial.message)

        enabled_var = tk.BooleanVar(value=self._initial.enabled)
        ttk.Checkbutton(frm, text="Enabled", variable=enabled_var).grid(
            row=3, column=1, sticky=tk.W, pady=4)

        frm.columnconfigure(1, weight=1)

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, sticky=tk.E, pady=(8, 0))

        def on_ok() -> None:
            name = name_var.get().strip()
            try:
                interval = int(interval_var.get())
            except ValueError:
                messagebox.showerror(
                    "Invalid interval",
                    "Interval must be a whole number of minutes.",
                    parent=dlg)
                return
            message = msg_text.get("1.0", tk.END).rstrip("\n")
            candidate = TimerConfig(
                name=name, interval_minutes=interval,
                message=message, enabled=bool(enabled_var.get()),
            )
            try:
                candidate.validate()
            except ValueError as e:
                messagebox.showerror("Invalid timer", str(e), parent=dlg)
                return
            self._result = candidate
            dlg.destroy()

        def on_cancel() -> None:
            self._result = None
            dlg.destroy()

        ttk.Button(btns, text="OK", command=on_ok).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="Cancel", command=on_cancel).pack(side=tk.RIGHT)

        dlg.protocol("WM_DELETE_WINDOW", on_cancel)
        dlg.wait_window()
        return self._result
