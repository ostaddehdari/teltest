# TelTest

Flask + Telethon Telegram job control panel.

Current version:

`v0.4.0`

Public URL:

`https://srun.ir/teltest/`

## Stage 01

Flask, authentication, dashboard, nginx, systemd.

## Stage 02

Telegram API settings, Telethon accounts, verification,
persistent sessions, channel/group discovery.

## Stage 03

Job creation, source resolution, auto join, extraction,
optional SQLite persistence, per-job logs.

## Stage 04

Real Telegram transfer:

- Native Forward
- Copy without Forward Header
- Transfer progress
- Transfer timer
- Messages per second
- Per-message transfer state
- FloodWait handling
- Resume from pending item
- Job transfer logs

Runtime data remains outside Git:

- `/var/lib/teltest/data`
- `/var/lib/teltest/sessions`
- `/var/lib/teltest/locks`
- `/etc/teltest/teltest.env`
