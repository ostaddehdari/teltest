(() => {

    "use strict";

    const BASE = "/teltest";

    const csrf = document
        .querySelector('meta[name="csrf-token"]')
        ?.getAttribute("content") || "";

    const healthNames = {
        healthy: "سالم",
        degraded: "نیازمند توجه",
        not_configured: "تنظیم‌نشده",
        planned: "برنامه آینده",
        failed: "خطادار",
        unavailable: "در دسترس نیست",
        unknown: "بررسی‌نشده",
    };

    const capabilityNames = {
        text: "متن",
        media: "رسانه",
        incremental: "استخراج افزایشی",
        date_cursor: "شروع از تاریخ",
        external_id_cursor: "شروع از شناسه",
        watch: "پایش دوره‌ای",
        public_sources: "منبع عمومی",
        private_invites: "لینک دعوت",
        groups: "گروه",
        comments: "دیدگاه",
        stories: "استوری",
        captions: "زیرنویس",
        short_video: "ویدئوی کوتاه",
        boards: "برد",
        structured_article: "مقاله ساختاریافته",
        custom_selector: "انتخاب‌گر سفارشی",
        atom: "Atom",
    };

    let connectors = [];

    function esc(value) {
        const div = document.createElement("div");
        div.textContent = String(value ?? "");
        return div.innerHTML;
    }

    function number(value) {
        return Number(value || 0).toLocaleString("fa-IR");
    }

    async function api(path, options = {}) {
        const method = String(options.method || "GET").toUpperCase();
        const headers = {
            Accept: "application/json",
            ...(options.headers || {}),
        };

        if (method !== "GET" && method !== "HEAD") {
            headers["Content-Type"] = "application/json";
            headers["X-CSRF-Token"] = csrf;
        }

        const response = await fetch(`${BASE}${path}`, {
            ...options,
            method,
            headers,
        });

        let data;

        try {
            data = await response.json();
        } catch (_error) {
            data = { ok: false, error: `HTTP ${response.status}` };
        }

        if (!response.ok || data.ok === false) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }

        return data;
    }

    function notify(message, type = "success") {
        const container = document.getElementById("toastContainer");
        if (!container) return;

        const item = document.createElement("div");
        item.className = `toast ${type}`;
        item.textContent = message;
        container.appendChild(item);

        window.setTimeout(() => item.classList.add("hide"), 4000);
        window.setTimeout(() => item.remove(), 4500);
    }

    function capabilitiesHtml(item) {
        return Object.entries(item.capabilities || {})
            .filter(([, enabled]) => Boolean(enabled))
            .slice(0, 7)
            .map(([key]) => `
                <span class="capability-chip">
                    ${esc(capabilityNames[key] || key)}
                </span>
            `)
            .join("");
    }

    function connectorCard(item) {
        const health = item.health || {};
        const healthKey = String(health.status || "unknown");
        const active = Boolean(item.enabled && item.selectable);
        const adapter = item.adapter || {};

        return `
            <article class="connector-card framework-card ${active ? "active" : "disabled"}">
                <span class="connector-health-state ${esc(healthKey)}">
                    ${esc(healthNames[healthKey] || healthKey)}
                </span>

                <div class="connector-card-head">
                    <div class="connector-icon">
                        <i class="${esc(item.icon || "fa-solid fa-plug")}" aria-hidden="true"></i>
                    </div>
                    <div class="connector-card-title">
                        <strong>${esc(item.display_name || item.name)}</strong>
                        <small>${esc(item.description || "")}</small>
                    </div>
                </div>

                <div class="connector-capabilities">
                    ${capabilitiesHtml(item)}
                </div>

                <p class="connector-health-message">
                    ${esc(health.summary || "هنوز بررسی نشده است.")}
                </p>

                <div class="connector-card-foot">
                    <span class="connector-adapter">
                        ${esc(adapter.key || "unknown")}@${esc(adapter.version || "0")}
                    </span>
                    ${item.lifecycle !== "planned" ? `
                        <button
                            type="button"
                            class="connector-refresh"
                            data-refresh-connector="${esc(item.code)}"
                        >
                            بررسی مجدد
                        </button>
                    ` : ""}
                </div>
            </article>
        `;
    }

    function compactCard(item) {
        const health = item.health || {};
        const key = String(health.status || "unknown");
        const active = Boolean(item.enabled && item.selectable);

        return `
            <div class="connector-mini ${active ? "active" : ""}">
                <i class="${esc(item.icon || "fa-solid fa-plug")}" aria-hidden="true"></i>
                <div>
                    <strong>${esc(item.display_name || item.name)}</strong>
                    <small>${esc(healthNames[key] || key)}</small>
                </div>
                <span class="mini-health-dot ${esc(key)}"></span>
            </div>
        `;
    }

    function render(data) {
        connectors = data.connectors || [];
        const summary = data.summary || {};

        const enabled = document.getElementById("connectorEnabledCount");
        const healthy = document.getElementById("connectorHealthyCount");
        const planned = document.getElementById("connectorPlannedCount");

        if (enabled) enabled.textContent = number(summary.enabled);
        if (healthy) {
            healthy.textContent = number(
                (summary.health_counts || {}).healthy
            );
        }
        if (planned) planned.textContent = number(summary.planned);

        const grid = document.getElementById("sourceConnectorGrid");
        if (grid) {
            grid.classList.add("framework-grid");
            grid.innerHTML = connectors.map(connectorCard).join("");
        }

        const compact = document.getElementById("dashboardConnectorGrid");
        if (compact) {
            compact.innerHTML = connectors.map(compactCard).join("");
        }
    }

    async function loadConnectors() {
        const data = await api("/api/v2/connectors");
        render(data);
    }

    async function refreshConnector(code, button = null) {
        if (button) {
            button.disabled = true;
            button.textContent = "در حال بررسی...";
        }

        try {
            const result = await api(
                `/api/v2/connectors/${encodeURIComponent(code)}/health/refresh`,
                { method: "POST", body: "{}" }
            );

            notify(result.health?.summary || "سلامت Connector بررسی شد.");
            await loadConnectors();
        } catch (error) {
            notify(error.message, "error");
        } finally {
            if (button && button.isConnected) {
                button.disabled = false;
                button.textContent = "بررسی مجدد";
            }
        }
    }

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-refresh-connector]");
        if (!button) return;
        refreshConnector(button.dataset.refreshConnector, button);
    });

    document.getElementById("refreshConnectorHealth")
        ?.addEventListener("click", async (event) => {
            const button = event.currentTarget;
            button.disabled = true;

            try {
                const active = connectors.filter(
                    (item) => item.lifecycle !== "planned"
                );

                for (const item of active) {
                    await api(
                        `/api/v2/connectors/${encodeURIComponent(item.code)}/health/refresh`,
                        { method: "POST", body: "{}" }
                    );
                }

                await loadConnectors();
                notify("سلامت منابع فعال بروزرسانی شد.");
            } catch (error) {
                notify(error.message, "error");
            } finally {
                button.disabled = false;
            }
        });

    loadConnectors().catch((error) => {
        console.error("Stage07:", error);
        notify(error.message, "error");
    });

})();
