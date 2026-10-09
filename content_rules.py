import hashlib
import json
import re

from contextlib import closing
from urllib.parse import urlparse

from flask import jsonify, request

from job_engine import db_connect


BASE_PATH = "/teltest"

RULE_ENGINE_VERSION = "1"


URL_PATTERN = re.compile(
    r"""(?ix)
    (?:
        https?://
        |
        www\.
        |
        t\.me/
        |
        telegram\.me/
    )
    [^\s<>"'\[\]{}]+
    """
)


HASHTAG_PATTERN = re.compile(
    r"(?<![\w\u200c])#([\w\u0600-\u06ff\u0750-\u077f\u200c]+)",
    re.UNICODE,
)


DEFAULT_RULES = {
    "remove_all_links": False,

    "remove_links_containing": [],

    "exclude_text_containing": [],

    "exclude_hashtags": [],

    "exclude_links_containing": [],

    "prefix_text": "",

    "suffix_text": "",

    "prefix_link": "",

    "suffix_link": "",
}


# ============================================================
# JSON
# ============================================================

def json_dump(value):

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def json_load(value, default=None):

    if default is None:
        default = {}

    if isinstance(value, dict):
        return value

    if not value:
        return default

    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else default
    except Exception:
        return default


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_scalar(value, max_length=4000):

    return str(
        value or ""
    ).strip()[:max_length]


def normalize_list(value):

    if isinstance(value, str):

        value = value.replace(
            "\r",
            "\n",
        ).split(
            "\n"
        )

    if not isinstance(
        value,
        (list, tuple),
    ):
        return []

    result = []
    seen = set()

    for item in value[:100]:

        item = str(
            item or ""
        ).strip()

        if not item:
            continue

        item = item[:300]

        key = item.casefold()

        if key in seen:
            continue

        seen.add(
            key
        )

        result.append(
            item
        )

    return result


def normalize_rules(value):

    source = json_load(
        value,
        {},
    )

    rules = dict(
        DEFAULT_RULES
    )

    rules[
        "remove_all_links"
    ] = bool(
        source.get(
            "remove_all_links",
            False,
        )
    )

    for key in (
        "remove_links_containing",
        "exclude_text_containing",
        "exclude_hashtags",
        "exclude_links_containing",
    ):

        rules[key] = normalize_list(
            source.get(
                key
            )
        )

    for key in (
        "prefix_text",
        "suffix_text",
        "prefix_link",
        "suffix_link",
    ):

        rules[key] = normalize_scalar(
            source.get(
                key
            ),
            4000,
        )

    return rules


def rules_digest(rules):

    normalized = normalize_rules(
        rules
    )

    return hashlib.sha256(
        json_dump(
            normalized
        ).encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# HASHTAGS
# ============================================================

def extract_hashtags(text):

    result = []
    seen = set()

    for match in HASHTAG_PATTERN.finditer(
        str(
            text or ""
        )
    ):

        hashtag = match.group(
            1
        ).strip(
            "_\u200c"
        )

        normalized = (
            hashtag
            .replace(
                "\u200c",
                "",
            )
            .casefold()
        )

        if (
            not hashtag
            or not normalized
            or normalized in seen
        ):
            continue

        seen.add(
            normalized
        )

        result.append(
            {
                "hashtag":
                    f"#{hashtag}",

                "normalized":
                    normalized,
            }
        )

    return result


# ============================================================
# LINKS
# ============================================================

def clean_url(value):

    value = str(
        value or ""
    ).strip()

    while (
        value
        and value[-1]
        in ".,،؛;:!?)]}»"
    ):
        value = value[:-1]

    return value


def url_domain(value):

    value = clean_url(
        value
    )

    candidate = value

    if candidate.startswith(
        "www."
    ):
        candidate = (
            "https://"
            + candidate
        )

    elif candidate.startswith(
        "t.me/"
    ):

        candidate = (
            "https://"
            + candidate
        )

    elif candidate.startswith(
        "telegram.me/"
    ):

        candidate = (
            "https://"
            + candidate
        )

    try:

        return (
            urlparse(
                candidate
            )
            .netloc
            .lower()
        )

    except Exception:

        return ""


def extract_links(text):

    result = []
    seen = set()

    for match in URL_PATTERN.finditer(
        str(
            text or ""
        )
    ):

        value = clean_url(
            match.group(0)
        )

        if not value:
            continue

        key = value.casefold()

        if key in seen:
            continue

        seen.add(
            key
        )

        result.append(
            {
                "url":
                    value,

                "domain":
                    url_domain(
                        value
                    ),

                "start":
                    match.start(),

                "end":
                    match.start()
                    + len(value),
            }
        )

    return result


# ============================================================
# APPLY RULES
# ============================================================

def contains_any(
    value,
    needles,
):

    value = str(
        value or ""
    ).casefold()

    for needle in needles:

        needle = str(
            needle or ""
        ).casefold()

        if (
            needle
            and needle in value
        ):
            return needle

    return None


def normalize_hashtag_rule(value):

    return (
        str(
            value or ""
        )
        .strip()
        .lstrip("#")
        .replace(
            "\u200c",
            "",
        )
        .casefold()
    )


def clean_processed_text(value):

    value = re.sub(
        r"[ \t]+\n",
        "\n",
        str(
            value or ""
        ),
    )

    value = re.sub(
        r"\n{3,}",
        "\n\n",
        value,
    )

    return value.strip()


def apply_content_rules(
    raw_text,
    rules,
):

    rules = normalize_rules(
        rules
    )

    raw_text = str(
        raw_text or ""
    )

    links = extract_links(
        raw_text
    )

    hashtags = extract_hashtags(
        raw_text
    )


    # --------------------------------------------------------
    # EXCLUSION
    # --------------------------------------------------------

    match = contains_any(
        raw_text,
        rules[
            "exclude_text_containing"
        ],
    )

    if match:

        return {
            "excluded":
                True,

            "reason":
                f"text:{match}",

            "processed_text":
                raw_text,

            "hashtags":
                hashtags,

            "links":
                links,
        }


    excluded_hashtags = {
        normalize_hashtag_rule(
            item
        )
        for item in rules[
            "exclude_hashtags"
        ]
        if normalize_hashtag_rule(
            item
        )
    }


    for hashtag in hashtags:

        if (
            hashtag[
                "normalized"
            ]
            in excluded_hashtags
        ):

            return {
                "excluded":
                    True,

                "reason":
                    (
                        "hashtag:"
                        + hashtag[
                            "hashtag"
                        ]
                    ),

                "processed_text":
                    raw_text,

                "hashtags":
                    hashtags,

                "links":
                    links,
            }


    for link in links:

        match = contains_any(
            link[
                "url"
            ],
            rules[
                "exclude_links_containing"
            ],
        )

        if match:

            return {
                "excluded":
                    True,

                "reason":
                    (
                        "link:"
                        + match
                    ),

                "processed_text":
                    raw_text,

                "hashtags":
                    hashtags,

                "links":
                    links,
            }


    # --------------------------------------------------------
    # TRANSFORM
    # --------------------------------------------------------

    processed = raw_text


    if rules[
        "remove_all_links"
    ]:

        processed = URL_PATTERN.sub(
            "",
            processed,
        )

    elif rules[
        "remove_links_containing"
    ]:

        needles = [
            str(
                item
            ).casefold()
            for item
            in rules[
                "remove_links_containing"
            ]
            if str(
                item
            ).strip()
        ]


        def replace_link(match):

            value = clean_url(
                match.group(0)
            )

            lower = value.casefold()

            for needle in needles:

                if (
                    needle
                    and needle in lower
                ):
                    return ""

            return match.group(0)


        processed = URL_PATTERN.sub(
            replace_link,
            processed,
        )


    processed = clean_processed_text(
        processed
    )


    parts = []


    if rules[
        "prefix_text"
    ]:

        parts.append(
            rules[
                "prefix_text"
            ]
        )


    if rules[
        "prefix_link"
    ]:

        parts.append(
            rules[
                "prefix_link"
            ]
        )


    if processed:

        parts.append(
            processed
        )


    if rules[
        "suffix_text"
    ]:

        parts.append(
            rules[
                "suffix_text"
            ]
        )


    if rules[
        "suffix_link"
    ]:

        parts.append(
            rules[
                "suffix_link"
            ]
        )


    processed = "\n".join(
        part.strip()
        for part in parts
        if str(
            part
        ).strip()
    )


    return {
        "excluded":
            False,

        "reason":
            None,

        "processed_text":
            processed,

        "hashtags":
            hashtags,

        "links":
            links,
    }


# ============================================================
# INDEX DATABASE
# ============================================================

def sync_content_index(
    conn,
    content_id,
    raw_text,
):

    hashtags = extract_hashtags(
        raw_text
    )

    links = extract_links(
        raw_text
    )


    conn.execute(
        """
        DELETE FROM content_hashtags
        WHERE content_id = ?
        """,
        (
            content_id,
        ),
    )


    for item in hashtags:

        conn.execute(
            """
            INSERT OR IGNORE INTO
                content_hashtags (
                    content_id,
                    hashtag,
                    normalized_hashtag
                )
            VALUES (
                ?, ?, ?
            )
            """,
            (
                content_id,
                item[
                    "hashtag"
                ],
                item[
                    "normalized"
                ],
            ),
        )


    conn.execute(
        """
        DELETE FROM content_links
        WHERE content_id = ?
        """,
        (
            content_id,
        ),
    )


    for item in links:

        conn.execute(
            """
            INSERT OR IGNORE INTO
                content_links (
                    content_id,
                    url,
                    domain,
                    link_text
                )
            VALUES (
                ?, ?, ?, NULL
            )
            """,
            (
                content_id,
                item[
                    "url"
                ],
                item[
                    "domain"
                ],
            ),
        )


# ============================================================
# SCHEMA
# ============================================================

def ensure_column(
    conn,
    table,
    name,
    ddl,
):

    columns = {
        row[
            "name"
        ]
        for row
        in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if name not in columns:

        conn.execute(
            f"""
            ALTER TABLE {table}
            ADD COLUMN {ddl}
            """
        )


def init_content_rules_schema():

    with closing(
        db_connect()
    ) as conn:

        ensure_column(
            conn,
            "extraction_job_items",
            "processed_text",
            "processed_text TEXT",
        )

        ensure_column(
            conn,
            "extraction_job_items",
            "excluded",
            (
                "excluded INTEGER "
                "NOT NULL DEFAULT 0"
            ),
        )

        ensure_column(
            conn,
            "extraction_job_items",
            "rule_reason",
            "rule_reason TEXT",
        )

        ensure_column(
            conn,
            "extraction_job_items",
            "rules_hash",
            "rules_hash TEXT",
        )

        ensure_column(
            conn,
            "extraction_job_items",
            "processed_at",
            "processed_at TEXT",
        )


        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS
                idx_extraction_job_items_excluded
                ON extraction_job_items(
                    extraction_job_id,
                    excluded,
                    content_id
                );

            CREATE INDEX IF NOT EXISTS
                idx_content_links_domain_v2
                ON content_links(
                    domain,
                    content_id
                );

            CREATE INDEX IF NOT EXISTS
                idx_content_hashtags_v2
                ON content_hashtags(
                    normalized_hashtag,
                    content_id
                );
            """
        )


        version_row = conn.execute(
            """
            SELECT value
            FROM schema_meta
            WHERE key =
                'content_rules_version'
            """
        ).fetchone()


        if (
            not version_row
            or version_row[
                "value"
            ]
            != RULE_ENGINE_VERSION
        ):

            rows = conn.execute(
                """
                SELECT
                    id,
                    raw_text
                FROM content_items
                """
            ).fetchall()


            for row in rows:

                sync_content_index(
                    conn,
                    row[
                        "id"
                    ],
                    row[
                        "raw_text"
                    ],
                )


            conn.execute(
                """
                INSERT INTO schema_meta (
                    key,
                    value,
                    updated_at
                )
                VALUES (
                    'content_rules_version',
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
                    RULE_ENGINE_VERSION,
                ),
            )


        conn.commit()


# ============================================================
# ROUTES
# ============================================================

def init_content_rules(
    app,
    login_required,
    api_post_required,
):

    init_content_rules_schema()


    @app.get(
        f"{BASE_PATH}/api/v2/content-rules/schema"
    )
    @login_required
    def content_rules_schema():

        return jsonify(
            ok=True,
            version=
                RULE_ENGINE_VERSION,

            defaults=
                DEFAULT_RULES,

            fields={
                "remove_all_links":
                    "boolean",

                "remove_links_containing":
                    "list",

                "exclude_text_containing":
                    "list",

                "exclude_hashtags":
                    "list",

                "exclude_links_containing":
                    "list",

                "prefix_text":
                    "text",

                "suffix_text":
                    "text",

                "prefix_link":
                    "text",

                "suffix_link":
                    "text",
            },
        )


    @app.get(
        f"{BASE_PATH}/api/v2/operations/extraction-jobs/<int:job_id>/rules"
    )
    @login_required
    def get_extraction_rules(
        job_id
    ):

        with closing(
            db_connect()
        ) as conn:

            row = conn.execute(
                """
                SELECT
                    id,
                    name,
                    rules_json
                FROM extraction_jobs
                WHERE id = ?
                """,
                (
                    job_id,
                ),
            ).fetchone()


        if not row:

            return jsonify(
                ok=False,
                error=(
                    "جاب استخراج پیدا نشد."
                ),
            ), 404


        return jsonify(
            ok=True,
            job_id=job_id,
            name=row[
                "name"
            ],
            rules=normalize_rules(
                row[
                    "rules_json"
                ]
            ),
        )


    @app.route(
        f"{BASE_PATH}/api/v2/operations/extraction-jobs/<int:job_id>/rules",
        methods=[
            "PATCH"
        ],
    )
    @api_post_required
    def save_extraction_rules(
        job_id
    ):

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        rules = normalize_rules(
            data.get(
                "rules",
                data,
            )
        )


        with closing(
            db_connect()
        ) as conn:

            exists = conn.execute(
                """
                SELECT 1
                FROM extraction_jobs
                WHERE id = ?
                """,
                (
                    job_id,
                ),
            ).fetchone()


            if not exists:

                return jsonify(
                    ok=False,
                    error=(
                        "جاب استخراج پیدا نشد."
                    ),
                ), 404


            conn.execute(
                """
                UPDATE extraction_jobs
                SET
                    rules_json = ?,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    json_dump(
                        rules
                    ),
                    job_id,
                ),
            )

            conn.commit()


        return jsonify(
            ok=True,
            job_id=job_id,
            rules=rules,
            message=(
                "قوانین استخراج ذخیره شد."
            ),
        )


    @app.post(
        f"{BASE_PATH}/api/v2/operations/extraction-jobs/<int:job_id>/rules/reapply"
    )
    @api_post_required
    def reapply_extraction_rules(
        job_id
    ):

        with closing(
            db_connect()
        ) as conn:

            job = conn.execute(
                """
                SELECT *
                FROM extraction_jobs
                WHERE id = ?
                """,
                (
                    job_id,
                ),
            ).fetchone()


            if not job:

                return jsonify(
                    ok=False,
                    error=(
                        "جاب استخراج پیدا نشد."
                    ),
                ), 404


            rules = normalize_rules(
                job[
                    "rules_json"
                ]
            )

            digest = rules_digest(
                rules
            )


            rows = conn.execute(
                """
                SELECT
                    ci.id,
                    ci.raw_text
                FROM extraction_job_items eji

                INNER JOIN content_items ci
                    ON ci.id =
                        eji.content_id

                WHERE
                    eji.extraction_job_id = ?
                """,
                (
                    job_id,
                ),
            ).fetchall()


            included = 0
            excluded = 0


            for row in rows:

                evaluation = (
                    apply_content_rules(
                        row[
                            "raw_text"
                        ],
                        rules,
                    )
                )


                is_excluded = int(
                    evaluation[
                        "excluded"
                    ]
                )


                conn.execute(
                    """
                    UPDATE extraction_job_items
                    SET
                        processed_text = ?,
                        excluded = ?,
                        rule_reason = ?,
                        rules_hash = ?,
                        processed_at =
                            CURRENT_TIMESTAMP
                    WHERE
                        extraction_job_id = ?
                        AND content_id = ?
                    """,
                    (
                        evaluation[
                            "processed_text"
                        ],
                        is_excluded,
                        evaluation[
                            "reason"
                        ],
                        digest,
                        job_id,
                        row[
                            "id"
                        ],
                    ),
                )


                conn.execute(
                    """
                    UPDATE content_items
                    SET
                        processed_text = ?,
                        updated_at =
                            CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        evaluation[
                            "processed_text"
                        ],
                        row[
                            "id"
                        ],
                    ),
                )


                sync_content_index(
                    conn,
                    row[
                        "id"
                    ],
                    row[
                        "raw_text"
                    ],
                )


                if is_excluded:
                    excluded += 1
                else:
                    included += 1


            #
            # آیتم‌های انتقال‌نشده‌ای که حالا Excluded شده‌اند
            # از صف فعلی پاک شوند. آیتم منتقل‌شده تاریخی حفظ می‌شود.
            #
            conn.execute(
                """
                DELETE FROM transfer_job_items

                WHERE
                    status <> 'transferred'

                    AND transfer_job_id IN (
                        SELECT id
                        FROM transfer_jobs
                        WHERE
                            json_extract(
                                selector_json,
                                '$.extraction_job_id'
                            ) = ?
                    )

                    AND content_id IN (
                        SELECT content_id
                        FROM extraction_job_items
                        WHERE
                            extraction_job_id = ?
                            AND excluded = 1
                    )
                """,
                (
                    job_id,
                    job_id,
                ),
            )


            conn.commit()


        return jsonify(
            ok=True,
            job_id=job_id,
            included=included,
            excluded=excluded,
            total=(
                included
                + excluded
            ),
            message=(
                "قوانین روی محتوای موجود "
                "دوباره اعمال شد."
            ),
        )


    @app.get(
        f"{BASE_PATH}/api/v2/operations/transfer-destinations/<int:destination_id>/rules"
    )
    @login_required
    def get_destination_rules(
        destination_id
    ):

        with closing(
            db_connect()
        ) as conn:

            row = conn.execute(
                """
                SELECT
                    id,
                    provider_code,
                    destination_ref,
                    rules_json
                FROM transfer_destinations
                WHERE id = ?
                """,
                (
                    destination_id,
                ),
            ).fetchone()


        if not row:

            return jsonify(
                ok=False,
                error=(
                    "مقصد انتقال پیدا نشد."
                ),
            ), 404


        return jsonify(
            ok=True,
            destination_id=
                destination_id,

            provider_code=
                row[
                    "provider_code"
                ],

            destination_ref=
                row[
                    "destination_ref"
                ],

            rules=normalize_rules(
                row[
                    "rules_json"
                ]
            ),
        )


    @app.route(
        f"{BASE_PATH}/api/v2/operations/transfer-destinations/<int:destination_id>/rules",
        methods=[
            "PATCH"
        ],
    )
    @api_post_required
    def save_destination_rules(
        destination_id
    ):

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        rules = normalize_rules(
            data.get(
                "rules",
                data,
            )
        )


        with closing(
            db_connect()
        ) as conn:

            exists = conn.execute(
                """
                SELECT 1
                FROM transfer_destinations
                WHERE id = ?
                """,
                (
                    destination_id,
                ),
            ).fetchone()


            if not exists:

                return jsonify(
                    ok=False,
                    error=(
                        "مقصد انتقال پیدا نشد."
                    ),
                ), 404


            conn.execute(
                """
                UPDATE transfer_destinations
                SET
                    rules_json = ?,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    json_dump(
                        rules
                    ),
                    destination_id,
                ),
            )

            conn.commit()


        return jsonify(
            ok=True,
            destination_id=
                destination_id,
            rules=rules,
            message=(
                "قوانین مقصد ذخیره شد."
            ),
        )
