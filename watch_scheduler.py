from contextlib import closing
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from job_engine import db_connect


BASE_PATH = "/teltest"
SCHEDULER_VERSION = "1"

MIN_INTERVAL = 1
MAX_INTERVAL = 1440
DEFAULT_INTERVAL = 5


def utc_now():
    return datetime.now(
        timezone.utc
    ).replace(
        microsecond=0
    )


def utc_iso(value):
    return value.astimezone(
        timezone.utc
    ).replace(
        microsecond=0
    ).isoformat()


def parse_bool(value):

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value != 0

    return str(
        value or ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def normalize_interval(value):

    try:
        value = int(value)
    except (TypeError, ValueError):
        value = DEFAULT_INTERVAL

    return max(
        MIN_INTERVAL,
        min(
            MAX_INTERVAL,
            value,
        ),
    )


def next_run_iso(
    interval_minutes,
):

    interval_minutes = normalize_interval(
        interval_minutes
    )

    return utc_iso(
        utc_now()
        + timedelta(
            minutes=interval_minutes
        )
    )


def init_watch_schema():

    with closing(
        db_connect()
    ) as conn:

        columns = {
            row["name"]
            for row
            in conn.execute(
                """
                PRAGMA table_info(
                    extraction_jobs
                )
                """
            ).fetchall()
        }


        additions = {
            "scheduler_failures":
                """
                scheduler_failures
                INTEGER NOT NULL DEFAULT 0
                """,

            "scheduler_backoff_until":
                """
                scheduler_backoff_until
                TEXT
                """,

            "scheduler_last_tick":
                """
                scheduler_last_tick
                TEXT
                """,
        }


        for name, ddl in additions.items():

            if name not in columns:

                conn.execute(
                    f"""
                    ALTER TABLE extraction_jobs
                    ADD COLUMN {ddl}
                    """
                )


        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS
                idx_extraction_watch_due
                ON extraction_jobs(
                    watch_enabled,
                    next_run_at,
                    status
                );

            CREATE INDEX IF NOT EXISTS
                idx_extraction_watch_backoff
                ON extraction_jobs(
                    scheduler_backoff_until
                );
            """
        )


        conn.execute(
            """
            INSERT INTO schema_meta(
                key,
                value,
                updated_at
            )
            VALUES(
                'watch_scheduler_version',
                ?,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(key)
            DO UPDATE SET
                value=excluded.value,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                SCHEDULER_VERSION,
            ),
        )


        conn.commit()


def configure_watch(
    job_id,
    enabled,
    interval,
    immediate=True,
):

    enabled = parse_bool(
        enabled
    )

    interval = normalize_interval(
        interval
    )


    with closing(
        db_connect()
    ) as conn:

        job = conn.execute(
            """
            SELECT *
            FROM extraction_jobs
            WHERE id=?
            """,
            (
                int(job_id),
            ),
        ).fetchone()


        if not job:

            raise ValueError(
                "جاب استخراج پیدا نشد."
            )


        if (
            enabled
            and job["connector_code"]
            != "telegram"
        ):

            raise ValueError(
                "فعلاً Watch فقط برای Telegram فعال است."
            )


        if enabled:

            next_run = (
                utc_iso(
                    utc_now()
                )
                if immediate
                else next_run_iso(
                    interval
                )
            )


            status = (
                "running"
                if job["status"]
                == "running"
                else "watching"
            )


        else:

            next_run = None

            status = (
                "completed"
                if job["status"]
                == "watching"
                else job["status"]
            )


        conn.execute(
            """
            UPDATE extraction_jobs
            SET
                watch_enabled=?,
                poll_interval_minutes=?,
                status=?,
                next_run_at=?,
                scheduler_failures=0,
                scheduler_backoff_until=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                int(enabled),
                interval,
                status,
                next_run,
                int(job_id),
            ),
        )


        conn.commit()


    return {
        "enabled":
            enabled,

        "interval_minutes":
            interval,

        "next_run_at":
            next_run,

        "status":
            status,
    }


def mark_scheduler_failure(
    job_id,
    error,
):

    error = str(
        error
    )[:2000]


    with closing(
        db_connect()
    ) as conn:

        job = conn.execute(
            """
            SELECT
                watch_enabled,
                poll_interval_minutes,
                scheduler_failures
            FROM extraction_jobs
            WHERE id=?
            """,
            (
                int(job_id),
            ),
        ).fetchone()


        if not job:
            return None


        failures = int(
            job[
                "scheduler_failures"
            ]
            or 0
        ) + 1


        base = normalize_interval(
            job[
                "poll_interval_minutes"
            ]
        )


        multiplier = 2 ** min(
            max(
                failures - 1,
                0,
            ),
            4,
        )


        backoff_minutes = min(
            60,
            max(
                base,
                base * multiplier,
            ),
        )


        retry_at = utc_iso(
            utc_now()
            + timedelta(
                minutes=backoff_minutes
            )
        )


        status = (
            "watching"
            if job[
                "watch_enabled"
            ]
            else "failed"
        )


        conn.execute(
            """
            UPDATE extraction_jobs
            SET
                status=?,
                last_error=?,
                scheduler_failures=?,
                scheduler_backoff_until=?,
                next_run_at=?,
                scheduler_last_tick=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                status,
                error,
                failures,
                retry_at,
                retry_at,
                utc_iso(
                    utc_now()
                ),
                int(job_id),
            ),
        )


        conn.execute(
            """
            UPDATE extraction_runs
            SET
                status='failed',
                error_text=?,
                finished_at=CURRENT_TIMESTAMP
            WHERE id=(
                SELECT id
                FROM extraction_runs
                WHERE
                    extraction_job_id=?
                    AND status='running'
                ORDER BY id DESC
                LIMIT 1
            )
            """,
            (
                error,
                int(job_id),
            ),
        )


        conn.commit()


    return {
        "failures":
            failures,

        "backoff_minutes":
            backoff_minutes,

        "retry_at":
            retry_at,
    }


def scheduler_summary():

    with closing(
        db_connect()
    ) as conn:

        watching = conn.execute(
            """
            SELECT COUNT(*)
            FROM extraction_jobs
            WHERE watch_enabled=1
            """
        ).fetchone()[0]


        due = conn.execute(
            """
            SELECT COUNT(*)
            FROM extraction_jobs
            WHERE
                watch_enabled=1
                AND next_run_at IS NOT NULL
                AND status <> 'running'
                AND datetime(next_run_at)
                    <= datetime('now')
            """
        ).fetchone()[0]


        next_row = conn.execute(
            """
            SELECT
                id,
                name,
                next_run_at
            FROM extraction_jobs
            WHERE
                watch_enabled=1
                AND next_run_at IS NOT NULL
            ORDER BY
                datetime(next_run_at),
                id
            LIMIT 1
            """
        ).fetchone()


    return {
        "watching_jobs":
            watching,

        "due_jobs":
            due,

        "next_job":
            (
                dict(
                    next_row
                )
                if next_row
                else None
            ),
    }


def init_watch_scheduler(
    app,
    login_required,
    api_post_required,
):

    init_watch_schema()


    @app.get(
        f"{BASE_PATH}/api/v2/scheduler/status"
    )
    @login_required
    def scheduler_status():

        return jsonify(
            ok=True,
            version=
                SCHEDULER_VERSION,
            **scheduler_summary(),
        )


    @app.route(
        f"{BASE_PATH}/api/v2/operations/extraction-jobs/<int:job_id>/watch",
        methods=[
            "PATCH",
        ],
    )
    @api_post_required
    def extraction_watch(
        job_id
    ):

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )


        try:

            result = configure_watch(
                job_id,
                data.get(
                    "enabled"
                ),
                data.get(
                    "poll_interval_minutes",
                    DEFAULT_INTERVAL,
                ),
                immediate=bool(
                    data.get(
                        "immediate",
                        True,
                    )
                ),
            )


        except ValueError as exc:

            return jsonify(
                ok=False,
                error=str(
                    exc
                ),
            ), 400


        return jsonify(
            ok=True,
            job_id=
                job_id,
            watch=
                result,
            message=(
                "پایش خودکار فعال شد."
                if result[
                    "enabled"
                ]
                else "پایش خودکار غیرفعال شد."
            ),
        )
