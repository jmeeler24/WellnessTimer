"""Detect whether the Windows session is locked.

Subscribes to Windows' ``WM_WTSSESSION_CHANGE`` notifications via
``WTSRegisterSessionNotification`` on a hidden message-only window pumped
from a daemon thread. ``is_locked()`` reads a thread-safe flag set by the
event handler.

Why event-driven instead of polling:
  - ``OpenInputDesktop`` returned "unlocked" in this process while the screen
    was actually locked (verified empirically — the suppression failed and
    notifications accumulated).
  - ``WTSQuerySessionInformation(SessionInfoEx)`` ``SessionFlags`` has a
    documented LOCK/UNLOCK semantics inversion across Windows versions; on
    this machine it reports "locked" while unlocked.
  - ``WTSRegisterSessionNotification`` is the only Microsoft-documented
    mechanism that reliably and unambiguously reports lock state changes.

The listener thread is started lazily on the first ``is_locked()`` call (or
eagerly via ``start()``). It runs as a daemon and dies with the process.

Initial state is assumed UNLOCKED: a user has to be unlocked to launch the
app or for autostart-at-login to fire it, so this is a safe default.

Fail-open: on any setup error, ``is_locked()`` returns False — better to
show a reminder than to silently stop showing them.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import sys
import threading
from typing import Optional


log = logging.getLogger(__name__)

# --- Win32 constants ------------------------------------------------------
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0
# CreateWindowEx parent sentinel for message-only windows.
HWND_MESSAGE = -3

# --- module state guarded by _state_lock ---------------------------------
_state_lock = threading.Lock()
_locked = False
_listener_thread: Optional[threading.Thread] = None
_listener_failed = False

# WNDPROC signature: LRESULT CALLBACK (HWND, UINT, WPARAM, LPARAM)
_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM
)

# Keep the trampoline alive at module scope (a GC'd WNDPROC would crash
# the message pump as soon as a message arrives).
_wndproc_holder: Optional["_WNDPROC"] = None


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hWnd", wt.HWND),
        ("message", wt.UINT),
        ("wParam", wt.WPARAM),
        ("lParam", wt.LPARAM),
        ("time", wt.DWORD),
        ("pt", wt.POINT),
    ]


# --- public API ----------------------------------------------------------

def start() -> None:
    """Eagerly start the session-change listener. Idempotent."""
    if not sys.platform.startswith("win"):
        return
    _ensure_started()


def is_locked() -> bool:
    """Return True iff the Windows session is currently locked."""
    if not sys.platform.startswith("win"):
        return False
    _ensure_started()
    with _state_lock:
        return _locked


# --- internals -----------------------------------------------------------

def _ensure_started() -> None:
    global _listener_thread
    with _state_lock:
        if _listener_thread is not None or _listener_failed:
            return
        _listener_thread = threading.Thread(
            target=_listener_loop, name="LockListener", daemon=True
        )
        _listener_thread.start()


def _set_locked(value: bool) -> None:
    global _locked
    changed = False
    with _state_lock:
        if _locked != value:
            _locked = value
            changed = True
    if changed:
        log.info("Session %s", "LOCKED" if value else "UNLOCKED")


def _mark_failed() -> None:
    global _listener_failed
    with _state_lock:
        _listener_failed = True


def _listener_loop() -> None:
    """Create a message-only window, register for WTS session-change
    notifications, and pump messages forever on this thread."""
    global _wndproc_holder
    try:
        user32 = ctypes.windll.user32
        wtsapi32 = ctypes.windll.wtsapi32
        kernel32 = ctypes.windll.kernel32

        user32.DefWindowProcW.restype = ctypes.c_long
        user32.DefWindowProcW.argtypes = [
            wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM,
        ]
        user32.RegisterClassW.restype = ctypes.c_ushort  # ATOM
        user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
        user32.CreateWindowExW.restype = wt.HWND
        user32.CreateWindowExW.argtypes = [
            wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
        ]
        user32.GetMessageW.restype = ctypes.c_int
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(_MSG), wt.HWND, wt.UINT, wt.UINT,
        ]
        user32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
        wtsapi32.WTSRegisterSessionNotification.restype = wt.BOOL
        wtsapi32.WTSRegisterSessionNotification.argtypes = [
            wt.HWND, wt.DWORD,
        ]

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_WTSSESSION_CHANGE:
                log.info("WTS session-change event: wparam=%d", wparam)
                if wparam == WTS_SESSION_LOCK:
                    _set_locked(True)
                elif wparam == WTS_SESSION_UNLOCK:
                    _set_locked(False)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        _wndproc_holder = _WNDPROC(wndproc)

        cls = _WNDCLASSW()
        cls.lpfnWndProc = _wndproc_holder
        cls.hInstance = kernel32.GetModuleHandleW(None)
        cls.lpszClassName = "WellnessTimerLockListener"

        atom = user32.RegisterClassW(ctypes.byref(cls))
        if not atom:
            log.error("RegisterClassW failed, last_error=%d",
                      kernel32.GetLastError())
            _mark_failed()
            return

        hwnd = user32.CreateWindowExW(
            0, cls.lpszClassName, "WellnessTimerLockListener", 0,
            0, 0, 0, 0,
            HWND_MESSAGE, None, cls.hInstance, None,
        )
        if not hwnd:
            log.error("CreateWindowExW failed, last_error=%d",
                      kernel32.GetLastError())
            _mark_failed()
            return

        if not wtsapi32.WTSRegisterSessionNotification(
                hwnd, NOTIFY_FOR_THIS_SESSION):
            log.error("WTSRegisterSessionNotification failed, last_error=%d",
                      kernel32.GetLastError())
            _mark_failed()
            return

        log.info("Lock listener started (hwnd=%#x); pumping messages", hwnd)

        msg = _MSG()
        while True:
            rc = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if rc <= 0:
                # 0 = WM_QUIT, -1 = error; either way, stop.
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    except Exception:
        log.exception("Lock listener crashed; assuming unlocked from now on")
        _mark_failed()
