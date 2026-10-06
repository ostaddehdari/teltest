# TelTest

Flask + Telethon control panel.

## Current version

`v0.3.0`

## URL

`https://srun.ir/teltest/`

## Stage 01

- Flask
- Login
- Single Page Dashboard
- Nginx
- Gunicorn/systemd

## Stage 02

- Telegram API settings
- Multi-account Telethon sessions
- Phone verification
- Telegram 2FA
- Channel/group discovery

## Stage 03

- Create Jobs
- Select connected Telegram account
- Source by username, t.me link or known Telegram ID
- Auto-join source channel when required
- Private invite link support
- Destination resolution
- Extract up to 5000 recent messages
- Save extracted posts to SQLite
- No-save extraction mode
- Extraction timing
- Job history
- Extracted posts UI

## Runtime data

Sensitive data is outside Git:

- `/var/lib/teltest/data`
- `/var/lib/teltest/sessions`
- `/var/lib/teltest/locks`
- `/etc/teltest/teltest.env`

## Next

Stage 04 adds:

- Native Forward
- Copy without forward attribution
- Transfer timer
- FloodWait retry/resume
