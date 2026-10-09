#!/usr/bin/env python3

import os
import sqlite3
import sys
import time

from datetime import datetime, timezone
from pathlib import Path


RUNTIME_ROOT = Path(
    os.getenv(
        "TELTEST_RUNTIME_ROOT",
        "/var/lib/teltest",
    )
)

DB_FILE = (
    RUNTIME_ROOT
    / "data"
    / "teltest.sqlite3"
)

MAX_JOBS_PER_TICK = 3


def utc_now():
    return datetime.now(
        timezone.utc
    )


def parse_datetime(value):

    if not value:
        return None

    try:

        result = datetime.fromisoformat(
            str(
                value
            ).replace(
                "Z",
                "+00:00",
            )
        )

        if result.tzinfo is None:

            result = result.replace(
                tzinfo=timezone.utc
            )

        return result.astimezone(
            timezone.utc
        )

    except Exception:

        return None


def lite_connect():

    conn = sqlite3.connect(
        DB_FILE,
        timeout=15,
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA busy_timeout=15000"
    )

    return conn


def due_jobs():

    if not DB_FILE.is_file():

        return []


    conn = lite_connect()


    try:

        rows = conn.execute(
            """
            SELECT
                id,
                name,
                status,
                next_run_at,
                scheduler_backoff_until
            FROM extraction_jobs
            WHERE
                watch_enabled=1
                AND connector_code='telegram'
                AND next_run_at IS NOT NULL
                AND status <> 'running'
            ORDER BY
                next_run_at ASC,
                id ASC
            LIMIT 50
            """
        ).fetchall()


    finally:

        conn.close()


    now = utc_now()

    result = []


    for row in rows:

        next_run = parse_datetime(
            row[
                "next_run_at"
            ]
        )


        backoff = parse_datetime(
            row[
                "scheduler_backoff_until"
            ]
        )


        if (
            next_run
            and next_run <= now
            and (
                not backoff
                or backoff <= now
            )
        ):

            result.append(
                dict(
                    row
                )
            )


        if (
            len(
                result
            )
            >= MAX_JOBS_PER_TICK
        ):

            break


    return result


def status():

    jobs = due_jobs()

    print(
        "SCHEDULER_STATUS_OK"
    )

    print(
        f"DUE_JOBS={len(jobs)}"
    )

    for job in jobs:

        print(
            "DUE "
            f"#{job['id']} "
            f"{job['name']} "
            f"next={job['next_run_at']}"
        )


def claim_job(
    job_id
):

    conn = lite_connect()


    try:

        cursor = conn.execute(
            """
            UPDATE extraction_jobs
            SET
                status='running',
                scheduler_last_tick=?,
                last_run_at=CURRENT_TIMESTAMP,
                last_error=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE
                id=?
                AND watch_enabled=1
                AND status <> 'running'
            """,
            (
                utc_now()
                    .replace(
                        microsecond=0
                    )
                    .isoformat(),
                int(
                    job_id
                ),
            ),
        )


        conn.commit()


        return (
            cursor.rowcount
            == 1
        )


    finally:

        conn.close()


def create_run(
    job_id,
    start_mode,
    cursor,
):

    conn = lite_connect()


    try:

        conn.execute(
            """
            INSERT INTO extraction_runs(
                extraction_job_id,
                status,
                start_mode,
                start_cursor
            )
            VALUES(
                ?,
                'running',
                ?,
                ?
            )
            """,
            (
                int(
                    job_id
                ),
                start_mode,
                cursor,
            ),
        )


        conn.commit()


    finally:

        conn.close()


def execute_job(
    job_id
):

    #
    # Heavy modules are intentionally imported only after
    # at least one due job exists.
    #
    from app import (
        account_get,
        telegram_client,
    )

    from job_engine import (
        account_lock,
        db_connect,
        run_async,
    )

    from telegram_extractor_v2 import (
        extraction_job,
        fetch_messages,
        json_load,
        persist_messages,
        write_operation_log,
    )

    from watch_scheduler import (
        mark_scheduler_failure,
    )


    job = extraction_job(
        job_id
    )


    if not job:

        return {
            "ok":
                False,

            "error":
                "job_not_found",
        }


    if not job[
        "watch_enabled"
    ]:

        return {
            "ok":
                True,

            "skipped":
                "watch_disabled",
        }


    if not claim_job(
        job_id
    ):

        return {
            "ok":
                True,

            "skipped":
                "already_running",
        }


    #
    # Re-read after claim.
    #
    job = extraction_job(
        job_id
    )


    account = account_get(
        job[
            "source_account_id"
        ]
    )


    if (
        not account
        or account[
            "status"
        ]
        != "connected"
    ):

        error = (
            "اکانت Telegram متصل جاب "
            "در دسترس نیست."
        )


        mark_scheduler_failure(
            job_id,
            error,
        )


        write_operation_log(
            job_id,
            "WATCH_FAILED",
            error,
            "error",
        )


        return {
            "ok":
                False,

            "error":
                error,
        }


    config = json_load(
        job[
            "config_json"
        ],
        {},
    )


    try:

        max_items = int(
            config.get(
                "max_items",
                250,
            )
        )

        if not (
            1
            <= max_items
            <= 5000
        ):
            raise ValueError


    except (
        TypeError,
        ValueError,
    ):

        error = (
            "max_items جاب معتبر نیست."
        )


        mark_scheduler_failure(
            job_id,
            error,
        )


        return {
            "ok":
                False,

            "error":
                error,
        }


    effective_mode = (
        "incremental"
        if job[
            "cursor_external_id"
        ]
        else job[
            "start_mode"
        ]
    )


    create_run(
        job_id,
        effective_mode,
        job[
            "cursor_external_id"
        ],
    )


    write_operation_log(
        job_id,
        "WATCH_RUN_STARTED",
        (
            f"بررسی خودکار از Cursor="
            f"{job['cursor_external_id'] or 'initial'}"
        ),
    )


    started = time.perf_counter()


    try:

        with account_lock(
            account[
                "id"
            ]
        ):

            result = run_async(
                fetch_messages(
                    telegram_client(
                        account
                    ),
                    job,
                    max_items,
                )
            )


        elapsed = round(
            time.perf_counter()
            - started,
            3,
        )


        inserted, updated, skipped = (
            persist_messages(
                job_id,
                result,
                elapsed,
            )
        )


        write_operation_log(
            job_id,
            "WATCH_RUN_FINISHED",
            (
                f"{len(result['messages'])} دریافت؛ "
                f"{inserted} جدید؛ "
                f"{updated} بروزرسانی؛ "
                f"{skipped} فیلتر."
            ),
        )


        return {
            "ok":
                True,

            "job_id":
                job_id,

            "fetched":
                len(
                    result[
                        "messages"
                    ]
                ),

            "inserted":
                inserted,

            "updated":
                updated,

            "skipped":
                skipped,

            "elapsed":
                elapsed,
        }


    except Exception as exc:

        error = (
            f"{type(exc).__name__}: "
            f"{exc}"
        )[:2000]


        failure = mark_scheduler_failure(
            job_id,
            error,
        )


        write_operation_log(
            job_id,
            "WATCH_FAILED",
            (
                error
                + (
                    f" | retry={failure['retry_at']}"
                    if failure
                    else ""
                )
            ),
            "error",
        )


        return {
            "ok":
                False,

            "job_id":
                job_id,

            "error":
                error,

            "retry":
                failure,
        }


def main():

    if (
        len(
            sys.argv
        )
        > 1
        and sys.argv[
            1
        ]
        == "--status"
    ):

        status()

        return 0


    jobs = due_jobs()


    if not jobs:

        print(
            "SCHEDULER_IDLE"
        )

        return 0


    print(
        f"SCHEDULER_DUE={len(jobs)}"
    )


    failures = 0


    for job in jobs:

        print(
            f"RUN_JOB={job['id']} "
            f"{job['name']}"
        )


        result = execute_job(
            int(
                job[
                    "id"
                ]
            )
        )


        print(
            f"RESULT={result}"
        )


        if not result.get(
            "ok"
        ):

            failures += 1


    print(
        f"SCHEDULER_COMPLETE failures={failures}"
    )


    #
    # A failing Telegram job is already persisted and backed off.
    # Do not mark the systemd unit failed merely because a remote
    # provider/source temporarily failed.
    #
    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )
