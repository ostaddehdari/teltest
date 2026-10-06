import asyncio
import mimetypes
import shutil
import time

from contextlib import closing
from pathlib import Path

import httpx

from flask import jsonify, request

from job_engine import (
    account_lock,
    db_connect,
    job_get,
    log_job,
    resolve_source,
)


BASE_PATH = "/teltest"

BALE_API = "https://tapi.bale.ai"

RUNTIME = Path(
    "/var/lib/teltest"
)

TMP_ROOT = (
    RUNTIME
    / "tmp"
    / "bale"
)

TMP_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# SCHEMA
# ============================================================

def ensure_schema():

    with closing(
        db_connect()
    ) as conn:

        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(jobs)"
            ).fetchall()
        }


        additions = {
            "bale_enabled":
                "bale_enabled INTEGER NOT NULL DEFAULT 0",

            "bale_status":
                "bale_status TEXT NOT NULL DEFAULT 'none'",

            "bale_sent_count":
                "bale_sent_count INTEGER NOT NULL DEFAULT 0",

            "bale_seconds":
                "bale_seconds REAL",

            "bale_rate":
                "bale_rate REAL",

            "bale_last_error":
                "bale_last_error TEXT",
        }


        for name, ddl in additions.items():

            if name not in columns:

                conn.execute(
                    f"""
                    ALTER TABLE jobs
                    ADD COLUMN {ddl}
                    """
                )


        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS bale_items (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                job_id INTEGER NOT NULL,

                source_message_id INTEGER NOT NULL,

                status TEXT NOT NULL
                    DEFAULT 'pending',

                bale_message_id TEXT,

                media_type TEXT,

                attempts INTEGER NOT NULL
                    DEFAULT 0,

                last_error TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                sent_at TEXT,

                UNIQUE(
                    job_id,
                    source_message_id
                ),

                FOREIGN KEY(job_id)
                    REFERENCES jobs(id)
                    ON DELETE CASCADE
            );


            CREATE INDEX IF NOT EXISTS
                idx_bale_items_job
                ON bale_items(
                    job_id,
                    status
                );
            """
        )


        conn.commit()


# ============================================================
# SETTINGS
# ============================================================

def setting_get(
    key,
    default="",
):

    with closing(
        db_connect()
    ) as conn:

        row = conn.execute(
            """
            SELECT value
            FROM settings
            WHERE key = ?
            """,
            (key,),
        ).fetchone()


    if not row:
        return default

    return row["value"]


def setting_set(
    key,
    value,
):

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            INSERT INTO settings (
                key,
                value,
                updated_at
            )
            VALUES (
                ?, ?,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                key,
                str(value),
            ),
        )

        conn.commit()


def bale_config():

    token = setting_get(
        "bale_bot_token"
    ).strip()

    chat_id = setting_get(
        "bale_chat_id"
    ).strip()


    if not token or not chat_id:
        return None


    return {
        "token": token,
        "chat_id": chat_id,
    }


# ============================================================
# BALE HTTP
# ============================================================

class BaleError(
    RuntimeError
):
    pass


async def bale_request(
    token,
    method,
    data=None,
    files=None,
    timeout=120,
):

    url = (
        f"{BALE_API}/bot{token}/{method}"
    )


    async with httpx.AsyncClient(
        timeout=httpx.Timeout(
            timeout,
            connect=20,
        )
    ) as client:

        response = await client.post(
            url,
            data=data or {},
            files=files,
        )


        response.raise_for_status()


        payload = response.json()


        if not payload.get(
            "ok"
        ):

            raise BaleError(
                payload.get(
                    "description"
                )
                or str(payload)
            )


        return payload.get(
            "result"
        )


async def bale_get_me(
    token
):

    return await bale_request(
        token,
        "getMe",
    )


async def bale_get_chat(
    token,
    chat_id
):

    return await bale_request(
        token,
        "getChat",
        {
            "chat_id":
                chat_id
        },
    )


# ============================================================
# MESSAGE HELPERS
# ============================================================

def message_media_type(
    message
):

    if getattr(
        message,
        "photo",
        None,
    ):
        return "photo"

    if getattr(
        message,
        "video",
        None,
    ):
        return "video"

    if getattr(
        message,
        "voice",
        None,
    ):
        return "voice"

    if getattr(
        message,
        "audio",
        None,
    ):
        return "audio"

    if getattr(
        message,
        "document",
        None,
    ):
        return "document"

    return "text"


def result_message_id(
    result
):

    if not isinstance(
        result,
        dict,
    ):
        return None


    value = result.get(
        "message_id"
    )


    if value is None:
        return None


    return str(
        value
    )


async def send_text(
    token,
    chat_id,
    text,
):

    return await bale_request(
        token,
        "sendMessage",
        {
            "chat_id":
                chat_id,

            "text":
                text,
        },
    )


async def send_file(
    token,
    chat_id,
    path,
    kind,
    caption,
):

    path = Path(
        path
    )


    mime = (
        mimetypes.guess_type(
            path.name
        )[0]
        or "application/octet-stream"
    )


    method = "sendDocument"
    field = "document"


    if kind == "photo":

        method = "sendPhoto"
        field = "photo"


    elif kind == "video":

        method = "sendVideo"
        field = "video"


    elif kind == "audio":

        method = "sendAudio"
        field = "audio"


    elif kind == "voice":

        method = "sendVoice"
        field = "voice"


    data = {
        "chat_id":
            chat_id,
    }


    #
    # Caption را عمداً محدود نگه می‌داریم.
    # اگر متن طولانی باشد ادامه آن با sendMessage
    # فرستاده می‌شود.
    #
    short_caption = (
        caption[:900]
        if caption
        else ""
    )


    if short_caption:

        data[
            "caption"
        ] = short_caption


    with path.open(
        "rb"
    ) as handle:

        result = await bale_request(
            token,
            method,
            data=data,
            files={
                field: (
                    path.name,
                    handle,
                    mime,
                )
            },
            timeout=300,
        )


    if (
        caption
        and len(
            caption
        ) > 900
    ):

        await send_text(
            token,
            chat_id,
            caption[900:],
        )


    return result


# ============================================================
# DATABASE ITEM STATE
# ============================================================

def reset_bale_items(
    job_id
):

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            DELETE FROM bale_items
            WHERE job_id = ?
            """,
            (job_id,),
        )

        conn.execute(
            """
            UPDATE jobs
            SET
                bale_sent_count = 0,
                bale_seconds = NULL,
                bale_rate = NULL,
                bale_last_error = NULL,
                bale_status = 'pending'
            WHERE id = ?
            """,
            (job_id,),
        )

        conn.commit()


def prepare_item(
    job_id,
    message_id,
):

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            INSERT OR IGNORE INTO bale_items (
                job_id,
                source_message_id,
                status
            )
            VALUES (
                ?, ?, 'pending'
            )
            """,
            (
                job_id,
                message_id,
            ),
        )

        conn.commit()


def mark_item(
    job_id,
    message_id,
    status,
    media_type=None,
    bale_message_id=None,
    error=None,
):

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            UPDATE bale_items
            SET
                status = ?,
                media_type = ?,
                bale_message_id = ?,
                attempts = attempts + 1,
                last_error = ?,
                sent_at =
                    CASE
                        WHEN ? = 'sent'
                        THEN CURRENT_TIMESTAMP
                        ELSE sent_at
                    END
            WHERE
                job_id = ?
                AND source_message_id = ?
            """,
            (
                status,
                media_type,
                bale_message_id,
                (
                    str(error)[:1500]
                    if error
                    else None
                ),
                status,
                job_id,
                message_id,
            ),
        )

        conn.commit()


def bale_count(
    job_id
):

    with closing(
        db_connect()
    ) as conn:

        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM bale_items
            WHERE
                job_id = ?
                AND status = 'sent'
            """,
            (job_id,),
        ).fetchone()


    return int(
        row["n"]
    )


def update_job(
    job_id,
    *,
    status=None,
    sent=None,
    seconds=None,
    rate=None,
    error=None,
):

    fields = []
    values = []


    mapping = {
        "bale_status":
            status,

        "bale_sent_count":
            sent,

        "bale_seconds":
            seconds,

        "bale_rate":
            rate,

        "bale_last_error":
            error,
    }


    for name, value in mapping.items():

        if value is not None:

            fields.append(
                f"{name} = ?"
            )

            values.append(
                value
            )


    if not fields:
        return


    values.append(
        job_id
    )


    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            f"""
            UPDATE jobs
            SET
                {", ".join(fields)}
            WHERE id = ?
            """,
            values,
        )

        conn.commit()


# ============================================================
# TELEGRAM -> BALE
# ============================================================

async def mirror_job(
    telegram_client,
    job,
    token,
    chat_id,
):

    job_id = int(
        job["id"]
    )


    await telegram_client.connect()


    tmp_dir = (
        TMP_ROOT
        / f"job-{job_id}"
    )


    if tmp_dir.exists():

        shutil.rmtree(
            tmp_dir,
            ignore_errors=True,
        )


    tmp_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    try:

        if not await telegram_client.is_user_authorized():

            raise RuntimeError(
                "Telegram Session authorized نیست."
            )


        source, _joined = (
            await resolve_source(
                telegram_client,
                job["source_ref"],
            )
        )


        log_job(
            job_id,
            "BALE_SOURCE_RESOLVED",
            (
                "Telegram Source برای انتقال "
                "به بله Resolve شد."
            ),
        )


        messages = [
            message
            async for message
            in telegram_client.iter_messages(
                source,
                limit=job[
                    "limit_count"
                ],
            )
        ]


        #
        # از قدیمی به جدید ارسال کنیم
        #
        messages.reverse()


        total = len(
            messages
        )


        log_job(
            job_id,
            "BALE_TRANSFER_STARTED",
            (
                f"{total} پیام برای بله آماده شد. "
                f"Destination={chat_id}"
            ),
        )


        for index, message in enumerate(
            messages,
            start=1,
        ):

            message_id = int(
                message.id
            )


            prepare_item(
                job_id,
                message_id,
            )


            kind = message_media_type(
                message
            )


            text = (
                message.message
                or ""
            )


            try:

                if kind == "text":

                    if not text:

                        mark_item(
                            job_id,
                            message_id,
                            "skipped",
                            media_type=kind,
                        )

                        continue


                    result = await send_text(
                        token,
                        chat_id,
                        text,
                    )


                else:

                    downloaded = (
                        await telegram_client.download_media(
                            message,
                            file=str(
                                tmp_dir
                            ),
                        )
                    )


                    if not downloaded:

                        #
                        # اگر مدیا قابل دانلود نبود،
                        # حداقل متن را از دست نده.
                        #
                        if text:

                            result = await send_text(
                                token,
                                chat_id,
                                text,
                            )

                        else:

                            raise RuntimeError(
                                "Media download returned empty path"
                            )


                    else:

                        result = await send_file(
                            token=token,
                            chat_id=chat_id,
                            path=downloaded,
                            kind=kind,
                            caption=text,
                        )


                mark_item(
                    job_id,
                    message_id,
                    "sent",
                    media_type=kind,
                    bale_message_id=
                        result_message_id(
                            result
                        ),
                )


                count = bale_count(
                    job_id
                )


                update_job(
                    job_id,
                    sent=count,
                )


                if (
                    index % 5 == 0
                    or index == total
                ):

                    log_job(
                        job_id,
                        "BALE_PROGRESS",
                        (
                            f"{count} / {total} "
                            "پیام به بله ارسال شد."
                        ),
                    )


            except Exception as exc:

                mark_item(
                    job_id,
                    message_id,
                    "failed",
                    media_type=kind,
                    error=(
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )


                log_job(
                    job_id,
                    "BALE_ITEM_FAILED",
                    (
                        f"Telegram Message "
                        f"{message_id}: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                    level="error",
                )


                raise


        return {
            "total":
                total,

            "sent":
                bale_count(
                    job_id
                ),
        }


    finally:

        await telegram_client.disconnect()

        shutil.rmtree(
            tmp_dir,
            ignore_errors=True,
        )


# ============================================================
# FLASK
# ============================================================

def init_bale(
    app,
    login_required,
    api_post_required,
    telegram_client,
    account_get,
):

    ensure_schema()


    # --------------------------------------------------------
    # SETTINGS GET
    # --------------------------------------------------------

    @app.get(
        f"{BASE_PATH}/api/settings/bale"
    )
    @login_required
    def get_bale_settings():

        token = setting_get(
            "bale_bot_token"
        )

        chat_id = setting_get(
            "bale_chat_id"
        )


        masked = ""


        if token:

            if len(token) > 12:

                masked = (
                    token[:5]
                    + "••••••••"
                    + token[-5:]
                )

            else:

                masked = "••••••••"


        return jsonify(
            ok=True,
            configured=bool(
                token
                and chat_id
            ),
            token_masked=
                masked,
            chat_id=
                chat_id,
        )


    # --------------------------------------------------------
    # SETTINGS SAVE
    # --------------------------------------------------------

    @app.post(
        f"{BASE_PATH}/api/settings/bale"
    )
    @api_post_required
    def save_bale_settings():

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )


        token = str(
            data.get(
                "token",
                "",
            )
        ).strip()


        chat_id = str(
            data.get(
                "chat_id",
                "",
            )
        ).strip()


        current = setting_get(
            "bale_bot_token"
        )


        if not token:

            token = current


        if not token:

            return jsonify(
                ok=False,
                error=(
                    "توکن ربات بله وارد نشده است."
                ),
            ), 400


        if not chat_id:

            return jsonify(
                ok=False,
                error=(
                    "Chat ID یا Username مقصد بله "
                    "وارد نشده است."
                ),
            ), 400


        setting_set(
            "bale_bot_token",
            token,
        )


        setting_set(
            "bale_chat_id",
            chat_id,
        )


        return jsonify(
            ok=True,
            message=(
                "تنظیمات ربات بله ذخیره شد."
            ),
        )


    # --------------------------------------------------------
    # CONNECTION TEST
    # --------------------------------------------------------

    @app.post(
        f"{BASE_PATH}/api/settings/bale/test"
    )
    @api_post_required
    def test_bale_settings():

        config = bale_config()


        if not config:

            return jsonify(
                ok=False,
                error=(
                    "ابتدا تنظیمات بله را ذخیره کن."
                ),
            ), 400


        try:

            async def test():

                me = await bale_get_me(
                    config["token"]
                )

                chat = await bale_get_chat(
                    config["token"],
                    config["chat_id"],
                )

                return me, chat


            me, chat = asyncio.run(
                test()
            )


            return jsonify(
                ok=True,

                bot=me,

                chat=chat,

                message=(
                    "ربات بله و مقصد با موفقیت "
                    "تأیید شدند."
                ),
            )


        except Exception as exc:

            return jsonify(
                ok=False,
                error=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            ), 400


    # --------------------------------------------------------
    # MIRROR JOB
    # --------------------------------------------------------

    @app.post(
        f"{BASE_PATH}/api/jobs/<int:job_id>/bale"
    )
    @api_post_required
    def send_job_to_bale(
        job_id
    ):

        config = bale_config()


        if not config:

            return jsonify(
                ok=False,
                error=(
                    "Bale Bot هنوز تنظیم نشده است."
                ),
            ), 400


        job = job_get(
            job_id
        )


        if not job:

            return jsonify(
                ok=False,
                error="Job پیدا نشد.",
            ), 404


        account = account_get(
            job["account_id"]
        )


        if not account:

            return jsonify(
                ok=False,
                error="اکانت Telegram پیدا نشد.",
            ), 404


        reset_bale_items(
            job_id
        )


        update_job(
            job_id,
            status="running",
            sent=0,
            error="",
        )


        log_job(
            job_id,
            "BALE_REQUESTED",
            (
                f"ارسال Job به بله آغاز شد. "
                f"Destination={config['chat_id']}"
            ),
        )


        started = time.perf_counter()


        try:

            with account_lock(
                job["account_id"]
            ):

                client = telegram_client(
                    account
                )


                result = asyncio.run(
                    mirror_job(
                        telegram_client=
                            client,
                        job=job,
                        token=config[
                            "token"
                        ],
                        chat_id=config[
                            "chat_id"
                        ],
                    )
                )


            elapsed = (
                time.perf_counter()
                - started
            )


            rate = (
                result["sent"]
                / elapsed
                if elapsed > 0
                else 0
            )


            update_job(
                job_id,
                status="completed",
                sent=result[
                    "sent"
                ],
                seconds=round(
                    elapsed,
                    4,
                ),
                rate=round(
                    rate,
                    4,
                ),
                error="",
            )


            log_job(
                job_id,
                "BALE_COMPLETED",
                (
                    f"{result['sent']} / "
                    f"{result['total']} پیام "
                    f"در {elapsed:.2f}s "
                    "به بله ارسال شد. "
                    f"Rate={rate:.2f} msg/s"
                ),
            )


            return jsonify(
                ok=True,
                job_id=job_id,
                sent=result[
                    "sent"
                ],
                total=result[
                    "total"
                ],
                seconds=round(
                    elapsed,
                    4,
                ),
                rate=round(
                    rate,
                    4,
                ),
                message=(
                    f"{result['sent']} پیام "
                    "به بله ارسال شد."
                ),
            )


        except Exception as exc:

            elapsed = (
                time.perf_counter()
                - started
            )


            update_job(
                job_id,
                status="failed",
                sent=bale_count(
                    job_id
                ),
                seconds=round(
                    elapsed,
                    4,
                ),
                error=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )


            log_job(
                job_id,
                "BALE_FAILED",
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                level="error",
            )


            return jsonify(
                ok=False,
                error=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            ), 500
