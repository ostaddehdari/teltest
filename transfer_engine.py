import asyncio
import time

from contextlib import closing

from flask import jsonify

from telethon import errors


from job_engine import (
    account_lock,
    db_connect,
    entity_peer_id,
    entity_title,
    job_get,
    log_job,
    resolve_destination,
    resolve_source,
)


BASE_PATH = "/teltest"

INLINE_FLOOD_WAIT_MAX = 30


# ============================================================
# DATABASE
# ============================================================

def ensure_transfer_schema():

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

            "transfer_mode":
                "transfer_mode TEXT NOT NULL DEFAULT 'none'",

            "transfer_status":
                "transfer_status TEXT NOT NULL DEFAULT 'none'",

            "transferred_count":
                "transferred_count INTEGER NOT NULL DEFAULT 0",

            "transfer_seconds":
                "transfer_seconds REAL",

            "transfer_rate":
                "transfer_rate REAL",

            "transfer_last_error":
                "transfer_last_error TEXT",

            "transfer_started_at":
                "transfer_started_at TEXT",

            "transfer_finished_at":
                "transfer_finished_at TEXT",
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
            CREATE TABLE IF NOT EXISTS
            transfer_items (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                job_id INTEGER NOT NULL,

                seq INTEGER NOT NULL,

                source_message_id INTEGER NOT NULL,

                destination_message_id INTEGER,

                status TEXT NOT NULL
                    DEFAULT 'pending',

                attempts INTEGER NOT NULL
                    DEFAULT 0,

                last_error TEXT,

                sent_at TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(job_id)
                    REFERENCES jobs(id)
                    ON DELETE CASCADE,

                UNIQUE(
                    job_id,
                    source_message_id
                )
            );


            CREATE INDEX IF NOT EXISTS
                idx_transfer_items_job
                ON transfer_items(
                    job_id,
                    seq
                );


            CREATE INDEX IF NOT EXISTS
                idx_transfer_items_status
                ON transfer_items(
                    job_id,
                    status
                );
            """
        )


        conn.commit()


# ============================================================
# JOB STATE
# ============================================================

def update_job_transfer(
    job_id,
    **values,
):

    allowed = {
        "transfer_mode",
        "transfer_status",
        "transferred_count",
        "transfer_seconds",
        "transfer_rate",
        "transfer_last_error",
        "transfer_started_at",
        "transfer_finished_at",
    }


    values = {
        key: value
        for key, value in values.items()
        if key in allowed
    }


    if not values:
        return


    fields = []

    params = []


    for key, value in values.items():

        fields.append(
            f"{key} = ?"
        )

        params.append(
            value
        )


    params.append(
        int(job_id)
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


def transfer_summary(
    job_id
):

    with closing(
        db_connect()
    ) as conn:

        rows = conn.execute(
            """
            SELECT
                status,
                COUNT(*) AS n
            FROM transfer_items
            WHERE job_id = ?
            GROUP BY status
            """,
            (job_id,),
        ).fetchall()


    result = {
        "pending": 0,
        "sent": 0,
        "skipped": 0,
        "failed": 0,
    }


    for row in rows:

        result[
            row["status"]
        ] = row["n"]


    result["total"] = sum(
        result.values()
    )

    return result


def reset_transfer(
    job_id
):

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            DELETE FROM transfer_items
            WHERE job_id = ?
            """,
            (job_id,),
        )

        conn.execute(
            """
            UPDATE jobs
            SET
                transferred_count = 0,
                transfer_seconds = NULL,
                transfer_rate = NULL,
                transfer_last_error = NULL,
                transfer_started_at = NULL,
                transfer_finished_at = NULL
            WHERE id = ?
            """,
            (job_id,),
        )

        conn.commit()


# ============================================================
# PLAN
# ============================================================

def saved_message_ids(
    job_id
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
            (job_id,),
        ).fetchall()


    return [
        int(row["message_id"])
        for row in rows
    ]


def existing_plan(
    job_id
):

    with closing(
        db_connect()
    ) as conn:

        rows = conn.execute(
            """
            SELECT
                seq,
                source_message_id,
                status
            FROM transfer_items
            WHERE job_id = ?
            ORDER BY seq ASC
            """,
            (job_id,),
        ).fetchall()


    return [
        dict(row)
        for row in rows
    ]


def save_plan(
    job_id,
    message_ids,
):

    with closing(
        db_connect()
    ) as conn:

        for seq, message_id in enumerate(
            message_ids,
            start=1,
        ):

            conn.execute(
                """
                INSERT OR IGNORE INTO transfer_items (
                    job_id,
                    seq,
                    source_message_id,
                    status
                )
                VALUES (
                    ?, ?, ?, 'pending'
                )
                """,
                (
                    job_id,
                    seq,
                    int(message_id),
                ),
            )


        conn.commit()


async def prepare_plan(
    client,
    job,
    source_entity,
):

    current = existing_plan(
        job["id"]
    )


    if current:

        log_job(
            job["id"],
            "TRANSFER_PLAN_REUSED",
            (
                f"برنامه انتقال موجود با "
                f"{len(current)} آیتم برای Resume استفاده شد."
            ),
        )

        return current


    ids = saved_message_ids(
        job["id"]
    )


    source_kind = "database"


    if not ids:

        source_kind = "live"


        messages = [
            message
            async for message
            in client.iter_messages(
                source_entity,
                limit=job["limit_count"],
            )
        ]


        messages = [
            message
            for message in messages
            if getattr(
                message,
                "id",
                None,
            )
        ]


        messages.reverse()


        ids = [
            int(message.id)
            for message in messages
        ]


    save_plan(
        job["id"],
        ids,
    )


    log_job(
        job["id"],
        "TRANSFER_PLAN_CREATED",
        (
            f"{len(ids)} پیام برای انتقال آماده شد. "
            f"PlanSource={source_kind}"
        ),
    )


    return existing_plan(
        job["id"]
    )


# ============================================================
# ITEM HELPERS
# ============================================================

def mark_item(
    job_id,
    message_id,
    status,
    destination_message_id=None,
    error=None,
):

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            UPDATE transfer_items
            SET
                status = ?,
                destination_message_id = ?,
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
                destination_message_id,
                (
                    str(error)[:1500]
                    if error
                    else None
                ),
                status,
                job_id,
                int(message_id),
            ),
        )

        conn.commit()


def pending_ids(
    job_id
):

    with closing(
        db_connect()
    ) as conn:

        rows = conn.execute(
            """
            SELECT source_message_id
            FROM transfer_items
            WHERE
                job_id = ?
                AND status IN (
                    'pending',
                    'failed'
                )
            ORDER BY seq ASC
            """,
            (job_id,),
        ).fetchall()


    return [
        int(row["source_message_id"])
        for row in rows
    ]


# ============================================================
# TELEGRAM SEND
# ============================================================

async def send_one(
    client,
    destination,
    source,
    message,
    mode,
):

    if mode == "forward":

        sent = await client.forward_messages(
            destination,
            message,
            from_peer=source,
        )

    elif mode == "copy":

        sent = await client.send_message(
            destination,
            message,
        )

    else:

        raise RuntimeError(
            f"Transfer mode نامعتبر: {mode}"
        )


    if isinstance(
        sent,
        (list, tuple),
    ):

        sent = (
            sent[0]
            if sent
            else None
        )


    return sent


async def send_with_wait(
    client,
    destination,
    source,
    message,
    mode,
    job_id,
):

    inline_wait_used = False


    while True:

        try:

            return await send_one(
                client=client,
                destination=destination,
                source=source,
                message=message,
                mode=mode,
            )


        except errors.FloodWaitError as exc:

            seconds = int(
                exc.seconds
            )


            log_job(
                job_id,
                "FLOOD_WAIT",
                (
                    f"Telegram درخواست توقف "
                    f"{seconds} ثانیه‌ای داد."
                ),
                level="warning",
            )


            if (
                seconds
                <= INLINE_FLOOD_WAIT_MAX
                and not inline_wait_used
            ):

                inline_wait_used = True

                await asyncio.sleep(
                    seconds + 1
                )

                log_job(
                    job_id,
                    "FLOOD_WAIT_RESUMED",
                    (
                        f"پس از رعایت FloodWait "
                        f"{seconds}s انتقال ادامه یافت."
                    ),
                )

                continue


            raise


# ============================================================
# TRANSFER
# ============================================================

async def execute_transfer(
    client,
    job,
):

    job_id = int(
        job["id"]
    )

    mode = job[
        "transfer_mode"
    ]


    if mode not in (
        "forward",
        "copy",
    ):

        raise RuntimeError(
            "Transfer Mode روی Forward یا Copy تنظیم نشده است."
        )


    await client.connect()


    try:

        if not await client.is_user_authorized():

            raise RuntimeError(
                "Session اکانت Authorized نیست."
            )


        source_entity, joined_source = (
            await resolve_source(
                client,
                job["source_ref"],
            )
        )


        destination_entity = (
            await resolve_destination(
                client,
                job["destination_ref"],
            )
        )


        log_job(
            job_id,
            "TRANSFER_SOURCE_RESOLVED",
            (
                f"Source: "
                f"{entity_title(source_entity)} "
                f"({entity_peer_id(source_entity)})"
            ),
        )


        log_job(
            job_id,
            "TRANSFER_DESTINATION_RESOLVED",
            (
                f"Destination: "
                f"{entity_title(destination_entity)} "
                f"({entity_peer_id(destination_entity)})"
            ),
        )


        await prepare_plan(
            client,
            job,
            source_entity,
        )


        ids = pending_ids(
            job_id
        )


        before = transfer_summary(
            job_id
        )


        log_job(
            job_id,
            "TRANSFER_STARTED",
            (
                f"Mode={mode} | "
                f"Total={before['total']} | "
                f"AlreadySent={before['sent']} | "
                f"Pending={len(ids)}"
            ),
        )


        if not ids:

            return {
                "mode": mode,
                "total": before["total"],
                "sent": before["sent"],
                "skipped": before["skipped"],
                "failed": before["failed"],
                "joined_source": joined_source,
            }


        messages = await client.get_messages(
            source_entity,
            ids=ids,
        )


        if not isinstance(
            messages,
            (list, tuple),
        ):

            messages = list(
                messages
            )


        message_map = {
            int(message.id): message
            for message in messages
            if (
                message is not None
                and getattr(
                    message,
                    "id",
                    None,
                )
            )
        }


        sent_during_run = 0


        for index, message_id in enumerate(
            ids,
            start=1,
        ):

            message = message_map.get(
                int(message_id)
            )


            if message is None:

                mark_item(
                    job_id,
                    message_id,
                    "skipped",
                    error=(
                        "Source message not found"
                    ),
                )


                log_job(
                    job_id,
                    "TRANSFER_ITEM_SKIPPED",
                    (
                        f"Message {message_id} "
                        f"در Source پیدا نشد."
                    ),
                    level="warning",
                )

                continue


            try:

                sent = await send_with_wait(
                    client=client,
                    destination=
                        destination_entity,
                    source=
                        source_entity,
                    message=
                        message,
                    mode=
                        mode,
                    job_id=
                        job_id,
                )


                destination_message_id = (
                    getattr(
                        sent,
                        "id",
                        None,
                    )
                    if sent is not None
                    else None
                )


                mark_item(
                    job_id,
                    message_id,
                    "sent",
                    destination_message_id=
                        destination_message_id,
                )


                sent_during_run += 1


                current = transfer_summary(
                    job_id
                )


                update_job_transfer(
                    job_id,
                    transferred_count=
                        current["sent"],
                )


                if (
                    current["sent"] % 10 == 0
                    or index == len(ids)
                ):

                    log_job(
                        job_id,
                        "TRANSFER_PROGRESS",
                        (
                            f"{current['sent']} / "
                            f"{current['total']} ارسال شد."
                        ),
                    )


            except errors.FloodWaitError as exc:

                seconds = int(
                    exc.seconds
                )


                update_job_transfer(
                    job_id,
                    transfer_status="paused",
                    transfer_last_error=(
                        f"FloodWait {seconds}s"
                    ),
                )


                log_job(
                    job_id,
                    "TRANSFER_PAUSED",
                    (
                        f"انتقال Pause شد. "
                        f"پس از {seconds} ثانیه "
                        f"دکمه انتقال را دوباره بزن؛ "
                        f"از پیام بعدی Resume می‌شود."
                    ),
                    level="warning",
                )


                return {
                    "mode": mode,
                    "paused": True,
                    "flood_wait": seconds,
                    **transfer_summary(
                        job_id
                    ),
                }


            except Exception as exc:

                mark_item(
                    job_id,
                    message_id,
                    "failed",
                    error=(
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )


                update_job_transfer(
                    job_id,
                    transfer_status="failed",
                    transfer_last_error=(
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )


                log_job(
                    job_id,
                    "TRANSFER_ITEM_FAILED",
                    (
                        f"Message {message_id}: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                    level="error",
                )


                raise


        return {
            "mode": mode,
            "paused": False,
            "sent_during_run":
                sent_during_run,
            **transfer_summary(
                job_id
            ),
        }


    finally:

        await client.disconnect()


# ============================================================
# FLASK
# ============================================================

def init_transfer(
    app,
    login_required,
    api_post_required,
    telegram_client,
    account_get,
):

    ensure_transfer_schema()


    # --------------------------------------------------------
    # CONFIG
    # --------------------------------------------------------

    @app.post(
        f"{BASE_PATH}/api/jobs/<int:job_id>/transfer/config"
    )
    @api_post_required
    def stage04_transfer_config(
        job_id
    ):

        data = (
            __import__(
                "flask"
            ).request.get_json(
                silent=True
            )
            or {}
        )


        mode = str(
            data.get(
                "transfer_mode",
                "none",
            )
        ).strip().lower()


        reset = bool(
            data.get(
                "reset",
                False,
            )
        )


        if mode not in (
            "none",
            "forward",
            "copy",
        ):

            return jsonify(
                ok=False,
                error="Transfer mode نامعتبر است.",
            ), 400


        job = job_get(
            job_id
        )


        if not job:

            return jsonify(
                ok=False,
                error="Job پیدا نشد.",
            ), 404


        old_mode = (
            job["transfer_mode"]
            if "transfer_mode" in job.keys()
            else "none"
        )


        if (
            reset
            or old_mode != mode
        ):

            reset_transfer(
                job_id
            )


        status = (
            "disabled"
            if mode == "none"
            else "pending"
        )


        update_job_transfer(
            job_id,
            transfer_mode=mode,
            transfer_status=status,
            transfer_last_error=None,
        )


        log_job(
            job_id,
            "TRANSFER_CONFIG",
            (
                f"TransferMode={mode} | "
                f"Reset={reset}"
            ),
        )


        return jsonify(
            ok=True,
            job_id=job_id,
            transfer_mode=mode,
            transfer_status=status,
        )


    # --------------------------------------------------------
    # EXECUTE
    # --------------------------------------------------------

    @app.post(
        f"{BASE_PATH}/api/jobs/<int:job_id>/transfer"
    )
    @api_post_required
    def stage04_transfer(
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


        if job["transfer_mode"] not in (
            "forward",
            "copy",
        ):

            return jsonify(
                ok=False,
                error=(
                    "ابتدا Transfer Mode را "
                    "روی Forward یا Copy قرار بده."
                ),
            ), 400


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
                error="اکانت متصل نیست.",
            ), 400


        update_job_transfer(
            job_id,
            transfer_status="running",
            transfer_last_error=None,
            transfer_started_at=(
                __import__(
                    "datetime"
                ).datetime.utcnow().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
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
                    execute_transfer(
                        client,
                        job,
                    )
                )


            elapsed = (
                time.perf_counter()
                - started
            )


            if result.get(
                "paused"
            ):

                current = transfer_summary(
                    job_id
                )


                rate = (
                    current["sent"] / elapsed
                    if elapsed > 0
                    else 0
                )


                update_job_transfer(
                    job_id,
                    transferred_count=
                        current["sent"],
                    transfer_seconds=
                        round(
                            elapsed,
                            4,
                        ),
                    transfer_rate=
                        round(
                            rate,
                            4,
                        ),
                )


                return jsonify(
                    ok=False,
                    paused=True,
                    job_id=job_id,
                    flood_wait=result.get(
                        "flood_wait"
                    ),
                    transferred=
                        current["sent"],
                    total=
                        current["total"],
                    message=(
                        "Telegram FloodWait اعمال کرد. "
                        "پیشرفت ذخیره شده و Job قابل Resume است."
                    ),
                ), 429


            current = transfer_summary(
                job_id
            )


            rate = (
                current["sent"]
                / elapsed
                if elapsed > 0
                else 0
            )


            update_job_transfer(
                job_id,
                transfer_status="completed",
                transferred_count=
                    current["sent"],
                transfer_seconds=
                    round(
                        elapsed,
                        4,
                    ),
                transfer_rate=
                    round(
                        rate,
                        4,
                    ),
                transfer_last_error=None,
                transfer_finished_at=(
                    __import__(
                        "datetime"
                    ).datetime.utcnow().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                ),
            )


            log_job(
                job_id,
                "TRANSFER_COMPLETED",
                (
                    f"{current['sent']} / "
                    f"{current['total']} پیام "
                    f"با Mode={job['transfer_mode']} "
                    f"در {elapsed:.2f}s منتقل شد. "
                    f"Rate={rate:.2f} msg/s"
                ),
            )


            return jsonify(
                ok=True,
                job_id=job_id,
                transfer_mode=
                    job["transfer_mode"],
                transfer_status=
                    "completed",
                transferred=
                    current["sent"],
                total=
                    current["total"],
                skipped=
                    current["skipped"],
                failed=
                    current["failed"],
                seconds=
                    round(
                        elapsed,
                        4,
                    ),
                rate=
                    round(
                        rate,
                        4,
                    ),
                message=(
                    f"{current['sent']} پیام "
                    f"در {elapsed:.2f} ثانیه "
                    f"به مقصد منتقل شد."
                ),
            )


        except errors.FloodWaitError as exc:

            seconds = int(
                exc.seconds
            )


            current = transfer_summary(
                job_id
            )


            update_job_transfer(
                job_id,
                transfer_status="paused",
                transferred_count=
                    current["sent"],
                transfer_last_error=(
                    f"FloodWait {seconds}s"
                ),
            )


            log_job(
                job_id,
                "TRANSFER_PAUSED",
                (
                    f"FloodWait {seconds}s. "
                    f"پیشرفت ذخیره شد."
                ),
                level="warning",
            )


            return jsonify(
                ok=False,
                paused=True,
                flood_wait=seconds,
                transferred=
                    current["sent"],
                total=
                    current["total"],
                error=(
                    f"FloodWait {seconds}s. "
                    f"بعداً همین انتقال را Resume کن."
                ),
            ), 429


        except Exception as exc:

            elapsed = (
                time.perf_counter()
                - started
            )


            current = transfer_summary(
                job_id
            )


            update_job_transfer(
                job_id,
                transfer_status="failed",
                transferred_count=
                    current["sent"],
                transfer_seconds=
                    round(
                        elapsed,
                        4,
                    ),
                transfer_last_error=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )


            log_job(
                job_id,
                "TRANSFER_FAILED",
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                level="error",
            )


            return jsonify(
                ok=False,
                job_id=job_id,
                transferred=
                    current["sent"],
                total=
                    current["total"],
                error=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            ), 500


    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    @app.get(
        f"{BASE_PATH}/api/jobs/<int:job_id>/transfer"
    )
    @login_required
    def stage04_transfer_status(
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


        return jsonify(
            ok=True,
            job_id=job_id,
            transfer_mode=
                job["transfer_mode"],
            transfer_status=
                job["transfer_status"],
            transferred_count=
                job["transferred_count"],
            transfer_seconds=
                job["transfer_seconds"],
            transfer_rate=
                job["transfer_rate"],
            transfer_last_error=
                job["transfer_last_error"],
            items=transfer_summary(
                job_id
            ),
        )
