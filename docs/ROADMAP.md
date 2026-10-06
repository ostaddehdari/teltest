# TelTest New Roadmap

## Stage 05 — Core Architecture Split

- 05.1 Baseline Freeze / Backup
- 05.2 Extraction Job Model
- 05.3 Transfer Job Model
- 05.4 Unified Content Model
- 05.5 Legacy Data Migration
- 05.6 Legacy Compatibility

Target: v0.5.x

## Stage 06 — UI / Design System

- Bootstrap 5
- Vazirmatn
- Font Awesome
- Light gradient theme
- Mobile-first navigation
- Extraction / Transfer split navigation

Target: v0.6.x

## Stage 07 — Connector Framework

- Source Connector Registry
- Connector interface
- Capabilities
- Connector health
- Disabled future sources

Target: v0.7.x

## Stage 08 — Telegram Extractor V2

- Telegram-only extraction
- Source ID
- Persian date picker
- Start from Message ID
- Incremental cursor
- Full persistence

Target: v0.8.x

## Stage 09 — Content Rules

- Raw / processed text
- Hashtags
- Links
- Exclusion rules
- Link removal
- Prefix / suffix rules

## Stage 10 — Scheduler

- Watching jobs
- Every N minutes
- Cron expressions
- next_run_at
- retry / backoff
- lightweight systemd worker

## Stage 11 — Content Library

- Search
- SQLite FTS5
- source filters
- hashtags
- dates
- types
- saved searches

## Stage 12 — Transfer Job Builder

- Extraction Job selector
- Search selector
- Hashtag selector
- manual selector
- multiple destinations

## Stage 13 — Provider Registry

- Telegram
- Bale
- Eitaa
- Rubika
- provider accounts
- credentials

## Stage 14 — Delivery Engine

- duplicate protection
- retry
- resume
- provider rate limits
- benchmarks

## Stage 15 — Future Sources

- Instagram
- YouTube
- TikTok
- Pinterest
- News
- Web
- RSS

## Stage 16 — Production v1

- DB tuning
- media cache TTL
- retention
- security
- CPU/RAM limits
- production verification
