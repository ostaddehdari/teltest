import json

from contextlib import closing

from flask import jsonify, request

from job_engine import db_connect

from content_library_v2 import (
    FILTER_KEYS,
    build_search_sql,
    sanitize_saved_filters,
)


BASE_PATH = "/teltest"

SELECTOR_VERSION = "1"

MAX_MANUAL_ITEMS = 5000
MAX_SELECTOR_ITEMS = 50000


SELECTOR_TYPES = {
    "extraction_job": {
        "label": "جاب استخراج",
    },

    "source": {
        "label": "منبع",
    },

    "hashtag": {
        "label": "هشتگ",
    },

    "search": {
        "label": "جستجو / فیلتر",
    },

    "saved_search": {
        "label": "جستجوی ذخیره‌شده",
    },

    "manual": {
        "label": "انتخاب دستی",
    },
}


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
        result = json.loads(value)

        return (
            result
            if isinstance(result, dict)
            else default
        )

    except Exception:
        return default


def normalize_hashtag(value):

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


def normalize_content_ids(value):

    if isinstance(value, str):

        value = (
            value
            .replace("\n", ",")
            .split(",")
        )


    if not isinstance(
        value,
        (list, tuple),
    ):
        return []


    result = []
    seen = set()


    for item in value:

        try:
            item = int(item)
        except (
            TypeError,
            ValueError,
        ):
            continue

        if item <= 0:
            continue

        if item in seen:
            continue

        seen.add(item)
        result.append(item)

        if (
            len(result)
            >= MAX_MANUAL_ITEMS
        ):
            break


    return result


def normalize_search_filters(value):

    value = sanitize_saved_filters(
        value
    )


    defaults = {
        "q": "",
        "connector": "",
        "source_key": "",
        "hashtag": "",
        "content_type": "",
        "media": "",
        "has_link": "",
        "from_jalali": "",
        "to_jalali": "",
        "extraction_job_id": None,
        "sort": "newest",
    }


    defaults.update(
        value
    )


    return defaults


def selector_label(
    selector_type,
    selector,
):

    selector = (
        selector
        if isinstance(selector, dict)
        else {}
    )


    if selector_type == "extraction_job":

        return (
            "جاب استخراج "
            f"#{selector.get('extraction_job_id')}"
        )


    if selector_type == "source":

        return (
            "منبع "
            + str(
                selector.get(
                    "source_title"
                )
                or selector.get(
                    "source_key"
                )
                or ""
            )
        ).strip()


    if selector_type == "hashtag":

        hashtag = str(
            selector.get(
                "hashtag"
            )
            or ""
        )

        if (
            hashtag
            and not hashtag.startswith("#")
        ):
            hashtag = (
                "#"
                + hashtag
            )

        return (
            "هشتگ "
            + hashtag
        ).strip()


    if selector_type == "search":

        filters = selector.get(
            "filters"
        ) or {}

        query = str(
            filters.get(
                "q"
            )
            or ""
        ).strip()

        return (
            "جستجو"
            + (
                f": {query}"
                if query
                else " با فیلتر"
            )
        )


    if selector_type == "saved_search":

        return (
            "جستجوی ذخیره‌شده "
            f"#{selector.get('saved_search_id')}"
        )


    if selector_type == "manual":

        return (
            "انتخاب دستی "
            f"({len(selector.get('content_ids') or [])} مورد)"
        )


    return selector_type


def validate_selector_payload(
    data,
    conn,
):

    if not isinstance(
        data,
        dict,
    ):
        raise ValueError(
            "ساختار انتخاب محتوا معتبر نیست."
        )


    selector_type = str(
        data.get(
            "selector_type"
        )
        or ""
    ).strip()


    raw_selector = data.get(
        "selector"
    )


    if not isinstance(
        raw_selector,
        dict,
    ):
        raw_selector = {}


    #
    # Backward compatibility
    #
    if not selector_type:

        if data.get(
            "extraction_job_id"
        ):

            selector_type = (
                "extraction_job"
            )

            raw_selector = {
                "extraction_job_id":
                    data.get(
                        "extraction_job_id"
                    ),
            }


    if selector_type not in SELECTOR_TYPES:

        raise ValueError(
            "نوع انتخاب محتوای انتقال معتبر نیست."
        )


    if selector_type == "extraction_job":

        try:
            job_id = int(
                raw_selector.get(
                    "extraction_job_id"
                )
                or data.get(
                    "extraction_job_id"
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            raise ValueError(
                "جاب استخراج مبدا انتخاب نشده است."
            )


        exists = conn.execute(
            """
            SELECT
                id,
                name
            FROM extraction_jobs
            WHERE id=?
            """,
            (
                job_id,
            ),
        ).fetchone()


        if not exists:

            raise ValueError(
                "جاب استخراج مبدا پیدا نشد."
            )


        return (
            selector_type,
            {
                "extraction_job_id":
                    job_id,

                "label":
                    exists[
                        "name"
                    ],
            },
        )


    if selector_type == "source":

        source_key = str(
            raw_selector.get(
                "source_key"
            )
            or ""
        ).strip()


        connector = str(
            raw_selector.get(
                "connector"
            )
            or "telegram"
        ).strip()


        if not source_key:

            raise ValueError(
                "منبع محتوا انتخاب نشده است."
            )


        source = conn.execute(
            """
            SELECT
                connector_code,
                source_key,
                MAX(source_title)
                    AS source_title,
                MAX(source_ref)
                    AS source_ref
            FROM content_items
            WHERE
                connector_code=?
                AND source_key=?
            GROUP BY
                connector_code,
                source_key
            """,
            (
                connector,
                source_key,
            ),
        ).fetchone()


        if not source:

            raise ValueError(
                "منبع انتخاب‌شده محتوایی ندارد."
            )


        return (
            selector_type,
            {
                "connector":
                    connector,

                "source_key":
                    source_key,

                "source_title":
                    source[
                        "source_title"
                    ],

                "source_ref":
                    source[
                        "source_ref"
                    ],
            },
        )


    if selector_type == "hashtag":

        hashtag = normalize_hashtag(
            raw_selector.get(
                "hashtag"
            )
        )


        if not hashtag:

            raise ValueError(
                "هشتگ وارد نشده است."
            )


        return (
            selector_type,
            {
                "hashtag":
                    hashtag,
            },
        )


    if selector_type == "search":

        filters = normalize_search_filters(
            raw_selector.get(
                "filters"
            )
        )


        meaningful = [
            value
            for key, value
            in filters.items()
            if (
                key != "sort"
                and value not in (
                    "",
                    None,
                    False,
                )
            )
        ]


        if not meaningful:

            raise ValueError(
                "حداقل یک عبارت یا فیلتر جستجو انتخاب کنید."
            )


        return (
            selector_type,
            {
                "filters":
                    filters,
            },
        )


    if selector_type == "saved_search":

        try:
            search_id = int(
                raw_selector.get(
                    "saved_search_id"
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            raise ValueError(
                "جستجوی ذخیره‌شده انتخاب نشده است."
            )


        search = conn.execute(
            """
            SELECT
                id,
                name,
                filters_json
            FROM saved_searches
            WHERE id=?
            """,
            (
                search_id,
            ),
        ).fetchone()


        if not search:

            raise ValueError(
                "جستجوی ذخیره‌شده پیدا نشد."
            )


        return (
            selector_type,
            {
                "saved_search_id":
                    search_id,

                "name":
                    search[
                        "name"
                    ],
            },
        )


    if selector_type == "manual":

        content_ids = normalize_content_ids(
            raw_selector.get(
                "content_ids"
            )
        )


        if not content_ids:

            raise ValueError(
                "هیچ محتوایی انتخاب نشده است."
            )


        placeholders = ",".join(
            "?"
            for _ in content_ids
        )


        count = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM content_items
            WHERE id IN(
                {placeholders}
            )
            """,
            content_ids,
        ).fetchone()[0]


        if count != len(
            content_ids
        ):

            raise ValueError(
                "بعضی محتواهای انتخاب‌شده دیگر وجود ندارند."
            )


        return (
            selector_type,
            {
                "content_ids":
                    content_ids,
            },
        )


    raise ValueError(
        "Selector معتبر نیست."
    )


def _eligible_clause():

    return """
        EXISTS(
            SELECT 1
            FROM extraction_job_items eji
            WHERE
                eji.content_id=ci.id
                AND COALESCE(
                    eji.excluded,
                    0
                )=0
        )
    """


def selector_content_ids(
    conn,
    selector_type,
    selector,
):

    selector = (
        selector
        if isinstance(selector, dict)
        else {}
    )


    if selector_type == "extraction_job":

        rows = conn.execute(
            """
            SELECT
                eji.content_id
            FROM extraction_job_items eji
            WHERE
                eji.extraction_job_id=?
                AND COALESCE(
                    eji.excluded,
                    0
                )=0
            ORDER BY
                eji.content_id ASC
            LIMIT ?
            """,
            (
                selector[
                    "extraction_job_id"
                ],
                MAX_SELECTOR_ITEMS,
            ),
        ).fetchall()


        return [
            row[
                "content_id"
            ]
            for row in rows
        ]


    if selector_type == "source":

        rows = conn.execute(
            f"""
            SELECT ci.id
            FROM content_items ci
            WHERE
                ci.connector_code=?
                AND ci.source_key=?
                AND {_eligible_clause()}
            ORDER BY
                datetime(
                    ci.published_at
                ) ASC,
                ci.id ASC
            LIMIT ?
            """,
            (
                selector.get(
                    "connector",
                    "telegram",
                ),
                selector[
                    "source_key"
                ],
                MAX_SELECTOR_ITEMS,
            ),
        ).fetchall()


        return [
            row["id"]
            for row in rows
        ]


    if selector_type == "hashtag":

        rows = conn.execute(
            f"""
            SELECT DISTINCT
                ci.id
            FROM content_items ci

            INNER JOIN content_hashtags ch
                ON ch.content_id=
                    ci.id

            WHERE
                ch.normalized_hashtag=?
                AND {_eligible_clause()}

            ORDER BY
                ci.id ASC

            LIMIT ?
            """,
            (
                normalize_hashtag(
                    selector[
                        "hashtag"
                    ]
                ),
                MAX_SELECTOR_ITEMS,
            ),
        ).fetchall()


        return [
            row["id"]
            for row in rows
        ]


    if selector_type == "search":

        filters = normalize_search_filters(
            selector.get(
                "filters"
            )
        )


        query = build_search_sql(
            filters
        )


        eligible = (
            _eligible_clause()
        )


        extra_where = (
            f"{query['where']} AND {eligible}"
            if query[
                "where"
            ]
            else f"WHERE {eligible}"
        )


        rows = conn.execute(
            f"""
            SELECT DISTINCT
                ci.id

            FROM content_items ci

            {query["joins"]}

            {extra_where}

            ORDER BY
                ci.id ASC

            LIMIT ?
            """,
            [
                *query[
                    "params"
                ],
                MAX_SELECTOR_ITEMS,
            ],
        ).fetchall()


        return [
            row["id"]
            for row in rows
        ]


    if selector_type == "saved_search":

        search = conn.execute(
            """
            SELECT filters_json
            FROM saved_searches
            WHERE id=?
            """,
            (
                selector[
                    "saved_search_id"
                ],
            ),
        ).fetchone()


        if not search:

            return []


        return selector_content_ids(
            conn,
            "search",
            {
                "filters":
                    json_load(
                        search[
                            "filters_json"
                        ],
                        {},
                    ),
            },
        )


    if selector_type == "manual":

        ids = normalize_content_ids(
            selector.get(
                "content_ids"
            )
        )


        if not ids:
            return []


        placeholders = ",".join(
            "?"
            for _ in ids
        )


        eligible = set(
            row["id"]
            for row in conn.execute(
                f"""
                SELECT ci.id
                FROM content_items ci
                WHERE
                    ci.id IN(
                        {placeholders}
                    )
                    AND {_eligible_clause()}
                """,
                ids,
            ).fetchall()
        )


        return [
            item
            for item in ids
            if item in eligible
        ]


    return []


def content_source_context(
    conn,
    content_id,
):

    #
    # Stage 12 hotfix:
    #
    # Do not reference outer content_items aliases from
    # ORDER BY inside a correlated scalar subquery.
    #
    # First resolve the content source, then resolve the
    # Telegram account in a separate query.
    #

    content = conn.execute(
        """
        SELECT
            id AS content_id,
            connector_code,
            source_key,
            source_ref,
            source_title

        FROM content_items

        WHERE id=?
        """,
        (
            int(content_id),
        ),
    ).fetchone()


    if not content:
        return None


    item = dict(
        content
    )


    account = conn.execute(
        """
        SELECT
            ej.source_account_id

        FROM extraction_job_items eji

        INNER JOIN extraction_jobs ej
            ON ej.id=
                eji.extraction_job_id

        WHERE
            eji.content_id=?

            AND ej.source_account_id
                IS NOT NULL

            AND (
                ej.source_key=?
                OR ej.source_key IS NULL
                OR ej.source_key=''
            )

        ORDER BY
            CASE
                WHEN ej.source_key=?
                THEN 0
                ELSE 1
            END,
            ej.id DESC

        LIMIT 1
        """,
        (
            int(content_id),
            item.get(
                "source_key"
            ),
            item.get(
                "source_key"
            ),
        ),
    ).fetchone()


    #
    # Compatibility fallback for old migrated records where
    # source_key may not have been populated consistently.
    #
    if not account:

        account = conn.execute(
            """
            SELECT
                ej.source_account_id

            FROM extraction_job_items eji

            INNER JOIN extraction_jobs ej
                ON ej.id=
                    eji.extraction_job_id

            WHERE
                eji.content_id=?

                AND ej.source_account_id
                    IS NOT NULL

            ORDER BY
                ej.id DESC

            LIMIT 1
            """,
            (
                int(content_id),
            ),
        ).fetchone()


    item[
        "source_account_id"
    ] = (
        account[
            "source_account_id"
        ]
        if account
        else None
    )


    return item


def selector_preview(
    conn,
    selector_type,
    selector,
):

    ids = selector_content_ids(
        conn,
        selector_type,
        selector,
    )


    source_count = 0


    if ids:

        placeholders = ",".join(
            "?"
            for _ in ids
        )


        source_count = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT
                    connector_code,
                    source_key

                FROM content_items

                WHERE id IN(
                    {placeholders}
                )

                GROUP BY
                    connector_code,
                    source_key
            )
            """,
            ids,
        ).fetchone()[0]


    return {
        "count":
            len(ids),

        "source_count":
            source_count,

        "label":
            selector_label(
                selector_type,
                selector,
            ),

        "sample_ids":
            ids[:20],
    }


def init_transfer_selector_v2(
    app,
    login_required,
    api_post_required,
):

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            INSERT INTO schema_meta(
                key,
                value,
                updated_at
            )
            VALUES(
                'transfer_selector_version',
                ?,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(key)
            DO UPDATE SET
                value=excluded.value,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                SELECTOR_VERSION,
            ),
        )


        conn.commit()


    @app.get(
        f"{BASE_PATH}/api/v2/transfer-selectors/meta"
    )
    @login_required
    def transfer_selector_meta():

        with closing(
            db_connect()
        ) as conn:

            sources = conn.execute(
                """
                SELECT
                    connector_code,
                    source_key,
                    MAX(source_title)
                        AS source_title,
                    MAX(source_ref)
                        AS source_ref,
                    COUNT(*) AS count

                FROM content_items

                GROUP BY
                    connector_code,
                    source_key

                ORDER BY
                    count DESC,
                    source_title

                LIMIT 250
                """
            ).fetchall()


            hashtags = conn.execute(
                """
                SELECT
                    MIN(hashtag)
                        AS hashtag,

                    normalized_hashtag,

                    COUNT(*)
                        AS count

                FROM content_hashtags

                GROUP BY
                    normalized_hashtag

                ORDER BY
                    count DESC,
                    normalized_hashtag

                LIMIT 200
                """
            ).fetchall()


            searches = conn.execute(
                """
                SELECT
                    id,
                    name,
                    filters_json

                FROM saved_searches

                ORDER BY
                    updated_at DESC,
                    id DESC

                LIMIT 100
                """
            ).fetchall()


        return jsonify(
            ok=True,

            version=
                SELECTOR_VERSION,

            selector_types=[
                {
                    "code":
                        code,

                    "label":
                        value[
                            "label"
                        ],
                }
                for code, value
                in SELECTOR_TYPES.items()
            ],

            sources=[
                dict(row)
                for row in sources
            ],

            hashtags=[
                dict(row)
                for row in hashtags
            ],

            saved_searches=[
                {
                    "id":
                        row["id"],

                    "name":
                        row["name"],

                    "filters":
                        json_load(
                            row[
                                "filters_json"
                            ],
                            {},
                        ),
                }
                for row in searches
            ],
        )


    @app.post(
        f"{BASE_PATH}/api/v2/transfer-selectors/preview"
    )
    @api_post_required
    def transfer_selector_preview():

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )


        with closing(
            db_connect()
        ) as conn:

            try:

                selector_type, selector = (
                    validate_selector_payload(
                        data,
                        conn,
                    )
                )


                preview = selector_preview(
                    conn,
                    selector_type,
                    selector,
                )


            except ValueError as exc:

                return jsonify(
                    ok=False,
                    error=str(exc),
                ), 400


        return jsonify(
            ok=True,
            selector_type=
                selector_type,
            selector=
                selector,
            preview=
                preview,
        )
