import asyncio
import io
import json
import os
import re
import time

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, request, send_file
from telethon import errors

from job_engine import (
    account_lock,
    clean_ref,
    db_connect,
    resolve_destination,
    resolve_source,
)
from telegram_extractor_v2 import parse_persian_date
from provider_destinations import (
    PROVIDERS,
    normalize_provider,
    provider_is_configured,
    run_destination,
    validate_destination_payload,
)


BASE_PATH = "/teltest"
OPERATIONS_VERSION = "2"
RUNTIME_ROOT = Path(os.getenv("TELTEST_RUNTIME_ROOT", "/var/lib/teltest"))
MEDIA_ROOT = RUNTIME_ROOT / "media-cache"
HASHTAG_PATTERN = re.compile(
    r"(?<![\w\u200c])#([\w\u0600-\u06ff\u0750-\u077f\u200c]+)",
    re.UNICODE,
)


def json_dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_load(value, default=None):
    if default is None:
        default = {}
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def json_body():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def init_operations_schema():
    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    with closing(db_connect()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS operation_job_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_kind TEXT NOT NULL,
                job_id INTEGER NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                event TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_operation_logs_job
                ON operation_job_logs(job_kind, job_id, id DESC);

            CREATE TABLE IF NOT EXISTS transfer_job_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transfer_job_id INTEGER NOT NULL,
                destination_id INTEGER NOT NULL,
                content_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'listed',
                attempts INTEGER NOT NULL DEFAULT 0,
                destination_external_id TEXT,
                last_error TEXT,
                started_at TEXT,
                transferred_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(transfer_job_id) REFERENCES transfer_jobs(id) ON DELETE CASCADE,
                FOREIGN KEY(destination_id) REFERENCES transfer_destinations(id) ON DELETE CASCADE,
                FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE CASCADE,
                UNIQUE(transfer_job_id, destination_id, content_id)
            );

            CREATE INDEX IF NOT EXISTS idx_transfer_job_items_status
                ON transfer_job_items(transfer_job_id, status, id);

            CREATE TABLE IF NOT EXISTS transfer_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transfer_job_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                listed_count INTEGER NOT NULL DEFAULT 0,
                transferred_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                elapsed_seconds REAL,
                error_text TEXT,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                FOREIGN KEY(transfer_job_id) REFERENCES transfer_jobs(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_transfer_runs_job
                ON transfer_runs(transfer_job_id, id DESC);
            """
        )
        conn.execute(
            """
            INSERT INTO schema_meta(key, value, updated_at)
            VALUES('operations_center_version', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value, updated_at=CURRENT_TIMESTAMP
            """,
            (OPERATIONS_VERSION,),
        )
        conn.commit()


def log_job(kind, job_id, event, message, level="info"):
    with closing(db_connect()) as conn:
        conn.execute(
            """
            INSERT INTO operation_job_logs(job_kind, job_id, level, event, message)
            VALUES(?, ?, ?, ?, ?)
            """,
            (kind, int(job_id), level, str(event)[:100], str(message)[:4000]),
        )
        conn.commit()


def hashtags_from_text(text):
    found = []
    seen = set()
    for match in HASHTAG_PATTERN.finditer(str(text or "")):
        tag = match.group(1).strip("_\u200c")
        normalized = tag.replace("\u200c", "").casefold()
        if tag and normalized and normalized not in seen:
            seen.add(normalized)
            found.append((f"#{tag}", normalized))
    return found


def sync_hashtags(conn, content_id, text):
    conn.execute("DELETE FROM content_hashtags WHERE content_id = ?", (content_id,))
    for hashtag, normalized in hashtags_from_text(text):
        conn.execute(
            """
            INSERT OR IGNORE INTO content_hashtags
                (content_id, hashtag, normalized_hashtag)
            VALUES(?, ?, ?)
            """,
            (content_id, hashtag, normalized),
        )


def bootstrap_hashtags():
    with closing(db_connect()) as conn:
        rows = conn.execute("SELECT id, raw_text FROM content_items").fetchall()
        for row in rows:
            sync_hashtags(conn, row["id"], row["raw_text"])
        conn.commit()
    return len(rows)


def public_post_url(source_ref, source_key, external_id):
    source = str(source_ref or "").strip()
    message_id = str(external_id or "").strip()
    username = None
    if source.startswith("@"):
        username = source[1:].split("/")[0]
    else:
        match = re.search(r"(?:https?://)?t\.me/(?!\+|joinchat/)([A-Za-z0-9_]+)", source)
        if match:
            username = match.group(1)
    if username and message_id.isdigit():
        return f"https://t.me/{username}/{message_id}"
    key = str(source_key or "")
    if key.startswith("-100") and message_id.isdigit():
        return f"https://t.me/c/{key[4:]}/{message_id}"
    return None


def hashtag_rows(conn, content_id):
    return [
        row["hashtag"]
        for row in conn.execute(
            """
            SELECT hashtag FROM content_hashtags
            WHERE content_id = ? ORDER BY normalized_hashtag
            """,
            (content_id,),
        ).fetchall()
    ]


def link_rows(conn, content_id):
    return [
        {
            "url": row["url"],
            "domain": row["domain"],
            "link_text": row["link_text"],
        }
        for row in conn.execute(
            """
            SELECT url, domain, link_text
            FROM content_links
            WHERE content_id = ?
            ORDER BY id
            """,
            (content_id,),
        ).fetchall()
    ]


def content_payload(conn, row, transfer_status=None):
    item = dict(row)
    item["hashtags"] = hashtag_rows(conn, item["id"])
    item["links"] = link_rows(conn, item["id"])
    item["media"] = json_load(item.pop("media_json", "[]"), [])
    item["metadata"] = json_load(item.pop("metadata_json", "{}"), {})
    item["original_url"] = public_post_url(
        item.get("source_ref"), item.get("source_key"), item.get("external_id")
    )
    item["download_url"] = f"{BASE_PATH}/api/v2/content-items/{item['id']}/download"
    if transfer_status is not None:
        item["transfer_status"] = transfer_status
    return item


def list_logs(conn, kind, job_id, legacy_job_id=None):
    rows = conn.execute(
        """
        SELECT id, level, event, message, created_at
        FROM operation_job_logs
        WHERE job_kind = ? AND job_id = ?
        ORDER BY id DESC LIMIT 150
        """,
        (kind, job_id),
    ).fetchall()
    logs = [dict(row) for row in rows]
    if legacy_job_id:
        legacy = conn.execute(
            """
            SELECT id, level, event, message, created_at
            FROM job_logs WHERE job_id = ? ORDER BY id DESC LIMIT 150
            """,
            (legacy_job_id,),
        ).fetchall()
        logs.extend({**dict(row), "legacy": True} for row in legacy)
        logs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        logs = logs[:150]
    return logs


def extraction_row(conn, job_id):
    return conn.execute("SELECT * FROM extraction_jobs WHERE id = ?", (job_id,)).fetchone()


def transfer_row(conn, job_id):
    return conn.execute("SELECT * FROM transfer_jobs WHERE id = ?", (job_id,)).fetchone()


def sync_transfer_plan(conn, transfer_job_id):
    job = transfer_row(conn, transfer_job_id)
    if not job:
        return 0
    selector = json_load(job["selector_json"], {})
    extraction_job_id = selector.get("extraction_job_id")
    if not extraction_job_id:
        return 0
    destinations = conn.execute(
        "SELECT id FROM transfer_destinations WHERE transfer_job_id = ? AND enabled = 1",
        (transfer_job_id,),
    ).fetchall()
    contents = conn.execute(
        """
        SELECT content_id
        FROM extraction_job_items
        WHERE
            extraction_job_id = ?
            AND COALESCE(excluded, 0) = 0
        """,
        (extraction_job_id,),
    ).fetchall()
    for destination in destinations:
        for content in contents:
            conn.execute(
                """
                INSERT OR IGNORE INTO transfer_job_items
                    (transfer_job_id, destination_id, content_id, status)
                VALUES(?, ?, ?, 'listed')
                """,
                (transfer_job_id, destination["id"], content["content_id"]),
            )
    return len(destinations) * len(contents)


def transfer_counts(conn, job_id):
    result = {"listed": 0, "transferring": 0, "transferred": 0, "failed": 0, "skipped": 0}
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS n FROM transfer_job_items
        WHERE transfer_job_id = ? GROUP BY status
        """,
        (job_id,),
    ).fetchall()
    for row in rows:
        result[row["status"]] = row["n"]
    result["total"] = sum(result.values())
    return result


def destination_payloads(conn, job_id):
    rows = conn.execute(
        """
        SELECT td.*,
               SUM(CASE WHEN tji.status='listed' THEN 1 ELSE 0 END) AS listed_count,
               SUM(CASE WHEN tji.status='transferring' THEN 1 ELSE 0 END) AS transferring_count,
               SUM(CASE WHEN tji.status='transferred' THEN 1 ELSE 0 END) AS transferred_count,
               SUM(CASE WHEN tji.status='failed' THEN 1 ELSE 0 END) AS failed_count,
               SUM(CASE WHEN tji.status='skipped' THEN 1 ELSE 0 END) AS skipped_count,
               COUNT(tji.id) AS total_count
        FROM transfer_destinations td
        LEFT JOIN transfer_job_items tji ON tji.destination_id=td.id
        WHERE td.transfer_job_id=?
        GROUP BY td.id ORDER BY td.position, td.id
        """,
        (job_id,),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["rules"] = json_load(
            item.pop("rules_json", "{}"),
            {},
        )
        code = normalize_provider(item["provider_code"])
        item["provider_code"] = code
        item["provider_label"] = PROVIDERS.get(code, {}).get("short_label", code)
        item["configured"] = provider_is_configured(code)
        item["counts"] = {
            "listed": item.pop("listed_count") or 0,
            "transferring": item.pop("transferring_count") or 0,
            "transferred": item.pop("transferred_count") or 0,
            "failed": item.pop("failed_count") or 0,
            "skipped": item.pop("skipped_count") or 0,
            "total": item.pop("total_count") or 0,
        }
        items.append(item)
    return items


def insert_destinations(conn, job_id, destinations):
    ids = []
    for index, destination in enumerate(destinations, start=1):
        cursor = conn.execute(
            """
            INSERT INTO transfer_destinations(
                transfer_job_id, provider_code, provider_account_id,
                destination_ref, mode, enabled, position,
                rules_json, status
            ) VALUES(?, ?, ?, ?, ?, 1, ?, ?, 'pending')
            """,
            (
                job_id,
                destination["provider_code"],
                destination["provider_account_id"],
                destination["destination_ref"],
                destination["mode"],
                index * 10,
                json_dump(
                    destination.get(
                        "rules",
                        {},
                    )
                ),
            ),
        )
        ids.append(cursor.lastrowid)
    return ids


async def download_telegram_media(client, source_ref, message_id, output_dir):
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Session تلگرام مجاز نیست.")
        entity, _joined = await resolve_source(client, source_ref)
        message = await client.get_messages(entity, ids=int(message_id))
        if not message:
            raise RuntimeError("پیام اصلی در تلگرام پیدا نشد.")
        if not getattr(message, "media", None):
            return None
        output_dir.mkdir(parents=True, exist_ok=True)
        result = await client.download_media(message, file=str(output_dir))
        return Path(result).resolve() if result else None
    finally:
        await client.disconnect()


async def execute_transfer(client, source_ref, destination_ref, mode, rows, mark):
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Session تلگرام مجاز نیست.")
        source, _joined = await resolve_source(client, source_ref)
        destination = await resolve_destination(client, destination_ref)
        ids = [int(row["external_id"]) for row in rows if str(row["external_id"]).isdigit()]
        messages = await client.get_messages(source, ids=ids) if ids else []
        if not isinstance(messages, (list, tuple)):
            messages = [messages]
        message_map = {int(item.id): item for item in messages if item and getattr(item, "id", None)}
        for row in rows:
            item_id = row["transfer_item_id"]
            message_id = int(row["external_id"]) if str(row["external_id"]).isdigit() else None
            message = message_map.get(message_id) if message_id else None
            if message is None:
                mark(item_id, "skipped", error="پیام اصلی پیدا نشد.")
                continue
            mark(item_id, "transferring")
            try:
                if mode == "forward":
                    sent = await client.forward_messages(destination, message, from_peer=source)
                elif mode == "copy":
                    sent = await client.send_message(destination, message)
                else:
                    raise RuntimeError("روش انتقال معتبر نیست.")
                if isinstance(sent, (list, tuple)):
                    sent = sent[0] if sent else None
                mark(item_id, "transferred", destination_external_id=getattr(sent, "id", None))
            except errors.FloodWaitError:
                mark(item_id, "failed", error="Telegram FloodWait")
                raise
            except Exception as exc:
                mark(item_id, "failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        await client.disconnect()


def init_operations_center(app, login_required, api_post_required, telegram_client, account_get):
    init_operations_schema()
    migrated_hashtags = bootstrap_hashtags()

    @app.get(f"{BASE_PATH}/api/v2/operations/summary")
    @login_required
    def operations_summary():
        with closing(db_connect()) as conn:
            counts = {
                name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in ("extraction_jobs", "transfer_jobs", "content_items", "content_hashtags")
            }
            counts["transferred_items"] = conn.execute(
                "SELECT COUNT(*) FROM transfer_job_items WHERE status='transferred'"
            ).fetchone()[0]
        return jsonify(ok=True, counts=counts, migrated_hashtags=migrated_hashtags)

    @app.get(f"{BASE_PATH}/api/v2/content-library")
    @login_required
    def content_library():
        query = str(request.args.get("q") or "").strip()
        job_id = request.args.get("extraction_job_id", type=int)
        params = []
        where = []
        join = ""
        if job_id:
            join = "INNER JOIN extraction_job_items eji ON eji.content_id = ci.id"
            where.append("eji.extraction_job_id = ?")
            params.append(job_id)
        if query:
            where.append("(ci.raw_text LIKE ? OR ci.source_title LIKE ? OR ci.external_id LIKE ?)")
            token = f"%{query}%"
            params.extend((token, token, token))
        clause = "WHERE " + " AND ".join(where) if where else ""
        with closing(db_connect()) as conn:
            rows = conn.execute(
                f"""
                SELECT ci.id, ci.connector_code, ci.source_key, ci.source_ref,
                       ci.source_title, ci.external_id, ci.published_at,
                       ci.content_type, ci.raw_text, ci.processed_text,
                       ci.media_json, ci.metadata_json,
                       ci.created_at, ci.updated_at
                FROM content_items ci {join} {clause}
                ORDER BY ci.id DESC LIMIT 250
                """,
                params,
            ).fetchall()
            items = [content_payload(conn, row) for row in rows]
        return jsonify(ok=True, count=len(items), items=items)

    @app.get(f"{BASE_PATH}/api/v2/content-items/<int:content_id>/download")
    @login_required
    def download_content(content_id):
        with closing(db_connect()) as conn:
            row = conn.execute("SELECT * FROM content_items WHERE id = ?", (content_id,)).fetchone()
            if not row:
                return jsonify(ok=False, error="محتوا پیدا نشد."), 404
            media = json_load(row["media_json"], [])
            cached = None
            for entry in media:
                candidate = entry.get("cached_path") if isinstance(entry, dict) else None
                if candidate:
                    path = Path(candidate).resolve()
                    if path.is_file() and MEDIA_ROOT.resolve() in path.parents:
                        cached = path
                        break
            if cached:
                return send_file(cached, as_attachment=True, download_name=cached.name)

            link = conn.execute(
                """
                SELECT ej.source_account_id, ej.source_ref
                FROM extraction_job_items eji
                INNER JOIN extraction_jobs ej ON ej.id=eji.extraction_job_id
                WHERE eji.content_id=? AND ej.source_account_id IS NOT NULL
                ORDER BY ej.id DESC LIMIT 1
                """,
                (content_id,),
            ).fetchone()

        if (media or row["content_type"] != "text") and link and str(row["external_id"]).isdigit():
            account = account_get(link["source_account_id"])
            if account and account["status"] == "connected":
                try:
                    with account_lock(account["id"]):
                        downloaded = asyncio.run(
                            download_telegram_media(
                                telegram_client(account),
                                link["source_ref"],
                                row["external_id"],
                                MEDIA_ROOT / f"content-{content_id}",
                            )
                        )
                    if downloaded and downloaded.is_file():
                        if not media:
                            media = [{"kind": row["content_type"]}]
                        media[0]["cached_path"] = str(downloaded)
                        with closing(db_connect()) as conn:
                            conn.execute(
                                "UPDATE content_items SET media_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                (json_dump(media), content_id),
                            )
                            conn.commit()
                        return send_file(downloaded, as_attachment=True, download_name=downloaded.name)
                except Exception as exc:
                    return jsonify(ok=False, error=f"دانلود رسانه ممکن نشد: {exc}"), 409

        text = str(row["raw_text"] or "")
        payload = io.BytesIO(text.encode("utf-8"))
        payload.seek(0)
        return send_file(
            payload,
            mimetype="text/plain; charset=utf-8",
            as_attachment=True,
            download_name=f"telegram-{row['source_key']}-{row['external_id']}.txt",
        )

    @app.get(f"{BASE_PATH}/api/v2/operations/extraction-jobs")
    @login_required
    def extraction_jobs_list():
        with closing(db_connect()) as conn:
            rows = conn.execute(
                """
                SELECT ej.*,
                    (SELECT COUNT(*) FROM extraction_job_items x WHERE x.extraction_job_id=ej.id) AS content_count,
                    (SELECT COUNT(*) FROM extraction_runs r WHERE r.extraction_job_id=ej.id) AS run_count
                FROM extraction_jobs ej ORDER BY ej.id DESC LIMIT 250
                """
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["config"] = json_load(item.pop("config_json", "{}"))
                item["rules"] = json_load(item.pop("rules_json", "{}"))
                items.append(item)
        return jsonify(ok=True, jobs=items)

    @app.get(f"{BASE_PATH}/api/v2/operations/extraction-jobs/<int:job_id>/dashboard")
    @login_required
    def extraction_dashboard(job_id):
        with closing(db_connect()) as conn:
            job = extraction_row(conn, job_id)
            if not job:
                return jsonify(ok=False, error="جاب استخراج پیدا نشد."), 404
            stats_rows = conn.execute(
                """
                SELECT ci.content_type, COUNT(*) AS n
                FROM extraction_job_items eji
                INNER JOIN content_items ci ON ci.id=eji.content_id
                WHERE eji.extraction_job_id=? GROUP BY ci.content_type
                """,
                (job_id,),
            ).fetchall()
            contents = conn.execute(
                """
                SELECT ci.id, ci.connector_code, ci.source_key, ci.source_ref,
                       ci.source_title, ci.external_id, ci.published_at,
                       ci.content_type, ci.raw_text, ci.processed_text,
                       ci.media_json, ci.metadata_json,
                       ci.created_at, ci.updated_at
                FROM extraction_job_items eji
                INNER JOIN content_items ci ON ci.id=eji.content_id
                WHERE eji.extraction_job_id=?
                ORDER BY CAST(ci.external_id AS INTEGER) DESC LIMIT 250
                """,
                (job_id,),
            ).fetchall()
            runs = conn.execute(
                "SELECT * FROM extraction_runs WHERE extraction_job_id=? ORDER BY id DESC LIMIT 50",
                (job_id,),
            ).fetchall()
            item = dict(job)
            item["config"] = json_load(item.pop("config_json", "{}"))
            item["rules"] = json_load(item.pop("rules_json", "{}"))
            stats = {row["content_type"]: row["n"] for row in stats_rows}
            stats["total"] = sum(stats.values())
            logs = list_logs(conn, "extraction", job_id, job["legacy_job_id"])
            payloads = [content_payload(conn, row) for row in contents]
        return jsonify(ok=True, job=item, stats=stats, runs=[dict(row) for row in runs], logs=logs, items=payloads)

    @app.route(f"{BASE_PATH}/api/v2/operations/extraction-jobs/<int:job_id>", methods=["PATCH"])
    @api_post_required
    def edit_extraction_job(job_id):
        data = json_body()
        with closing(db_connect()) as conn:
            job = extraction_row(conn, job_id)
            if not job:
                return jsonify(ok=False, error="جاب استخراج پیدا نشد."), 404
            name = str(data.get("name") or job["name"]).strip()[:255]
            try:
                source_ref = clean_ref(data.get("source_ref") or job["source_ref"])
                account_id = int(data.get("source_account_id") or job["source_account_id"])
                max_items = int(data.get("max_items") or json_load(job["config_json"], {}).get("max_items", 250))
                if not 1 <= max_items <= 5000:
                    raise ValueError("حداکثر پیام باید بین ۱ تا ۵۰۰۰ باشد.")
            except (TypeError, ValueError) as exc:
                return jsonify(ok=False, error=str(exc) or "مقادیر معتبر نیست."), 400
            start_mode = str(data.get("start_mode") or job["start_mode"])
            if start_mode not in {"all", "date", "message_id", "incremental", "legacy"}:
                return jsonify(ok=False, error="روش شروع معتبر نیست."), 400
            start_date = job["start_date_utc"]
            start_id = job["start_external_id"]
            if start_mode == "date" and data.get("start_date_jalali"):
                try:
                    start_date = parse_persian_date(data["start_date_jalali"])
                except ValueError as exc:
                    return jsonify(ok=False, error=str(exc)), 400
            if start_mode == "message_id":
                try:
                    start_id = str(int(data.get("start_external_id") or start_id))
                except (TypeError, ValueError):
                    return jsonify(ok=False, error="Message ID معتبر نیست."), 400
            config = json_load(
                job[
                    "config_json"
                ],
                {},
            )

            config[
                "max_items"
            ] = max_items

            watch_value = data.get(
                "watch_enabled",
                job[
                    "watch_enabled"
                ],
            )

            watch_enabled = (
                watch_value is True
                or str(
                    watch_value
                ).strip().lower()
                in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }
            )

            try:
                poll_interval = int(
                    data.get(
                        "poll_interval_minutes",
                        job[
                            "poll_interval_minutes"
                        ]
                        or 5,
                    )
                )

                if not 1 <= poll_interval <= 1440:
                    raise ValueError(
                        "فاصله بررسی باید بین ۱ تا ۱۴۴۰ دقیقه باشد."
                    )

            except (
                TypeError,
                ValueError,
            ) as exc:

                return jsonify(
                    ok=False,
                    error=str(exc)
                    or "فاصله بررسی معتبر نیست.",
                ), 400

            if watch_enabled:

                next_run_at = (
                    job[
                        "next_run_at"
                    ]
                    or datetime.now(
                        timezone.utc
                    )
                    .replace(
                        microsecond=0
                    )
                    .isoformat()
                )

                status = (
                    "running"
                    if job[
                        "status"
                    ]
                    == "running"
                    else "watching"
                )

            else:

                next_run_at = None

                status = (
                    "completed"
                    if job[
                        "status"
                    ]
                    == "watching"
                    else job[
                        "status"
                    ]
                )

            conn.execute(
                """
                UPDATE extraction_jobs SET
                    name=?,
                    source_account_id=?,
                    source_ref=?,
                    start_mode=?,
                    start_date_utc=?,
                    start_external_id=?,
                    config_json=?,
                    watch_enabled=?,
                    poll_interval_minutes=?,
                    next_run_at=?,
                    status=?,
                    scheduler_failures=0,
                    scheduler_backoff_until=NULL,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    name,
                    account_id,
                    source_ref,
                    start_mode,
                    start_date,
                    start_id,
                    json_dump(
                        config
                    ),
                    int(
                        watch_enabled
                    ),
                    poll_interval,
                    next_run_at,
                    status,
                    job_id,
                ),
            )
            conn.commit()
        log_job("extraction", job_id, "JOB_EDITED", "تنظیمات جاب استخراج ویرایش شد.")
        return jsonify(ok=True, job_id=job_id, message="جاب استخراج ویرایش شد.")

    @app.post(f"{BASE_PATH}/api/v2/operations/extraction-jobs/<int:job_id>/repeat")
    @api_post_required
    def repeat_extraction_job(job_id):
        with closing(db_connect()) as conn:
            job = extraction_row(conn, job_id)
            if not job:
                return jsonify(ok=False, error="جاب استخراج پیدا نشد."), 404
            cursor = conn.execute(
                """
                INSERT INTO extraction_jobs(
                    name, connector_code, source_account_id, source_ref, source_key,
                    source_title, status, start_mode, start_date_utc, start_external_id,
                    watch_enabled, poll_interval_minutes, config_json, rules_json,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, 0, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    f"{job['name']} — تکرار", job["connector_code"], job["source_account_id"],
                    job["source_ref"], job["source_key"], job["source_title"], job["start_mode"],
                    job["start_date_utc"], job["start_external_id"], job["poll_interval_minutes"],
                    job["config_json"], job["rules_json"],
                ),
            )
            new_id = cursor.lastrowid
            conn.commit()
        log_job("extraction", new_id, "JOB_REPEATED", f"از جاب استخراج #{job_id} ساخته شد.")
        return jsonify(ok=True, job_id=new_id, message="نسخه تکراری جاب استخراج ساخته شد."), 201

    @app.get(f"{BASE_PATH}/api/v2/operations/transfer-jobs")
    @login_required
    def transfer_jobs_list():
        with closing(db_connect()) as conn:
            jobs = conn.execute(
                """
                SELECT tj.*, ej.name AS extraction_name,
                       (SELECT COUNT(*) FROM transfer_destinations td
                        WHERE td.transfer_job_id=tj.id AND td.enabled=1) AS destination_count
                FROM transfer_jobs tj
                LEFT JOIN extraction_jobs ej ON ej.id=json_extract(tj.selector_json, '$.extraction_job_id')
                ORDER BY tj.id DESC LIMIT 250
                """
            ).fetchall()
            items = []
            for row in jobs:
                sync_transfer_plan(conn, row["id"])
                item = dict(row)
                item["selector"] = json_load(item.pop("selector_json", "{}"))
                item["counts"] = transfer_counts(conn, row["id"])
                item["destinations"] = destination_payloads(conn, row["id"])
                items.append(item)
            conn.commit()
        return jsonify(ok=True, jobs=items)

    @app.post(f"{BASE_PATH}/api/v2/operations/transfer-jobs")
    @api_post_required
    def create_transfer_job():
        data = json_body()
        try:
            extraction_job_id = int(data.get("extraction_job_id"))
        except (TypeError, ValueError) as exc:
            return jsonify(ok=False, error=str(exc) or "تنظیمات انتقال معتبر نیست."), 400
        raw_destinations = data.get("destinations")
        if not isinstance(raw_destinations, list):
            raw_destinations = [
                {
                    "provider_code": data.get("provider_code") or "telegram_user",
                    "provider_account_id": data.get("provider_account_id"),
                    "destination_ref": data.get("destination_ref"),
                    "mode": data.get("mode") or "copy",
                }
            ]
        if not 1 <= len(raw_destinations) <= 20:
            return jsonify(ok=False, error="هر جاب باید بین ۱ تا ۲۰ مقصد داشته باشد."), 400
        try:
            destinations = [
                validate_destination_payload(item, account_get)
                for item in raw_destinations
                if isinstance(item, dict)
            ]
            if len(destinations) != len(raw_destinations):
                raise ValueError("ساختار یکی از مقصدها معتبر نیست.")
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        with closing(db_connect()) as conn:
            extraction = extraction_row(conn, extraction_job_id)
            if not extraction:
                return jsonify(ok=False, error="جاب استخراج مبدا پیدا نشد."), 404
            name = str(data.get("name") or f"انتقال {extraction['name']}").strip()[:255]
            cursor = conn.execute(
                """
                INSERT INTO transfer_jobs(name, selector_type, selector_json, status, created_at, updated_at)
                VALUES(?, 'extraction_job', ?, 'draft', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (name, json_dump({"extraction_job_id": extraction_job_id})),
            )
            job_id = cursor.lastrowid
            destination_ids = insert_destinations(conn, job_id, destinations)
            sync_transfer_plan(conn, job_id)
            conn.commit()
        labels = ", ".join(PROVIDERS[item["provider_code"]]["short_label"] for item in destinations)
        log_job("transfer", job_id, "JOB_CREATED", f"{len(destinations)} مقصد ثبت شد: {labels}")
        return jsonify(
            ok=True, job_id=job_id, destination_ids=destination_ids,
            destination_count=len(destination_ids), message="جاب انتقال چندمقصدی ساخته شد.",
        ), 201

    @app.get(f"{BASE_PATH}/api/v2/operations/transfer-jobs/<int:job_id>/dashboard")
    @login_required
    def transfer_dashboard(job_id):
        with closing(db_connect()) as conn:
            job = transfer_row(conn, job_id)
            if not job:
                return jsonify(ok=False, error="جاب انتقال پیدا نشد."), 404
            sync_transfer_plan(conn, job_id)
            destinations = destination_payloads(conn, job_id)
            rows = conn.execute(
                """
                SELECT tji.status AS item_status, tji.attempts, tji.last_error,
                       tji.destination_external_id, tji.transferred_at,
                       td.id AS destination_id, td.provider_code, td.destination_ref,
                       td.mode AS transfer_mode,
                       ci.id, ci.connector_code, ci.source_key, ci.source_ref,
                       ci.source_title, ci.external_id, ci.published_at,
                       ci.content_type, ci.raw_text, ci.processed_text,
                       ci.media_json, ci.metadata_json,
                       ci.created_at, ci.updated_at
                FROM transfer_job_items tji
                INNER JOIN transfer_destinations td ON td.id=tji.destination_id
                INNER JOIN content_items ci ON ci.id=tji.content_id
                WHERE tji.transfer_job_id=? ORDER BY tji.id DESC LIMIT 500
                """,
                (job_id,),
            ).fetchall()
            runs = conn.execute(
                "SELECT * FROM transfer_runs WHERE transfer_job_id=? ORDER BY id DESC LIMIT 50",
                (job_id,),
            ).fetchall()
            item = dict(job)
            item["selector"] = json_load(item.pop("selector_json", "{}"))
            payloads = []
            for row in rows:
                data = content_payload(conn, row, row["item_status"])
                data["attempts"] = row["attempts"]
                data["last_error"] = row["last_error"]
                data["destination_external_id"] = row["destination_external_id"]
                data["transferred_at"] = row["transferred_at"]
                data["destination_id"] = row["destination_id"]
                data["provider_code"] = normalize_provider(row["provider_code"])
                data["provider_label"] = PROVIDERS.get(data["provider_code"], {}).get(
                    "short_label", data["provider_code"]
                )
                data["destination_ref"] = row["destination_ref"]
                data["transfer_mode"] = row["transfer_mode"]
                data.pop("item_status", None)
                payloads.append(data)
            logs = list_logs(conn, "transfer", job_id, job["legacy_job_id"])
            counts = transfer_counts(conn, job_id)
            conn.commit()
        return jsonify(
            ok=True, job=item, destinations=destinations,
            counts=counts, runs=[dict(row) for row in runs], logs=logs, items=payloads,
        )

    @app.route(f"{BASE_PATH}/api/v2/operations/transfer-jobs/<int:job_id>", methods=["PATCH"])
    @api_post_required
    def edit_transfer_job(job_id):
        data = json_body()
        raw_destinations = data.get("destinations")
        if not isinstance(raw_destinations, list) or not 1 <= len(raw_destinations) <= 20:
            return jsonify(ok=False, error="برای جاب بین ۱ تا ۲۰ مقصد وارد کنید."), 400
        try:
            destinations = [
                validate_destination_payload(item, account_get)
                for item in raw_destinations
                if isinstance(item, dict)
            ]
            if len(destinations) != len(raw_destinations):
                raise ValueError("ساختار یکی از مقصدها معتبر نیست.")
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        with closing(db_connect()) as conn:
            job = transfer_row(conn, job_id)
            if not job:
                return jsonify(ok=False, error="جاب انتقال پیدا نشد."), 404
            name = str(data.get("name") or job["name"]).strip()[:255]
            conn.execute(
                "UPDATE transfer_jobs SET name=?, status='draft', last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (name, job_id),
            )
            conn.execute("DELETE FROM transfer_destinations WHERE transfer_job_id=?", (job_id,))
            insert_destinations(conn, job_id, destinations)
            sync_transfer_plan(conn, job_id)
            conn.commit()
        log_job("transfer", job_id, "JOB_EDITED", f"جاب با {len(destinations)} مقصد ویرایش و صف بازسازی شد.")
        return jsonify(ok=True, job_id=job_id, message="جاب انتقال ویرایش شد.")

    @app.post(f"{BASE_PATH}/api/v2/operations/transfer-jobs/<int:job_id>/repeat")
    @api_post_required
    def repeat_transfer_job(job_id):
        with closing(db_connect()) as conn:
            job = transfer_row(conn, job_id)
            if not job:
                return jsonify(ok=False, error="جاب انتقال پیدا نشد."), 404
            destinations = conn.execute(
                "SELECT * FROM transfer_destinations WHERE transfer_job_id=? ORDER BY position, id",
                (job_id,),
            ).fetchall()
            cursor = conn.execute(
                """
                INSERT INTO transfer_jobs(name, selector_type, selector_json, status, created_at, updated_at)
                VALUES(?, ?, ?, 'draft', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (f"{job['name']} — تکرار", job["selector_type"], job["selector_json"]),
            )
            new_id = cursor.lastrowid
            for destination in destinations:
                conn.execute(
                    """
                    INSERT INTO transfer_destinations(
                        transfer_job_id, provider_code, provider_account_id,
                        destination_ref, mode, enabled, position, rules_json, status
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        new_id, normalize_provider(destination["provider_code"]), destination["provider_account_id"],
                        destination["destination_ref"], destination["mode"], destination["enabled"],
                        destination["position"], destination["rules_json"],
                    ),
                )
            sync_transfer_plan(conn, new_id)
            conn.commit()
        log_job("transfer", new_id, "JOB_REPEATED", f"از جاب انتقال #{job_id} ساخته شد.")
        return jsonify(ok=True, job_id=new_id, message="نسخه تکراری جاب انتقال ساخته شد."), 201

    @app.post(f"{BASE_PATH}/api/v2/internal/legacy-telegram-transfer-jobs/<int:job_id>/run")
    @api_post_required
    def legacy_run_transfer_job(job_id):
        with closing(db_connect()) as conn:
            job = transfer_row(conn, job_id)
            if not job:
                return jsonify(ok=False, error="جاب انتقال پیدا نشد."), 404
            selector = json_load(job["selector_json"], {})
            extraction = extraction_row(conn, selector.get("extraction_job_id"))
            destination = conn.execute(
                "SELECT * FROM transfer_destinations WHERE transfer_job_id=? AND enabled=1 ORDER BY position LIMIT 1",
                (job_id,),
            ).fetchone()
            if not extraction or not destination:
                return jsonify(ok=False, error="مبدا یا مقصد انتقال کامل نیست."), 400
            sync_transfer_plan(conn, job_id)
            rows = conn.execute(
                """
                SELECT tji.id AS transfer_item_id, ci.external_id
                FROM transfer_job_items tji
                INNER JOIN content_items ci ON ci.id=tji.content_id
                WHERE tji.transfer_job_id=? AND tji.destination_id=?
                  AND tji.status IN('listed','failed','transferring')
                ORDER BY CAST(ci.external_id AS INTEGER) ASC
                """,
                (job_id, destination["id"]),
            ).fetchall()
            run = conn.execute(
                "INSERT INTO transfer_runs(transfer_job_id,status,listed_count) VALUES(?, 'running', ?)",
                (job_id, len(rows)),
            )
            run_id = run.lastrowid
            conn.execute(
                "UPDATE transfer_jobs SET status='running', last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
            conn.commit()

        account = account_get(destination["provider_account_id"])
        if not account or account["status"] != "connected":
            with closing(db_connect()) as conn:
                error = "اکانت متصل انتقال در دسترس نیست."
                conn.execute(
                    "UPDATE transfer_jobs SET status='failed', last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (error, job_id),
                )
                conn.execute(
                    """
                    UPDATE transfer_runs SET status='failed', error_text=?,
                        finished_at=CURRENT_TIMESTAMP WHERE id=?
                    """,
                    (error, run_id),
                )
                conn.commit()
            log_job("transfer", job_id, "RUN_FAILED", error, "error")
            return jsonify(ok=False, error="اکانت متصل انتقال در دسترس نیست."), 400

        def mark(item_id, status, destination_external_id=None, error=None):
            with closing(db_connect()) as marker:
                marker.execute(
                    """
                    UPDATE transfer_job_items SET status=?,
                        attempts=attempts+CASE WHEN ?='transferring' THEN 1 ELSE 0 END,
                        destination_external_id=COALESCE(?, destination_external_id),
                        last_error=?, started_at=CASE WHEN ?='transferring' THEN CURRENT_TIMESTAMP ELSE started_at END,
                        transferred_at=CASE WHEN ?='transferred' THEN CURRENT_TIMESTAMP ELSE transferred_at END,
                        updated_at=CURRENT_TIMESTAMP WHERE id=?
                    """,
                    (
                        status, status,
                        str(destination_external_id) if destination_external_id else None,
                        error, status, status, item_id,
                    ),
                )
                marker.commit()

        started = time.perf_counter()
        log_job("transfer", job_id, "RUN_STARTED", f"انتقال {len(rows)} آیتم آغاز شد.")
        try:
            with account_lock(account["id"]):
                asyncio.run(
                    execute_transfer(
                        telegram_client(account), extraction["source_ref"],
                        destination["destination_ref"], destination["mode"], rows, mark,
                    )
                )
            elapsed = round(time.perf_counter() - started, 3)
            with closing(db_connect()) as conn:
                counts = transfer_counts(conn, job_id)
                status = "completed" if counts["failed"] == 0 else "failed"
                conn.execute(
                    "UPDATE transfer_jobs SET status=?, last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (status, job_id),
                )
                conn.execute(
                    """
                    UPDATE transfer_runs SET status=?, transferred_count=?, failed_count=?,
                        skipped_count=?, elapsed_seconds=?, finished_at=CURRENT_TIMESTAMP WHERE id=?
                    """,
                    (status, counts["transferred"], counts["failed"], counts["skipped"], elapsed, run_id),
                )
                conn.commit()
            log_job("transfer", job_id, "RUN_FINISHED", f"انتقال تمام شد: {counts}")
            return jsonify(ok=True, job_id=job_id, counts=counts, elapsed_seconds=elapsed, message="اجرای انتقال تمام شد.")
        except Exception as exc:
            elapsed = round(time.perf_counter() - started, 3)
            with closing(db_connect()) as conn:
                counts = transfer_counts(conn, job_id)
                error = f"{type(exc).__name__}: {exc}"[:2000]
                conn.execute(
                    "UPDATE transfer_jobs SET status='failed', last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (error, job_id),
                )
                conn.execute(
                    """
                    UPDATE transfer_runs SET status='failed', transferred_count=?, failed_count=?,
                        skipped_count=?, elapsed_seconds=?, error_text=?, finished_at=CURRENT_TIMESTAMP WHERE id=?
                    """,
                    (counts["transferred"], counts["failed"], counts["skipped"], elapsed, error, run_id),
                )
                conn.commit()
            log_job("transfer", job_id, "RUN_FAILED", error, "error")
            return jsonify(ok=False, error=error, counts=counts), 500

    @app.post(f"{BASE_PATH}/api/v2/operations/transfer-jobs/<int:job_id>/run")
    @api_post_required
    def run_multi_provider_transfer_job(job_id):
        with closing(db_connect()) as conn:
            job = transfer_row(conn, job_id)
            if not job:
                return jsonify(ok=False, error="جاب انتقال پیدا نشد."), 404
            selector = json_load(job["selector_json"], {})
            extraction = extraction_row(conn, selector.get("extraction_job_id"))
            destinations = conn.execute(
                """
                SELECT * FROM transfer_destinations
                WHERE transfer_job_id=? AND enabled=1 ORDER BY position, id
                """,
                (job_id,),
            ).fetchall()
            if not extraction or not destinations:
                return jsonify(ok=False, error="مبدا یا مقصدهای انتقال کامل نیست."), 400
            sync_transfer_plan(conn, job_id)
            total_pending = conn.execute(
                """
                SELECT COUNT(*) FROM transfer_job_items
                WHERE transfer_job_id=? AND status IN('listed','failed','transferring')
                """,
                (job_id,),
            ).fetchone()[0]
            run = conn.execute(
                "INSERT INTO transfer_runs(transfer_job_id,status,listed_count) VALUES(?, 'running', ?)",
                (job_id, total_pending),
            )
            run_id = run.lastrowid
            conn.execute(
                "UPDATE transfer_jobs SET status='running', last_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
            conn.commit()
            extraction = dict(extraction)
            destinations = [dict(item) for item in destinations]

        def mark(item_id, status, destination_external_id=None, error=None):
            with closing(db_connect()) as marker:
                marker.execute(
                    """
                    UPDATE transfer_job_items SET status=?,
                        attempts=attempts+CASE WHEN ?='transferring' THEN 1 ELSE 0 END,
                        destination_external_id=COALESCE(?, destination_external_id),
                        last_error=?,
                        started_at=CASE WHEN ?='transferring' THEN CURRENT_TIMESTAMP ELSE started_at END,
                        transferred_at=CASE WHEN ?='transferred' THEN CURRENT_TIMESTAMP ELSE transferred_at END,
                        updated_at=CURRENT_TIMESTAMP WHERE id=?
                    """,
                    (
                        status,
                        status,
                        str(destination_external_id) if destination_external_id is not None else None,
                        error,
                        status,
                        status,
                        item_id,
                    ),
                )
                marker.commit()

        started = time.perf_counter()
        destination_results = []
        errors_seen = []
        log_job(
            "transfer",
            job_id,
            "RUN_STARTED",
            f"انتقال چندمقصدی با {len(destinations)} مقصد و {total_pending} آیتم آغاز شد.",
        )

        for destination in destinations:
            provider = normalize_provider(destination["provider_code"])
            destination["provider_code"] = provider
            label = PROVIDERS.get(provider, {}).get("short_label", provider)
            with closing(db_connect()) as conn:
                rows = conn.execute(
                    """
                    SELECT tji.id AS transfer_item_id, ci.external_id,
                           ci.content_type, ci.raw_text, ci.processed_text
                    FROM transfer_job_items tji
                    INNER JOIN content_items ci ON ci.id=tji.content_id
                    WHERE tji.transfer_job_id=? AND tji.destination_id=?
                      AND tji.status IN('listed','failed','transferring')
                    ORDER BY CAST(ci.external_id AS INTEGER) ASC
                    """,
                    (job_id, destination["id"]),
                ).fetchall()
                rows = [dict(row) for row in rows]
                conn.execute(
                    """
                    UPDATE transfer_destinations SET status='running', last_error=NULL,
                        updated_at=CURRENT_TIMESTAMP WHERE id=?
                    """,
                    (destination["id"],),
                )
                conn.commit()

            if not rows:
                with closing(db_connect()) as conn:
                    conn.execute(
                        "UPDATE transfer_destinations SET status='completed', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (destination["id"],),
                    )
                    conn.commit()
                destination_results.append(
                    {"destination_id": destination["id"], "provider_code": provider, "status": "completed", "pending": 0}
                )
                continue

            account_id = (
                destination.get("provider_account_id")
                if provider == "telegram_user"
                else extraction.get("source_account_id")
            )
            account = account_get(account_id) if account_id else None
            failure = None
            if provider not in PROVIDERS:
                failure = "پروایدر مقصد ناشناخته است."
            elif provider != "telegram_user" and not provider_is_configured(provider):
                failure = f"توکن {label} تنظیم نشده است."
            elif not account or account["status"] != "connected":
                failure = "اکانت تلگرام متصل برای خواندن محتوای مبدا در دسترس نیست."

            try:
                if failure:
                    raise RuntimeError(failure)
                log_job(
                    "transfer",
                    job_id,
                    "DESTINATION_STARTED",
                    f"{label} → {destination['destination_ref']} | {len(rows)} آیتم",
                )
                run_destination(
                    telegram_client,
                    account,
                    extraction,
                    destination,
                    rows,
                    mark,
                )
                with closing(db_connect()) as conn:
                    failed = conn.execute(
                        "SELECT COUNT(*) FROM transfer_job_items WHERE destination_id=? AND status='failed'",
                        (destination["id"],),
                    ).fetchone()[0]
                    status = "failed" if failed else "completed"
                    conn.execute(
                        """
                        UPDATE transfer_destinations SET status=?, last_error=NULL,
                            updated_at=CURRENT_TIMESTAMP WHERE id=?
                        """,
                        (status, destination["id"]),
                    )
                    conn.commit()
                if failed:
                    errors_seen.append(f"{label}: {failed} آیتم ناموفق")
                log_job(
                    "transfer",
                    job_id,
                    "DESTINATION_FINISHED",
                    f"{label} → {destination['destination_ref']} | status={status}",
                    "warning" if failed else "info",
                )
                destination_results.append(
                    {
                        "destination_id": destination["id"],
                        "provider_code": provider,
                        "status": status,
                        "pending": len(rows),
                        "failed": failed,
                    }
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:2000]
                errors_seen.append(f"{label}: {error}")
                for row in rows:
                    mark(row["transfer_item_id"], "failed", error=error)
                with closing(db_connect()) as conn:
                    conn.execute(
                        """
                        UPDATE transfer_destinations SET status='failed', last_error=?,
                            updated_at=CURRENT_TIMESTAMP WHERE id=?
                        """,
                        (error, destination["id"]),
                    )
                    conn.commit()
                log_job(
                    "transfer",
                    job_id,
                    "DESTINATION_FAILED",
                    f"{label} → {destination['destination_ref']} | {error}",
                    "error",
                )
                destination_results.append(
                    {
                        "destination_id": destination["id"],
                        "provider_code": provider,
                        "status": "failed",
                        "pending": len(rows),
                        "error": error,
                    }
                )

        elapsed = round(time.perf_counter() - started, 3)
        with closing(db_connect()) as conn:
            counts = transfer_counts(conn, job_id)
            status = "failed" if counts["failed"] or errors_seen else "completed"
            error_text = " | ".join(errors_seen)[:2000] if errors_seen else None
            conn.execute(
                "UPDATE transfer_jobs SET status=?, last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, error_text, job_id),
            )
            conn.execute(
                """
                UPDATE transfer_runs SET status=?, transferred_count=?, failed_count=?,
                    skipped_count=?, elapsed_seconds=?, error_text=?, finished_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    status,
                    counts["transferred"],
                    counts["failed"],
                    counts["skipped"],
                    elapsed,
                    error_text,
                    run_id,
                ),
            )
            conn.commit()

        log_job(
            "transfer",
            job_id,
            "RUN_FINISHED" if status == "completed" else "RUN_PARTIAL_FAILED",
            f"انتقال چندمقصدی پایان یافت: {counts}",
            "info" if status == "completed" else "error",
        )
        payload = {
            "ok": status == "completed",
            "job_id": job_id,
            "status": status,
            "counts": counts,
            "destinations": destination_results,
            "elapsed_seconds": elapsed,
            "message": "اجرای انتقال همه مقصدها تمام شد."
            if status == "completed"
            else "اجرای انتقال پایان یافت، اما بعضی مقصدها یا آیتم‌ها خطا داشتند.",
        }
        if error_text:
            payload["error"] = error_text
        return jsonify(payload), 200 if status == "completed" else 500
