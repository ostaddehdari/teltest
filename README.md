# TelTest

Single-page Flask + Telethon control panel.

## URL

`https://srun.ir/teltest/`

## Current Version

`v0.2.0`

## Completed

### Stage 01

- Flask application
- Login without user database
- RTL single-page dashboard
- Nginx `/teltest`
- Gunicorn + systemd

### Stage 02

- Telegram API ID / API Hash settings
- Add Telegram account by phone
- Send verification code
- Verify login code
- Telegram 2FA support
- Persistent Telethon session per account
- Discover channels and groups
- Refresh dialogs
- Multiple Telegram accounts

## Runtime storage

Sensitive runtime data is outside Git:

- Database: `/var/lib/teltest/data/`
- Telethon sessions: `/var/lib/teltest/sessions/`
- Environment: `/etc/teltest/teltest.env`

Telegram API Hash and session files must not be committed.

## Next

Stage 03:

- Jobs
- Source channel
- Join source
- Destination channel
- Message extraction
- Optional post persistence
