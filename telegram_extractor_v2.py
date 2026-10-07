import hashlib
import json
import re
import time

from contextlib import closing
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import jsonify, request

from job_engine import (
    account_lock,
    clean_ref,
    db_connect,
    entity_kind,
    entity_peer_id,
    entity_title,
    entity_username,
    media_type,
    resolve_source,
    run_async,
)


BASE_PATH = "/teltest"
EXTRACTOR_VERSION = "2"
TEHRAN = ZoneInfo("Asia/Tehran")
HASHTAG_PATTERN = re.compile(
    r"(?<![\w\u200c])#([\w\u0600-\u06ff\u0750-\u077f\u200c]+)",
    re.UNICODE,
)


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def write_operation_log(job_id, event, message, level="info"):
    try:
        with closing(db_connect()) as conn:
            conn.execute(
                """
                INSERT INTO operation_job_logs(job_kind, job_id, level, event, message)
                VALUES('extraction', ?, ?, ?, ?)
                """,
                (job_id, level, event, str(message)[:4000]),
            )
            conn.commit()
    except Exception:
        pass


def sync_content_hashtags(conn, content_id, text):
    conn.execute("DELETE FROM content_hashtags WHERE content_id = ?", (content_id,))
    seen = set()
    for match in HASHTAG_PATTERN.finditer(str(text or "")):
        hashtag = match.group(1).strip("_\u200c")
        normalized = hashtag.replace("\u200c", "").casefold()
        if not hashtag or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        conn.execute(
            """
            INSERT OR IGNORE INTO content_hashtags(content_id, hashtag, normalized_hashtag)
            VALUES(?, ?, ?)
            """,
            (content_id, f"#{hashtag}", normalized),
        )


def gregorian_to_jalali(gy, gm, gd):
    gdm = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        + gd
        + gdm[gm - 1]
    )
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def jalali_to_gregorian(jy, jm, jd):
    jy += 1595
    days = (
        -355668
        + (365 * jy)
        + ((jy // 33) * 8)
        + (((jy % 33) + 3) // 4)
        + jd
        + ((jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186)
    )
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    month_days = (
        0,
        31,
        29 if (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0 else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    )
    gm = 1
    while gm <= 12 and gd > month_days[gm]:
        gd -= month_days[gm]
        gm += 1
    return gy, gm, gd


def parse_persian_date(value):
    normalized = str(value or "").strip().translate(
        str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    )
    match = re.fullmatch(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", normalized)
    if not match:
        raise ValueError("تاریخ شمسی باید با قالب ۱۴۰۵/۰۷/۱۴ وارد شود.")
    jy, jm, jd = (int(item) for item in match.groups())
    if not 1200 <= jy <= 1600 or not 1 <= jm <= 12 or not 1 <= jd <= 31:
        raise ValueError("تاریخ شمسی معتبر نیست.")
    gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
    if gregorian_to_jalali(gy, gm, gd) != (jy, jm, jd):
        raise ValueError("تاریخ شمسی معتبر نیست.")
    local_date = datetime(gy, gm, gd, tzinfo=TEHRAN)
    return local_date.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def init_extractor_schema():
    with closing(db_connect()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS extraction_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                extraction_job_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                start_mode TEXT NOT NULL,
                start_cursor TEXT,
                resolved_source_key TEXT,
                fetched_count INTEGER NOT NULL DEFAULT 0,
                inserted_count INTEGER NOT NULL DEFAULT 0,
                updated_count INTEGER NOT NULL DEFAULT 0,
                elapsed_seconds REAL,
                error_text TEXT,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                FOREIGN KEY(extraction_job_id)
                    REFERENCES extraction_jobs(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_extraction_runs_job
                ON extraction_runs(extraction_job_id, id DESC);
            """
        )
        conn.execute(
            """
            INSERT INTO schema_meta (key, value, updated_at)
            VALUES ('telegram_extractor_version', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (EXTRACTOR_VERSION,),
        )
        conn.commit()


def extraction_job(job_id):
    with closing(db_connect()) as conn:
        return conn.execute(
            "SELECT * FROM extraction_jobs WHERE id = ?",
            (int(job_id),),
        ).fetchone()


def serialize_job(row):
    item = dict(row)
    item["watch_enabled"] = bool(item.get("watch_enabled"))
    item["config"] = json_load(item.pop("config_json", "{}"))
    item["rules"] = json_load(item.pop("rules_json", "{}"))
    return item


def message_media_payload(message):
    kind = media_type(message)
    file_info = getattr(message, "file", None)
    payload = {
        "kind": kind,
        "grouped_id": str(getattr(message, "grouped_id", "") or "") or None,
    }
    if file_info:
        payload.update(
            {
                "name": getattr(file_info, "name", None),
                "mime_type": getattr(file_info, "mime_type", None),
                "size": getattr(file_info, "size", None),
                "ext": getattr(file_info, "ext", None),
            }
        )
    return [] if kind == "text" else [payload]


def message_metadata(message, joined_source):
    replies = getattr(message, "replies", None)
    reply_to = getattr(message, "reply_to", None)
    return {
        "telegram": {
            "views": getattr(message, "views", None),
            "forwards": getattr(message, "forwards", None),
            "replies": getattr(replies, "replies", None) if replies else None,
            "sender_id": getattr(message, "sender_id", None),
            "grouped_id": str(getattr(message, "grouped_id", "") or "") or None,
            "edit_date": (
                message.edit_date.isoformat()
                if getattr(message, "edit_date", None)
                else None
            ),
            "post_author": getattr(message, "post_author", None),
            "reply_to_msg_id": (
                getattr(reply_to, "reply_to_msg_id", None) if reply_to else None
            ),
            "entities_count": len(getattr(message, "entities", None) or []),
            "joined_source": bool(joined_source),
        }
    }


async def fetch_messages(client, job, max_items):
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Session این اکانت مجاز نیست؛ اتصال اکانت را تجدید کنید.")

        entity, joined_source = await resolve_source(client, job["source_ref"])
        start_mode = job["start_mode"]
        cursor = job["cursor_external_id"]
        rows = []

        kwargs = {"limit": max_items}
        if start_mode == "message_id":
            kwargs.update(
                min_id=max(0, int(job["start_external_id"]) - 1),
                reverse=True,
            )
        elif start_mode == "incremental" and cursor:
            kwargs.update(min_id=max(0, int(cursor)), reverse=True)

        threshold = None
        if start_mode == "date":
            threshold = datetime.fromisoformat(job["start_date_utc"])
            if threshold.tzinfo is None:
                threshold = threshold.replace(tzinfo=timezone.utc)

        async for message in client.iter_messages(entity, **kwargs):
            published = getattr(message, "date", None)
            if published and published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if threshold and published and published < threshold:
                break
            raw_text = getattr(message, "message", None) or ""
            rows.append(
                {
                    "external_id": str(message.id),
                    "published_at": published.isoformat() if published else None,
                    "content_type": media_type(message),
                    "raw_text": raw_text,
                    "media": message_media_payload(message),
                    "metadata": message_metadata(message, joined_source),
                }
            )

        return {
            "source_key": entity_peer_id(entity),
            "source_title": entity_title(entity),
            "source_username": entity_username(entity),
            "source_kind": entity_kind(entity),
            "joined_source": joined_source,
            "messages": rows,
        }
    finally:
        await client.disconnect()


def persist_messages(job_id, result, elapsed):
    source_key = result["source_key"]
    source_title = result["source_title"]
    messages = result["messages"]
    inserted = 0
    updated = 0

    with closing(db_connect()) as conn:
        job = conn.execute(
            "SELECT * FROM extraction_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if not job:
            raise RuntimeError("جاب استخراج هنگام ذخیره پیدا نشد.")

        for item in messages:
            current = conn.execute(
                """
                SELECT id FROM content_items
                WHERE connector_code = 'telegram'
                  AND source_key = ? AND external_id = ?
                """,
                (source_key, item["external_id"]),
            ).fetchone()
            content_hash = hashlib.sha256(
                (
                    "telegram|"
                    + source_key
                    + "|"
                    + item["external_id"]
                    + "|"
                    + item["raw_text"]
                    + "|"
                    + json_dump(item["media"])
                ).encode("utf-8")
            ).hexdigest()
            conn.execute(
                """
                INSERT INTO content_items (
                    connector_code, source_key, source_ref, source_title,
                    external_id, published_at, content_type, raw_text,
                    processed_text, media_json, metadata_json, content_hash,
                    updated_at
                ) VALUES (
                    'telegram', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
                )
                ON CONFLICT(connector_code, source_key, external_id) DO UPDATE SET
                    source_ref = excluded.source_ref,
                    source_title = excluded.source_title,
                    published_at = excluded.published_at,
                    content_type = excluded.content_type,
                    raw_text = excluded.raw_text,
                    processed_text = excluded.processed_text,
                    media_json = excluded.media_json,
                    metadata_json = excluded.metadata_json,
                    content_hash = excluded.content_hash,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    source_key,
                    job["source_ref"],
                    source_title,
                    item["external_id"],
                    item["published_at"],
                    item["content_type"],
                    item["raw_text"],
                    item["raw_text"],
                    json_dump(item["media"]),
                    json_dump(item["metadata"]),
                    content_hash,
                ),
            )
            content_id = conn.execute(
                """
                SELECT id FROM content_items
                WHERE connector_code = 'telegram'
                  AND source_key = ? AND external_id = ?
                """,
                (source_key, item["external_id"]),
            ).fetchone()["id"]
            conn.execute(
                """
                INSERT OR IGNORE INTO extraction_job_items
                    (extraction_job_id, content_id)
                VALUES (?, ?)
                """,
                (job_id, content_id),
            )
            sync_content_hashtags(conn, content_id, item["raw_text"])
            if current:
                updated += 1
            else:
                inserted += 1

        numeric_ids = [
            int(item["external_id"])
            for item in messages
            if str(item["external_id"]).isdigit()
        ]
        published_dates = [item["published_at"] for item in messages if item["published_at"]]
        old_cursor = int(job["cursor_external_id"] or 0) if str(job["cursor_external_id"] or "").isdigit() else 0
        new_cursor = max([old_cursor, *numeric_ids]) if numeric_ids else old_cursor
        cursor_date = max(published_dates) if published_dates else job["cursor_published_at"]

        conn.execute(
            """
            UPDATE extraction_jobs SET
                source_key = ?, source_title = ?, status = 'completed',
                cursor_external_id = ?, cursor_published_at = ?,
                last_run_at = CURRENT_TIMESTAMP,
                last_success_at = CURRENT_TIMESTAMP,
                last_error = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                source_key,
                source_title,
                str(new_cursor) if new_cursor else job["cursor_external_id"],
                cursor_date,
                job_id,
            ),
        )
        conn.execute(
            """
            UPDATE extraction_runs SET
                status = 'completed', resolved_source_key = ?,
                fetched_count = ?, inserted_count = ?, updated_count = ?,
                elapsed_seconds = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = (
                SELECT id FROM extraction_runs
                WHERE extraction_job_id = ? AND status = 'running'
                ORDER BY id DESC LIMIT 1
            )
            """,
            (source_key, len(messages), inserted, updated, elapsed, job_id),
        )
        conn.commit()

    return inserted, updated


def init_telegram_extractor_v2(
    app,
    login_required,
    api_post_required,
    telegram_client,
    account_get,
):
    init_extractor_schema()

    @app.get(f"{BASE_PATH}/api/v2/telegram-extractor/meta")
    @login_required
    def telegram_extractor_meta():
        with closing(db_connect()) as conn:
            accounts = conn.execute(
                """
                SELECT id, phone, display_name, username
                FROM accounts WHERE status = 'connected'
                ORDER BY id DESC
                """
            ).fetchall()
            channels = conn.execute(
                """
                SELECT id, account_id, entity_id, title, username, kind
                FROM channels ORDER BY title COLLATE NOCASE
                """
            ).fetchall()
        return jsonify(
            ok=True,
            extractor_version=EXTRACTOR_VERSION,
            accounts=[dict(row) for row in accounts],
            channels=[dict(row) for row in channels],
            limits={"minimum": 1, "default": 250, "maximum": 5000},
            start_modes=["all", "date", "message_id", "incremental"],
        )

    @app.post(f"{BASE_PATH}/api/v2/extraction-jobs")
    @api_post_required
    def create_extraction_job():
        data = json_body()
        try:
            account_id = int(data.get("source_account_id"))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="اکانت تلگرام معتبر نیست."), 400
        account = account_get(account_id)
        if not account:
            return jsonify(ok=False, error="اکانت تلگرام پیدا نشد."), 404
        if account["status"] != "connected":
            return jsonify(ok=False, error="اکانت تلگرام متصل نیست."), 400

        try:
            source_ref = clean_ref(data.get("source_ref"))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

        name = str(data.get("name") or source_ref).strip()[:255]
        start_mode = str(data.get("start_mode") or "all").strip()
        if start_mode not in {"all", "date", "message_id", "incremental"}:
            return jsonify(ok=False, error="روش شروع استخراج معتبر نیست."), 400

        start_date_utc = None
        start_external_id = None
        try:
            if start_mode == "date":
                start_date_utc = parse_persian_date(data.get("start_date_jalali"))
            elif start_mode == "message_id":
                start_external_id = str(int(data.get("start_external_id")))
                if int(start_external_id) < 1:
                    raise ValueError("شناسه پیام باید بزرگ‌تر از صفر باشد.")
            max_items = int(data.get("max_items", 250))
            if not 1 <= max_items <= 5000:
                raise ValueError("حداکثر پیام باید بین ۱ تا ۵۰۰۰ باشد.")
        except (TypeError, ValueError) as exc:
            return jsonify(ok=False, error=str(exc) or "مقدار شروع معتبر نیست."), 400

        config = {
            "extractor": "telegram-v2",
            "max_items": max_items,
            "start_date_jalali": str(data.get("start_date_jalali") or "") or None,
        }
        with closing(db_connect()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO extraction_jobs (
                    name, connector_code, source_account_id, source_ref,
                    status, start_mode, start_date_utc, start_external_id,
                    watch_enabled, poll_interval_minutes, config_json, rules_json,
                    created_at, updated_at
                ) VALUES (?, 'telegram', ?, ?, 'draft', ?, ?, ?, 0, 5, ?, '{}',
                          CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    name,
                    account_id,
                    source_ref,
                    start_mode,
                    start_date_utc,
                    start_external_id,
                    json_dump(config),
                ),
            )
            conn.commit()
            job_id = cursor.lastrowid
        write_operation_log(job_id, "JOB_CREATED", f"جاب استخراج برای {source_ref} ساخته شد.")
        return jsonify(ok=True, job_id=job_id, status="draft", message="جاب استخراج ساخته شد."), 201

    @app.get(f"{BASE_PATH}/api/v2/extraction-jobs/<int:job_id>")
    @login_required
    def get_extraction_job(job_id):
        row = extraction_job(job_id)
        if not row:
            return jsonify(ok=False, error="جاب استخراج پیدا نشد."), 404
        with closing(db_connect()) as conn:
            content_count = conn.execute(
                "SELECT COUNT(*) AS n FROM extraction_job_items WHERE extraction_job_id = ?",
                (job_id,),
            ).fetchone()["n"]
        return jsonify(ok=True, job=serialize_job(row), content_count=content_count)

    @app.post(f"{BASE_PATH}/api/v2/extraction-jobs/<int:job_id>/run")
    @api_post_required
    def run_extraction_job(job_id):
        job = extraction_job(job_id)
        if not job:
            return jsonify(ok=False, error="جاب استخراج پیدا نشد."), 404
        if job["connector_code"] != "telegram":
            return jsonify(ok=False, error="در Stage 08 فقط تلگرام قابل اجرا است."), 400
        if job["status"] == "running":
            return jsonify(ok=False, error="این جاب هم‌اکنون در حال اجرا است."), 409
        account = account_get(job["source_account_id"])
        if not account or account["status"] != "connected":
            return jsonify(ok=False, error="اکانت متصل جاب در دسترس نیست."), 400

        config = json_load(job["config_json"])
        try:
            max_items = int(config.get("max_items", 250))
            if not 1 <= max_items <= 5000:
                raise ValueError
            if job["start_mode"] == "message_id" and not job["start_external_id"]:
                raise ValueError
            if job["start_mode"] == "date" and not job["start_date_utc"]:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify(ok=False, error="پیکربندی جاب معتبر نیست."), 400

        with closing(db_connect()) as conn:
            conn.execute(
                """
                UPDATE extraction_jobs SET status = 'running', last_error = NULL,
                    last_run_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (job_id,),
            )
            conn.execute(
                """
                INSERT INTO extraction_runs
                    (extraction_job_id, status, start_mode, start_cursor)
                VALUES (?, 'running', ?, ?)
                """,
                (job_id, job["start_mode"], job["cursor_external_id"]),
            )
            conn.commit()

        write_operation_log(job_id, "RUN_STARTED", f"استخراج با سقف {max_items} پیام آغاز شد.")

        started = time.perf_counter()
        try:
            with account_lock(account["id"]):
                result = run_async(
                    fetch_messages(
                        telegram_client(account),
                        job,
                        max_items,
                    )
                )
            elapsed = round(time.perf_counter() - started, 3)
            inserted, updated = persist_messages(job_id, result, elapsed)
            write_operation_log(
                job_id,
                "RUN_FINISHED",
                f"{len(result['messages'])} دریافت؛ {inserted} جدید؛ {updated} بروزرسانی.",
            )
            return jsonify(
                ok=True,
                job_id=job_id,
                source={
                    "key": result["source_key"],
                    "title": result["source_title"],
                    "username": result["source_username"],
                    "kind": result["source_kind"],
                },
                fetched=len(result["messages"]),
                inserted=inserted,
                updated=updated,
                cursor=max(
                    [
                        int(item["external_id"])
                        for item in result["messages"]
                        if str(item["external_id"]).isdigit()
                    ]
                    or [
                        int(job["cursor_external_id"])
                        if str(job["cursor_external_id"] or "").isdigit()
                        else 0
                    ]
                ),
                elapsed_seconds=elapsed,
                message="استخراج و ذخیره کامل شد.",
            )
        except Exception as exc:
            error_text = str(exc)[:2000]
            elapsed = round(time.perf_counter() - started, 3)
            with closing(db_connect()) as conn:
                conn.execute(
                    """
                    UPDATE extraction_jobs SET status = 'failed', last_error = ?,
                        updated_at = CURRENT_TIMESTAMP WHERE id = ?
                    """,
                    (error_text, job_id),
                )
                conn.execute(
                    """
                    UPDATE extraction_runs SET status = 'failed', error_text = ?,
                        elapsed_seconds = ?, finished_at = CURRENT_TIMESTAMP
                    WHERE id = (
                        SELECT id FROM extraction_runs
                        WHERE extraction_job_id = ? AND status = 'running'
                        ORDER BY id DESC LIMIT 1
                    )
                    """,
                    (error_text, elapsed, job_id),
                )
                conn.commit()
            write_operation_log(job_id, "RUN_FAILED", error_text, "error")
            return jsonify(ok=False, error=error_text, job_id=job_id), 500

    @app.get(f"{BASE_PATH}/api/v2/extraction-jobs/<int:job_id>/runs")
    @login_required
    def extraction_job_runs(job_id):
        if not extraction_job(job_id):
            return jsonify(ok=False, error="جاب استخراج پیدا نشد."), 404
        with closing(db_connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM extraction_runs
                WHERE extraction_job_id = ? ORDER BY id DESC LIMIT 50
                """,
                (job_id,),
            ).fetchall()
        return jsonify(ok=True, runs=[dict(row) for row in rows])

    @app.get(f"{BASE_PATH}/api/v2/extraction-jobs/<int:job_id>/content")
    @login_required
    def extraction_job_content(job_id):
        if not extraction_job(job_id):
            return jsonify(ok=False, error="جاب استخراج پیدا نشد."), 404
        with closing(db_connect()) as conn:
            rows = conn.execute(
                """
                SELECT ci.id, ci.external_id, ci.published_at, ci.content_type,
                       ci.raw_text, ci.source_title, ci.media_json, ci.metadata_json
                FROM extraction_job_items eji
                INNER JOIN content_items ci ON ci.id = eji.content_id
                WHERE eji.extraction_job_id = ?
                ORDER BY CAST(ci.external_id AS INTEGER) DESC LIMIT 100
                """,
                (job_id,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["media"] = json_load(item.pop("media_json"), [])
            item["metadata"] = json_load(item.pop("metadata_json"), {})
            items.append(item)
        return jsonify(ok=True, count=len(items), items=items)
