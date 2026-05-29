# Security Policy

## Reporting a Vulnerability

Please report security issues privately via GitHub Security Advisories:
https://github.com/jmeeler24/WellnessTimer/security/advisories/new

I'll acknowledge within a week on a best-effort basis (this is a hobby
project — no SLA). Please don't open a public issue for security reports.

## Scope

WellnessTimer is a local Windows tray app with no network calls and no
remote services. In-scope concerns:

- Config-file parsing (`%APPDATA%\WellnessTimer\config.json`)
- Registry writes (HKCU `Run` key for autostart)
- Toast XML construction (winrt notifications)
- Lock-state detection (WTS session listener on a message-only window)

Out of scope: anything requiring physical access to an already-unlocked
Windows session, or social-engineering an admin install.
