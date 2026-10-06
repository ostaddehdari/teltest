import hashlib
import json

from contextlib import closing

from flask import jsonify

from job_engine import db_connect


BASE_PATH = "/teltest"

CORE_SCHEMA_VERSION = "2"


# ============================================================
# JSON
# ============================================================

def json_dump(
    value
):

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(
            ",",
            ":",
        ),
    )


def json_load(
    value,
    default=None,
):

    if default is None:
        default = {}


    if not value:
        return default


    try:

        return json.loads(
            value
        )

    except Exception:

        return default


# ============================================================
# SCHEMA
# ============================================================

def init_core_v2_schema():

    with closing(
        db_connect()
    ) as conn:

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (

                key TEXT PRIMARY KEY,

                value TEXT NOT NULL,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );


            CREATE TABLE IF NOT EXISTS source_connectors (

                code TEXT PRIMARY KEY,

                name TEXT NOT NULL,

                category TEXT NOT NULL
                    DEFAULT 'content',

                enabled INTEGER NOT NULL
                    DEFAULT 0,

                selectable INTEGER NOT NULL
                    DEFAULT 0,

                position INTEGER NOT NULL
                    DEFAULT 100,

                capabilities_json TEXT NOT NULL
                    DEFAULT '{}',

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );


            CREATE TABLE IF NOT EXISTS extraction_jobs (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                connector_code TEXT NOT NULL,

                source_account_id INTEGER,

                source_ref TEXT NOT NULL,

                source_key TEXT,

                source_title TEXT,

                status TEXT NOT NULL
                    DEFAULT 'draft',

                start_mode TEXT NOT NULL
                    DEFAULT 'all',

                start_date_utc TEXT,

                start_external_id TEXT,

                watch_enabled INTEGER NOT NULL
                    DEFAULT 0,

                poll_interval_minutes INTEGER NOT NULL
                    DEFAULT 5,

                cursor_external_id TEXT,

                cursor_published_at TEXT,

                next_run_at TEXT,

                last_run_at TEXT,

                last_success_at TEXT,

                last_error TEXT,

                config_json TEXT NOT NULL
                    DEFAULT '{}',

                rules_json TEXT NOT NULL
                    DEFAULT '{}',

                legacy_job_id INTEGER UNIQUE,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(connector_code)
                    REFERENCES source_connectors(code),

                FOREIGN KEY(source_account_id)
                    REFERENCES accounts(id)
                    ON DELETE SET NULL
            );


            CREATE TABLE IF NOT EXISTS content_items (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                connector_code TEXT NOT NULL,

                source_key TEXT NOT NULL,

                source_ref TEXT,

                source_title TEXT,

                external_id TEXT NOT NULL,

                published_at TEXT,

                content_type TEXT NOT NULL
                    DEFAULT 'text',

                raw_text TEXT,

                processed_text TEXT,

                media_json TEXT NOT NULL
                    DEFAULT '[]',

                metadata_json TEXT NOT NULL
                    DEFAULT '{}',

                content_hash TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(connector_code)
                    REFERENCES source_connectors(code),

                UNIQUE(
                    connector_code,
                    source_key,
                    external_id
                )
            );


            CREATE TABLE IF NOT EXISTS extraction_job_items (

                extraction_job_id INTEGER NOT NULL,

                content_id INTEGER NOT NULL,

                first_seen_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY(
                    extraction_job_id,
                    content_id
                ),

                FOREIGN KEY(extraction_job_id)
                    REFERENCES extraction_jobs(id)
                    ON DELETE CASCADE,

                FOREIGN KEY(content_id)
                    REFERENCES content_items(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS content_hashtags (

                content_id INTEGER NOT NULL,

                hashtag TEXT NOT NULL,

                normalized_hashtag TEXT NOT NULL,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY(
                    content_id,
                    normalized_hashtag
                ),

                FOREIGN KEY(content_id)
                    REFERENCES content_items(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS content_links (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                content_id INTEGER NOT NULL,

                url TEXT NOT NULL,

                domain TEXT,

                link_text TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(content_id)
                    REFERENCES content_items(id)
                    ON DELETE CASCADE,

                UNIQUE(
                    content_id,
                    url
                )
            );


            CREATE TABLE IF NOT EXISTS transfer_jobs (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                selector_type TEXT NOT NULL
                    DEFAULT 'extraction_job',

                selector_json TEXT NOT NULL
                    DEFAULT '{}',

                status TEXT NOT NULL
                    DEFAULT 'draft',

                last_error TEXT,

                legacy_state_json TEXT NOT NULL
                    DEFAULT '{}',

                legacy_job_id INTEGER UNIQUE,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );


            CREATE TABLE IF NOT EXISTS transfer_destinations (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                transfer_job_id INTEGER NOT NULL,

                provider_code TEXT NOT NULL,

                provider_account_id INTEGER,

                destination_ref TEXT NOT NULL,

                mode TEXT NOT NULL
                    DEFAULT 'copy',

                enabled INTEGER NOT NULL
                    DEFAULT 1,

                position INTEGER NOT NULL
                    DEFAULT 100,

                rules_json TEXT NOT NULL
                    DEFAULT '{}',

                status TEXT NOT NULL
                    DEFAULT 'pending',

                last_error TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(transfer_job_id)
                    REFERENCES transfer_jobs(id)
                    ON DELETE CASCADE,

                UNIQUE(
                    transfer_job_id,
                    provider_code,
                    destination_ref,
                    mode
                )
            );


            CREATE TABLE IF NOT EXISTS legacy_job_map (

                legacy_job_id INTEGER PRIMARY KEY,

                extraction_job_id INTEGER NOT NULL UNIQUE,

                transfer_job_id INTEGER NOT NULL UNIQUE,

                migrated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(extraction_job_id)
                    REFERENCES extraction_jobs(id)
                    ON DELETE CASCADE,

                FOREIGN KEY(transfer_job_id)
                    REFERENCES transfer_jobs(id)
                    ON DELETE CASCADE
            );


            CREATE INDEX IF NOT EXISTS
                idx_extraction_jobs_connector
                ON extraction_jobs(
                    connector_code,
                    status
                );


            CREATE INDEX IF NOT EXISTS
                idx_extraction_jobs_next_run
                ON extraction_jobs(
                    watch_enabled,
                    next_run_at
                );


            CREATE INDEX IF NOT EXISTS
                idx_content_source_external
                ON content_items(
                    connector_code,
                    source_key,
                    external_id
                );


            CREATE INDEX IF NOT EXISTS
                idx_content_published
                ON content_items(
                    published_at
                );


            CREATE INDEX IF NOT EXISTS
                idx_content_type
                ON content_items(
                    content_type
                );


            CREATE INDEX IF NOT EXISTS
                idx_hashtag_normalized
                ON content_hashtags(
                    normalized_hashtag
                );


            CREATE INDEX IF NOT EXISTS
                idx_links_domain
                ON content_links(
                    domain
                );


            CREATE INDEX IF NOT EXISTS
                idx_transfer_jobs_status
                ON transfer_jobs(
                    status
                );


            CREATE INDEX IF NOT EXISTS
                idx_transfer_destinations_job
                ON transfer_destinations(
                    transfer_job_id,
                    enabled
                );
            """
        )


        conn.execute(
            """
            INSERT INTO schema_meta (
                key,
                value,
                updated_at
            )
            VALUES (
                'core_schema_version',
                ?,
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
                CORE_SCHEMA_VERSION,
            ),
        )


        conn.commit()


# ============================================================
# CONNECTOR REGISTRY
# ============================================================

CONNECTORS = [

    {
        "code":
            "telegram",

        "name":
            "Telegram",

        "position":
            10,

        "enabled":
            1,

        "selectable":
            1,

        "capabilities": {
            "text":
                True,

            "media":
                True,

            "incremental":
                True,

            "date_cursor":
                True,

            "external_id_cursor":
                True,

            "watch":
                True,
        },
    },

    {
        "code":
            "instagram",

        "name":
            "Instagram",

        "position":
            20,
    },

    {
        "code":
            "youtube",

        "name":
            "YouTube",

        "position":
            30,
    },

    {
        "code":
            "tiktok",

        "name":
            "TikTok",

        "position":
            40,
    },

    {
        "code":
            "pinterest",

        "name":
            "Pinterest",

        "position":
            50,
    },

    {
        "code":
            "news",

        "name":
            "News Sites",

        "position":
            60,
    },

    {
        "code":
            "web",

        "name":
            "Websites",

        "position":
            70,
    },

    {
        "code":
            "rss",

        "name":
            "RSS",

        "position":
            80,
    },
]


def seed_connectors():

    with closing(
        db_connect()
    ) as conn:

        for item in CONNECTORS:

            enabled = int(
                item.get(
                    "enabled",
                    0,
                )
            )

            selectable = int(
                item.get(
                    "selectable",
                    0,
                )
            )

            capabilities = item.get(
                "capabilities",
                {
                    "planned":
                        True,
                },
            )


            conn.execute(
                """
                INSERT INTO source_connectors (
                    code,
                    name,
                    category,
                    enabled,
                    selectable,
                    position,
                    capabilities_json,
                    updated_at
                )
                VALUES (
                    ?, ?,
                    'content',
                    ?, ?, ?, ?,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT(code)
                DO UPDATE SET
                    name =
                        excluded.name,
                    position =
                        excluded.position,
                    capabilities_json =
                        excluded.capabilities_json,
                    updated_at =
                        CURRENT_TIMESTAMP
                """,
                (
                    item["code"],
                    item["name"],
                    enabled,
                    selectable,
                    item["position"],
                    json_dump(
                        capabilities
                    ),
                ),
            )


        #
        # Telegram باید فعلاً تنها Connector فعال باشد.
        #
        conn.execute(
            """
            UPDATE source_connectors
            SET
                enabled = 1,
                selectable = 1,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE code = 'telegram'
            """
        )


        conn.execute(
            """
            UPDATE source_connectors
            SET
                enabled = 0,
                selectable = 0,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE code <> 'telegram'
            """
        )


        conn.commit()


# ============================================================
# LEGACY MIGRATION
# ============================================================

def legacy_table_exists(
    conn,
    table
):

    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE
            type = 'table'
            AND name = ?
        """,
        (
            table,
        ),
    ).fetchone()


    return bool(
        row
    )


def normalize_legacy_status(
    value
):

    value = str(
        value
        or "draft"
    )


    mapping = {
        "pending":
            "draft",

        "running":
            "running",

        "completed":
            "completed",

        "failed":
            "failed",

        "paused":
            "paused",
    }


    return mapping.get(
        value,
        value,
    )


def migrate_legacy():

    with closing(
        db_connect()
    ) as conn:

        if not legacy_table_exists(
            conn,
            "jobs",
        ):

            return {
                "legacy_jobs":
                    0,

                "mapped_jobs":
                    0,

                "legacy_posts":
                    0,

                "mapped_posts":
                    0,
            }


        jobs = conn.execute(
            """
            SELECT *
            FROM jobs
            ORDER BY id ASC
            """
        ).fetchall()


        for legacy in jobs:

            legacy_id = int(
                legacy["id"]
            )


            existing = conn.execute(
                """
                SELECT
                    extraction_job_id,
                    transfer_job_id
                FROM legacy_job_map
                WHERE legacy_job_id = ?
                """,
                (
                    legacy_id,
                ),
            ).fetchone()


            if existing:

                extraction_job_id = int(
                    existing[
                        "extraction_job_id"
                    ]
                )

                transfer_job_id = int(
                    existing[
                        "transfer_job_id"
                    ]
                )


            else:

                source_key = (
                    str(
                        legacy[
                            "source_entity_id"
                        ]
                    )
                    if (
                        "source_entity_id"
                        in legacy.keys()
                        and legacy[
                            "source_entity_id"
                        ]
                    )
                    else str(
                        legacy[
                            "source_ref"
                        ]
                    )
                )


                cursor_row = conn.execute(
                    """
                    SELECT
                        MAX(message_id)
                            AS max_message_id,

                        MAX(message_date)
                            AS max_message_date

                    FROM posts

                    WHERE job_id = ?
                    """,
                    (
                        legacy_id,
                    ),
                ).fetchone()


                extraction_cursor = (
                    str(
                        cursor_row[
                            "max_message_id"
                        ]
                    )
                    if (
                        cursor_row
                        and cursor_row[
                            "max_message_id"
                        ]
                        is not None
                    )
                    else None
                )


                cursor_date = (
                    cursor_row[
                        "max_message_date"
                    ]
                    if cursor_row
                    else None
                )


                extraction_cursor_insert = (
                    conn.execute(
                        """
                        INSERT INTO extraction_jobs (
                            name,
                            connector_code,
                            source_account_id,
                            source_ref,
                            source_key,
                            source_title,
                            status,
                            start_mode,
                            watch_enabled,
                            poll_interval_minutes,
                            cursor_external_id,
                            cursor_published_at,
                            last_run_at,
                            last_success_at,
                            last_error,
                            config_json,
                            rules_json,
                            legacy_job_id,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            ?,
                            'telegram',
                            ?,
                            ?,
                            ?,
                            ?,
                            ?,
                            'legacy',
                            0,
                            5,
                            ?,
                            ?,
                            ?,
                            ?,
                            ?,
                            ?,
                            '{}',
                            ?,
                            COALESCE(
                                ?,
                                CURRENT_TIMESTAMP
                            ),
                            CURRENT_TIMESTAMP
                        )
                        """,
                        (
                            (
                                legacy[
                                    "name"
                                ]
                                or (
                                    "Legacy Extract "
                                    f"#{legacy_id}"
                                )
                            ),
                            legacy[
                                "account_id"
                            ],
                            legacy[
                                "source_ref"
                            ],
                            source_key,
                            (
                                legacy[
                                    "source_title"
                                ]
                                if (
                                    "source_title"
                                    in legacy.keys()
                                )
                                else None
                            ),
                            normalize_legacy_status(
                                legacy[
                                    "status"
                                ]
                            ),
                            extraction_cursor,
                            cursor_date,
                            (
                                legacy[
                                    "finished_at"
                                ]
                                if (
                                    "finished_at"
                                    in legacy.keys()
                                )
                                else None
                            ),
                            (
                                legacy[
                                    "finished_at"
                                ]
                                if (
                                    legacy[
                                        "status"
                                    ]
                                    == "completed"
                                )
                                else None
                            ),
                            (
                                legacy[
                                    "last_error"
                                ]
                                if (
                                    "last_error"
                                    in legacy.keys()
                                )
                                else None
                            ),
                            json_dump(
                                {
                                    "migrated_from":
                                        "legacy_jobs",

                                    "legacy_job_id":
                                        legacy_id,

                                    "legacy_limit":
                                        legacy[
                                            "limit_count"
                                        ],

                                    "legacy_storage_mode":
                                        legacy[
                                            "storage_mode"
                                        ],
                                }
                            ),
                            legacy_id,
                            (
                                legacy[
                                    "created_at"
                                ]
                                if (
                                    "created_at"
                                    in legacy.keys()
                                )
                                else None
                            ),
                        ),
                    )
                )


                extraction_job_id = (
                    extraction_cursor_insert.lastrowid
                )


                transfer_mode = (
                    legacy[
                        "transfer_mode"
                    ]
                    if (
                        "transfer_mode"
                        in legacy.keys()
                        and legacy[
                            "transfer_mode"
                        ]
                    )
                    else "none"
                )


                transfer_status = (
                    legacy[
                        "transfer_status"
                    ]
                    if (
                        "transfer_status"
                        in legacy.keys()
                        and legacy[
                            "transfer_status"
                        ]
                    )
                    else "none"
                )


                legacy_state = {
                    "telegram": {
                        "mode":
                            transfer_mode,

                        "status":
                            transfer_status,

                        "count":
                            (
                                legacy[
                                    "transferred_count"
                                ]
                                if (
                                    "transferred_count"
                                    in legacy.keys()
                                )
                                else 0
                            ),
                    },

                    "bale": {
                        "status":
                            (
                                legacy[
                                    "bale_status"
                                ]
                                if (
                                    "bale_status"
                                    in legacy.keys()
                                )
                                else "none"
                            ),

                        "count":
                            (
                                legacy[
                                    "bale_sent_count"
                                ]
                                if (
                                    "bale_sent_count"
                                    in legacy.keys()
                                )
                                else 0
                            ),
                    },

                    "eitaa": {
                        "status":
                            (
                                legacy[
                                    "eitaa_status"
                                ]
                                if (
                                    "eitaa_status"
                                    in legacy.keys()
                                )
                                else "none"
                            ),

                        "count":
                            (
                                legacy[
                                    "eitaa_sent_count"
                                ]
                                if (
                                    "eitaa_sent_count"
                                    in legacy.keys()
                                )
                                else 0
                            ),
                    },

                    "rubika": {
                        "status":
                            (
                                legacy[
                                    "rubika_status"
                                ]
                                if (
                                    "rubika_status"
                                    in legacy.keys()
                                )
                                else "none"
                            ),

                        "count":
                            (
                                legacy[
                                    "rubika_sent_count"
                                ]
                                if (
                                    "rubika_sent_count"
                                    in legacy.keys()
                                )
                                else 0
                            ),
                    },
                }


                transfer_cursor = conn.execute(
                    """
                    INSERT INTO transfer_jobs (
                        name,
                        selector_type,
                        selector_json,
                        status,
                        last_error,
                        legacy_state_json,
                        legacy_job_id,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        ?,
                        'extraction_job',
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        COALESCE(
                            ?,
                            CURRENT_TIMESTAMP
                        ),
                        CURRENT_TIMESTAMP
                    )
                    """,
                    (
                        (
                            legacy[
                                "name"
                            ]
                            or (
                                "Legacy Transfer "
                                f"#{legacy_id}"
                            )
                        ),
                        json_dump(
                            {
                                "extraction_job_id":
                                    extraction_job_id,

                                "legacy_job_id":
                                    legacy_id,
                            }
                        ),
                        (
                            "completed"
                            if (
                                transfer_status
                                == "completed"
                            )
                            else "draft"
                        ),
                        (
                            legacy[
                                "transfer_last_error"
                            ]
                            if (
                                "transfer_last_error"
                                in legacy.keys()
                            )
                            else None
                        ),
                        json_dump(
                            legacy_state
                        ),
                        legacy_id,
                        (
                            legacy[
                                "created_at"
                            ]
                            if (
                                "created_at"
                                in legacy.keys()
                            )
                            else None
                        ),
                    ),
                )


                transfer_job_id = (
                    transfer_cursor.lastrowid
                )


                conn.execute(
                    """
                    INSERT INTO legacy_job_map (
                        legacy_job_id,
                        extraction_job_id,
                        transfer_job_id
                    )
                    VALUES (
                        ?, ?, ?
                    )
                    """,
                    (
                        legacy_id,
                        extraction_job_id,
                        transfer_job_id,
                    ),
                )


                destination_ref = str(
                    legacy[
                        "destination_ref"
                    ]
                    or ""
                ).strip()


                if destination_ref:

                    enabled = int(
                        transfer_mode
                        in (
                            "forward",
                            "copy",
                        )
                    )


                    mode = (
                        transfer_mode
                        if transfer_mode
                        in (
                            "forward",
                            "copy",
                        )
                        else "copy"
                    )


                    conn.execute(
                        """
                        INSERT OR IGNORE INTO
                            transfer_destinations (
                                transfer_job_id,
                                provider_code,
                                provider_account_id,
                                destination_ref,
                                mode,
                                enabled,
                                position,
                                rules_json,
                                status,
                                last_error
                            )
                        VALUES (
                            ?,
                            'telegram',
                            ?,
                            ?,
                            ?,
                            ?,
                            10,
                            '{}',
                            ?,
                            ?
                        )
                        """,
                        (
                            transfer_job_id,
                            legacy[
                                "account_id"
                            ],
                            destination_ref,
                            mode,
                            enabled,
                            transfer_status,
                            (
                                legacy[
                                    "transfer_last_error"
                                ]
                                if (
                                    "transfer_last_error"
                                    in legacy.keys()
                                )
                                else None
                            ),
                        ),
                    )


            #
            # Content migration is idempotent.
            #
            source_key_row = conn.execute(
                """
                SELECT
                    source_key,
                    source_ref,
                    source_title
                FROM extraction_jobs
                WHERE id = ?
                """,
                (
                    extraction_job_id,
                ),
            ).fetchone()


            legacy_posts = conn.execute(
                """
                SELECT *
                FROM posts
                WHERE job_id = ?
                ORDER BY message_id ASC
                """,
                (
                    legacy_id,
                ),
            ).fetchall()


            for post in legacy_posts:

                raw_text = (
                    post[
                        "text"
                    ]
                    or ""
                )


                hash_input = (
                    "telegram|"
                    + str(
                        source_key_row[
                            "source_key"
                        ]
                    )
                    + "|"
                    + str(
                        post[
                            "message_id"
                        ]
                    )
                    + "|"
                    + raw_text
                )


                content_hash = hashlib.sha256(
                    hash_input.encode(
                        "utf-8"
                    )
                ).hexdigest()


                metadata = {
                    "telegram": {
                        "views":
                            post[
                                "views"
                            ],

                        "forwards":
                            post[
                                "forwards"
                            ],

                        "grouped_id":
                            post[
                                "grouped_id"
                            ],
                    },

                    "legacy": {
                        "job_id":
                            legacy_id,

                        "post_id":
                            post["id"],
                    },
                }


                conn.execute(
                    """
                    INSERT INTO content_items (
                        connector_code,
                        source_key,
                        source_ref,
                        source_title,
                        external_id,
                        published_at,
                        content_type,
                        raw_text,
                        processed_text,
                        media_json,
                        metadata_json,
                        content_hash,
                        updated_at
                    )
                    VALUES (
                        'telegram',
                        ?, ?, ?, ?, ?,
                        ?, ?, ?,
                        '[]',
                        ?, ?,
                        CURRENT_TIMESTAMP
                    )
                    ON CONFLICT(
                        connector_code,
                        source_key,
                        external_id
                    )
                    DO UPDATE SET
                        source_ref =
                            excluded.source_ref,

                        source_title =
                            COALESCE(
                                excluded.source_title,
                                content_items.source_title
                            ),

                        published_at =
                            COALESCE(
                                excluded.published_at,
                                content_items.published_at
                            ),

                        raw_text =
                            excluded.raw_text,

                        processed_text =
                            excluded.processed_text,

                        content_type =
                            excluded.content_type,

                        metadata_json =
                            excluded.metadata_json,

                        content_hash =
                            excluded.content_hash,

                        updated_at =
                            CURRENT_TIMESTAMP
                    """,
                    (
                        source_key_row[
                            "source_key"
                        ],
                        source_key_row[
                            "source_ref"
                        ],
                        source_key_row[
                            "source_title"
                        ],
                        str(
                            post[
                                "message_id"
                            ]
                        ),
                        post[
                            "message_date"
                        ],
                        (
                            post[
                                "media_type"
                            ]
                            or "text"
                        ),
                        raw_text,
                        raw_text,
                        json_dump(
                            metadata
                        ),
                        content_hash,
                    ),
                )


                content = conn.execute(
                    """
                    SELECT id
                    FROM content_items
                    WHERE
                        connector_code =
                            'telegram'

                        AND source_key = ?

                        AND external_id = ?
                    """,
                    (
                        source_key_row[
                            "source_key"
                        ],
                        str(
                            post[
                                "message_id"
                            ]
                        ),
                    ),
                ).fetchone()


                conn.execute(
                    """
                    INSERT OR IGNORE INTO
                        extraction_job_items (
                            extraction_job_id,
                            content_id
                        )
                    VALUES (
                        ?, ?
                    )
                    """,
                    (
                        extraction_job_id,
                        content[
                            "id"
                        ],
                    ),
                )


        conn.execute(
            """
            INSERT INTO schema_meta (
                key,
                value,
                updated_at
            )
            VALUES (
                'legacy_migration_last_run',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(key)
            DO UPDATE SET
                value =
                    excluded.value,
                updated_at =
                    CURRENT_TIMESTAMP
            """
        )


        conn.commit()


        legacy_jobs_count = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM jobs
            """
        ).fetchone()["n"]


        mapped_jobs_count = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM legacy_job_map
            """
        ).fetchone()["n"]


        legacy_posts_count = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM posts
            """
        ).fetchone()["n"]


        mapped_post_rows = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM extraction_job_items eji

            INNER JOIN extraction_jobs ej
                ON ej.id =
                    eji.extraction_job_id

            WHERE
                ej.legacy_job_id
                IS NOT NULL
            """
        ).fetchone()["n"]


        return {
            "legacy_jobs":
                legacy_jobs_count,

            "mapped_jobs":
                mapped_jobs_count,

            "legacy_posts":
                legacy_posts_count,

            "mapped_posts":
                mapped_post_rows,
        }


# ============================================================
# BOOT
# ============================================================

def bootstrap_core_v2():

    init_core_v2_schema()

    seed_connectors()

    return migrate_legacy()


# ============================================================
# SERIALIZATION
# ============================================================

def connector_dict(
    row
):

    item = dict(
        row
    )

    item[
        "enabled"
    ] = bool(
        item[
            "enabled"
        ]
    )

    item[
        "selectable"
    ] = bool(
        item[
            "selectable"
        ]
    )

    item[
        "capabilities"
    ] = json_load(
        item.pop(
            "capabilities_json",
            "{}",
        )
    )

    return item


def extraction_dict(
    row
):

    item = dict(
        row
    )

    item[
        "watch_enabled"
    ] = bool(
        item[
            "watch_enabled"
        ]
    )

    item[
        "config"
    ] = json_load(
        item.pop(
            "config_json",
            "{}",
        )
    )

    item[
        "rules"
    ] = json_load(
        item.pop(
            "rules_json",
            "{}",
        )
    )

    return item


def transfer_dict(
    row
):

    item = dict(
        row
    )

    item[
        "selector"
    ] = json_load(
        item.pop(
            "selector_json",
            "{}",
        )
    )

    item[
        "legacy_state"
    ] = json_load(
        item.pop(
            "legacy_state_json",
            "{}",
        )
    )

    return item


# ============================================================
# FLASK API
# ============================================================

def init_core_v2(
    app,
    login_required,
):

    migration = bootstrap_core_v2()


    @app.get(
        f"{BASE_PATH}/api/v2/source-connectors"
    )
    @login_required
    def v2_source_connectors():

        with closing(
            db_connect()
        ) as conn:

            rows = conn.execute(
                """
                SELECT *
                FROM source_connectors
                ORDER BY
                    position ASC,
                    name COLLATE NOCASE ASC
                """
            ).fetchall()


        return jsonify(
            ok=True,

            connectors=[
                connector_dict(
                    row
                )
                for row in rows
            ],
        )


    @app.get(
        f"{BASE_PATH}/api/v2/extraction-jobs"
    )
    @login_required
    def v2_extraction_jobs():

        with closing(
            db_connect()
        ) as conn:

            rows = conn.execute(
                """
                SELECT
                    ej.*,

                    (
                        SELECT COUNT(*)
                        FROM extraction_job_items eji
                        WHERE
                            eji.extraction_job_id =
                                ej.id
                    ) AS content_count

                FROM extraction_jobs ej

                ORDER BY
                    ej.id DESC

                LIMIT 250
                """
            ).fetchall()


        return jsonify(
            ok=True,

            jobs=[
                extraction_dict(
                    row
                )
                for row in rows
            ],
        )


    @app.get(
        f"{BASE_PATH}/api/v2/content-items"
    )
    @login_required
    def v2_content_items():

        with closing(
            db_connect()
        ) as conn:

            rows = conn.execute(
                """
                SELECT
                    id,
                    connector_code,
                    source_key,
                    source_ref,
                    source_title,
                    external_id,
                    published_at,
                    content_type,
                    raw_text,
                    processed_text,
                    content_hash,
                    created_at,
                    updated_at
                FROM content_items
                ORDER BY
                    id DESC
                LIMIT 100
                """
            ).fetchall()


        return jsonify(
            ok=True,

            count=len(
                rows
            ),

            items=[
                dict(
                    row
                )
                for row in rows
            ],
        )


    @app.get(
        f"{BASE_PATH}/api/v2/transfer-jobs"
    )
    @login_required
    def v2_transfer_jobs():

        with closing(
            db_connect()
        ) as conn:

            rows = conn.execute(
                """
                SELECT
                    tj.*,

                    (
                        SELECT COUNT(*)
                        FROM transfer_destinations td
                        WHERE
                            td.transfer_job_id =
                                tj.id
                    ) AS destination_count

                FROM transfer_jobs tj

                ORDER BY
                    tj.id DESC

                LIMIT 250
                """
            ).fetchall()


        return jsonify(
            ok=True,

            jobs=[
                transfer_dict(
                    row
                )
                for row in rows
            ],
        )


    @app.get(
        f"{BASE_PATH}/api/v2/architecture/summary"
    )
    @login_required
    def v2_architecture_summary():

        with closing(
            db_connect()
        ) as conn:

            def count(
                table
            ):

                return conn.execute(
                    f"""
                    SELECT COUNT(*) AS n
                    FROM {table}
                    """
                ).fetchone()["n"]


            connectors = conn.execute(
                """
                SELECT
                    code,
                    name,
                    enabled,
                    selectable
                FROM source_connectors
                ORDER BY position
                """
            ).fetchall()


            schema_version = conn.execute(
                """
                SELECT value
                FROM schema_meta
                WHERE
                    key =
                    'core_schema_version'
                """
            ).fetchone()


            counts = {
                "extraction_jobs":
                    count(
                        "extraction_jobs"
                    ),

                "content_items":
                    count(
                        "content_items"
                    ),

                "transfer_jobs":
                    count(
                        "transfer_jobs"
                    ),

                "transfer_destinations":
                    count(
                        "transfer_destinations"
                    ),

                "legacy_maps":
                    count(
                        "legacy_job_map"
                    ),
            }


        return jsonify(
            ok=True,

            architecture=
                "split-core-v2",

            schema_version=(
                schema_version[
                    "value"
                ]
                if schema_version
                else None
            ),

            counts=counts,

            connectors=[
                {
                    "code":
                        row["code"],

                    "name":
                        row["name"],

                    "enabled":
                        bool(
                            row[
                                "enabled"
                            ]
                        ),

                    "selectable":
                        bool(
                            row[
                                "selectable"
                            ]
                        ),
                }
                for row in connectors
            ],

            boot_migration=
                migration,
        )
