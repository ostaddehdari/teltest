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

RUNTIME = Path(
    "/var/lib/teltest"
)

TMP_ROOT = (
    RUNTIME
    / "tmp"
    / "external-mirror"
)

TMP_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# DATABASE
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

            "eitaa_status":
                "eitaa_status TEXT NOT NULL DEFAULT 'none'",

            "eitaa_sent_count":
                "eitaa_sent_count INTEGER NOT NULL DEFAULT 0",

            "eitaa_seconds":
                "eitaa_seconds REAL",

            "eitaa_rate":
                "eitaa_rate REAL",

            "eitaa_last_error":
                "eitaa_last_error TEXT",


            "rubika_status":
                "rubika_status TEXT NOT NULL DEFAULT 'none'",

            "rubika_sent_count":
                "rubika_sent_count INTEGER NOT NULL DEFAULT 0",

            "rubika_seconds":
                "rubika_seconds REAL",

            "rubika_rate":
                "rubika_rate REAL",

            "rubika_last_error":
                "rubika_last_error TEXT",
        }


        for _name, ddl in additions.items():

            name = ddl.split()[0]

            if name not in columns:

                conn.execute(
                    f"""
                    ALTER TABLE jobs
                    ADD COLUMN {ddl}
                    """
                )


        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS eitaa_items (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                job_id INTEGER NOT NULL,

                source_message_id INTEGER NOT NULL,

                status TEXT NOT NULL
                    DEFAULT 'pending',

                provider_message_id TEXT,

                media_type TEXT,

                attempts INTEGER NOT NULL
                    DEFAULT 0,

                last_error TEXT,

                sent_at TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(
                    job_id,
                    source_message_id
                ),

                FOREIGN KEY(job_id)
                    REFERENCES jobs(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS rubika_items (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                job_id INTEGER NOT NULL,

                source_message_id INTEGER NOT NULL,

                status TEXT NOT NULL
                    DEFAULT 'pending',

                provider_message_id TEXT,

                media_type TEXT,

                attempts INTEGER NOT NULL
                    DEFAULT 0,

                last_error TEXT,

                sent_at TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(
                    job_id,
                    source_message_id
                ),

                FOREIGN KEY(job_id)
                    REFERENCES jobs(id)
                    ON DELETE CASCADE
            );


            CREATE INDEX IF NOT EXISTS
                idx_eitaa_items_job
                ON eitaa_items(
                    job_id,
                    status
                );


            CREATE INDEX IF NOT EXISTS
                idx_rubika_items_job
                ON rubika_items(
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
                value =
                    excluded.value,
                updated_at =
                    CURRENT_TIMESTAMP
            """,
            (
                key,
                str(value),
            ),
        )

        conn.commit()


def provider_config(
    provider
):

    token = setting_get(
        f"{provider}_bot_token"
    ).strip()

    chat_id = setting_get(
        f"{provider}_chat_id"
    ).strip()


    if not token or not chat_id:
        return None


    return {
        "token": token,
        "chat_id": chat_id,
    }


# ============================================================
# GENERIC
# ============================================================

def media_type(
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

    if getattr(
        message,
        "media",
        None,
    ):
        return "media"

    return "text"


def chunks(
    text,
    size=3500,
):

    text = str(
        text or ""
    )


    if not text:
        return []


    return [
        text[i:i + size]
        for i in range(
            0,
            len(text),
            size,
        )
    ]


def table_for(
    provider
):

    if provider == "eitaa":
        return "eitaa_items"

    if provider == "rubika":
        return "rubika_items"

    raise ValueError(
        "Unknown provider"
    )


def prepare_item(
    provider,
    job_id,
    message_id,
):

    table = table_for(
        provider
    )


    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            f"""
            INSERT OR IGNORE INTO {table} (
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


def item_sent(
    provider,
    job_id,
    message_id,
):

    table = table_for(
        provider
    )


    with closing(
        db_connect()
    ) as conn:

        row = conn.execute(
            f"""
            SELECT status
            FROM {table}
            WHERE
                job_id = ?
                AND source_message_id = ?
            """,
            (
                job_id,
                message_id,
            ),
        ).fetchone()


    return bool(
        row
        and row["status"] == "sent"
    )


def mark_item(
    provider,
    job_id,
    message_id,
    status,
    *,
    media=None,
    provider_message_id=None,
    error=None,
):

    table = table_for(
        provider
    )


    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            f"""
            UPDATE {table}
            SET
                status = ?,
                provider_message_id = ?,
                media_type = ?,
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
                (
                    str(
                        provider_message_id
                    )
                    if provider_message_id
                    is not None
                    else None
                ),
                media,
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


def sent_count(
    provider,
    job_id,
):

    table = table_for(
        provider
    )


    with closing(
        db_connect()
    ) as conn:

        row = conn.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM {table}
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
    provider,
    job_id,
    *,
    status=None,
    sent=None,
    seconds=None,
    rate=None,
    error=None,
):

    if provider not in (
        "eitaa",
        "rubika",
    ):
        raise ValueError(
            "Invalid provider"
        )


    values = {
        f"{provider}_status":
            status,

        f"{provider}_sent_count":
            sent,

        f"{provider}_seconds":
            seconds,

        f"{provider}_rate":
            rate,

        f"{provider}_last_error":
            error,
    }


    fields = []
    params = []


    for key, value in values.items():

        if value is not None:

            fields.append(
                f"{key} = ?"
            )

            params.append(
                value
            )


    if not fields:
        return


    params.append(
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
            params,
        )

        conn.commit()


# ============================================================
# EXACT JOB MESSAGE IDS
# ============================================================

async def get_job_messages(
    telegram_client,
    job,
    source,
):

    with closing(
        db_connect()
    ) as conn:

        rows = conn.execute(
            """
            SELECT message_id
            FROM posts
            WHERE job_id = ?
            ORDER BY message_id ASC
            """,
            (job["id"],),
        ).fetchall()


        if not rows:

            try:

                rows = conn.execute(
                    """
                    SELECT source_message_id
                           AS message_id
                    FROM transfer_items
                    WHERE job_id = ?
                    ORDER BY seq ASC
                    """,
                    (job["id"],),
                ).fetchall()

            except Exception:

                rows = []


    ids = [
        int(row["message_id"])
        for row in rows
    ]


    if ids:

        result = await telegram_client.get_messages(
            source,
            ids=ids,
        )


        if not isinstance(
            result,
            (list, tuple),
        ):
            result = list(
                result
            )


        by_id = {
            int(item.id): item
            for item in result
            if (
                item is not None
                and getattr(
                    item,
                    "id",
                    None,
                )
            )
        }


        return [
            by_id[item_id]
            for item_id in ids
            if item_id in by_id
        ]


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


    messages.reverse()

    return messages


# ============================================================
# EITAA API
# ============================================================

class EitaaError(
    RuntimeError
):
    pass


def eitaa_ok(
    payload
):

    if not isinstance(
        payload,
        dict,
    ):
        return False


    return bool(
        payload.get("ok") is True
        or payload.get("status")
        in (
            "success",
            "ok",
        )
        or payload.get("result")
        == "success"
    )


async def eitaa_send_message(
    token,
    chat_id,
    text,
):

    last_result = None


    for part in chunks(
        text
    ):

        url = (
            "https://eitaayar.ir/api/"
            f"{token}/sendMessage"
        )


        async with httpx.AsyncClient(
            timeout=60
        ) as client:

            response = await client.post(
                url,
                json={
                    "chat_id":
                        chat_id,

                    "text":
                        part,
                },
            )


            response.raise_for_status()

            payload = response.json()


        if not eitaa_ok(
            payload
        ):

            raise EitaaError(
                str(payload)
            )


        last_result = payload


    return last_result


async def eitaa_send_document(
    token,
    chat_id,
    path,
    caption,
):

    path = Path(
        path
    )


    url = (
        "https://eitaayar.ir/api/"
        f"{token}/sendDocument"
    )


    mime = (
        mimetypes.guess_type(
            path.name
        )[0]
        or "application/octet-stream"
    )


    short_caption = (
        caption[:900]
        if caption
        else ""
    )


    with path.open(
        "rb"
    ) as handle:

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                300,
                connect=30,
            )
        ) as client:

            response = await client.post(
                url,
                data={
                    "chat_id":
                        chat_id,

                    "caption":
                        short_caption,
                },
                files={
                    "file": (
                        path.name,
                        handle,
                        mime,
                    )
                },
            )


            response.raise_for_status()

            payload = response.json()


    if not eitaa_ok(
        payload
    ):

        raise EitaaError(
            str(payload)
        )


    if (
        caption
        and len(
            caption
        ) > 900
    ):

        await eitaa_send_message(
            token,
            chat_id,
            caption[900:],
        )


    return payload


# ============================================================
# RUBIKA BOT API
# ============================================================

class RubikaError(
    RuntimeError
):
    pass


async def rubika_request(
    token,
    method,
    data=None,
):

    url = (
        "https://messengerg2b1.iranlms.ir"
        f"/v3/{token}/{method}"
    )


    async with httpx.AsyncClient(
        timeout=90
    ) as client:

        response = await client.post(
            url,
            json=data or {},
        )


        response.raise_for_status()

        payload = response.json()


    if payload.get(
        "status"
    ) != "OK":

        raise RubikaError(
            str(payload)
        )


    return (
        payload.get(
            "data"
        )
        or {}
    )


async def rubika_send_message(
    token,
    chat_id,
    text,
):

    last = None


    for part in chunks(
        text
    ):

        result = await rubika_request(
            token,
            "sendMessage",
            {
                "chat_id":
                    chat_id,

                "text":
                    part,

                "disable_notification":
                    False,
            },
        )


        last = result


    return last


def rubika_file_type(
    kind
):

    if kind == "photo":
        return "Image"

    if kind == "voice":
        return "Voice"

    if kind == "audio":
        return "Music"

    return "File"


async def rubika_upload(
    token,
    path,
    kind,
):

    path = Path(
        path
    )


    prepare = await rubika_request(
        token,
        "requestSendFile",
        {
            "type":
                rubika_file_type(
                    kind
                )
        },
    )


    upload_url = prepare.get(
        "upload_url"
    )


    if not upload_url:

        raise RubikaError(
            f"upload_url missing: {prepare}"
        )


    with path.open(
        "rb"
    ) as handle:

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                300,
                connect=30,
            ),
            verify=False,
        ) as client:

            response = await client.post(
                upload_url,
                files={
                    "file": (
                        path.name,
                        handle,
                    )
                },
            )


            response.raise_for_status()

            payload = response.json()


    data = (
        payload.get(
            "data"
        )
        or {}
    )


    file_id = data.get(
        "file_id"
    )


    if not file_id:

        raise RubikaError(
            f"file_id missing: {payload}"
        )


    return file_id


async def rubika_send_file(
    token,
    chat_id,
    file_id,
):

    return await rubika_request(
        token,
        "sendFile",
        {
            "chat_id":
                chat_id,

            "file_id":
                file_id,

            "disable_notification":
                False,
        },
    )


# ============================================================
# MIRROR
# ============================================================

async def mirror_job(
    telegram_client,
    job,
    provider,
    token,
    chat_id,
):

    job_id = int(
        job["id"]
    )


    await telegram_client.connect()


    tmp = (
        TMP_ROOT
        / provider
        / f"job-{job_id}"
    )


    if tmp.exists():

        shutil.rmtree(
            tmp,
            ignore_errors=True,
        )


    tmp.mkdir(
        parents=True,
        exist_ok=True,
    )


    try:

        if not await telegram_client.is_user_authorized():

            raise RuntimeError(
                "Telegram Session authorized نیست."
            )


        source, _joined = await resolve_source(
            telegram_client,
            job["source_ref"],
        )


        log_job(
            job_id,
            f"{provider.upper()}_SOURCE_RESOLVED",
            (
                f"Source برای {provider} "
                "Resolve شد."
            ),
        )


        messages = await get_job_messages(
            telegram_client,
            job,
            source,
        )


        log_job(
            job_id,
            f"{provider.upper()}_TRANSFER_STARTED",
            (
                f"{len(messages)} پیام "
                f"برای {provider} آماده شد. "
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
                provider,
                job_id,
                message_id,
            )


            if item_sent(
                provider,
                job_id,
                message_id,
            ):

                continue


            kind = media_type(
                message
            )


            text = (
                message.message
                or ""
            )


            try:

                provider_message_id = None


                if kind == "text":

                    if not text:

                        mark_item(
                            provider,
                            job_id,
                            message_id,
                            "skipped",
                            media=kind,
                        )

                        continue


                    if provider == "eitaa":

                        result = await eitaa_send_message(
                            token,
                            chat_id,
                            text,
                        )


                    else:

                        result = await rubika_send_message(
                            token,
                            chat_id,
                            text,
                        )


                    if isinstance(
                        result,
                        dict,
                    ):

                        provider_message_id = (
                            result.get(
                                "message_id"
                            )
                            or result.get(
                                "id"
                            )
                        )


                else:

                    downloaded = (
                        await telegram_client.download_media(
                            message,
                            file=str(
                                tmp
                            ),
                        )
                    )


                    if not downloaded:

                        if text:

                            if provider == "eitaa":

                                result = await eitaa_send_message(
                                    token,
                                    chat_id,
                                    text,
                                )

                            else:

                                result = await rubika_send_message(
                                    token,
                                    chat_id,
                                    text,
                                )

                        else:

                            raise RuntimeError(
                                "Media download returned empty path"
                            )


                    elif provider == "eitaa":

                        result = await eitaa_send_document(
                            token,
                            chat_id,
                            downloaded,
                            text,
                        )


                    else:

                        file_id = await rubika_upload(
                            token,
                            downloaded,
                            kind,
                        )


                        result = await rubika_send_file(
                            token,
                            chat_id,
                            file_id,
                        )


                        if text:

                            await rubika_send_message(
                                token,
                                chat_id,
                                text,
                            )


                    if isinstance(
                        result,
                        dict,
                    ):

                        provider_message_id = (
                            result.get(
                                "message_id"
                            )
                            or result.get(
                                "id"
                            )
                        )


                mark_item(
                    provider,
                    job_id,
                    message_id,
                    "sent",
                    media=kind,
                    provider_message_id=
                        provider_message_id,
                )


                current = sent_count(
                    provider,
                    job_id,
                )


                update_job(
                    provider,
                    job_id,
                    sent=current,
                )


                if (
                    index % 5 == 0
                    or index == len(
                        messages
                    )
                ):

                    log_job(
                        job_id,
                        f"{provider.upper()}_PROGRESS",
                        (
                            f"{current} / "
                            f"{len(messages)} "
                            f"پیام به {provider} "
                            "ارسال شد."
                        ),
                    )


            except Exception as exc:

                mark_item(
                    provider,
                    job_id,
                    message_id,
                    "failed",
                    media=kind,
                    error=(
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )


                log_job(
                    job_id,
                    f"{provider.upper()}_ITEM_FAILED",
                    (
                        f"Message {message_id}: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                    level="error",
                )


                raise


        return {
            "total":
                len(messages),

            "sent":
                sent_count(
                    provider,
                    job_id,
                ),
        }


    finally:

        await telegram_client.disconnect()

        shutil.rmtree(
            tmp,
            ignore_errors=True,
        )


# ============================================================
# FLASK REGISTRATION
# ============================================================

def init_external_mirrors(
    app,
    login_required,
    api_post_required,
    telegram_client,
    account_get,
):

    ensure_schema()


    # ========================================================
    # SETTINGS HELPERS
    # ========================================================

    def settings_response(
        provider
    ):

        token = setting_get(
            f"{provider}_bot_token"
        )

        chat_id = setting_get(
            f"{provider}_chat_id"
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


    def save_settings(
        provider
    ):

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


        if not token:

            token = setting_get(
                f"{provider}_bot_token"
            )


        if not token:

            return jsonify(
                ok=False,
                error=(
                    "توکن وارد نشده است."
                ),
            ), 400


        if not chat_id:

            return jsonify(
                ok=False,
                error=(
                    "Chat ID مقصد وارد نشده است."
                ),
            ), 400


        setting_set(
            f"{provider}_bot_token",
            token,
        )


        setting_set(
            f"{provider}_chat_id",
            chat_id,
        )


        return jsonify(
            ok=True,
            message=(
                f"تنظیمات {provider} ذخیره شد."
            ),
        )


    # ========================================================
    # EITAA SETTINGS
    # ========================================================

    @app.get(
        f"{BASE_PATH}/api/settings/eitaa"
    )
    @login_required
    def get_eitaa_settings():

        return settings_response(
            "eitaa"
        )


    @app.post(
        f"{BASE_PATH}/api/settings/eitaa"
    )
    @api_post_required
    def save_eitaa_settings():

        return save_settings(
            "eitaa"
        )


    @app.post(
        f"{BASE_PATH}/api/settings/eitaa/test"
    )
    @api_post_required
    def test_eitaa():

        config = provider_config(
            "eitaa"
        )


        if not config:

            return jsonify(
                ok=False,
                error=(
                    "ابتدا تنظیمات ایتا را ذخیره کن."
                ),
            ), 400


        try:

            asyncio.run(
                eitaa_send_message(
                    config["token"],
                    config["chat_id"],
                    (
                        "✅ اتصال TelTest به ایتا "
                        "با موفقیت برقرار شد."
                    ),
                )
            )


            return jsonify(
                ok=True,
                message=(
                    "پیام تست به ایتا ارسال شد."
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


    # ========================================================
    # RUBIKA SETTINGS
    # ========================================================

    @app.get(
        f"{BASE_PATH}/api/settings/rubika"
    )
    @login_required
    def get_rubika_settings():

        return settings_response(
            "rubika"
        )


    @app.post(
        f"{BASE_PATH}/api/settings/rubika"
    )
    @api_post_required
    def save_rubika_settings():

        return save_settings(
            "rubika"
        )


    @app.post(
        f"{BASE_PATH}/api/settings/rubika/test"
    )
    @api_post_required
    def test_rubika():

        config = provider_config(
            "rubika"
        )


        if not config:

            return jsonify(
                ok=False,
                error=(
                    "ابتدا تنظیمات روبیکا را ذخیره کن."
                ),
            ), 400


        try:

            async def run_test():

                me = await rubika_request(
                    config["token"],
                    "getMe",
                    {},
                )

                chat = await rubika_request(
                    config["token"],
                    "getChat",
                    {
                        "chat_id":
                            config[
                                "chat_id"
                            ]
                    },
                )

                return me, chat


            me, chat = asyncio.run(
                run_test()
            )


            return jsonify(
                ok=True,
                bot=me,
                chat=chat,
                message=(
                    "ربات و مقصد روبیکا "
                    "با موفقیت تأیید شدند."
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


    # ========================================================
    # JOB MIRROR
    # ========================================================

    def execute_provider(
        job_id,
        provider
    ):

        config = provider_config(
            provider
        )


        if not config:

            return jsonify(
                ok=False,
                error=(
                    f"{provider} هنوز تنظیم نشده است."
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
                error=(
                    "اکانت Telegram پیدا نشد."
                ),
            ), 404


        update_job(
            provider,
            job_id,
            status="running",
            error="",
        )


        log_job(
            job_id,
            f"{provider.upper()}_REQUESTED",
            (
                f"Mirror به {provider} آغاز شد. "
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

                        job=
                            job,

                        provider=
                            provider,

                        token=
                            config["token"],

                        chat_id=
                            config["chat_id"],
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
                provider,
                job_id,
                status="completed",
                sent=result["sent"],
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
                f"{provider.upper()}_COMPLETED",
                (
                    f"{result['sent']} / "
                    f"{result['total']} پیام "
                    f"در {elapsed:.2f}s "
                    f"به {provider} ارسال شد. "
                    f"Rate={rate:.2f} msg/s"
                ),
            )


            return jsonify(
                ok=True,
                provider=provider,
                sent=result["sent"],
                total=result["total"],
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
                    f"به {provider} ارسال شد."
                ),
            )


        except Exception as exc:

            elapsed = (
                time.perf_counter()
                - started
            )


            update_job(
                provider,
                job_id,
                status="failed",
                sent=sent_count(
                    provider,
                    job_id,
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
                f"{provider.upper()}_FAILED",
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


    @app.post(
        f"{BASE_PATH}/api/jobs/<int:job_id>/eitaa"
    )
    @api_post_required
    def mirror_eitaa(
        job_id
    ):

        return execute_provider(
            job_id,
            "eitaa"
        )


    @app.post(
        f"{BASE_PATH}/api/jobs/<int:job_id>/rubika"
    )
    @api_post_required
    def mirror_rubika(
        job_id
    ):

        return execute_provider(
            job_id,
            "rubika"
        )
