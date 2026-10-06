# TelTest Architecture V2

## Core Rule

Extraction and Transfer are independent systems.

```text
Source Connector
    ↓
Extraction Job
    ↓
Unified Content Item
    ↓
Content Library
    ↓
Transfer Job
    ↓
One or More Destinations
```

## Source Connectors

Current:

- Telegram — enabled

Registered for future implementation:

- Instagram
- YouTube
- TikTok
- Pinterest
- News Sites
- Websites
- RSS

Future connectors are visible in the registry but are not selectable.

## Extraction

An Extraction Job owns:

- source connector
- source account
- source reference
- start strategy
- cursor
- watch state
- polling interval
- extraction rules

It does not know anything about destinations.

## Content

All connectors normalize their output into `content_items`.

Important fields:

- connector
- source identity
- external content ID
- published time
- raw text
- processed text
- media metadata
- source metadata
- content hash

Raw content must remain available after processing.

## Transfer

A Transfer Job selects content independently.

Selectors may later include:

- Extraction Job
- Source
- Search
- Hashtag
- Saved Search
- Manual Selection

One Transfer Job can have many destinations.

## Legacy

The old `jobs` and `posts` tables remain intact during migration.

`legacy_job_map` connects old jobs to:

- extraction_jobs
- transfer_jobs

No destructive conversion is performed in Stage 05.
