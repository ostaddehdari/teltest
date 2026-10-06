(() => {

    "use strict";

    const BASE = "/teltest";

    const connectorIcons = {
        telegram: "fa-brands fa-telegram",
        instagram: "fa-brands fa-instagram",
        youtube: "fa-brands fa-youtube",
        tiktok: "fa-brands fa-tiktok",
        pinterest: "fa-brands fa-pinterest",
        news: "fa-regular fa-newspaper",
        web: "fa-solid fa-globe",
        rss: "fa-solid fa-rss",
    };

    const connectorNames = {
        telegram: "تلگرام",
        instagram: "اینستاگرام",
        youtube: "یوتیوب",
        tiktok: "تیک‌تاک",
        pinterest: "پینترست",
        news: "سایت‌های خبری",
        web: "وب‌سایت‌ها",
        rss: "خوراک RSS",
    };

    const statusNames = {
        draft: "پیش‌نویس",
        pending: "در انتظار",
        running: "در حال اجرا",
        completed: "تکمیل‌شده",
        failed: "خطادار",
        paused: "متوقف",
        active: "فعال",
        none: "بدون اجرا",
    };

    function esc(value) {
        const div = document.createElement("div");
        div.textContent = String(value ?? "");
        return div.innerHTML;
    }

    function number(value) {
        return Number(value || 0).toLocaleString("fa-IR");
    }

    function status(value) {
        const key = String(value || "draft").toLowerCase();
        return {
            key,
            label: statusNames[key] || key,
        };
    }

    async function api(path) {
        const response = await fetch(`${BASE}${path}`, {
            headers: { Accept: "application/json" },
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

    function setText(id, value) {
        const item = document.getElementById(id);
        if (item) item.textContent = value;
    }

    function connectorCard(item, compact = false) {
        const code = String(item.code || "web");
        const active = Boolean(item.enabled && item.selectable);
        const icon = connectorIcons[code] || "fa-solid fa-plug";
        const name = connectorNames[code] || item.name || code;

        if (compact) {
            return `
                <div class="connector-mini ${active ? "active" : ""}">
                    <i class="${icon}" aria-hidden="true"></i>
                    <div>
                        <strong>${esc(name)}</strong>
                        <small>${active ? "فعال" : "به‌زودی"}</small>
                    </div>
                </div>
            `;
        }

        return `
            <article class="connector-card ${active ? "active" : "disabled"}">
                <span class="connector-state">${active ? "فعال" : "غیرفعال"}</span>
                <div class="connector-icon">
                    <i class="${icon}" aria-hidden="true"></i>
                </div>
                <strong>${esc(name)}</strong>
                <small>${esc(item.name || code)}</small>
            </article>
        `;
    }

    async function loadSummary() {
        const data = await api("/api/v2/architecture/summary");
        const counts = data.counts || {};

        setText("statExtractionJobs", number(counts.extraction_jobs));
        setText("statContentItems", number(counts.content_items));
        setText("statTransferJobs", number(counts.transfer_jobs));

        const badge = document.getElementById("architectureBadge");
        if (badge) {
            badge.textContent = data.architecture === "split-core-v2"
                ? "Split Core V2 فعال"
                : "معماری در حال بررسی";
        }

        const compact = document.getElementById("dashboardConnectorGrid");
        if (compact) {
            compact.innerHTML = (data.connectors || [])
                .map((item) => connectorCard(item, true))
                .join("");
        }
    }

    async function loadConnectors() {
        const box = document.getElementById("sourceConnectorGrid");
        if (!box) return;

        try {
            const data = await api("/api/v2/source-connectors");
            box.innerHTML = (data.connectors || [])
                .map((item) => connectorCard(item))
                .join("");
        } catch (error) {
            box.innerHTML = `<div class="empty-v2">${esc(error.message)}</div>`;
        }
    }

    function extractionCard(item) {
        const state = status(item.status);
        return `
            <article class="v2-job-card">
                <div class="v2-job-title">
                    <strong>${esc(item.name || `استخراج #${item.id}`)}</strong>
                    <small class="ltr">${esc(item.source_ref || "—")}</small>
                </div>
                <div class="v2-job-metric">
                    <span>منبع</span>
                    <strong>${esc(connectorNames[item.connector_code] || item.connector_code)}</strong>
                </div>
                <div class="v2-job-metric">
                    <span>محتوا</span>
                    <strong>${number(item.content_count)}</strong>
                </div>
                <span class="status-chip ${esc(state.key)}">${esc(state.label)}</span>
            </article>
        `;
    }

    async function loadExtractionJobs() {
        const box = document.getElementById("extractionJobsList");
        if (!box) return;

        box.innerHTML = '<div class="loading-box">در حال دریافت جاب‌های استخراج...</div>';

        try {
            const data = await api("/api/v2/extraction-jobs");
            const jobs = data.jobs || [];
            box.innerHTML = jobs.length
                ? jobs.map(extractionCard).join("")
                : '<div class="empty-v2">هنوز جاب استخراجی ثبت نشده است.</div>';
        } catch (error) {
            box.innerHTML = `<div class="empty-v2">${esc(error.message)}</div>`;
        }
    }

    function transferCard(item) {
        const state = status(item.status);
        const selector = item.selector || {};
        return `
            <article class="v2-job-card">
                <div class="v2-job-title">
                    <strong>${esc(item.name || `انتقال #${item.id}`)}</strong>
                    <small>انتخاب‌گر: ${esc(item.selector_type || "extraction_job")}</small>
                </div>
                <div class="v2-job-metric">
                    <span>استخراج مرتبط</span>
                    <strong>${esc(selector.extraction_job_id || "—")}</strong>
                </div>
                <div class="v2-job-metric">
                    <span>تعداد مقصد</span>
                    <strong>${number(item.destination_count)}</strong>
                </div>
                <span class="status-chip ${esc(state.key)}">${esc(state.label)}</span>
            </article>
        `;
    }

    async function loadTransferJobs() {
        const box = document.getElementById("transferJobsList");
        if (!box) return;

        box.innerHTML = '<div class="loading-box">در حال دریافت جاب‌های انتقال...</div>';

        try {
            const data = await api("/api/v2/transfer-jobs");
            const jobs = data.jobs || [];
            box.innerHTML = jobs.length
                ? jobs.map(transferCard).join("")
                : '<div class="empty-v2">هنوز جاب انتقالی ثبت نشده است.</div>';
        } catch (error) {
            box.innerHTML = `<div class="empty-v2">${esc(error.message)}</div>`;
        }
    }

    document.getElementById("reloadExtractionJobs")
        ?.addEventListener("click", loadExtractionJobs);

    document.getElementById("reloadTransferJobs")
        ?.addEventListener("click", loadTransferJobs);

    Promise.all([
        loadSummary(),
        loadConnectors(),
        loadExtractionJobs(),
        loadTransferJobs(),
    ]).catch((error) => console.error("Stage06:", error));

})();
