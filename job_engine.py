import asyncio
import fcntl
import os
import re
import sqlite3
import time

from contextlib import closing, contextmanager
from pathlib import Path

from flask import jsonify, request

from telethon import (
    errors,
    functions,
    types,
    utils,
)


BASE_PATH = "/teltest"

RUNTIME_ROOT = Path(
    os.getenv(
        "TELTEST_RUNTIME_ROOT",
        "/var/lib/teltest",
    )
)

DATA_DIR = (
    RUNTIME_ROOT
    / "data"
)

LOCK_DIR = (
    RUNTIME_ROOT
    / "locks"
)

DB_FILE = (
    DATA_DIR
    / "teltest.sqlite3"
)


DATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

LOCK_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# DATABASE
# ============================================================

def db_connect():

    conn = sqlite3.connect(
        DB_FILE,
        timeout=30,
    )

    conn.row_factory = (
        sqlite3.Row
    )

    conn.execute(
        "PRAGMA foreign_keys=ON"
    )

    conn.execute(
        "PRAGMA journal_mode=WAL"
    )

    conn.execute(
        "PRAGMA busy_timeout=30000"
    )

    return conn


def init_schema():

    with closing(
        db_connect()
    ) as conn:

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT,

                account_id INTEGER NOT NULL,

                source_ref TEXT NOT NULL,

                destination_ref TEXT NOT NULL,

                source_entity_id TEXT,

                source_title TEXT,

                source_username TEXT,

                destination_entity_id TEXT,

                destination_title TEXT,

                destination_username TEXT,

                limit_count INTEGER NOT NULL
                    DEFAULT 100,

                storage_mode TEXT NOT NULL
                    DEFAULT 'save',

                status TEXT NOT NULL
                    DEFAULT 'pending',

                joined_source INTEGER NOT NULL
                    DEFAULT 0,

                extracted_count INTEGER NOT NULL
                    DEFAULT 0,

                extraction_seconds REAL,

                last_error TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                started_at TEXT,

                finished_at TEXT,

                FOREIGN KEY(account_id)
                    REFERENCES accounts(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS posts (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                job_id INTEGER NOT NULL,

                account_id INTEGER NOT NULL,

                source_entity_id TEXT NOT NULL,

                message_id INTEGER NOT NULL,

                message_date TEXT,

                text TEXT,

                media_type TEXT,

                views INTEGER,

                forwards INTEGER,

                grouped_id TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(job_id)
                    REFERENCES jobs(id)
                    ON DELETE CASCADE,

                FOREIGN KEY(account_id)
                    REFERENCES accounts(id)
                    ON DELETE CASCADE,

                UNIQUE(
                    job_id,
                    message_id
                )
            );


            CREATE TABLE IF NOT EXISTS job_logs (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                job_id INTEGER NOT NULL,

                event TEXT NOT NULL,

                level TEXT NOT NULL
                    DEFAULT 'info',

                message TEXT,

                details TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(job_id)
                    REFERENCES jobs(id)
                    ON DELETE CASCADE
            );


            CREATE INDEX IF NOT EXISTS
                idx_job_logs_job
                ON job_logs(
                    job_id,
                    id
                );



            CREATE INDEX IF NOT EXISTS
                idx_jobs_account
                ON jobs(account_id);


            CREATE INDEX IF NOT EXISTS
                idx_jobs_status
                ON jobs(status);


            CREATE INDEX IF NOT EXISTS
                idx_posts_job
                ON posts(job_id);


            CREATE INDEX IF NOT EXISTS
                idx_posts_message
                ON posts(
                    source_entity_id,
                    message_id
                );
            """
        )

        # STAGE03_JOB_LOG_MIGRATION
        conn.execute(
            """
            INSERT INTO job_logs (
                job_id,
                event,
                level,
                message
            )

            SELECT
                j.id,
                'LEGACY_STATE',
                'info',

                CASE
                    WHEN j.status = 'completed'
                    THEN
                        'این Job قبل از فعال شدن Job Log اجرا شده است. '
                        || 'استخراج انجام شده ولی Stage 03 هیچ انتقالی '
                        || 'به Destination انجام نمی‌دهد.'

                    WHEN j.status = 'failed'
                    THEN
                        'این Job قبل از فعال شدن Job Log با خطا پایان یافته است.'

                    ELSE
                        'این Job قبل از فعال شدن Job Log ساخته شده است.'
                END

            FROM jobs j

            WHERE NOT EXISTS (
                SELECT 1
                FROM job_logs l
                WHERE l.job_id = j.id
            )
            """
        )

        conn.commit()


# ============================================================
# GENERIC HELPERS
# ============================================================

def json_body():

    data = request.get_json(
        silent=True
    )

    if isinstance(
        data,
        dict,
    ):
        return data

    return {}


def run_async(coro):

    return asyncio.run(
        coro
    )


def clean_ref(value):

    value = str(
        value or ""
    ).strip()

    if not value:
        raise ValueError(
            "Source/Destination خالی است."
        )

    return value


def public_ref(value):

    value = clean_ref(
        value
    )

    value = re.sub(
        r"^tg://resolve\?domain=",
        "",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"^https?://(?:www\.)?t\.me/",
        "",
        value,
        flags=re.I,
    )

    value = value.strip("/")

    if value.startswith(
        "joinchat/"
    ):
        return value

    if value.startswith("+"):
        return value

    if "/" in value:
        value = value.split(
            "/",
            1,
        )[0]

    if value.startswith("@"):
        value = value[1:]

    return value


def invite_hash(value):

    raw = clean_ref(
        value
    )

    match = re.search(
        r"(?:t\.me/(?:joinchat/|\+)|^joinchat/|^\+)"
        r"([A-Za-z0-9_-]+)",
        raw,
        flags=re.I,
    )

    if not match:
        return None

    return match.group(1)


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
        "sticker",
        None,
    ):
        return "sticker"

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


def entity_title(
    entity
):

    title = getattr(
        entity,
        "title",
        None,
    )

    if title:
        return title

    first = (
        getattr(
            entity,
            "first_name",
            "",
        )
        or ""
    )

    last = (
        getattr(
            entity,
            "last_name",
            "",
        )
        or ""
    )

    name = (
        f"{first} {last}"
    ).strip()

    return (
        name
        or "Unknown"
    )


def entity_username(
    entity
):

    return getattr(
        entity,
        "username",
        None,
    )


def entity_peer_id(
    entity
):

    try:

        return str(
            utils.get_peer_id(
                entity
            )
        )

    except Exception:

        return str(
            getattr(
                entity,
                "id",
                "",
            )
        )


def entity_kind(
    entity
):

    if isinstance(
        entity,
        types.Channel,
    ):

        if getattr(
            entity,
            "broadcast",
            False,
        ):
            return "channel"

        if getattr(
            entity,
            "megagroup",
            False,
        ):
            return "supergroup"

        return "channel"

    if isinstance(
        entity,
        types.Chat,
    ):
        return "group"

    return "unknown"


# ============================================================
# ACCOUNT LOCK
# ============================================================

@contextmanager
def account_lock(
    account_id
):

    lock_file = (
        LOCK_DIR
        / f"account_{int(account_id)}.lock"
    )

    handle = open(
        lock_file,
        "a+",
        encoding="utf-8",
    )

    try:

        fcntl.flock(
            handle.fileno(),
            fcntl.LOCK_EX,
        )

        yield

    finally:

        fcntl.flock(
            handle.fileno(),
            fcntl.LOCK_UN,
        )

        handle.close()


# ============================================================
# ENTITY RESOLUTION
# ============================================================

def find_in_dialogs(
    raw_ref,
    dialogs,
):

    ref = public_ref(
        raw_ref
    )

    numeric = None

    try:
        numeric = int(ref)
    except ValueError:
        pass


    for dialog in dialogs:

        entity = dialog.entity


        if numeric is not None:

            candidates = {
                str(
                    getattr(
                        entity,
                        "id",
                        "",
                    )
                ),
                entity_peer_id(
                    entity
                ),
            }

            if str(
                numeric
            ) in candidates:
                return entity


        username = getattr(
            entity,
            "username",
            None,
        )

        if (
            username
            and username.lower()
            == ref.lower()
        ):
            return entity

    return None


async def resolve_source(
    client,
    raw_ref,
):

    dialogs = await client.get_dialogs(
        limit=None
    )

    entity = find_in_dialogs(
        raw_ref,
        dialogs,
    )

    if entity is not None:

        return (
            entity,
            False,
        )


    private_hash = invite_hash(
        raw_ref
    )


    if private_hash:

        invite = await client(
            functions.messages.CheckChatInviteRequest(
                private_hash
            )
        )


        if isinstance(
            invite,
            types.ChatInviteAlready,
        ):

            return (
                invite.chat,
                False,
            )


        updates = await client(
            functions.messages.ImportChatInviteRequest(
                private_hash
            )
        )


        if not updates.chats:

            raise RuntimeError(
                "Telegram کانال لینک دعوت را برنگرداند."
            )


        return (
            updates.chats[0],
            True,
        )


    ref = public_ref(
        raw_ref
    )


    if re.fullmatch(
        r"-?[0-9]+",
        ref,
    ):

        raise RuntimeError(
            "این ID در Dialogهای اکانت پیدا نشد. "
            "برای کانالی که عضو نیستی Username یا لینک t.me بده."
        )


    entity = await client.get_entity(
        ref
    )


    dialogs_peer_ids = {
        entity_peer_id(
            item.entity
        )
        for item in dialogs
    }


    if (
        isinstance(
            entity,
            types.Channel,
        )
        and entity_peer_id(
            entity
        )
        not in dialogs_peer_ids
    ):

        await client(
            functions.channels.JoinChannelRequest(
                entity
            )
        )

        entity = await client.get_entity(
            ref
        )

        return (
            entity,
            True,
        )


    return (
        entity,
        False,
    )


async def resolve_destination(
    client,
    raw_ref,
):

    dialogs = await client.get_dialogs(
        limit=None
    )

    entity = find_in_dialogs(
        raw_ref,
        dialogs,
    )

    if entity is not None:
        return entity


    private_hash = invite_hash(
        raw_ref
    )


    if private_hash:

        invite = await client(
            functions.messages.CheckChatInviteRequest(
                private_hash
            )
        )


        if isinstance(
            invite,
            types.ChatInviteAlready,
        ):
            return invite.chat


        raise RuntimeError(
            "اکانت عضو کانال مقصد خصوصی نیست. "
            "ابتدا مقصد را به اکانت اضافه کن."
        )


    ref = public_ref(
        raw_ref
    )


    if re.fullmatch(
        r"-?[0-9]+",
        ref,
    ):

        raise RuntimeError(
            "ID مقصد در Dialogهای اکانت پیدا نشد."
        )


    return await client.get_entity(
        ref
    )


# ============================================================
# EXTRACT
# ============================================================

async def execute_extraction(
    client,
    source_ref,
    destination_ref,
    limit_count,
    save_posts,
    job_id=None,
):

    await client.connect()

    if job_id is not None:
        log_job(
            job_id,
            "TELEGRAM_CONNECTED",
            "اتصال Telethon برقرار شد.",
        )

    try:

        if not await client.is_user_authorized():

            raise RuntimeError(
                "Session این اکانت Authorized نیست."
            )


        if job_id is not None:
            log_job(
                job_id,
                "SESSION_AUTHORIZED",
                "Session اکانت Authorized است.",
            )


        source_entity, joined_source = (
            await resolve_source(
                client,
                source_ref,
            )
        )


        if job_id is not None:

            log_job(
                job_id,
                "SOURCE_RESOLVED",
                (
                    f"Source: {entity_title(source_entity)} "
                    f"({entity_peer_id(source_entity)})"
                ),
            )

            if joined_source:

                log_job(
                    job_id,
                    "SOURCE_JOINED",
                    "اکانت با موفقیت عضو Source شد.",
                )

            else:

                log_job(
                    job_id,
                    "SOURCE_ALREADY_MEMBER",
                    "اکانت از قبل به Source دسترسی داشت.",
                )


        destination_entity = (
            await resolve_destination(
                client,
                destination_ref,
            )
        )


        if job_id is not None:

            log_job(
                job_id,
                "DESTINATION_RESOLVED",
                (
                    f"Destination: {entity_title(destination_entity)} "
                    f"({entity_peer_id(destination_entity)})"
                ),
            )


        rows = []

        extracted = 0


        if job_id is not None:

            log_job(
                job_id,
                "EXTRACT_STARTED",
                (
                    f"شروع خواندن حداکثر "
                    f"{limit_count} پیام از Source."
                ),
            )


        async for message in client.iter_messages(
            source_entity,
            limit=limit_count,
        ):

            extracted += 1


            if not save_posts:
                continue


            rows.append(
                {
                    "message_id":
                        message.id,

                    "message_date":
                        message.date.isoformat()
                        if message.date
                        else None,

                    "text":
                        message.message
                        or "",

                    "media_type":
                        media_type(
                            message
                        ),

                    "views":
                        getattr(
                            message,
                            "views",
                            None,
                        ),

                    "forwards":
                        getattr(
                            message,
                            "forwards",
                            None,
                        ),

                    "grouped_id":
                        str(
                            getattr(
                                message,
                                "grouped_id",
                                "",
                            )
                            or ""
                        ),
                }
            )


        if job_id is not None:

            log_job(
                job_id,
                "EXTRACT_COMPLETED",
                (
                    f"{extracted} پیام از Source خوانده شد."
                ),
            )


        return {

            "source": {
                "id":
                    entity_peer_id(
                        source_entity
                    ),

                "title":
                    entity_title(
                        source_entity
                    ),

                "username":
                    entity_username(
                        source_entity
                    ),

                "kind":
                    entity_kind(
                        source_entity
                    ),
            },

            "destination": {
                "id":
                    entity_peer_id(
                        destination_entity
                    ),

                "title":
                    entity_title(
                        destination_entity
                    ),

                "username":
                    entity_username(
                        destination_entity
                    ),

                "kind":
                    entity_kind(
                        destination_entity
                    ),
            },

            "joined_source":
                joined_source,

            "extracted":
                extracted,

            "posts":
                rows,
        }

    finally:

        await client.disconnect()


# ============================================================
# DATABASE HELPERS
# ============================================================

def job_get(
    job_id
):

    with closing(
        db_connect()
    ) as conn:

        return conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()


def log_job(
    job_id,
    event,
    message="",
    level="info",
    details=None,
):

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            INSERT INTO job_logs (
                job_id,
                event,
                level,
                message,
                details
            )
            VALUES (
                ?, ?, ?, ?, ?
            )
            """,
            (
                int(job_id),
                str(event)[:100],
                str(level)[:20],
                str(message or "")[:4000],
                (
                    str(details)[:8000]
                    if details is not None
                    else None
                ),
            ),
        )

        conn.commit()




def mark_failed(
    job_id,
    error
):

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            UPDATE jobs
            SET
                status = 'failed',
                last_error = ?,
                finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                str(error)[:1500],
                job_id,
            ),
        )

        conn.commit()

    log_job(
        job_id=job_id,
        event="FAILED",
        level="error",
        message=str(error),
    )


def upsert_channel(
    account_id,
    entity_data,
):

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            INSERT INTO channels (
                account_id,
                entity_id,
                access_hash,
                title,
                username,
                kind,
                is_creator,
                is_admin,
                updated_at
            )
            VALUES (
                ?,
                ?,
                '',
                ?,
                ?,
                ?,
                0,
                0,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(
                account_id,
                entity_id
            )
            DO UPDATE SET
                title =
                    excluded.title,
                username =
                    excluded.username,
                kind =
                    excluded.kind,
                updated_at =
                    CURRENT_TIMESTAMP
            """,
            (
                account_id,
                entity_data["id"],
                entity_data["title"],
                entity_data["username"],
                entity_data["kind"],
            ),
        )

        conn.commit()


# ============================================================
# FLASK REGISTRATION
# ============================================================

def init_jobs(
    app,
    login_required,
    api_post_required,
    telegram_client,
    account_get,
):

    init_schema()


    # --------------------------------------------------------
    # META
    # --------------------------------------------------------

    @app.get(
        f"{BASE_PATH}/api/jobs/meta"
    )
    @login_required
    def stage03_jobs_meta():

        with closing(
            db_connect()
        ) as conn:

            accounts = conn.execute(
                """
                SELECT
                    id,
                    phone,
                    display_name,
                    username,
                    telegram_user_id
                FROM accounts
                WHERE status = 'connected'
                ORDER BY id DESC
                """
            ).fetchall()


            channels = conn.execute(
                """
                SELECT
                    id,
                    account_id,
                    entity_id,
                    title,
                    username,
                    kind
                FROM channels
                ORDER BY
                    title COLLATE NOCASE
                """
            ).fetchall()


        return jsonify(
            ok=True,

            accounts=[
                dict(row)
                for row in accounts
            ],

            channels=[
                dict(row)
                for row in channels
            ],
        )


    # --------------------------------------------------------
    # CREATE JOB
    # --------------------------------------------------------

    @app.post(
        f"{BASE_PATH}/api/jobs"
    )
    @api_post_required
    def stage03_create_job():

        data = json_body()


        try:

            account_id = int(
                data.get(
                    "account_id"
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            return jsonify(
                ok=False,
                error="اکانت معتبر نیست.",
            ), 400


        account = account_get(
            account_id
        )


        if not account:

            return jsonify(
                ok=False,
                error="اکانت پیدا نشد.",
            ), 404


        if account["status"] != "connected":

            return jsonify(
                ok=False,
                error="اکانت متصل نیست.",
            ), 400


        try:

            source_ref = clean_ref(
                data.get(
                    "source_ref"
                )
            )

            destination_ref = clean_ref(
                data.get(
                    "destination_ref"
                )
            )

        except ValueError as exc:

            return jsonify(
                ok=False,
                error=str(exc),
            ), 400


        try:

            limit_count = int(
                data.get(
                    "limit_count",
                    100,
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            return jsonify(
                ok=False,
                error="تعداد پیام نامعتبر است.",
            ), 400


        if not (
            1
            <= limit_count
            <= 5000
        ):

            return jsonify(
                ok=False,
                error=(
                    "در Stage 03 تعداد پیام باید "
                    "بین 1 تا 5000 باشد."
                ),
            ), 400


        storage_mode = str(
            data.get(
                "storage_mode",
                "save",
            )
        )


        if storage_mode not in (
            "save",
            "nosave",
        ):

            return jsonify(
                ok=False,
                error="Storage mode نامعتبر است.",
            ), 400


        name = str(
            data.get(
                "name",
                "",
            )
        ).strip()


        if not name:

            name = (
                f"{source_ref} → "
                f"{destination_ref}"
            )


        with closing(
            db_connect()
        ) as conn:

            cursor = conn.execute(
                """
                INSERT INTO jobs (
                    name,
                    account_id,
                    source_ref,
                    destination_ref,
                    limit_count,
                    storage_mode,
                    status
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    'pending'
                )
                """,
                (
                    name[:255],
                    account_id,
                    source_ref,
                    destination_ref,
                    limit_count,
                    storage_mode,
                ),
            )

            conn.commit()

            job_id = cursor.lastrowid


        log_job(
            job_id,
            "CREATED",
            (
                f"Job ساخته شد. Source={source_ref} | "
                f"Destination={destination_ref} | "
                f"Limit={limit_count} | "
                f"Storage={storage_mode}"
            ),
        )


        return jsonify(
            ok=True,
            job_id=job_id,
            status="pending",
            message=(
                f"Job #{job_id} ساخته شد."
            ),
        )


    # --------------------------------------------------------
    # LIST JOBS
    # --------------------------------------------------------

    @app.get(
        f"{BASE_PATH}/api/jobs"
    )
    @login_required
    def stage03_list_jobs():

        with closing(
            db_connect()
        ) as conn:

            rows = conn.execute(
                """
                SELECT
                    j.*,
                    a.phone AS account_phone,
                    a.display_name AS account_name,

                    (
                        SELECT COUNT(*)
                        FROM posts p
                        WHERE p.job_id = j.id
                    ) AS saved_posts

                FROM jobs j

                INNER JOIN accounts a
                    ON a.id = j.account_id

                ORDER BY
                    j.id DESC

                LIMIT 200
                """
            ).fetchall()


        return jsonify(
            ok=True,
            jobs=[
                dict(row)
                for row in rows
            ],
        )


    # --------------------------------------------------------
    # RUN JOB
    # --------------------------------------------------------

    @app.post(
        f"{BASE_PATH}/api/jobs/<int:job_id>/run"
    )
    @api_post_required
    def stage03_run_job(
        job_id
    ):

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
                error="اکانت Job پیدا نشد.",
            ), 404


        if account["status"] != "connected":

            return jsonify(
                ok=False,
                error="اکانت Job متصل نیست.",
            ), 400


        with closing(
            db_connect()
        ) as conn:

            conn.execute(
                """
                DELETE FROM posts
                WHERE job_id = ?
                """,
                (job_id,),
            )

            conn.execute(
                """
                UPDATE jobs
                SET
                    status = 'running',
                    extracted_count = 0,
                    extraction_seconds = NULL,
                    joined_source = 0,
                    last_error = NULL,
                    started_at = CURRENT_TIMESTAMP,
                    finished_at = NULL
                WHERE id = ?
                """,
                (job_id,),
            )

            conn.commit()


        started = time.perf_counter()


        log_job(
            job_id,
            "RUN_STARTED",
            "اجرای Job آغاز شد.",
        )


        try:

            with account_lock(
                job["account_id"]
            ):

                client = telegram_client(
                    account
                )


                result = run_async(
                    execute_extraction(
                        client=client,

                        source_ref=
                            job["source_ref"],

                        destination_ref=
                            job[
                                "destination_ref"
                            ],

                        limit_count=
                            job["limit_count"],

                        save_posts=(
                            job[
                                "storage_mode"
                            ]
                            == "save"
                        ),

                        job_id=job_id,
                    )
                )


            elapsed = (
                time.perf_counter()
                - started
            )


            with closing(
                db_connect()
            ) as conn:

                if (
                    job["storage_mode"]
                    == "save"
                ):

                    for post in result[
                        "posts"
                    ]:

                        conn.execute(
                            """
                            INSERT INTO posts (
                                job_id,
                                account_id,
                                source_entity_id,
                                message_id,
                                message_date,
                                text,
                                media_type,
                                views,
                                forwards,
                                grouped_id
                            )
                            VALUES (
                                ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?
                            )
                            ON CONFLICT(
                                job_id,
                                message_id
                            )
                            DO UPDATE SET
                                message_date =
                                    excluded.message_date,
                                text =
                                    excluded.text,
                                media_type =
                                    excluded.media_type,
                                views =
                                    excluded.views,
                                forwards =
                                    excluded.forwards,
                                grouped_id =
                                    excluded.grouped_id
                            """,
                            (
                                job_id,
                                job["account_id"],
                                result[
                                    "source"
                                ]["id"],
                                post[
                                    "message_id"
                                ],
                                post[
                                    "message_date"
                                ],
                                post[
                                    "text"
                                ],
                                post[
                                    "media_type"
                                ],
                                post[
                                    "views"
                                ],
                                post[
                                    "forwards"
                                ],
                                post[
                                    "grouped_id"
                                ],
                            ),
                        )


                conn.execute(
                    """
                    UPDATE jobs
                    SET
                        source_entity_id = ?,
                        source_title = ?,
                        source_username = ?,

                        destination_entity_id = ?,
                        destination_title = ?,
                        destination_username = ?,

                        joined_source = ?,

                        extracted_count = ?,
                        extraction_seconds = ?,

                        status = 'completed',

                        finished_at =
                            CURRENT_TIMESTAMP

                    WHERE id = ?
                    """,
                    (
                        result[
                            "source"
                        ]["id"],

                        result[
                            "source"
                        ]["title"],

                        result[
                            "source"
                        ]["username"],

                        result[
                            "destination"
                        ]["id"],

                        result[
                            "destination"
                        ]["title"],

                        result[
                            "destination"
                        ]["username"],

                        int(
                            result[
                                "joined_source"
                            ]
                        ),

                        result[
                            "extracted"
                        ],

                        round(
                            elapsed,
                            4,
                        ),

                        job_id,
                    ),
                )

                conn.commit()


            if job["storage_mode"] == "save":

                log_job(
                    job_id,
                    "POSTS_SAVED",
                    (
                        f"{len(result['posts'])} پیام "
                        f"در دیتابیس ذخیره شد."
                    ),
                )

            else:

                log_job(
                    job_id,
                    "POSTS_NOT_SAVED",
                    (
                        "Storage Mode روی No Save است؛ "
                        "پیام‌ها در جدول Posts ذخیره نشدند."
                    ),
                )


            log_job(
                job_id,
                "EXTRACTION_PHASE_COMPLETED",
                (
                    "مرحله Extract کامل شد. "
                    "Stage 04 می‌تواند انتقال واقعی را اجرا کند."
                ),
            )


            log_job(
                job_id,
                "COMPLETED",
                (
                    f"Job با موفقیت تمام شد: "
                    f"{result['extracted']} پیام در "
                    f"{elapsed:.2f} ثانیه."
                ),
            )


            upsert_channel(
                job["account_id"],
                result["source"],
            )


            upsert_channel(
                job["account_id"],
                result[
                    "destination"
                ],
            )


            return jsonify(
                ok=True,

                job_id=job_id,

                status="completed",

                extracted=result[
                    "extracted"
                ],

                saved=(
                    len(
                        result[
                            "posts"
                        ]
                    )
                    if (
                        job[
                            "storage_mode"
                        ]
                        == "save"
                    )
                    else 0
                ),

                joined_source=result[
                    "joined_source"
                ],

                seconds=round(
                    elapsed,
                    4,
                ),

                source=result[
                    "source"
                ],

                destination=result[
                    "destination"
                ],

                message=(
                    f"{result['extracted']} پیام "
                    f"در {elapsed:.2f} ثانیه استخراج شد؛ "
                    f"آماده انتقال است."
                ),
            )


        except errors.FloodWaitError as exc:

            mark_failed(
                job_id,
                f"FloodWait {exc.seconds}s",
            )

            return jsonify(
                ok=False,

                error=(
                    "Telegram محدودیت FloodWait "
                    f"{exc.seconds} ثانیه اعمال کرد."
                ),

                flood_wait=
                    exc.seconds,
            ), 429


        except errors.InviteHashExpiredError:

            mark_failed(
                job_id,
                "InviteHashExpiredError",
            )

            return jsonify(
                ok=False,
                error=(
                    "لینک دعوت Source منقضی یا نامعتبر است."
                ),
            ), 400


        except errors.InviteHashInvalidError:

            mark_failed(
                job_id,
                "InviteHashInvalidError",
            )

            return jsonify(
                ok=False,
                error=(
                    "لینک دعوت Source معتبر نیست."
                ),
            ), 400


        except errors.ChannelPrivateError:

            mark_failed(
                job_id,
                "ChannelPrivateError",
            )

            return jsonify(
                ok=False,
                error=(
                    "کانال خصوصی است و این اکانت "
                    "به آن دسترسی ندارد."
                ),
            ), 403


        except Exception as exc:

            mark_failed(
                job_id,
                f"{type(exc).__name__}: {exc}",
            )

            return jsonify(
                ok=False,
                error=(
                    f"{type(exc).__name__}: {exc}"
                ),
            ), 500


    # --------------------------------------------------------
    # JOB LOGS
    # --------------------------------------------------------

    @app.get(
        f"{BASE_PATH}/api/jobs/<int:job_id>/logs"
    )
    @login_required
    def stage03_job_logs(
        job_id
    ):

        with closing(
            db_connect()
        ) as conn:

            job = conn.execute(
                """
                SELECT
                    id,
                    name,
                    status,
                    source_ref,
                    destination_ref,
                    source_title,
                    destination_title,
                    storage_mode,
                    extracted_count,
                    extraction_seconds,

                    transfer_mode,
                    transfer_status,
                    transferred_count,
                    transfer_seconds,
                    transfer_rate,
                    transfer_last_error,

                    last_error,
                    created_at,
                    started_at,
                    finished_at
                FROM jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()


            if not job:

                return jsonify(
                    ok=False,
                    error="Job پیدا نشد.",
                ), 404


            rows = conn.execute(
                """
                SELECT
                    id,
                    event,
                    level,
                    message,
                    details,
                    created_at
                FROM job_logs
                WHERE job_id = ?
                ORDER BY id ASC
                """,
                (job_id,),
            ).fetchall()


        return jsonify(
            ok=True,
            job=dict(job),
            logs=[
                dict(row)
                for row in rows
            ],
        )



    # --------------------------------------------------------
    # POSTS
    # --------------------------------------------------------

    @app.get(
        f"{BASE_PATH}/api/posts"
    )
    @login_required
    def stage03_posts():

        raw_job_id = request.args.get(
            "job_id",
            "",
        ).strip()


        params = []

        where = ""


        if raw_job_id:

            if not raw_job_id.isdigit():

                return jsonify(
                    ok=False,
                    error="job_id نامعتبر است.",
                ), 400


            where = (
                "WHERE p.job_id = ?"
            )

            params.append(
                int(
                    raw_job_id
                )
            )


        with closing(
            db_connect()
        ) as conn:

            rows = conn.execute(
                f"""
                SELECT
                    p.*,
                    j.name AS job_name,
                    j.source_title
                FROM posts p

                INNER JOIN jobs j
                    ON j.id = p.job_id

                {where}

                ORDER BY
                    p.id DESC

                LIMIT 500
                """,
                params,
            ).fetchall()


        return jsonify(
            ok=True,

            posts=[
                dict(row)
                for row in rows
            ],

            count=len(
                rows
            ),
        )
