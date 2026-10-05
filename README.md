# TelTest

A lightweight Flask + Telethon control panel deployed at `https://srun.ir/teltest/`.

## Current version

`v0.1.0` — Stage 01 complete.

### Stage 01

- Flask application foundation
- Simple session login without a user database
- Single-page RTL dashboard with sidebar
- Nginx reverse proxy under `/teltest`
- systemd + Gunicorn deployment
- Health endpoint at `/teltest/health`

## Roadmap

1. Stage 01 — Flask/UI/Auth
2. Stage 02 — Telethon accounts, phone verification, sessions, channel discovery
3. Stage 03 — Jobs, source/destination, join, extraction, optional SQLite storage
4. Stage 04 — Forward/copy engine, benchmark timer, FloodWait/retry
5. Stage 05 — History, live logs, settings, production hardening

Secrets and Telegram session files are intentionally excluded from Git.
