import json

from abc import ABC, abstractmethod
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from flask import jsonify

from job_engine import db_connect


BASE_PATH = "/teltest"
FRAMEWORK_VERSION = "1"


def json_dump(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def json_load(value, default):
    if not value:
        return default

    try:
        return json.loads(value)
    except Exception:
        return default


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class ConnectorDefinition:
    code: str
    name: str
    display_name: str
    description: str
    icon: str
    position: int
    lifecycle: str
    adapter_key: str
    adapter_version: str
    enabled: bool
    selectable: bool
    requires_account: bool
    capabilities: dict
    config_schema: dict


@dataclass(frozen=True)
class ConnectorHealth:
    status: str
    summary: str
    details: dict
    checked_at: str


class SourceConnector(ABC):
    def __init__(self, definition):
        self.definition = definition

    @abstractmethod
    def health(self):
        raise NotImplementedError


class PlannedSourceConnector(SourceConnector):
    def health(self):
        return ConnectorHealth(
            status="planned",
            summary="این منبع برای یکی از مراحل آینده ثبت شده است.",
            details={
                "implemented": False,
                "enabled": False,
                "selectable": False,
            },
            checked_at=utc_now(),
        )


class TelegramSourceConnector(SourceConnector):
    def health(self):
        with closing(db_connect()) as conn:
            settings = {
                row["key"]: row["value"]
                for row in conn.execute(
                    """
                    SELECT key, value
                    FROM settings
                    WHERE key IN (
                        'telegram_api_id',
                        'telegram_api_hash'
                    )
                    """
                ).fetchall()
            }

            account_stats = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(
                        CASE WHEN status = 'connected'
                        THEN 1 ELSE 0 END
                    ) AS connected,
                    SUM(
                        CASE WHEN last_error IS NOT NULL
                                  AND TRIM(last_error) <> ''
                        THEN 1 ELSE 0 END
                    ) AS with_error
                FROM accounts
                """
            ).fetchone()

            channel_count = conn.execute(
                "SELECT COUNT(*) AS n FROM channels"
            ).fetchone()["n"]

        configured = bool(
            settings.get("telegram_api_id")
            and settings.get("telegram_api_hash")
        )

        total_accounts = int(account_stats["total"] or 0)
        connected_accounts = int(account_stats["connected"] or 0)
        accounts_with_error = int(account_stats["with_error"] or 0)

        details = {
            "implemented": True,
            "configured": configured,
            "accounts": total_accounts,
            "connected_accounts": connected_accounts,
            "accounts_with_error": accounts_with_error,
            "discovered_channels": int(channel_count or 0),
        }

        if not configured:
            status = "not_configured"
            summary = "API ID و API Hash تلگرام هنوز کامل تنظیم نشده است."
        elif connected_accounts < 1:
            status = "degraded"
            summary = "تنظیمات موجود است اما Session متصل تلگرام پیدا نشد."
        else:
            status = "healthy"
            summary = (
                f"تلگرام آماده است؛ {connected_accounts} Session متصل "
                f"و {int(channel_count or 0)} کانال یا گروه شناسایی شده است."
            )

        return ConnectorHealth(
            status=status,
            summary=summary,
            details=details,
            checked_at=utc_now(),
        )


class EitaaSourceConnector(SourceConnector):
    def health(self):
        return ConnectorHealth(status="healthy", summary="کرولر کانال عمومی ایتا آماده است.",
            details={"implemented": True, "public_only": True, "requires_account": False},
            checked_at=utc_now())


COMMON_CAPABILITIES = {
    "text": True,
    "media": True,
    "incremental": True,
    "date_cursor": True,
    "external_id_cursor": True,
    "watch": True,
}


CONNECTOR_DEFINITIONS = (
    ConnectorDefinition(
        code="telegram",
        name="Telegram",
        display_name="تلگرام",
        description="کانال‌ها، گروه‌ها و تاریخچه پیام با Telethon",
        icon="fa-brands fa-telegram",
        position=10,
        lifecycle="stable",
        adapter_key="telegram.telethon",
        adapter_version="2.0.0",
        enabled=True,
        selectable=True,
        requires_account=True,
        capabilities={
            **COMMON_CAPABILITIES,
            "public_sources": True,
            "private_invites": True,
            "groups": True,
        },
        config_schema={
            "required": ["telegram_api_id", "telegram_api_hash"],
            "account_type": "user_session",
        },
    ),
    ConnectorDefinition(
        code="eitaa", name="Eitaa", display_name="ایتا",
        description="استخراج کانال‌های عمومی ایتا با صفحه‌بندی",
        icon="fa-solid fa-message", position=15, lifecycle="experimental",
        adapter_key="eitaa.public_html", adapter_version="1.0.0",
        enabled=True, selectable=True, requires_account=False,
        capabilities={**COMMON_CAPABILITIES, "public_sources": True,
                      "private_invites": False, "groups": False},
        config_schema={"required": ["source_ref"], "account_type": "none"},
    ),
    ConnectorDefinition(
        code="instagram",
        name="Instagram",
        display_name="اینستاگرام",
        description="پست، ریلز، کپشن و دیدگاه‌ها",
        icon="fa-brands fa-instagram",
        position=20,
        lifecycle="planned",
        adapter_key="planned.instagram",
        adapter_version="0.0.0",
        enabled=False,
        selectable=False,
        requires_account=True,
        capabilities={**COMMON_CAPABILITIES, "comments": True, "stories": True},
        config_schema={},
    ),
    ConnectorDefinition(
        code="youtube",
        name="YouTube",
        display_name="یوتیوب",
        description="ویدئو، توضیحات، زیرنویس و دیدگاه‌ها",
        icon="fa-brands fa-youtube",
        position=30,
        lifecycle="planned",
        adapter_key="planned.youtube",
        adapter_version="0.0.0",
        enabled=False,
        selectable=False,
        requires_account=False,
        capabilities={**COMMON_CAPABILITIES, "captions": True, "comments": True},
        config_schema={},
    ),
    ConnectorDefinition(
        code="tiktok",
        name="TikTok",
        display_name="تیک‌تاک",
        description="ویدئو، کپشن و اطلاعات انتشار",
        icon="fa-brands fa-tiktok",
        position=40,
        lifecycle="planned",
        adapter_key="planned.tiktok",
        adapter_version="0.0.0",
        enabled=False,
        selectable=False,
        requires_account=True,
        capabilities={**COMMON_CAPABILITIES, "short_video": True},
        config_schema={},
    ),
    ConnectorDefinition(
        code="pinterest",
        name="Pinterest",
        display_name="پینترست",
        description="پین‌ها، بردها، متن و تصویر",
        icon="fa-brands fa-pinterest",
        position=50,
        lifecycle="planned",
        adapter_key="planned.pinterest",
        adapter_version="0.0.0",
        enabled=False,
        selectable=False,
        requires_account=False,
        capabilities={**COMMON_CAPABILITIES, "boards": True},
        config_schema={},
    ),
    ConnectorDefinition(
        code="news",
        name="News Sites",
        display_name="سایت‌های خبری",
        description="خبر، نویسنده، زمان انتشار و دسته‌بندی",
        icon="fa-regular fa-newspaper",
        position=60,
        lifecycle="planned",
        adapter_key="planned.news",
        adapter_version="0.0.0",
        enabled=False,
        selectable=False,
        requires_account=False,
        capabilities={**COMMON_CAPABILITIES, "structured_article": True},
        config_schema={},
    ),
    ConnectorDefinition(
        code="web",
        name="Websites",
        display_name="وب‌سایت‌ها",
        description="صفحه وب با الگوی استخراج قابل تنظیم",
        icon="fa-solid fa-globe",
        position=70,
        lifecycle="planned",
        adapter_key="planned.web",
        adapter_version="0.0.0",
        enabled=False,
        selectable=False,
        requires_account=False,
        capabilities={**COMMON_CAPABILITIES, "custom_selector": True},
        config_schema={},
    ),
    ConnectorDefinition(
        code="rss",
        name="RSS",
        display_name="خوراک RSS",
        description="خوراک‌های RSS و Atom",
        icon="fa-solid fa-rss",
        position=80,
        lifecycle="planned",
        adapter_key="planned.rss",
        adapter_version="0.0.0",
        enabled=False,
        selectable=False,
        requires_account=False,
        capabilities={**COMMON_CAPABILITIES, "atom": True},
        config_schema={},
    ),
)


class ConnectorRegistry:
    def __init__(self, definitions):
        self.definitions = {
            item.code: item
            for item in definitions
        }

        self.adapters = {
            code: (
                TelegramSourceConnector(definition)
                if code == "telegram"
                else EitaaSourceConnector(definition) if code == "eitaa"
                else PlannedSourceConnector(definition)
            )
            for code, definition in self.definitions.items()
        }

    def get(self, code):
        return self.adapters.get(code)

    def all(self):
        return [
            self.adapters[item.code]
            for item in sorted(
                self.definitions.values(),
                key=lambda value: value.position,
            )
        ]


REGISTRY = ConnectorRegistry(CONNECTOR_DEFINITIONS)


def init_connector_schema():
    with closing(db_connect()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS connector_registry_meta (
                code TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                description TEXT NOT NULL,
                icon TEXT NOT NULL,
                lifecycle TEXT NOT NULL,
                adapter_key TEXT NOT NULL,
                adapter_version TEXT NOT NULL,
                requires_account INTEGER NOT NULL DEFAULT 0,
                config_schema_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(code)
                    REFERENCES source_connectors(code)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS connector_health (
                connector_code TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                summary TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                checked_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(connector_code)
                    REFERENCES source_connectors(code)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_connector_meta_lifecycle
                ON connector_registry_meta(lifecycle);

            CREATE INDEX IF NOT EXISTS idx_connector_health_status
                ON connector_health(status);
            """
        )

        conn.execute(
            """
            INSERT INTO schema_meta (key, value, updated_at)
            VALUES ('connector_framework_version', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (FRAMEWORK_VERSION,),
        )

        conn.commit()


def seed_connector_registry():
    with closing(db_connect()) as conn:
        for definition in CONNECTOR_DEFINITIONS:
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
                VALUES (?, ?, 'content', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    enabled = excluded.enabled,
                    selectable = excluded.selectable,
                    position = excluded.position,
                    capabilities_json = excluded.capabilities_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    definition.code,
                    definition.name,
                    int(definition.enabled),
                    int(definition.selectable),
                    definition.position,
                    json_dump(definition.capabilities),
                ),
            )

            conn.execute(
                """
                INSERT INTO connector_registry_meta (
                    code,
                    display_name,
                    description,
                    icon,
                    lifecycle,
                    adapter_key,
                    adapter_version,
                    requires_account,
                    config_schema_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(code) DO UPDATE SET
                    display_name = excluded.display_name,
                    description = excluded.description,
                    icon = excluded.icon,
                    lifecycle = excluded.lifecycle,
                    adapter_key = excluded.adapter_key,
                    adapter_version = excluded.adapter_version,
                    requires_account = excluded.requires_account,
                    config_schema_json = excluded.config_schema_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    definition.code,
                    definition.display_name,
                    definition.description,
                    definition.icon,
                    definition.lifecycle,
                    definition.adapter_key,
                    definition.adapter_version,
                    int(definition.requires_account),
                    json_dump(definition.config_schema),
                ),
            )

        conn.commit()


def save_health(code, health):
    with closing(db_connect()) as conn:
        conn.execute(
            """
            INSERT INTO connector_health (
                connector_code,
                status,
                summary,
                details_json,
                checked_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(connector_code) DO UPDATE SET
                status = excluded.status,
                summary = excluded.summary,
                details_json = excluded.details_json,
                checked_at = excluded.checked_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                code,
                health.status,
                health.summary,
                json_dump(health.details),
                health.checked_at,
            ),
        )
        conn.commit()


def refresh_connector(code):
    adapter = REGISTRY.get(code)

    if not adapter:
        return None

    health = adapter.health()
    save_health(code, health)
    return health


def refresh_all_connectors():
    return {
        adapter.definition.code: refresh_connector(
            adapter.definition.code
        )
        for adapter in REGISTRY.all()
    }


def connector_rows(code=None):
    where = "WHERE sc.code = ?" if code else ""
    params = (code,) if code else ()

    with closing(db_connect()) as conn:
        rows = conn.execute(
            f"""
            SELECT
                sc.code,
                sc.name,
                sc.category,
                sc.enabled,
                sc.selectable,
                sc.position,
                sc.capabilities_json,
                sc.created_at,
                sc.updated_at,
                crm.display_name,
                crm.description,
                crm.icon,
                crm.lifecycle,
                crm.adapter_key,
                crm.adapter_version,
                crm.requires_account,
                crm.config_schema_json,
                ch.status AS health_status,
                ch.summary AS health_summary,
                ch.details_json AS health_details_json,
                ch.checked_at AS health_checked_at
            FROM source_connectors sc
            INNER JOIN connector_registry_meta crm
                ON crm.code = sc.code
            LEFT JOIN connector_health ch
                ON ch.connector_code = sc.code
            {where}
            ORDER BY sc.position, sc.code
            """,
            params,
        ).fetchall()

    return rows


def connector_payload(row):
    return {
        "code": row["code"],
        "name": row["name"],
        "display_name": row["display_name"],
        "description": row["description"],
        "icon": row["icon"],
        "category": row["category"],
        "enabled": bool(row["enabled"]),
        "selectable": bool(row["selectable"]),
        "position": row["position"],
        "lifecycle": row["lifecycle"],
        "adapter": {
            "key": row["adapter_key"],
            "version": row["adapter_version"],
        },
        "requires_account": bool(row["requires_account"]),
        "capabilities": json_load(row["capabilities_json"], {}),
        "config_schema": json_load(row["config_schema_json"], {}),
        "health": {
            "status": row["health_status"] or "unknown",
            "summary": row["health_summary"] or "هنوز بررسی نشده است.",
            "details": json_load(row["health_details_json"], {}),
            "checked_at": row["health_checked_at"],
        },
    }


def framework_summary():
    items = [connector_payload(row) for row in connector_rows()]
    health_counts = {}

    for item in items:
        key = item["health"]["status"]
        health_counts[key] = health_counts.get(key, 0) + 1

    return {
        "framework_version": FRAMEWORK_VERSION,
        "total": len(items),
        "enabled": sum(1 for item in items if item["enabled"]),
        "selectable": sum(1 for item in items if item["selectable"]),
        "planned": sum(1 for item in items if item["lifecycle"] == "planned"),
        "health_counts": health_counts,
    }


def bootstrap_connector_framework():
    init_connector_schema()
    seed_connector_registry()
    refresh_all_connectors()
    return framework_summary()


def init_connector_framework(app, login_required, api_post_required):
    boot_summary = bootstrap_connector_framework()

    @app.get(f"{BASE_PATH}/api/v2/connectors")
    @login_required
    def api_v2_connectors():
        items = [connector_payload(row) for row in connector_rows()]
        return jsonify(
            ok=True,
            summary=framework_summary(),
            connectors=items,
            boot_summary=boot_summary,
        )

    @app.get(f"{BASE_PATH}/api/v2/connectors/<string:code>")
    @login_required
    def api_v2_connector_detail(code):
        rows = connector_rows(code)

        if not rows:
            return jsonify(ok=False, error="connector_not_found"), 404

        return jsonify(ok=True, connector=connector_payload(rows[0]))

    @app.get(f"{BASE_PATH}/api/v2/connectors/<string:code>/health")
    @login_required
    def api_v2_connector_health(code):
        rows = connector_rows(code)

        if not rows:
            return jsonify(ok=False, error="connector_not_found"), 404

        item = connector_payload(rows[0])
        return jsonify(
            ok=True,
            connector_code=code,
            health=item["health"],
        )

    @app.post(f"{BASE_PATH}/api/v2/connectors/<string:code>/health/refresh")
    @api_post_required
    def api_v2_connector_health_refresh(code):
        health = refresh_connector(code)

        if not health:
            return jsonify(ok=False, error="connector_not_found"), 404

        return jsonify(
            ok=True,
            connector_code=code,
            health=asdict(health),
        )
