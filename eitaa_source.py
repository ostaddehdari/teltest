"""Public Eitaa channel extractor for TelTest (no Eitaa account required).

The public HTML interface is unofficial and may change. Only public channels
are supported. Extraction stores media URLs; transfer downloads media on demand.
"""
import hashlib
import json
import re
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from flask import jsonify

from job_engine import db_connect
from content_rules import normalize_rules
from telegram_extractor_v2 import (
    json_dump, parse_persian_date, write_operation_log,
)
from content_rules import apply_content_rules, sync_content_index

BASE_PATH = "/teltest"
CHANNEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,63}$")
IMAGE_RE = re.compile(r"background-image\\s*:\\s*url\\(\\s*['\\\"]?([^)'\\\"]+)", re.I)
MAX_PAGE_BYTES = 5 * 1024 * 1024


def clean_channel(value):
    raw = str(value or "").strip()
    if raw.startswith("@"):
        raw = raw[1:]
    elif "://" in raw or raw.startswith("eitaa.com/"):
        url = urlparse(raw if "://" in raw else "https://" + raw)
        if url.hostname not in {"eitaa.com", "www.eitaa.com"} or url.username or url.password:
            raise ValueError("فقط شناسه یا لینک عمومی eitaa.com پذیرفته می‌شود.")
        raw = url.path.strip("/").split("/")[0]
        if raw == "s":
            parts = url.path.strip("/").split("/")
            raw = parts[1] if len(parts) >= 2 else ""
    if not CHANNEL_RE.fullmatch(raw):
        raise ValueError("شناسه کانال عمومی ایتا معتبر نیست.")
    return raw.lower()


def safe_media_url(value):
    url = urljoin("https://eitaa.com/", str(value or "").strip())
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or (
        parsed.hostname != "eitaa.com"
        and not parsed.hostname.endswith(".eitaa.com")
    ) or parsed.username or parsed.password or parsed.port not in (None, 443):
        return None
    return url.split("#", 1)[0]


def parse_page(html, username):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one(".etme_channel_info_header_title, .etme_header_title, .etme_channel_info_header_username")
    title_text = title.get_text(" ", strip=True) if title else username
    output = {}
    for node in soup.select(".etme_widget_message[data-post]"):
        post_ref = str(node.get("data-post") or "")
        try:
            mid = int(post_ref.rsplit("/", 1)[-1])
            if mid < 1:
                continue
        except ValueError:
            continue
        body = node.select_one(".etme_widget_message_text")
        raw_text = body.get_text(separator=" ", strip=True) if body else ""
        links = []
        if body:
            for anchor in body.select("a[href]"):
                href = str(anchor.get("href") or "").strip()
                if href.startswith(("http://", "https://")):
                    links.append(href)
                elif href.startswith(("eitaa.com/", "t.me/")):
                    links.append("https://" + href)
        when = node.select_one("time[datetime]")
        published = when.get("datetime") if when else None
        if published:
            try:
                published = datetime.fromisoformat(published.replace("Z", "+00:00")).isoformat()
            except ValueError:
                published = None
        media, seen = [], set()
        def add(kind, url):
            safe = safe_media_url(url)
            if safe and safe not in seen:
                seen.add(safe)
                media.append({"kind": kind, "url": safe})
        for image in node.select(".etme_widget_message_photo_wrap, .etme_widget_message_photo"):
            match = IMAGE_RE.search(image.get("style") or "")
            if match:
                add("photo", match.group(1))
        for video in node.select("video[src], video source[src]"):
            add("video", video.get("src"))
        for a in node.select("a.etme_widget_message_document_wrap[href], a.etme_widget_message_video_player[href]"):
            add("document", a.get("href"))
        kind = media[0]["kind"] if media else "text"
        view_tag = node.select_one(".etme_widget_message_views")
        views = (view_tag.get("data-count") or view_tag.get_text(" ", strip=True)) if view_tag else None
        output[mid] = {
            "external_id": str(mid),
            "published_at": published,
            "content_type": kind,
            "raw_text": raw_text,
            "media": media,
            "metadata": {"eitaa": {"views": views, "url": f"https://eitaa.com/{username}/{mid}"},
                         "links": list(dict.fromkeys(links))},
        }
    return title_text, [output[mid] for mid in sorted(output, reverse=True)]


def fetch_messages(job, max_items):
    username = clean_channel(job["source_ref"])
    cfg = json.loads(job["config_json"] or "{}")
    before = cfg.get("backfill_before")
    cursor = int(job["cursor_external_id"] or 0)
    backfill_done = bool(cfg.get("backfill_done"))
    incremental = backfill_done and (job["start_mode"] == "incremental" or job["watch_enabled"]) and cursor > 0
    if incremental:
        before = None
    all_rows, visited, title = [], set(), username
    page_count, exhausted = 0, False
    threshold = None
    if job["start_mode"] == "date" and job["start_date_utc"]:
        threshold = datetime.fromisoformat(job["start_date_utc"])
        if threshold.tzinfo is None:
            threshold = threshold.replace(tzinfo=timezone.utc)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; TelTest-EitaaCrawler/1.0)"}
    with httpx.Client(timeout=httpx.Timeout(25, connect=10), headers=headers, follow_redirects=False) as client:
        while len(all_rows) < max_items and page_count < 300:
            url = f"https://eitaa.com/{username}"
            params = {"before": int(before)} if before else None
            response = client.get(url, params=params)
            response.raise_for_status()
            if len(response.content) > MAX_PAGE_BYTES:
                raise RuntimeError("اندازه صفحه عمومی ایتا بیش از حد مجاز است.")
            title, rows = parse_page(response.text, username)
            page_count += 1
            if not rows:
                exhausted = True
                break
            oldest = min(int(item["external_id"]) for item in rows)
            for item in rows:
                number = int(item["external_id"])
                if number in visited:
                    continue
                visited.add(number)
                if incremental and number <= cursor:
                    exhausted = True
                    continue
                if job["start_mode"] == "message_id" and job["start_external_id"] and number < int(job["start_external_id"]):
                    exhausted = True
                    continue
                if threshold and item["published_at"]:
                    post_date = datetime.fromisoformat(item["published_at"])
                    if post_date.tzinfo is None:
                        post_date = post_date.replace(tzinfo=timezone.utc)
                    if post_date < threshold:
                        exhausted = True
                        continue
                all_rows.append(item)
            if exhausted or before == oldest:
                break
            before = oldest
            # No unbounded polling: each request must move to an older post.
            if len(rows) < 2:
                exhausted = True
                break
    historical_before = None if (exhausted or incremental) else before
    return {
        "connector_code": "eitaa",
        "source_key": "eitaa:" + username,
        "source_title": title,
        "source_username": username,
        "source_kind": "public_channel",
        "joined_source": False,
        "messages": all_rows,
        "backfill_before": historical_before,
        "backfill_done": bool(exhausted or incremental),
        "pages": page_count,
    }


def create_eitaa_job(data):
    try:
        username = clean_channel(data.get("source_ref"))
        start_mode = str(data.get("start_mode") or "all")
        if start_mode not in {"all", "date", "message_id", "incremental"}:
            raise ValueError("حالت شروع معتبر نیست.")
        max_items = int(data.get("max_items", 250))
        interval = int(data.get("poll_interval_minutes", 5))
        if not 1 <= max_items <= 5000 or not 1 <= interval <= 1440:
            raise ValueError("محدوده تعداد پیام یا فاصله پایش معتبر نیست.")
        start_date = parse_persian_date(data.get("start_date_jalali")) if start_mode == "date" else None
        start_id = str(int(data.get("start_external_id"))) if start_mode == "message_id" else None
        if start_mode == "message_id" and (not start_id or int(start_id) < 1):
            raise ValueError("شناسه شروع معتبر نیست.")
    except (TypeError, ValueError) as exc:
        return jsonify(ok=False, error=str(exc)), 400
    watch = str(data.get("watch_enabled", "0")).lower() in {"true", "1", "yes", "on"}
    cfg = {"extractor": "eitaa-public-html", "max_items": max_items,
           "backfill_before": None, "backfill_done": start_mode == "incremental"}
    with closing(db_connect()) as conn:
        result = conn.execute("""
            INSERT INTO extraction_jobs
            (name, connector_code, source_account_id, source_ref, status,
             start_mode, start_date_utc, start_external_id, watch_enabled,
             poll_interval_minutes, config_json, rules_json, next_run_at)
            VALUES (?, 'eitaa', NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(data.get("name") or username)[:255], "https://eitaa.com/" + username,
              "watching" if watch else "draft", start_mode, start_date, start_id,
              int(watch), interval, json_dump(cfg), json_dump(normalize_rules(data.get("rules") or {})),
              datetime.now(timezone.utc).isoformat() if watch else None))
        job_id = result.lastrowid
        conn.commit()
    write_operation_log(job_id, "JOB_CREATED", f"کانال عمومی ایتا: @{username}")
    return jsonify(ok=True, job_id=job_id, status="watching" if watch else "draft",
                   message="جاب استخراج ایتا ساخته شد."), 201


def persist_messages(job_id, result, elapsed):
    rows = result["messages"]
    with closing(db_connect()) as conn:
        job = conn.execute("SELECT * FROM extraction_jobs WHERE id=?", (job_id,)).fetchone()
        rules = normalize_rules(json.loads(job["rules_json"] or "{}"))
        inserted = updated = skipped = 0
        for item in rows:
            evaluation = apply_content_rules(item["raw_text"], rules)
            skipped += int(evaluation["excluded"])
            old = conn.execute("""
                SELECT id FROM content_items WHERE connector_code='eitaa'
                AND source_key=? AND external_id=?
            """, (result["source_key"], item["external_id"])).fetchone()
            digest = hashlib.sha256(json_dump(item).encode()).hexdigest()
            conn.execute("""
                INSERT INTO content_items
                (connector_code,source_key,source_ref,source_title,external_id,
                 published_at,content_type,raw_text,processed_text,media_json,
                 metadata_json,content_hash,updated_at)
                VALUES('eitaa',?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(connector_code,source_key,external_id) DO UPDATE SET
                  source_title=excluded.source_title, published_at=excluded.published_at,
                  content_type=excluded.content_type, raw_text=excluded.raw_text,
                  processed_text=excluded.processed_text, media_json=excluded.media_json,
                  metadata_json=excluded.metadata_json,content_hash=excluded.content_hash,
                  updated_at=CURRENT_TIMESTAMP
            """, (result["source_key"], job["source_ref"], result["source_title"],
                  item["external_id"], item["published_at"], item["content_type"],
                  item["raw_text"], evaluation["processed_text"],
                  json_dump(item["media"]), json_dump(item["metadata"]), digest))
            content_id = conn.execute("""
                SELECT id FROM content_items WHERE connector_code='eitaa'
                AND source_key=? AND external_id=?
            """, (result["source_key"],item["external_id"])).fetchone()["id"]
            conn.execute("""
                INSERT INTO extraction_job_items
                (extraction_job_id,content_id,processed_text,excluded,rule_reason,rules_hash,processed_at)
                VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(extraction_job_id,content_id) DO UPDATE SET
                  processed_text=excluded.processed_text,excluded=excluded.excluded,
                  rule_reason=excluded.rule_reason,rules_hash=excluded.rules_hash,
                  processed_at=CURRENT_TIMESTAMP
            """, (job_id,content_id,evaluation["processed_text"],int(evaluation["excluded"]),
                  evaluation["reason"],hashlib.sha256(json_dump(rules).encode()).hexdigest()))
            sync_content_index(conn,content_id,item["raw_text"])
            updated += int(bool(old))
            inserted += int(not old)
        cursor = max([int(job["cursor_external_id"] or 0)] +
                     [int(i["external_id"]) for i in rows])
        published = sorted([i["published_at"] for i in rows if i["published_at"]])
        next_run = (datetime.now(timezone.utc) + timedelta(
            minutes=int(job["poll_interval_minutes"] or 5))).isoformat() if job["watch_enabled"] else None
        conn.execute("""
            UPDATE extraction_jobs SET source_key=?,source_title=?,status=?,
            cursor_external_id=?,cursor_published_at=?,next_run_at=?,
            last_success_at=CURRENT_TIMESTAMP,last_error=NULL,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (result["source_key"],result["source_title"],
              "watching" if job["watch_enabled"] else "completed",
              str(cursor),published[-1] if published else job["cursor_published_at"],
              next_run,job_id))
        conn.execute("""
            UPDATE extraction_runs SET status='completed', resolved_source_key=?,
            fetched_count=?,inserted_count=?,updated_count=?,skipped_count=?,
            elapsed_seconds=?,finished_at=CURRENT_TIMESTAMP
            WHERE id=(SELECT id FROM extraction_runs WHERE extraction_job_id=?
                      AND status='running' ORDER BY id DESC LIMIT 1)
        """, (result["source_key"],len(rows),inserted,updated,skipped,elapsed,job_id))
        conn.commit()
    return inserted,updated,skipped


def run_eitaa_job(job_id, watch_run=False):
    with closing(db_connect()) as conn:
        job = conn.execute("SELECT * FROM extraction_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            return {"ok": False, "error": "جاب پیدا نشد.", "http_status": 404}
        if job["connector_code"] != "eitaa":
            return {"ok": False, "error": "جاب ایتا نیست.", "http_status": 400}
        if watch_run and not job["watch_enabled"]:
            return {"ok": True, "skipped": "watch_disabled"}
        claimed = conn.execute("""
            UPDATE extraction_jobs SET status='running', last_error=NULL,
                last_run_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND status<>'running'
        """, (job_id,))
        if claimed.rowcount != 1:
            return {"ok": False, "error": "جاب در حال اجرا است.", "http_status": 409}
        conn.execute("""
            INSERT INTO extraction_runs(extraction_job_id,status,start_mode,start_cursor)
            VALUES (?, 'running', ?, ?)
        """, (job_id, job["start_mode"], job["cursor_external_id"]))
        conn.commit()
    began = time.monotonic()
    try:
        cfg = json.loads(job["config_json"] or "{}")
        limit = int(cfg.get("max_items", 250))
        result = fetch_messages(job, limit)
        elapsed = round(time.monotonic() - began, 3)
        inserted, updated, skipped = persist_messages(job_id, result, elapsed)
        cfg["backfill_before"] = result["backfill_before"]
        cfg["backfill_done"] = result["backfill_done"]
        with closing(db_connect()) as conn:
            conn.execute("UPDATE extraction_jobs SET config_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (json_dump(cfg), job_id))
            # When backfilling, continue promptly even if page limit reached.
            if job["watch_enabled"] and result["backfill_before"]:
                conn.execute("UPDATE extraction_jobs SET next_run_at=? WHERE id=?",
                             ((datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(), job_id))
            conn.commit()
        write_operation_log(job_id, "RUN_FINISHED",
                            f"ایتا: {len(result['messages'])} دریافت، {inserted} جدید، {updated} بروزرسانی")
        return {"ok": True, "job_id": job_id, "fetched": len(result["messages"]),
                "inserted": inserted, "updated": updated, "skipped": skipped,
                "pages": result["pages"], "backfill_remaining": bool(result["backfill_before"]),
                "elapsed_seconds": elapsed, "message": "استخراج ایتا ذخیره شد."}
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:1900]
        with closing(db_connect()) as conn:
            delay = (datetime.now(timezone.utc) + timedelta(minutes=max(5, int(job["poll_interval_minutes"] or 5)))).isoformat()
            conn.execute("""
                UPDATE extraction_jobs SET status=?, last_error=?, next_run_at=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=?
            """, ("watching" if job["watch_enabled"] else "failed", error,
                  delay if job["watch_enabled"] else None, job_id))
            conn.execute("""
                UPDATE extraction_runs SET status='failed', error_text=?, elapsed_seconds=?,
                    finished_at=CURRENT_TIMESTAMP
                WHERE id=(SELECT id FROM extraction_runs
                          WHERE extraction_job_id=? AND status='running'
                          ORDER BY id DESC LIMIT 1)
            """, (error, round(time.monotonic() - began, 3), job_id))
            conn.commit()
        write_operation_log(job_id, "RUN_FAILED", error, "error")
        return {"ok": False, "job_id": job_id, "error": error, "http_status": 502}


def run_eitaa_response(job_id):
    result = run_eitaa_job(job_id)
    return jsonify(**{k: v for k, v in result.items() if k != "http_status"}), result.get("http_status", 200)
