# Eitaa public-channel connector (experimental)

This connector extends TelTest's existing extraction jobs and shared content database. It does **not** change Telegram collection.

## Create a job

Open the Extraction Center, choose **Eitaa** as the source, and enter a public channel handle like `@my_channel` or `https://eitaa.com/my_channel`. Select starting point and optional scheduled watch.

- Uses the public HTML view; **private channels and private messages are not supported**.
- Extracts text, hashtags, hyperlinks, post URL, published timestamp (where published), available media URLs, and metadata.
- Saves to SQLite `content_items`, `content_hashtags`, `content_links`, `extraction_job_items` and `extraction_runs`.
- Deduplicates by `(connector_code, source_key, external_id)`.
- Keeps page backlog in `extraction_jobs.config_json.backfill_before` for subsequent bounded runs.
- Scheduled jobs use the existing `scheduler_worker.py`.
- Media files are not downloaded during extraction. In the multi-destination transfer job, permitted media URLs are downloaded to temporary storage (100 MiB per media item) then sent and deleted.
- Destination support for Eitaa sources: Telegram bot, Bale, EitaaYar, Rubika; Telegram user destination is intentionally not yet implemented.

## Deploy

```bash
git pull
pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_eitaa*.py'
```

Restart the Gunicorn application and scheduler service after backing up `/var/lib/teltest/data/teltest.sqlite3`. Do not commit runtime `.env` files or sessions.

## Operational caveats

Eitaa's public HTML layout is unofficial and may change. Run a small extraction against a known public channel before production and verify media endpoints. Some video/document links might be unavailable in public HTML. Media downloads permit only HTTPS hosts at `eitaa.com` or subdomains; off-site CDN links are intentionally ignored. The parser does not claim 100% coverage of all media types. Avoid high-frequency polling.
