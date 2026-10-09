# TelTest Stage 11 — Content Library & Search

## Goals

Stage 11 provides a low-resource searchable content archive.

No Redis, Elasticsearch or OpenSearch is required.

## Search engine

SQLite FTS5 is used.

Indexed fields:

- raw_text
- processed_text
- source_title
- external_id

The index uses external content mode with `content_items`.

SQLite triggers automatically update the FTS index when watched
sources insert or modify content.

## Filters

Supported filters:

- search text
- connector
- source
- hashtag
- content type
- media / text only
- has link / no link
- Jalali start date
- Jalali end date
- extraction job
- newest / oldest / relevance

## Pagination

Pagination is server-side.

Default page size:

24

Maximum page size:

100

This prevents the browser and backend from loading the complete
content archive on every request.

## Saved Search

A user may save the current filter state.

Saved searches store filters only, not copies of content.

Therefore saved searches consume very little disk space.

## Resource strategy

- SQLite FTS5
- server-side pagination
- no resident search process
- no additional database service
- automatic index triggers
