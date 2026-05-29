# Wellness Timer

A lightweight Windows 10/11 system-tray app that fires native toast
notifications for hydration, posture, movement, and eye-rest breaks.
Distributed as a single self-contained `.exe`.

## Download

Grab the latest `WellnessTimer.exe` from the
[Releases](../../releases/latest) page. Run it directly — no installer
required.

## Features

- Pre-configured wellness timers (hydration / posture / movement / 20-20-20)
- Custom timers with editable name, interval, message, and on/off toggle
- Native Windows toast notifications (winrt direct, winotify fallback)
- **Suppressed while the screen is locked** so reminders don't pile up
  while you're away from your machine
- **Auto-cleaned from the Action Center** after 5 minutes — stale wellness
  nudges don't accumulate in the notification list
- System-tray icon with right-click menu: settings, pause/resume, snooze
  all (15 min), about, quit
- Tkinter settings window — no extra UI dependency
- Optional autostart at Windows login (HKCU `Run` key)
- Config persisted as JSON in `%APPDATA%\WellnessTimer\config.json`

## Project layout

```
wellness_timer/
├── main.py              # Entry point: tray icon + lifecycle
├── notifier.py          # Toast notification wrapper (winrt direct)
├── lock_state.py        # WTS session-change listener
├── settings_ui.py       # Tkinter settings window
├── config.py            # Config load/save + defaults
├── scheduler.py         # Threaded repeating timers
├── autostart.py         # Windows registry autostart helper
├── assets/icon.ico      # Tray + window icon
├── requirements.txt
└── build.spec           # PyInstaller spec
```

## Run from source

Requires Python 3.10+ (tested on 3.13 and 3.14).

```powershell
cd wellness_timer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

The app starts minimized to the system tray. Left-click the tray icon to
open settings; right-click for the full menu.

## Build the executable

From the `wellness_timer` directory:

```powershell
pip install -r requirements.txt
pyinstaller build.spec
```

The output is `dist\WellnessTimer.exe` — a single-file, no-console
executable around 22 MB. Run it directly; no installer required.

To get a smaller binary, ensure UPX is on `PATH` (PyInstaller picks it up
automatically; the spec leaves `upx=True`).

The same build is reproduced in CI on every `v*` tag — see
`.github/workflows/release.yml`.

## Autostart at login

Two ways:
1. Tick **Start at Windows login** in the settings window and click Save.
2. Or set it manually — the app reconciles the registry on every save
   and on launch.

The autostart entry lives at:
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run\WellnessTimer`

To remove it: untick the setting and save, or delete the value with
`reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v WellnessTimer`.

## Config location

`%APPDATA%\WellnessTimer\config.json`

If the file is corrupt at load time, it is renamed to `config.json.bak`
and fresh defaults are written. Logs go to `wellness_timer.log` in the
same directory.

## Uninstall

1. Disable autostart (see above) or delete the registry value.
2. Delete `WellnessTimer.exe`.
3. Optionally delete `%APPDATA%\WellnessTimer\` to remove config and logs.

## Notes on notifications

- The toast header reads **Wellness Timer**, which is also used as the
  AppUserModelID. Notifications respect Windows' notification settings for
  that app (right-click any reminder → *Notification settings* to adjust).
- Toasts include an `expiration_time` of 5 minutes — Windows removes
  them from the Action Center automatically after that.
- Reminders are skipped entirely while the workstation is locked
  (detected via `WTSRegisterSessionNotification`). The next reminder
  after unlock fires on its normal interval; nothing queues.
- On non-Windows hosts the notifier degrades to a no-op stub so the
  rest of the app can still be developed and tested.
