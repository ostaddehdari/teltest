import asyncio
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from telethon import TelegramClient, errors


BASE_PATH = "/teltest"

VERSION = os.getenv(
    "TELTEST_VERSION",
    "0.3.2",
)

ADMIN_USERNAME = os.getenv(
    "TELTEST_USERNAME",
    "teletonadmin",
)

ADMIN_PASSWORD = os.getenv(
    "TELTEST_PASSWORD",
    "",
)

RUNTIME_ROOT = Path(
    os.getenv(
        "TELTEST_RUNTIME_ROOT",
        "/var/lib/teltest",
    )
)

DATA_DIR = RUNTIME_ROOT / "data"

SESSIONS_DIR = RUNTIME_ROOT / "sessions"

DB_FILE = DATA_DIR / "teltest.sqlite3"


DATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

SESSIONS_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


app = Flask(
    __name__,
    static_folder="static",
    static_url_path=f"{BASE_PATH}/static",
    template_folder="templates",
)


app.config.update(

    SECRET_KEY=os.environ.get(
        "TELTEST_SECRET_KEY",
        secrets.token_hex(48),
    ),

    SESSION_COOKIE_NAME="teltest_session",

    SESSION_COOKIE_HTTPONLY=True,

    SESSION_COOKIE_SECURE=(
        os.getenv(
            "TELTEST_COOKIE_SECURE",
            "1",
        )
        == "1"
    ),

    SESSION_COOKIE_SAMESITE="Lax",

    SESSION_COOKIE_PATH=f"{BASE_PATH}/",

    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,

)


# ============================================================
# DATABASE
# ============================================================

def db_connect():

    conn = sqlite3.connect(
        DB_FILE,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    conn.execute(
        "PRAGMA journal_mode = WAL"
    )

    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )

    return conn


def init_db():

    with closing(
        db_connect()
    ) as conn:

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                phone TEXT NOT NULL UNIQUE,

                session_name TEXT UNIQUE,

                status TEXT NOT NULL
                    DEFAULT 'new',

                phone_code_hash TEXT,

                telegram_user_id TEXT,

                username TEXT,

                display_name TEXT,

                last_error TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                account_id INTEGER NOT NULL,

                entity_id TEXT NOT NULL,

                access_hash TEXT,

                title TEXT NOT NULL,

                username TEXT,

                kind TEXT NOT NULL,

                is_creator INTEGER NOT NULL
                    DEFAULT 0,

                is_admin INTEGER NOT NULL
                    DEFAULT 0,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(account_id)
                    REFERENCES accounts(id)
                    ON DELETE CASCADE,

                UNIQUE(account_id, entity_id)
            );

            CREATE INDEX IF NOT EXISTS
                idx_channels_account
                ON channels(account_id);

            CREATE INDEX IF NOT EXISTS
                idx_channels_username
                ON channels(username);
            """
        )

        conn.commit()


init_db()


# ============================================================
# DB HELPERS
# ============================================================

def setting_get(key, default=None):

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


def setting_set(key, value):

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
                ?,
                ?,
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


def telegram_config():

    api_id = setting_get(
        "telegram_api_id"
    )

    api_hash = setting_get(
        "telegram_api_hash"
    )

    if not api_id or not api_hash:
        return None

    try:
        api_id = int(api_id)

    except (TypeError, ValueError):
        return None

    return {
        "api_id": api_id,
        "api_hash": api_hash,
    }


# ============================================================
# AUTH / CSRF
# ============================================================

def csrf_token():

    token = session.get(
        "csrf_token"
    )

    if not token:

        token = secrets.token_urlsafe(
            32
        )

        session["csrf_token"] = token

    return token


app.jinja_env.globals[
    "csrf_token"
] = csrf_token


def valid_csrf_form():

    expected = session.get(
        "csrf_token",
        "",
    )

    supplied = request.form.get(
        "csrf_token",
        "",
    )

    return bool(
        expected
        and supplied
        and hmac.compare_digest(
            expected,
            supplied,
        )
    )


def valid_csrf_api():

    expected = session.get(
        "csrf_token",
        "",
    )

    supplied = request.headers.get(
        "X-CSRF-Token",
        "",
    )

    return bool(
        expected
        and supplied
        and hmac.compare_digest(
            expected,
            supplied,
        )
    )


def login_required(view):

    @wraps(view)
    def wrapped(*args, **kwargs):

        if not session.get(
            "authenticated"
        ):

            if request.path.startswith(
                f"{BASE_PATH}/api/"
            ):

                return jsonify(
                    ok=False,
                    error="authentication_required",
                ), 401

            return redirect(
                url_for(
                    "login"
                )
            )

        return view(
            *args,
            **kwargs,
        )

    return wrapped


def api_post_required(view):

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):

        if not valid_csrf_api():

            return jsonify(
                ok=False,
                error="invalid_csrf",
            ), 400

        return view(
            *args,
            **kwargs,
        )

    return wrapped


def payload():

    data = request.get_json(
        silent=True
    )

    if isinstance(data, dict):
        return data

    return {}


# ============================================================
# TELEGRAM HELPERS
# ============================================================

def normalize_phone(value):

    value = str(
        value or ""
    ).strip()

    value = re.sub(
        r"[\s\-\(\)]",
        "",
        value,
    )

    if value.startswith("00"):
        value = "+" + value[2:]

    if not value.startswith("+"):
        value = "+" + value

    if not re.fullmatch(
        r"\+[0-9]{8,15}",
        value,
    ):
        raise ValueError(
            "شماره تلفن معتبر نیست. مثال: +989121234567"
        )

    return value


def run_async(coro):

    return asyncio.run(
        coro
    )


def account_get(account_id):

    with closing(
        db_connect()
    ) as conn:

        row = conn.execute(
            """
            SELECT *
            FROM accounts
            WHERE id = ?
            """,
            (account_id,),
        ).fetchone()

    return row


def account_get_by_phone(phone):

    with closing(
        db_connect()
    ) as conn:

        row = conn.execute(
            """
            SELECT *
            FROM accounts
            WHERE phone = ?
            """,
            (phone,),
        ).fetchone()

    return row


def account_ensure(phone):

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            INSERT INTO accounts (
                phone,
                status
            )
            VALUES (
                ?,
                'new'
            )
            ON CONFLICT(phone)
            DO NOTHING
            """,
            (phone,),
        )

        conn.commit()

        row = conn.execute(
            """
            SELECT *
            FROM accounts
            WHERE phone = ?
            """,
            (phone,),
        ).fetchone()

        if not row["session_name"]:

            session_name = (
                f"account_{row['id']}"
            )

            conn.execute(
                """
                UPDATE accounts
                SET
                    session_name = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    session_name,
                    row["id"],
                ),
            )

            conn.commit()

            row = conn.execute(
                """
                SELECT *
                FROM accounts
                WHERE id = ?
                """,
                (row["id"],),
            ).fetchone()

    return row


def session_base_path(account):

    name = account["session_name"]

    if not name:
        raise RuntimeError(
            "Session name is missing"
        )

    if not re.fullmatch(
        r"account_[0-9]+",
        name,
    ):
        raise RuntimeError(
            "Invalid session name"
        )

    return str(
        SESSIONS_DIR / name
    )


def telegram_client(account):

    config = telegram_config()

    if not config:
        raise RuntimeError(
            "ابتدا API ID و API Hash تلگرام را در تنظیمات ذخیره کنید."
        )

    return TelegramClient(
        session_base_path(account),
        config["api_id"],
        config["api_hash"],
    )


def dialog_payloads(dialogs):

    result = []

    for dialog in dialogs:

        if not (
            dialog.is_channel
            or dialog.is_group
        ):
            continue

        entity = dialog.entity

        broadcast = bool(
            getattr(
                entity,
                "broadcast",
                False,
            )
        )

        megagroup = bool(
            getattr(
                entity,
                "megagroup",
                False,
            )
        )

        if broadcast:
            kind = "channel"

        elif megagroup:
            kind = "supergroup"

        elif dialog.is_group:
            kind = "group"

        else:
            kind = "channel"

        result.append(
            {
                "entity_id": str(
                    getattr(
                        entity,
                        "id",
                        "",
                    )
                ),

                "access_hash": str(
                    getattr(
                        entity,
                        "access_hash",
                        "",
                    )
                    or ""
                ),

                "title": (
                    dialog.name
                    or getattr(
                        entity,
                        "title",
                        "",
                    )
                    or "بدون نام"
                ),

                "username": getattr(
                    entity,
                    "username",
                    None,
                ),

                "kind": kind,

                "is_creator": int(
                    bool(
                        getattr(
                            entity,
                            "creator",
                            False,
                        )
                    )
                ),

                "is_admin": int(
                    getattr(
                        entity,
                        "admin_rights",
                        None,
                    )
                    is not None
                ),
            }
        )

    return result


async def telethon_send_code(account):

    client = telegram_client(
        account
    )

    try:

        await client.connect()

        if await client.is_user_authorized():

            me = await client.get_me()

            dialogs = await client.get_dialogs(
                limit=None
            )

            return {
                "authorized": True,
                "me": me,
                "dialogs": dialog_payloads(
                    dialogs
                ),
            }

        sent = await client.send_code_request(
            account["phone"]
        )

        return {
            "authorized": False,
            "phone_code_hash": (
                sent.phone_code_hash
            ),
        }

    finally:

        await client.disconnect()


async def telethon_verify_code(
    account,
    code,
):

    client = telegram_client(
        account
    )

    try:

        await client.connect()

        try:

            await client.sign_in(
                phone=account["phone"],
                code=code,
                phone_code_hash=(
                    account[
                        "phone_code_hash"
                    ]
                ),
            )

        except errors.SessionPasswordNeededError:

            return {
                "password_required": True
            }

        me = await client.get_me()

        dialogs = await client.get_dialogs(
            limit=None
        )

        return {
            "password_required": False,
            "me": me,
            "dialogs": dialog_payloads(
                dialogs
            ),
        }

    finally:

        await client.disconnect()


async def telethon_verify_password(
    account,
    password,
):

    client = telegram_client(
        account
    )

    try:

        await client.connect()

        await client.sign_in(
            password=password
        )

        me = await client.get_me()

        dialogs = await client.get_dialogs(
            limit=None
        )

        return {
            "me": me,
            "dialogs": dialog_payloads(
                dialogs
            ),
        }

    finally:

        await client.disconnect()


async def telethon_refresh(
    account,
):

    client = telegram_client(
        account
    )

    try:

        await client.connect()

        authorized = (
            await client.is_user_authorized()
        )

        if not authorized:

            return {
                "authorized": False
            }

        me = await client.get_me()

        dialogs = await client.get_dialogs(
            limit=None
        )

        return {
            "authorized": True,
            "me": me,
            "dialogs": dialog_payloads(
                dialogs
            ),
        }

    finally:

        await client.disconnect()


def save_connected(
    account_id,
    me,
    dialogs,
):

    first_name = (
        getattr(
            me,
            "first_name",
            "",
        )
        or ""
    )

    last_name = (
        getattr(
            me,
            "last_name",
            "",
        )
        or ""
    )

    display_name = (
        f"{first_name} {last_name}"
    ).strip()

    username = getattr(
        me,
        "username",
        None,
    )

    user_id = str(
        getattr(
            me,
            "id",
            "",
        )
    )

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            UPDATE accounts
            SET
                status = 'connected',
                phone_code_hash = NULL,
                telegram_user_id = ?,
                username = ?,
                display_name = ?,
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                user_id,
                username,
                display_name,
                account_id,
            ),
        )

        conn.execute(
            """
            DELETE FROM channels
            WHERE account_id = ?
            """,
            (account_id,),
        )

        for item in dialogs:

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
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT(
                    account_id,
                    entity_id
                )
                DO UPDATE SET
                    access_hash =
                        excluded.access_hash,
                    title =
                        excluded.title,
                    username =
                        excluded.username,
                    kind =
                        excluded.kind,
                    is_creator =
                        excluded.is_creator,
                    is_admin =
                        excluded.is_admin,
                    updated_at =
                        CURRENT_TIMESTAMP
                """,
                (
                    account_id,
                    item["entity_id"],
                    item["access_hash"],
                    item["title"],
                    item["username"],
                    item["kind"],
                    item["is_creator"],
                    item["is_admin"],
                ),
            )

        conn.commit()


def account_error(
    account_id,
    message,
):

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            UPDATE accounts
            SET
                last_error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                str(message)[:1000],
                account_id,
            ),
        )

        conn.commit()


# ============================================================
# WEB
# ============================================================

@app.get(
    f"{BASE_PATH}/health"
)
def health():

    config = telegram_config()

    return jsonify(
        ok=True,
        app="teltest",
        version=VERSION,
        stage="03",
        status="ready",
        telegram_configured=bool(
            config
        ),
    )


@app.route(
    f"{BASE_PATH}/login",
    methods=[
        "GET",
        "POST",
    ],
)
def login():

    if session.get(
        "authenticated"
    ):

        return redirect(
            url_for(
                "dashboard"
            )
        )

    error = None

    if request.method == "POST":

        if not valid_csrf_form():
            abort(400)

        username = request.form.get(
            "username",
            "",
        )

        password = request.form.get(
            "password",
            "",
        )

        user_ok = hmac.compare_digest(
            username,
            ADMIN_USERNAME,
        )

        pass_ok = (
            bool(
                ADMIN_PASSWORD
            )
            and hmac.compare_digest(
                password,
                ADMIN_PASSWORD,
            )
        )

        if user_ok and pass_ok:

            session.clear()

            session[
                "authenticated"
            ] = True

            session[
                "username"
            ] = ADMIN_USERNAME

            session[
                "csrf_token"
            ] = secrets.token_urlsafe(
                32
            )

            session.permanent = True

            return redirect(
                url_for(
                    "dashboard"
                )
            )

        time.sleep(
            0.45
        )

        error = (
            "نام کاربری یا رمز عبور صحیح نیست."
        )

    return render_template(
        "login.html",
        error=error,
        version=VERSION,
    )


@app.post(
    f"{BASE_PATH}/logout"
)
@login_required
def logout():

    if not valid_csrf_form():
        abort(400)

    session.clear()

    return redirect(
        url_for(
            "login"
        )
    )


@app.get(
    f"{BASE_PATH}"
)
def dashboard_no_slash():

    return redirect(
        url_for(
            "dashboard"
        )
    )


@app.get(
    f"{BASE_PATH}/"
)
@login_required
def dashboard():

    return render_template(
        "dashboard.html",

        username=session.get(
            "username",
            ADMIN_USERNAME,
        ),

        version=VERSION,
    )


# ============================================================
# API - OVERVIEW
# ============================================================

@app.get(
    f"{BASE_PATH}/api/overview"
)
@login_required
def api_overview():

    with closing(
        db_connect()
    ) as conn:

        accounts = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM accounts
            """
        ).fetchone()["n"]

        connected = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM accounts
            WHERE status = 'connected'
            """
        ).fetchone()["n"]

        channels = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM channels
            """
        ).fetchone()["n"]

    return jsonify(
        ok=True,
        accounts=accounts,
        connected=connected,
        channels=channels,
        jobs=0,
        posts=0,
        forwarded=0,
        failed=0,
    )


# ============================================================
# API - TELEGRAM SETTINGS
# ============================================================

@app.get(
    f"{BASE_PATH}/api/settings/telegram"
)
@login_required
def api_get_telegram_settings():

    api_id = setting_get(
        "telegram_api_id",
        "",
    )

    api_hash = setting_get(
        "telegram_api_hash",
        "",
    )

    masked = ""

    if api_hash:

        masked = (
            api_hash[:4]
            + "••••••••••••••••••••"
            + api_hash[-4:]
        )

    return jsonify(
        ok=True,
        configured=bool(
            api_id
            and api_hash
        ),
        api_id=api_id,
        api_hash_masked=masked,
    )


@app.post(
    f"{BASE_PATH}/api/settings/telegram"
)
@api_post_required
def api_save_telegram_settings():

    data = payload()

    api_id = str(
        data.get(
            "api_id",
            "",
        )
    ).strip()

    api_hash = str(
        data.get(
            "api_hash",
            "",
        )
    ).strip()

    if not api_id.isdigit():

        return jsonify(
            ok=False,
            error=(
                "API ID باید عدد باشد."
            ),
        ), 400

    if int(api_id) <= 0:

        return jsonify(
            ok=False,
            error="API ID نامعتبر است.",
        ), 400

    current_hash = setting_get(
        "telegram_api_hash",
        "",
    )

    if not api_hash:
        api_hash = current_hash

    if not re.fullmatch(
        r"[A-Fa-f0-9]{32}",
        api_hash or "",
    ):

        return jsonify(
            ok=False,
            error=(
                "API Hash باید مقدار ۳۲ کاراکتری "
                "دریافتی از Telegram باشد."
            ),
        ), 400

    setting_set(
        "telegram_api_id",
        api_id,
    )

    setting_set(
        "telegram_api_hash",
        api_hash,
    )

    return jsonify(
        ok=True,
        message=(
            "تنظیمات Telegram API ذخیره شد."
        ),
    )


# ============================================================
# API - ACCOUNTS
# ============================================================

@app.get(
    f"{BASE_PATH}/api/accounts"
)
@login_required
def api_accounts():

    with closing(
        db_connect()
    ) as conn:

        rows = conn.execute(
            """
            SELECT
                a.*,
                (
                    SELECT COUNT(*)
                    FROM channels c
                    WHERE c.account_id = a.id
                ) AS channel_count
            FROM accounts a
            ORDER BY
                a.id DESC
            """
        ).fetchall()

    items = []

    for row in rows:

        items.append(
            {
                "id": row["id"],
                "phone": row["phone"],
                "status": row["status"],
                "telegram_user_id": (
                    row[
                        "telegram_user_id"
                    ]
                ),
                "username": (
                    row["username"]
                ),
                "display_name": (
                    row[
                        "display_name"
                    ]
                ),
                "last_error": (
                    row[
                        "last_error"
                    ]
                ),
                "channel_count": (
                    row[
                        "channel_count"
                    ]
                ),
                "created_at": (
                    row["created_at"]
                ),
                "updated_at": (
                    row["updated_at"]
                ),
            }
        )

    return jsonify(
        ok=True,
        accounts=items,
    )


@app.post(
    f"{BASE_PATH}/api/accounts/send-code"
)
@api_post_required
def api_send_code():

    if not telegram_config():

        return jsonify(
            ok=False,
            error=(
                "ابتدا API ID و API Hash "
                "را در تنظیمات ذخیره کنید."
            ),
        ), 400

    data = payload()

    try:

        phone = normalize_phone(
            data.get(
                "phone"
            )
        )

    except ValueError as exc:

        return jsonify(
            ok=False,
            error=str(exc),
        ), 400

    account = account_ensure(
        phone
    )

    try:

        result = run_async(
            telethon_send_code(
                account
            )
        )

        if result["authorized"]:

            save_connected(
                account["id"],
                result["me"],
                result["dialogs"],
            )

            return jsonify(
                ok=True,
                state="connected",
                account_id=account["id"],
                channels=len(
                    result["dialogs"]
                ),
                message=(
                    "این Session از قبل متصل بود "
                    "و کانال‌ها بروزرسانی شدند."
                ),
            )

        with closing(
            db_connect()
        ) as conn:

            conn.execute(
                """
                UPDATE accounts
                SET
                    status = 'code_sent',
                    phone_code_hash = ?,
                    last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    result[
                        "phone_code_hash"
                    ],
                    account["id"],
                ),
            )

            conn.commit()

        return jsonify(
            ok=True,
            state="code_sent",
            account_id=account["id"],
            message=(
                "کد ورود توسط Telegram ارسال شد."
            ),
        )

    except errors.FloodWaitError as exc:

        account_error(
            account["id"],
            f"FloodWait {exc.seconds}s",
        )

        return jsonify(
            ok=False,
            error=(
                f"Telegram محدودیت موقت اعمال کرده است. "
                f"{exc.seconds} ثانیه."
            ),
            flood_wait=exc.seconds,
        ), 429

    except errors.PhoneNumberInvalidError:

        account_error(
            account["id"],
            "PhoneNumberInvalidError",
        )

        return jsonify(
            ok=False,
            error=(
                "Telegram این شماره را معتبر نمی‌داند."
            ),
        ), 400

    except errors.ApiIdInvalidError:

        account_error(
            account["id"],
            "ApiIdInvalidError",
        )

        return jsonify(
            ok=False,
            error=(
                "API ID یا API Hash نامعتبر است."
            ),
        ), 400

    except Exception as exc:

        account_error(
            account["id"],
            exc,
        )

        return jsonify(
            ok=False,
            error=(
                f"{type(exc).__name__}: {exc}"
            ),
        ), 500


@app.post(
    f"{BASE_PATH}/api/accounts/<int:account_id>/verify-code"
)
@api_post_required
def api_verify_code(account_id):

    account = account_get(
        account_id
    )

    if not account:

        return jsonify(
            ok=False,
            error="اکانت پیدا نشد.",
        ), 404

    code = str(
        payload().get(
            "code",
            "",
        )
    ).strip().replace(
        " ",
        "",
    )

    if not re.fullmatch(
        r"[0-9]{3,10}",
        code,
    ):

        return jsonify(
            ok=False,
            error="کد وریفای معتبر نیست.",
        ), 400

    if not account[
        "phone_code_hash"
    ]:

        return jsonify(
            ok=False,
            error=(
                "ابتدا Send Code را انجام دهید."
            ),
        ), 400

    try:

        result = run_async(
            telethon_verify_code(
                account,
                code,
            )
        )

        if result[
            "password_required"
        ]:

            with closing(
                db_connect()
            ) as conn:

                conn.execute(
                    """
                    UPDATE accounts
                    SET
                        status = 'password_required',
                        last_error = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (account_id,),
                )

                conn.commit()

            return jsonify(
                ok=True,
                state="password_required",
                message=(
                    "این حساب 2FA دارد. "
                    "رمز دوم Telegram را وارد کنید."
                ),
            )

        save_connected(
            account_id,
            result["me"],
            result["dialogs"],
        )

        return jsonify(
            ok=True,
            state="connected",
            channels=len(
                result["dialogs"]
            ),
            message=(
                "اکانت با موفقیت متصل شد."
            ),
        )

    except errors.PhoneCodeInvalidError:

        return jsonify(
            ok=False,
            error="کد واردشده اشتباه است.",
        ), 400

    except errors.PhoneCodeExpiredError:

        return jsonify(
            ok=False,
            error=(
                "کد منقضی شده است. "
                "دوباره Send Code بزنید."
            ),
        ), 400

    except errors.FloodWaitError as exc:

        return jsonify(
            ok=False,
            error=(
                f"FloodWait: {exc.seconds} ثانیه"
            ),
            flood_wait=exc.seconds,
        ), 429

    except Exception as exc:

        account_error(
            account_id,
            exc,
        )

        return jsonify(
            ok=False,
            error=(
                f"{type(exc).__name__}: {exc}"
            ),
        ), 500


@app.post(
    f"{BASE_PATH}/api/accounts/<int:account_id>/verify-password"
)
@api_post_required
def api_verify_password(account_id):

    account = account_get(
        account_id
    )

    if not account:

        return jsonify(
            ok=False,
            error="اکانت پیدا نشد.",
        ), 404

    password = str(
        payload().get(
            "password",
            "",
        )
    )

    if not password:

        return jsonify(
            ok=False,
            error=(
                "رمز 2FA را وارد کنید."
            ),
        ), 400

    try:

        result = run_async(
            telethon_verify_password(
                account,
                password,
            )
        )

        save_connected(
            account_id,
            result["me"],
            result["dialogs"],
        )

        return jsonify(
            ok=True,
            state="connected",
            channels=len(
                result["dialogs"]
            ),
            message=(
                "2FA تأیید شد و Session ذخیره شد."
            ),
        )

    except errors.PasswordHashInvalidError:

        return jsonify(
            ok=False,
            error="رمز 2FA اشتباه است.",
        ), 400

    except errors.FloodWaitError as exc:

        return jsonify(
            ok=False,
            error=(
                f"FloodWait: {exc.seconds} ثانیه"
            ),
            flood_wait=exc.seconds,
        ), 429

    except Exception as exc:

        account_error(
            account_id,
            exc,
        )

        return jsonify(
            ok=False,
            error=(
                f"{type(exc).__name__}: {exc}"
            ),
        ), 500


@app.post(
    f"{BASE_PATH}/api/accounts/<int:account_id>/refresh"
)
@api_post_required
def api_refresh_account(account_id):

    account = account_get(
        account_id
    )

    if not account:

        return jsonify(
            ok=False,
            error="اکانت پیدا نشد.",
        ), 404

    try:

        result = run_async(
            telethon_refresh(
                account
            )
        )

        if not result[
            "authorized"
        ]:

            with closing(
                db_connect()
            ) as conn:

                conn.execute(
                    """
                    UPDATE accounts
                    SET
                        status = 'disconnected',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (account_id,),
                )

                conn.commit()

            return jsonify(
                ok=False,
                error=(
                    "Session دیگر Authorized نیست. "
                    "دوباره شماره را متصل کنید."
                ),
            ), 401

        save_connected(
            account_id,
            result["me"],
            result["dialogs"],
        )

        return jsonify(
            ok=True,
            channels=len(
                result["dialogs"]
            ),
            message=(
                "کانال‌ها و گروه‌ها بروزرسانی شدند."
            ),
        )

    except errors.FloodWaitError as exc:

        return jsonify(
            ok=False,
            error=(
                f"FloodWait: {exc.seconds} ثانیه"
            ),
            flood_wait=exc.seconds,
        ), 429

    except Exception as exc:

        account_error(
            account_id,
            exc,
        )

        return jsonify(
            ok=False,
            error=(
                f"{type(exc).__name__}: {exc}"
            ),
        ), 500


@app.delete(
    f"{BASE_PATH}/api/accounts/<int:account_id>"
)
@api_post_required
def api_delete_account(account_id):

    account = account_get(
        account_id
    )

    if not account:

        return jsonify(
            ok=False,
            error="اکانت پیدا نشد.",
        ), 404

    session_name = account[
        "session_name"
    ]

    with closing(
        db_connect()
    ) as conn:

        conn.execute(
            """
            DELETE FROM accounts
            WHERE id = ?
            """,
            (account_id,),
        )

        conn.commit()

    if session_name and re.fullmatch(
        r"account_[0-9]+",
        session_name,
    ):

        for file_path in (
            SESSIONS_DIR.glob(
                f"{session_name}*"
            )
        ):

            try:

                if file_path.is_file():
                    file_path.unlink()

            except OSError:
                pass

    return jsonify(
        ok=True,
        message=(
            "اتصال محلی و Session حذف شد."
        ),
    )


# ============================================================
# API - CHANNELS
# ============================================================

@app.get(
    f"{BASE_PATH}/api/channels"
)
@login_required
def api_channels():

    raw_account_id = request.args.get(
        "account_id",
        "",
    ).strip()

    params = []

    where = ""

    if raw_account_id:

        if not raw_account_id.isdigit():

            return jsonify(
                ok=False,
                error="account_id invalid",
            ), 400

        where = (
            " WHERE c.account_id = ? "
        )

        params.append(
            int(raw_account_id)
        )

    with closing(
        db_connect()
    ) as conn:

        rows = conn.execute(
            f"""
            SELECT
                c.*,
                a.phone AS account_phone,
                a.display_name AS account_name
            FROM channels c
            INNER JOIN accounts a
                ON a.id = c.account_id
            {where}
            ORDER BY
                c.title COLLATE NOCASE ASC
            """,
            params,
        ).fetchall()

    items = []

    for row in rows:

        items.append(
            {
                "id": row["id"],
                "account_id": (
                    row["account_id"]
                ),
                "account_phone": (
                    row[
                        "account_phone"
                    ]
                ),
                "account_name": (
                    row[
                        "account_name"
                    ]
                ),
                "entity_id": (
                    row["entity_id"]
                ),
                "title": row["title"],
                "username": (
                    row["username"]
                ),
                "kind": row["kind"],
                "is_creator": bool(
                    row["is_creator"]
                ),
                "is_admin": bool(
                    row["is_admin"]
                ),
                "updated_at": (
                    row["updated_at"]
                ),
            }
        )

    return jsonify(
        ok=True,
        channels=items,
        count=len(items),
    )



# TELTEST_STAGE03_START
from job_engine import init_jobs

init_jobs(
    app=app,
    login_required=login_required,
    api_post_required=api_post_required,
    telegram_client=telegram_client,
    account_get=account_get,
)
# TELTEST_STAGE03_END

# ============================================================
# ERRORS
# ============================================================

@app.errorhandler(400)
def bad_request(_error):

    if request.path.startswith(
        f"{BASE_PATH}/api/"
    ):

        return jsonify(
            ok=False,
            error="bad_request",
        ), 400

    return "Bad request", 400


@app.errorhandler(404)
def not_found(_error):

    if request.path.startswith(
        f"{BASE_PATH}/api/"
    ):

        return jsonify(
            ok=False,
            error="not_found",
        ), 404

    return "Not found", 404


if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=18870,
        debug=False,
    )
