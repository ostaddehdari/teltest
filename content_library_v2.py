import json
import math
import re

from contextlib import closing
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import jsonify, request

from job_engine import db_connect
from telegram_extractor_v2 import parse_persian_date


BASE_PATH = "/teltest"

LIBRARY_VERSION = "1"

DEFAULT_PAGE_SIZE = 24
MAX_PAGE_SIZE = 100


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
        result = json.loads(value)

        if isinstance(
            result,
            dict,
        ):
            return result

        return default

    except Exception:
        return default


# ============================================================
# HELPERS
# ============================================================

def bounded_int(
    value,
    default,
    minimum,
    maximum,
):

    try:
        value = int(value)
    except (
        TypeError,
        ValueError,
    ):
        value = default

    return max(
        minimum,
        min(
            maximum,
            value,
        ),
    )


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


def fts_query(value):

    value = str(
        value or ""
    ).strip()

    if not value:
        return None

    tokens = re.findall(
        r"[\w\u0600-\u06ff\u0750-\u077f\u200c]+",
        value,
        flags=re.UNICODE,
    )

    result = []

    seen = set()

    for token in tokens[:16]:

        token = token.strip()

        if not token:
            continue

        key = token.casefold()

        if key in seen:
            continue

        seen.add(key)

        token = token.replace(
            '"',
            '""',
        )

        result.append(
            f'"{token}"'
        )

    if not result:
        return None

    return " AND ".join(
        result
    )


def parse_from_date(value):

    value = str(
        value or ""
    ).strip()

    if not value:
        return None

    return parse_persian_date(
        value
    )


def parse_to_date(value):

    value = str(
        value or ""
    ).strip()

    if not value:
        return None

    start = datetime.fromisoformat(
        parse_persian_date(
            value
        )
    )

    return (
        start
        + timedelta(days=1)
    ).isoformat()


def public_post_url(
    source_ref,
    source_key,
    external_id,
):

    source = str(
        source_ref or ""
    ).strip()
    if source.startswith("https://eitaa.com/"):
        channel = source.split("eitaa.com/", 1)[1].strip("/").split("/")[0]
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,63}", channel) and str(external_id or "").isdigit():
            return f"https://eitaa.com/{channel}/{external_id}"

    message_id = str(
        external_id or ""
    ).strip()

    username = None


    if source.startswith("@"):

        username = (
            source[1:]
            .split("/")[0]
        )


    else:

        match = re.search(
            r"(?:https?://)?t\.me/(?!\+|joinchat/)([A-Za-z0-9_]+)",
            source,
        )

        if match:
            username = match.group(1)


    if (
        username
        and message_id.isdigit()
    ):

        return (
            f"https://t.me/"
            f"{username}/"
            f"{message_id}"
        )


    key = str(
        source_key or ""
    )


    if (
        key.startswith("-100")
        and message_id.isdigit()
    ):

        return (
            "https://t.me/c/"
            + key[4:]
            + "/"
            + message_id
        )


    return None


# ============================================================
# SCHEMA / FTS5
# ============================================================

def init_content_library_schema():

    with closing(
        db_connect()
    ) as conn:

        #
        # Fail fast if SQLite does not support FTS5.
        #
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS
                content_fts
            USING fts5(
                raw_text,
                processed_text,
                source_title,
                external_id,
                content='content_items',
                content_rowid='id',
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )


        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS saved_searches (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                filters_json TEXT NOT NULL
                    DEFAULT '{}',

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );


            CREATE INDEX IF NOT EXISTS
                idx_saved_searches_name
                ON saved_searches(
                    name COLLATE NOCASE
                );


            CREATE TRIGGER IF NOT EXISTS
                content_fts_insert

            AFTER INSERT ON content_items

            BEGIN

                INSERT INTO content_fts(
                    rowid,
                    raw_text,
                    processed_text,
                    source_title,
                    external_id
                )
                VALUES(
                    new.id,
                    COALESCE(new.raw_text, ''),
                    COALESCE(new.processed_text, ''),
                    COALESCE(new.source_title, ''),
                    COALESCE(new.external_id, '')
                );

            END;


            CREATE TRIGGER IF NOT EXISTS
                content_fts_delete

            AFTER DELETE ON content_items

            BEGIN

                INSERT INTO content_fts(
                    content_fts,
                    rowid,
                    raw_text,
                    processed_text,
                    source_title,
                    external_id
                )
                VALUES(
                    'delete',
                    old.id,
                    COALESCE(old.raw_text, ''),
                    COALESCE(old.processed_text, ''),
                    COALESCE(old.source_title, ''),
                    COALESCE(old.external_id, '')
                );

            END;


            CREATE TRIGGER IF NOT EXISTS
                content_fts_update

            AFTER UPDATE OF
                raw_text,
                processed_text,
                source_title,
                external_id

            ON content_items

            BEGIN

                INSERT INTO content_fts(
                    content_fts,
                    rowid,
                    raw_text,
                    processed_text,
                    source_title,
                    external_id
                )
                VALUES(
                    'delete',
                    old.id,
                    COALESCE(old.raw_text, ''),
                    COALESCE(old.processed_text, ''),
                    COALESCE(old.source_title, ''),
                    COALESCE(old.external_id, '')
                );


                INSERT INTO content_fts(
                    rowid,
                    raw_text,
                    processed_text,
                    source_title,
                    external_id
                )
                VALUES(
                    new.id,
                    COALESCE(new.raw_text, ''),
                    COALESCE(new.processed_text, ''),
                    COALESCE(new.source_title, ''),
                    COALESCE(new.external_id, '')
                );

            END;
            """
        )


        version = conn.execute(
            """
            SELECT value
            FROM schema_meta
            WHERE key =
                'content_library_version'
            """
        ).fetchone()


        if (
            not version
            or version["value"]
            != LIBRARY_VERSION
        ):

            conn.execute(
                """
                INSERT INTO content_fts(
                    content_fts
                )
                VALUES(
                    'rebuild'
                )
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
                    'content_library_version',
                    ?,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT(key)
                DO UPDATE SET
                    value=excluded.value,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    LIBRARY_VERSION,
                ),
            )


        conn.commit()


# ============================================================
# SERIALIZATION
# ============================================================

def content_hashtags(
    conn,
    content_id,
):

    return [
        row["hashtag"]

        for row in conn.execute(
            """
            SELECT hashtag
            FROM content_hashtags
            WHERE content_id=?
            ORDER BY normalized_hashtag
            """,
            (
                content_id,
            ),
        ).fetchall()
    ]


def content_links(
    conn,
    content_id,
):

    return [
        {
            "url":
                row["url"],

            "domain":
                row["domain"],

            "link_text":
                row["link_text"],
        }

        for row in conn.execute(
            """
            SELECT
                url,
                domain,
                link_text
            FROM content_links
            WHERE content_id=?
            ORDER BY id
            """,
            (
                content_id,
            ),
        ).fetchall()
    ]


def content_payload(
    conn,
    row,
):

    item = dict(
        row
    )


    item["hashtags"] = (
        content_hashtags(
            conn,
            item["id"],
        )
    )


    item["links"] = (
        content_links(
            conn,
            item["id"],
        )
    )


    item["media"] = json_load(
        item.pop(
            "media_json",
            "[]",
        ),
        {},
    )


    item["original_url"] = (
        public_post_url(
            item.get(
                "source_ref"
            ),
            item.get(
                "source_key"
            ),
            item.get(
                "external_id"
            ),
        )
    )


    item["download_url"] = (
        f"{BASE_PATH}/api/v2/"
        f"content-items/"
        f"{item['id']}/download"
    )


    return item


# ============================================================
# FILTER BUILDING
# ============================================================

FILTER_KEYS = {
    "q",
    "connector",
    "source_key",
    "hashtag",
    "content_type",
    "media",
    "has_link",
    "from_jalali",
    "to_jalali",
    "extraction_job_id",
    "sort",
}


def sanitize_saved_filters(
    value,
):

    if not isinstance(
        value,
        dict,
    ):
        return {}

    result = {}

    for key in FILTER_KEYS:

        if key not in value:
            continue

        item = value[key]

        if item is None:
            continue

        if isinstance(
            item,
            (
                str,
                int,
                float,
                bool,
            ),
        ):

            result[key] = item

    return result


def search_arguments():

    result = {
        "q":
            str(
                request.args.get(
                    "q"
                )
                or ""
            ).strip(),

        "connector":
            str(
                request.args.get(
                    "connector"
                )
                or ""
            ).strip(),

        "source_key":
            str(
                request.args.get(
                    "source_key"
                )
                or ""
            ).strip(),

        "hashtag":
            str(
                request.args.get(
                    "hashtag"
                )
                or ""
            ).strip(),

        "content_type":
            str(
                request.args.get(
                    "content_type"
                )
                or ""
            ).strip(),

        "media":
            str(
                request.args.get(
                    "media"
                )
                or ""
            ).strip(),

        "has_link":
            str(
                request.args.get(
                    "has_link"
                )
                or ""
            ).strip(),

        "from_jalali":
            str(
                request.args.get(
                    "from_jalali"
                )
                or ""
            ).strip(),

        "to_jalali":
            str(
                request.args.get(
                    "to_jalali"
                )
                or ""
            ).strip(),

        "sort":
            str(
                request.args.get(
                    "sort"
                )
                or "newest"
            ).strip(),

        "extraction_job_id":
            request.args.get(
                "extraction_job_id",
                type=int,
            ),
    }


    result["page"] = bounded_int(
        request.args.get(
            "page"
        ),
        1,
        1,
        1000000,
    )


    result["per_page"] = bounded_int(
        request.args.get(
            "per_page"
        ),
        DEFAULT_PAGE_SIZE,
        6,
        MAX_PAGE_SIZE,
    )


    return result


def build_search_sql(
    filters,
):

    joins = []

    where = []

    params = []


    search = fts_query(
        filters[
            "q"
        ]
    )


    if search:

        joins.append(
            """
            INNER JOIN content_fts
                ON content_fts.rowid =
                    ci.id
            """
        )

        where.append(
            "content_fts MATCH ?"
        )

        params.append(
            search
        )


    connector = filters[
        "connector"
    ]


    if connector:

        where.append(
            "ci.connector_code = ?"
        )

        params.append(
            connector
        )


    source_key = filters[
        "source_key"
    ]


    if source_key:

        where.append(
            "ci.source_key = ?"
        )

        params.append(
            source_key
        )


    hashtag = normalize_hashtag(
        filters[
            "hashtag"
        ]
    )


    if hashtag:

        where.append(
            """
            EXISTS(
                SELECT 1
                FROM content_hashtags ch
                WHERE
                    ch.content_id=ci.id
                    AND ch.normalized_hashtag=?
            )
            """
        )

        params.append(
            hashtag
        )


    content_type = filters[
        "content_type"
    ]


    if content_type:

        where.append(
            "ci.content_type = ?"
        )

        params.append(
            content_type
        )


    media = filters[
        "media"
    ]


    if media == "yes":

        where.append(
            "ci.content_type <> 'text'"
        )


    elif media == "no":

        where.append(
            "ci.content_type = 'text'"
        )


    has_link = filters[
        "has_link"
    ]


    if has_link == "yes":

        where.append(
            """
            EXISTS(
                SELECT 1
                FROM content_links cl
                WHERE cl.content_id=ci.id
            )
            """
        )


    elif has_link == "no":

        where.append(
            """
            NOT EXISTS(
                SELECT 1
                FROM content_links cl
                WHERE cl.content_id=ci.id
            )
            """
        )


    if filters[
        "from_jalali"
    ]:

        where.append(
            """
            datetime(ci.published_at)
                >= datetime(?)
            """
        )

        params.append(
            parse_from_date(
                filters[
                    "from_jalali"
                ]
            )
        )


    if filters[
        "to_jalali"
    ]:

        where.append(
            """
            datetime(ci.published_at)
                < datetime(?)
            """
        )

        params.append(
            parse_to_date(
                filters[
                    "to_jalali"
                ]
            )
        )


    extraction_job_id = filters[
        "extraction_job_id"
    ]


    if extraction_job_id:

        where.append(
            """
            EXISTS(
                SELECT 1
                FROM extraction_job_items eji
                WHERE
                    eji.content_id=ci.id
                    AND eji.extraction_job_id=?
                    AND COALESCE(
                        eji.excluded,
                        0
                    )=0
            )
            """
        )

        params.append(
            extraction_job_id
        )


    return {
        "joins":
            "\n".join(
                joins
            ),

        "where":
            (
                "WHERE "
                + " AND ".join(
                    where
                )
                if where
                else ""
            ),

        "params":
            params,

        "search":
            search,
    }


# ============================================================
# API
# ============================================================

def init_content_library_v2(
    app,
    login_required,
    api_post_required,
):

    init_content_library_schema()


    @app.get(
        f"{BASE_PATH}/api/v2/content-library/meta"
    )
    @login_required
    def content_library_meta():

        with closing(
            db_connect()
        ) as conn:

            total = conn.execute(
                """
                SELECT COUNT(*)
                FROM content_items
                """
            ).fetchone()[0]


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
                    COUNT(*) AS count
                FROM content_hashtags
                GROUP BY
                    normalized_hashtag
                ORDER BY
                    count DESC,
                    normalized_hashtag
                LIMIT 150
                """
            ).fetchall()


            types = conn.execute(
                """
                SELECT
                    content_type,
                    COUNT(*) AS count
                FROM content_items
                GROUP BY content_type
                ORDER BY
                    count DESC,
                    content_type
                """
            ).fetchall()


            connectors = conn.execute(
                """
                SELECT
                    sc.code,
                    sc.name,
                    COUNT(ci.id)
                        AS count
                FROM source_connectors sc
                LEFT JOIN content_items ci
                    ON ci.connector_code=
                        sc.code
                GROUP BY
                    sc.code,
                    sc.name,
                    sc.position
                ORDER BY
                    sc.position,
                    sc.name
                """
            ).fetchall()


        return jsonify(
            ok=True,
            version=
                LIBRARY_VERSION,
            total=
                total,
            sources=[
                dict(row)
                for row in sources
            ],
            hashtags=[
                dict(row)
                for row in hashtags
            ],
            types=[
                dict(row)
                for row in types
            ],
            connectors=[
                dict(row)
                for row in connectors
            ],
        )


    @app.get(
        f"{BASE_PATH}/api/v2/content-library/search"
    )
    @login_required
    def content_library_search():

        try:

            filters = search_arguments()

            query = build_search_sql(
                filters
            )


        except ValueError as exc:

            return jsonify(
                ok=False,
                error=str(exc),
            ), 400


        page = filters[
            "page"
        ]

        per_page = filters[
            "per_page"
        ]

        offset = (
            page - 1
        ) * per_page


        sort = filters[
            "sort"
        ]


        if sort == "oldest":

            order_sql = (
                """
                ORDER BY
                    datetime(
                        ci.published_at
                    ) ASC,
                    ci.id ASC
                """
            )


        elif (
            sort == "relevance"
            and query[
                "search"
            ]
        ):

            order_sql = (
                """
                ORDER BY
                    bm25(content_fts) ASC,
                    ci.id DESC
                """
            )


        else:

            order_sql = (
                """
                ORDER BY
                    datetime(
                        ci.published_at
                    ) DESC,
                    ci.id DESC
                """
            )


        with closing(
            db_connect()
        ) as conn:

            total = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM content_items ci

                {query["joins"]}

                {query["where"]}
                """,
                query[
                    "params"
                ],
            ).fetchone()[0]


            rows = conn.execute(
                f"""
                SELECT
                    ci.id,
                    ci.connector_code,
                    ci.source_key,
                    ci.source_ref,
                    ci.source_title,
                    ci.external_id,
                    ci.published_at,
                    ci.content_type,
                    ci.raw_text,
                    ci.processed_text,
                    ci.media_json,
                    ci.created_at,
                    ci.updated_at

                FROM content_items ci

                {query["joins"]}

                {query["where"]}

                {order_sql}

                LIMIT ?
                OFFSET ?
                """,
                [
                    *query[
                        "params"
                    ],
                    per_page,
                    offset,
                ],
            ).fetchall()


            type_rows = conn.execute(
                f"""
                SELECT
                    ci.content_type,
                    COUNT(*) AS count

                FROM content_items ci

                {query["joins"]}

                {query["where"]}

                GROUP BY
                    ci.content_type
                """,
                query[
                    "params"
                ],
            ).fetchall()


            items = [
                content_payload(
                    conn,
                    row,
                )
                for row in rows
            ]


        pages = max(
            1,
            math.ceil(
                total
                / per_page
            ),
        )


        return jsonify(
            ok=True,
            filters={
                key:
                    filters[key]
                for key
                in FILTER_KEYS
            },
            pagination={
                "page":
                    page,
                "per_page":
                    per_page,
                "total":
                    total,
                "pages":
                    pages,
                "has_previous":
                    page > 1,
                "has_next":
                    page < pages,
            },
            facets={
                "content_types": [
                    dict(row)
                    for row
                    in type_rows
                ],
            },
            items=
                items,
        )


    @app.get(
        f"{BASE_PATH}/api/v2/content-library/saved-searches"
    )
    @login_required
    def saved_searches_list():

        with closing(
            db_connect()
        ) as conn:

            rows = conn.execute(
                """
                SELECT *
                FROM saved_searches
                ORDER BY
                    updated_at DESC,
                    id DESC
                LIMIT 100
                """
            ).fetchall()


        return jsonify(
            ok=True,
            searches=[
                {
                    **dict(row),
                    "filters":
                        json_load(
                            row[
                                "filters_json"
                            ],
                            {},
                        ),
                }
                for row in rows
            ],
        )


    @app.post(
        f"{BASE_PATH}/api/v2/content-library/saved-searches"
    )
    @api_post_required
    def saved_search_create():

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )


        name = str(
            data.get(
                "name"
            )
            or ""
        ).strip()[:100]


        if not name:

            return jsonify(
                ok=False,
                error=(
                    "برای جستجوی ذخیره‌شده نام وارد کنید."
                ),
            ), 400


        filters = (
            sanitize_saved_filters(
                data.get(
                    "filters"
                )
            )
        )


        with closing(
            db_connect()
        ) as conn:

            cursor = conn.execute(
                """
                INSERT INTO saved_searches(
                    name,
                    filters_json
                )
                VALUES(
                    ?,
                    ?
                )
                """,
                (
                    name,
                    json_dump(
                        filters
                    ),
                ),
            )


            conn.commit()


            search_id = (
                cursor.lastrowid
            )


        return jsonify(
            ok=True,
            id=
                search_id,
            name=
                name,
            filters=
                filters,
            message=(
                "جستجو ذخیره شد."
            ),
        ), 201


    @app.delete(
        f"{BASE_PATH}/api/v2/content-library/saved-searches/<int:search_id>"
    )
    @api_post_required
    def saved_search_delete(
        search_id
    ):

        with closing(
            db_connect()
        ) as conn:

            cursor = conn.execute(
                """
                DELETE FROM saved_searches
                WHERE id=?
                """,
                (
                    search_id,
                ),
            )


            conn.commit()


        if cursor.rowcount != 1:

            return jsonify(
                ok=False,
                error=(
                    "جستجوی ذخیره‌شده پیدا نشد."
                ),
            ), 404


        return jsonify(
            ok=True,
            message=(
                "جستجوی ذخیره‌شده حذف شد."
            ),
        )
