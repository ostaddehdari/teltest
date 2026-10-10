import asyncio
import mimetypes
import shutil

from contextlib import closing
from urllib.parse import urlparse
from eitaa_source import safe_media_url
from pathlib import Path

import httpx

from flask import jsonify, request

from bale_engine import send_file as bale_send_file
from bale_engine import send_text as bale_send_text
from external_mirror import (
    eitaa_send_document,
    eitaa_send_message,
    rubika_send_file,
    rubika_send_message,
    rubika_upload,
)
from job_engine import account_lock, db_connect, resolve_destination, resolve_source

from content_rules import (
    apply_content_rules,
    normalize_rules,
)


BASE_PATH = "/teltest"
TELEGRAM_BOT_API = "https://api.telegram.org"
TMP_ROOT = Path("/var/lib/teltest/tmp/provider-destinations")

PROVIDERS = {
    "telegram_user": {
        "label": "تلگرام — اکانت کاربری",
        "short_label": "تلگرام",
        "requires_account": True,
        "token_key": None,
        "default_destination_key": None,
        "modes": ["copy", "forward"],
        "destination_hint": "@channel، لینک t.me یا شناسه کانال",
    },
    "telegram_bot": {
        "label": "تلگرام — ربات",
        "short_label": "ربات تلگرام",
        "requires_account": False,
        "token_key": "telegram_bot_token",
        "default_destination_key": "telegram_bot_chat_id",
        "modes": ["copy"],
        "destination_hint": "@channel یا Chat ID؛ ربات باید مدیر باشد",
    },
    "bale": {
        "label": "بله — Bot API",
        "short_label": "بله",
        "requires_account": False,
        "token_key": "bale_bot_token",
        "default_destination_key": "bale_chat_id",
        "modes": ["copy"],
        "destination_hint": "@channel یا Chat ID بله",
    },
    "eitaa": {
        "label": "ایتا — EitaaYar API",
        "short_label": "ایتا",
        "requires_account": False,
        "token_key": "eitaa_bot_token",
        "default_destination_key": "eitaa_chat_id",
        "modes": ["copy"],
        "destination_hint": "Chat ID کانال ایتا",
    },
    "rubika": {
        "label": "روبیکا — Bot API",
        "short_label": "روبیکا",
        "requires_account": False,
        "token_key": "rubika_bot_token",
        "default_destination_key": "rubika_chat_id",
        "modes": ["copy"],
        "destination_hint": "Chat ID یا GUID کانال روبیکا",
    },
}

PROVIDER_ALIASES = {
    "telegram": "telegram_user",
    "telegram_mtproto": "telegram_user",
    "telegram-user": "telegram_user",
    "telegram-bot": "telegram_bot",
}


def normalize_provider(value):
    code = str(value or "").strip().lower()
    return PROVIDER_ALIASES.get(code, code)


def setting_get(key, default=""):
    if not key:
        return default
    with closing(db_connect()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return str(row["value"] if row else default)


def setting_set(key, value):
    with closing(db_connect()) as conn:
        conn.execute(
            """
            INSERT INTO settings(key,value,updated_at)
            VALUES(?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
            """,
            (key, str(value)),
        )
        conn.commit()


def mask_secret(value):
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 12:
        return "••••••••"
    return f"{value[:5]}••••••••{value[-5:]}"


def provider_token(provider):
    spec = PROVIDERS.get(normalize_provider(provider))
    return setting_get(spec["token_key"]).strip() if spec and spec["token_key"] else ""


def provider_is_configured(provider):
    provider = normalize_provider(provider)
    if provider == "telegram_user":
        with closing(db_connect()) as conn:
            return bool(
                conn.execute("SELECT 1 FROM accounts WHERE status='connected' LIMIT 1").fetchone()
            )
    return bool(provider_token(provider))


def provider_catalog():
    catalog = []
    for code, spec in PROVIDERS.items():
        catalog.append(
            {
                "code": code,
                "label": spec["label"],
                "short_label": spec["short_label"],
                "configured": provider_is_configured(code),
                "requires_account": spec["requires_account"],
                "modes": spec["modes"],
                "destination_hint": spec["destination_hint"],
                "default_destination": setting_get(spec["default_destination_key"]).strip()
                if spec["default_destination_key"]
                else "",
            }
        )
    return catalog


def validate_destination_payload(data, account_get):
    provider = normalize_provider(data.get("provider_code"))
    if provider not in PROVIDERS:
        raise ValueError("پروایدر انتقال معتبر نیست.")
    destination_ref = str(data.get("destination_ref") or "").strip()
    if not destination_ref:
        raise ValueError(f"شناسه کانال مقصد برای {PROVIDERS[provider]['short_label']} الزامی است.")
    mode = str(data.get("mode") or "copy").strip().lower()
    if mode not in PROVIDERS[provider]["modes"]:
        raise ValueError(f"روش انتقال برای {PROVIDERS[provider]['short_label']} معتبر نیست.")
    account_id = data.get("provider_account_id")
    if PROVIDERS[provider]["requires_account"]:
        try:
            account_id = int(account_id)
        except (TypeError, ValueError):
            raise ValueError("برای انتقال کاربری تلگرام یک اکانت متصل انتخاب کنید.")
        account = account_get(account_id)
        if not account or account["status"] != "connected":
            raise ValueError("اکانت انتخاب‌شده تلگرام متصل نیست.")
    else:
        account_id = None
        if not provider_is_configured(provider):
            raise ValueError(f"توکن {PROVIDERS[provider]['short_label']} هنوز در بخش پروایدرها تنظیم نشده است.")
    return {
        "provider_code": provider,
        "provider_account_id": account_id,
        "destination_ref": destination_ref,
        "mode": mode,
        "enabled": 1,
        "rules": normalize_rules(
            data.get("rules") or {}
        ),
    }


def result_message_id(result):
    if not isinstance(result, dict):
        return None
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    inner = result.get("result") if isinstance(result.get("result"), dict) else {}
    return (
        result.get("message_id")
        or result.get("id")
        or data.get("message_id")
        or data.get("id")
        or inner.get("message_id")
        or inner.get("id")
    )


async def telegram_bot_request(token, method, data=None, files=None, timeout=120):
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=25)) as client:
        response = await client.post(
            f"{TELEGRAM_BOT_API}/bot{token}/{method}",
            data=data or {},
            files=files,
        )
        response.raise_for_status()
        payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or str(payload))
    return payload.get("result")


async def telegram_bot_send_text(token, chat_id, text):
    result = None
    value = str(text or "")
    for offset in range(0, len(value), 4000):
        result = await telegram_bot_request(
            token,
            "sendMessage",
            {"chat_id": chat_id, "text": value[offset : offset + 4000]},
        )
    return result


async def telegram_bot_send_file(token, chat_id, path, kind, caption):
    path = Path(path)
    mapping = {
        "photo": ("sendPhoto", "photo"),
        "video": ("sendVideo", "video"),
        "audio": ("sendAudio", "audio"),
        "voice": ("sendVoice", "voice"),
    }
    method, field = mapping.get(kind, ("sendDocument", "document"))
    short_caption = str(caption or "")[:900]
    data = {"chat_id": chat_id}
    if short_caption:
        data["caption"] = short_caption
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as handle:
        result = await telegram_bot_request(
            token,
            method,
            data=data,
            files={field: (path.name, handle, mime)},
            timeout=300,
        )
    if caption and len(caption) > 900:
        await telegram_bot_send_text(token, chat_id, caption[900:])
    return result


async def send_external(provider, token, destination_ref, kind, text, downloaded):
    if provider == "telegram_bot":
        if downloaded:
            return await telegram_bot_send_file(token, destination_ref, downloaded, kind, text)
        return await telegram_bot_send_text(token, destination_ref, text)
    if provider == "bale":
        if downloaded:
            return await bale_send_file(token, destination_ref, downloaded, kind, text)
        return await bale_send_text(token, destination_ref, text)
    if provider == "eitaa":
        if downloaded:
            return await eitaa_send_document(token, destination_ref, downloaded, text)
        return await eitaa_send_message(token, destination_ref, text)
    if provider == "rubika":
        if downloaded:
            file_id = await rubika_upload(token, downloaded, kind)
            result = await rubika_send_file(token, destination_ref, file_id)
            if text:
                await rubika_send_message(token, destination_ref, text)
            return result
        return await rubika_send_message(token, destination_ref, text)
    raise RuntimeError("پروایدر انتقال پشتیبانی نمی‌شود.")



async def download_eitaa_media(url, tmp_dir, media_index):
    from pathlib import Path
    target_url = safe_media_url(url)
    if not target_url:
        raise RuntimeError("نشانی رسانه ایتا مجاز نیست.")
    target = Path(tmp_dir) / f"eitaa-media-{media_index}"
    total = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=15), follow_redirects=False) as client:
        async with client.stream("GET", target_url) as response:
            if response.status_code != 200:
                raise RuntimeError(f"دانلود رسانه ایتا: HTTP {response.status_code}")
            with target.open("wb") as f:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise RuntimeError("فایل رسانه از سقف ۱۰۰ مگابایت بیشتر است.")
                    f.write(chunk)
    return str(target)


async def execute_eitaa_destination(extraction, destination, rows, mark):
    tmp = TMP_ROOT / f"job-{destination['transfer_job_id']}" / f"destination-{destination['id']}"
    tmp.mkdir(parents=True, exist_ok=True)
    provider = normalize_provider(destination["provider_code"])
    token = provider_token(provider)
    rules = normalize_rules(destination.get("rules_json") or destination.get("rules") or {})
    try:
        if provider == "telegram_user":
            raise RuntimeError("مقصد اکانت کاربری تلگرام از منبع ایتا هنوز پشتیبانی نمی‌شود؛ از Telegram Bot استفاده کنید.")
        for row in rows:
            item_id = row["transfer_item_id"]
            evaluation = apply_content_rules(row.get("processed_text") or row.get("raw_text") or "", rules)
            if evaluation["excluded"]:
                mark(item_id, "skipped", error="Destination rules excluded this post.")
                continue
            text = evaluation["processed_text"]
            media = row.get("media_json") or "[]"
            if isinstance(media, str):
                import json
                media = json.loads(media)
            media = [m for m in media if isinstance(m, dict) and m.get("url")]
            mark(item_id, "transferring")
            try:
                sent = None
                if not media:
                    if text:
                        sent = await send_external(provider, token, destination["destination_ref"], "text", text, None)
                    else:
                        mark(item_id, "skipped", error="پست فاقد متن یا رسانه است.")
                        continue
                else:
                    for idx, item in enumerate(media):
                        downloaded = await download_eitaa_media(item["url"], tmp, idx)
                        try:
                            sent = await send_external(provider, token, destination["destination_ref"],
                                                       item.get("kind") or "document",
                                                       text if idx == 0 else "", downloaded)
                        finally:
                            Path(downloaded).unlink(missing_ok=True)
                mark(item_id, "transferred", destination_external_id=result_message_id(sent))
            except Exception as exc:
                mark(item_id, "failed", error=f"{type(exc).__name__}: {exc}"[:2000])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def execute_destination(
    client,
    extraction,
    destination,
    rows,
    mark,
):

    provider = normalize_provider(
        destination["provider_code"]
    )

    rules = normalize_rules(
        destination.get(
            "rules_json"
        )
        or destination.get(
            "rules"
        )
        or {}
    )

    tmp = (
        TMP_ROOT
        / f"job-{destination['transfer_job_id']}"
        / f"destination-{destination['id']}"
    )

    tmp.mkdir(
        parents=True,
        exist_ok=True,
    )


    await client.connect()


    try:

        if not await client.is_user_authorized():

            raise RuntimeError(
                "Session تلگرام اکانت مبدا مجاز نیست."
            )


        source, _joined = await resolve_source(
            client,
            extraction[
                "source_ref"
            ],
        )


        telegram_destination = None


        if provider == "telegram_user":

            telegram_destination = await resolve_destination(
                client,
                destination[
                    "destination_ref"
                ],
            )


        token = provider_token(
            provider
        )


        ids = [
            int(
                row[
                    "external_id"
                ]
            )
            for row in rows
            if str(
                row[
                    "external_id"
                ]
            ).isdigit()
        ]


        messages = (
            await client.get_messages(
                source,
                ids=ids,
            )
            if ids
            else []
        )


        if not isinstance(
            messages,
            (list, tuple),
        ):

            messages = [
                messages
            ]


        by_id = {
            int(
                item.id
            ):
                item

            for item in messages

            if (
                item
                and getattr(
                    item,
                    "id",
                    None,
                )
            )
        }


        for row in rows:

            item_id = row[
                "transfer_item_id"
            ]


            message_id = (
                int(
                    row[
                        "external_id"
                    ]
                )
                if str(
                    row[
                        "external_id"
                    ]
                ).isdigit()
                else None
            )


            message = (
                by_id.get(
                    message_id
                )
                if message_id
                else None
            )


            if message is None:

                mark(
                    item_id,
                    "skipped",
                    error=(
                        "پیام اصلی در منبع پیدا نشد."
                    ),
                )

                continue


            base_text = str(
                row.get(
                    "processed_text"
                )
                or row.get(
                    "raw_text"
                )
                or getattr(
                    message,
                    "message",
                    None,
                )
                or ""
            )


            evaluation = apply_content_rules(
                base_text,
                rules,
            )


            if evaluation[
                "excluded"
            ]:

                mark(
                    item_id,
                    "skipped",
                    error=(
                        "Destination Rule: "
                        + str(
                            evaluation[
                                "reason"
                            ]
                            or "excluded"
                        )
                    ),
                )

                continue


            text = evaluation[
                "processed_text"
            ]


            mark(
                item_id,
                "transferring",
            )


            try:

                if provider == "telegram_user":

                    #
                    # Forward باید ماهیت Forward واقعی را حفظ کند.
                    # بنابراین تغییر متن فقط برای Copy اعمال می‌شود.
                    #
                    if destination[
                        "mode"
                    ] == "forward":

                        sent = await client.forward_messages(
                            telegram_destination,
                            message,
                            from_peer=source,
                        )


                    else:

                        original_text = str(
                            getattr(
                                message,
                                "message",
                                None,
                            )
                            or ""
                        )


                        has_media = bool(
                            getattr(
                                message,
                                "media",
                                None,
                            )
                        )


                        if (
                            has_media
                            and text == original_text
                        ):

                            #
                            # مسیر سبک؛ اگر Rule متن را تغییر نداده،
                            # Telegram همان Message را Copy می‌کند.
                            #
                            sent = await client.send_message(
                                telegram_destination,
                                message,
                            )


                        elif has_media:

                            downloaded = await client.download_media(
                                message,
                                file=str(
                                    tmp
                                ),
                            )


                            if downloaded:

                                sent = await client.send_file(
                                    telegram_destination,
                                    downloaded,
                                    caption=(
                                        text
                                        or None
                                    ),
                                )


                            elif text:

                                sent = await client.send_message(
                                    telegram_destination,
                                    text,
                                )


                            else:

                                mark(
                                    item_id,
                                    "skipped",
                                    error=(
                                        "متن یا رسانه قابل ارسال وجود ندارد."
                                    ),
                                )

                                continue


                        else:

                            if not text:

                                mark(
                                    item_id,
                                    "skipped",
                                    error=(
                                        "متن قابل ارسال وجود ندارد."
                                    ),
                                )

                                continue


                            sent = await client.send_message(
                                telegram_destination,
                                text,
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


                    external_id = getattr(
                        sent,
                        "id",
                        None,
                    )


                else:

                    kind = str(
                        row.get(
                            "content_type"
                        )
                        or "text"
                    )


                    downloaded = None


                    if (
                        kind != "text"
                        or getattr(
                            message,
                            "media",
                            None,
                        )
                    ):

                        downloaded = await client.download_media(
                            message,
                            file=str(
                                tmp
                            ),
                        )


                    if (
                        not downloaded
                        and not text
                    ):

                        mark(
                            item_id,
                            "skipped",
                            error=(
                                "متن یا رسانه قابل ارسال وجود ندارد."
                            ),
                        )

                        continue


                    sent = await send_external(
                        provider,
                        token,
                        destination[
                            "destination_ref"
                        ],
                        kind,
                        text,
                        downloaded,
                    )


                    external_id = result_message_id(
                        sent
                    )


                mark(
                    item_id,
                    "transferred",
                    destination_external_id=
                        external_id,
                )


            except Exception as exc:

                mark(
                    item_id,
                    "failed",
                    error=(
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )


    finally:

        await client.disconnect()

        shutil.rmtree(
            tmp,
            ignore_errors=True,
        )


def run_destination(telegram_client, account, extraction, destination, rows, mark):
    if extraction["connector_code"] == "eitaa":
        asyncio.run(execute_eitaa_destination(extraction, destination, rows, mark))
        return
    with account_lock(account["id"]):
        asyncio.run(execute_destination(telegram_client(account), extraction, destination, rows, mark))


def init_provider_destinations(app, login_required, api_post_required, account_get):
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with closing(db_connect()) as conn:
        conn.execute(
            "UPDATE transfer_destinations SET provider_code='telegram_user' WHERE provider_code IN ('telegram','telegram_mtproto')"
        )
        conn.execute(
            """
            INSERT INTO schema_meta(key,value,updated_at)
            VALUES('provider_destinations_version','1',CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
            """
        )
        conn.commit()

    @app.get(f"{BASE_PATH}/api/v2/transfer-providers")
    @login_required
    def transfer_providers():
        return jsonify(ok=True, providers=provider_catalog())

    @app.get(f"{BASE_PATH}/api/settings/telegram-bot")
    @login_required
    def telegram_bot_settings():
        token = setting_get("telegram_bot_token").strip()
        return jsonify(
            ok=True,
            configured=bool(token),
            token_masked=mask_secret(token),
            chat_id=setting_get("telegram_bot_chat_id").strip(),
        )

    @app.post(f"{BASE_PATH}/api/settings/telegram-bot")
    @api_post_required
    def save_telegram_bot_settings():
        data = request.get_json(silent=True) or {}
        token = str(data.get("token") or "").strip() or setting_get("telegram_bot_token").strip()
        chat_id = str(data.get("chat_id") or "").strip()
        if not token:
            return jsonify(ok=False, error="توکن ربات تلگرام وارد نشده است."), 400
        setting_set("telegram_bot_token", token)
        setting_set("telegram_bot_chat_id", chat_id)
        return jsonify(ok=True, message="تنظیمات ربات تلگرام ذخیره شد.")

    @app.post(f"{BASE_PATH}/api/settings/telegram-bot/test")
    @api_post_required
    def test_telegram_bot_settings():
        data = request.get_json(silent=True) or {}
        token = setting_get("telegram_bot_token").strip()
        chat_id = str(data.get("chat_id") or setting_get("telegram_bot_chat_id") or "").strip()
        if not token:
            return jsonify(ok=False, error="ابتدا توکن ربات تلگرام را ذخیره کنید."), 400
        try:
            me = asyncio.run(telegram_bot_request(token, "getMe"))
            if chat_id:
                asyncio.run(
                    telegram_bot_send_text(
                        token, chat_id, "✅ اتصال ربات تلگرام به TelTest با موفقیت برقرار شد."
                    )
                )
            return jsonify(
                ok=True,
                bot=me,
                message="ربات تلگرام تأیید شد و پیام تست ارسال شد."
                if chat_id
                else "توکن ربات تلگرام با موفقیت تأیید شد.",
            )
        except Exception as exc:
            return jsonify(ok=False, error=f"{type(exc).__name__}: {exc}"), 400
