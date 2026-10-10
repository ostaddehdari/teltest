# TelTest Stage 12 — Transfer Query Builder

## Selector types

A Transfer Job can select content by:

- Extraction Job
- Source
- Hashtag
- Search / Content Library filters
- Saved Search
- Manual content selection

## Architecture

Transfer Jobs no longer require a direct Extraction Job relationship.

The job stores:

- selector_type
- selector_json

The selector is resolved into content IDs when the transfer plan is synchronized.

## Dynamic selectors

Source, hashtag, search and saved-search selectors are dynamic.

If new matching content arrives later, running or refreshing the job can add
new content to the transfer plan with `INSERT OR IGNORE`.

Previously transferred items are not duplicated because
`transfer_job_items` has a unique key for:

- transfer_job_id
- destination_id
- content_id

## Multiple Telegram sources

For query results containing several Telegram sources, pending items are
grouped by source before transmission.

The system therefore does not assume that every item belongs to the same
Telegram channel.

## Current source support

Actual extraction source transfer currently supports Telegram content.

Future Instagram, YouTube, TikTok, Pinterest, News and Web connectors must
provide their own source/media adapters before their content can be delivered.

## Resource policy

- selector resolution uses SQLite
- no new daemon
- no Redis
- no Elasticsearch
- maximum manual selection: 5000 items
- maximum dynamic selector plan: 50000 items
