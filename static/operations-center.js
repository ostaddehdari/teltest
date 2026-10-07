(() => {
    "use strict";

    const BASE = "/teltest";
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const statusNames = {
        draft: "پیش‌نویس", pending: "در انتظار", running: "در حال اجرا",
        completed: "تکمیل‌شده", failed: "خطادار", paused: "متوقف",
        listed: "در فهرست", transferring: "در حال انتقال",
        transferred: "منتقل‌شده", skipped: "ردشده",
    };
    const modeNames = {
        all: "آخرین پیام‌ها", date: "از تاریخ", message_id: "از Message ID",
        incremental: "افزایشی", legacy: "قدیمی", copy: "کپی", forward: "فوروارد",
    };

    let meta = { accounts: [], channels: [] };
    let extractionJobs = [];
    let transferJobs = [];
    let transferProviders = [];

    function esc(value) {
        const node = document.createElement("div");
        node.textContent = String(value ?? "");
        return node.innerHTML;
    }

    function number(value) {
        return Number(value || 0).toLocaleString("fa-IR");
    }

    function clip(value, length = 230) {
        const text = String(value || "").trim();
        return text.length > length ? `${text.slice(0, length)}…` : text;
    }

    async function api(path, options = {}) {
        const method = String(options.method || "GET").toUpperCase();
        const headers = { Accept: "application/json", ...(options.headers || {}) };
        if (!['GET', 'HEAD'].includes(method)) {
            headers["Content-Type"] = "application/json";
            headers["X-CSRF-Token"] = csrf;
        }
        const response = await fetch(`${BASE}${path}`, { ...options, method, headers });
        let data;
        try { data = await response.json(); }
        catch (_error) { data = { ok: false, error: `HTTP ${response.status}` }; }
        if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
        return data;
    }

    function notify(message, type = "success") {
        const container = document.getElementById("toastContainer");
        if (!container) return;
        const item = document.createElement("div");
        item.className = `toast ${type}`;
        item.textContent = message;
        container.appendChild(item);
        window.setTimeout(() => item.classList.add("hide"), 4500);
        window.setTimeout(() => item.remove(), 5000);
    }

    function setBusy(button, busy, text = "در حال انجام...") {
        if (!button) return;
        if (busy) {
            button.dataset.originalHtml = button.innerHTML;
            button.disabled = true;
            button.textContent = text;
        } else {
            button.disabled = false;
            if (button.dataset.originalHtml) button.innerHTML = button.dataset.originalHtml;
        }
    }

    function accountOptions(selected) {
        return `<option value="">انتخاب اکانت</option>${meta.accounts.map((item) => {
            const label = item.display_name || item.username || item.phone || `اکانت ${item.id}`;
            return `<option value="${item.id}" ${Number(selected) === Number(item.id) ? "selected" : ""}>${esc(label)}</option>`;
        }).join("")}`;
    }

    function hashtagsHtml(tags) {
        return (tags || []).length
            ? `<div class="hashtag-list">${tags.map((tag) => `<span class="hashtag-chip">${esc(tag)}</span>`).join("")}</div>`
            : "";
    }

    function contentRow(item, showTransfer = false) {
        const original = item.original_url
            ? `<a class="btn soft" href="${esc(item.original_url)}" target="_blank" rel="noopener">پست اصلی</a>`
            : `<button class="btn soft" disabled>لینک عمومی ندارد</button>`;
        const state = showTransfer
            ? `<span class="transfer-state ${esc(item.transfer_status || 'listed')}">${esc(statusNames[item.transfer_status] || item.transfer_status)}</span>`
            : "";
        const destination = showTransfer
            ? `<span class="badge">${esc(item.provider_label || item.provider_code || "مقصد")} · ${esc(item.destination_ref || "—")}</span>`
            : "";
        return `
            <article class="content-row">
                <div class="content-row-main">
                    <div class="content-row-head">
                        <strong>${esc(item.source_title || item.source_ref || "تلگرام")}</strong>
                        <small class="ltr">#${esc(item.external_id)}</small>
                        <small>${esc(item.published_at || "بدون تاریخ")}</small>
                        <span class="badge">${esc(item.content_type || "text")}</span>
                        ${state}
                        ${destination}
                    </div>
                    <p class="content-row-text">${esc(clip(item.raw_text) || `[${item.content_type || "محتوا"}]`)}</p>
                    ${hashtagsHtml(item.hashtags)}
                    ${item.last_error ? `<small class="text-danger">${esc(item.last_error)}</small>` : ""}
                </div>
                <div class="content-row-actions">
                    ${original}
                    <a class="btn secondary" href="${esc(item.download_url)}">دانلود محتوا</a>
                </div>
            </article>
        `;
    }

    function logRows(logs) {
        return (logs || []).length
            ? `<div class="operation-log-list">${logs.map((item) => `
                <div class="operation-log-row ${esc(item.level || 'info')}">
                    <small class="ltr">${esc(item.created_at || "")}</small>
                    <code>${esc(item.event || "LOG")}</code>
                    <span>${esc(item.message || "")}</span>
                </div>
            `).join("")}</div>`
            : '<div class="empty-inline">هنوز لاگی برای این جاب ثبت نشده است.</div>';
    }

    function workspaceTabs(kind, items) {
        return `
            <div class="workspace-tabs">
                ${items.map((item, index) => `<button type="button" class="${index === 0 ? 'active' : ''}" data-workspace-tab="${kind}:${item.key}">${esc(item.label)}</button>`).join("")}
            </div>
        `;
    }

    async function loadMeta() {
        meta = await api("/api/v2/telegram-extractor/meta");
    }

    function providerOptions(selected) {
        return transferProviders.map((item) => `
            <option value="${esc(item.code)}" ${item.code === selected ? "selected" : ""} ${item.configured ? "" : "disabled"}>
                ${esc(item.label)}${item.configured ? "" : " — تنظیم نشده"}
            </option>
        `).join("");
    }

    function destinationRowHtml(value = {}) {
        const selected = value.provider_code || transferProviders.find((item) => item.configured)?.code || "telegram_user";
        return `
            <div class="transfer-destination-row" data-transfer-destination-row>
                <label>پروایدر انتقال
                    <select data-destination-provider>${providerOptions(selected)}</select>
                    <small class="provider-health" data-provider-health></small>
                </label>
                <label data-destination-account-wrap>اکانت تلگرام
                    <select data-destination-account>${accountOptions(value.provider_account_id)}</select>
                </label>
                <label>شناسه کانال / مقصد
                    <input data-destination-ref dir="ltr" value="${esc(value.destination_ref || "")}" required>
                    <small data-destination-hint></small>
                </label>
                <label>روش انتقال
                    <select data-destination-mode></select>
                </label>
                <button type="button" class="btn danger-soft" data-remove-transfer-destination>حذف</button>
            </div>
        `;
    }

    function configureDestinationRow(row, preferredMode) {
        const code = row.querySelector("[data-destination-provider]")?.value;
        const provider = transferProviders.find((item) => item.code === code) || transferProviders[0];
        if (!provider) return;
        const accountWrap = row.querySelector("[data-destination-account-wrap]");
        if (accountWrap) accountWrap.hidden = !provider.requires_account;
        const mode = row.querySelector("[data-destination-mode]");
        if (mode) {
            mode.innerHTML = (provider.modes || ["copy"]).map((item) => `<option value="${esc(item)}" ${item === preferredMode ? "selected" : ""}>${esc(modeNames[item] || item)}</option>`).join("");
        }
        const destination = row.querySelector("[data-destination-ref]");
        if (destination && !destination.value && provider.default_destination) destination.value = provider.default_destination;
        if (destination) destination.placeholder = provider.destination_hint || "شناسه مقصد";
        const hint = row.querySelector("[data-destination-hint]");
        if (hint) hint.textContent = provider.destination_hint || "";
        const health = row.querySelector("[data-provider-health]");
        if (health) {
            health.textContent = provider.configured ? "آماده و متصل" : "ابتدا در بخش پروایدرها تنظیم شود";
            health.className = `provider-health ${provider.configured ? "ready" : "missing"}`;
        }
    }

    function addDestinationRow(container, value = {}) {
        if (!container) return;
        container.insertAdjacentHTML("beforeend", destinationRowHtml(value));
        const row = container.lastElementChild;
        configureDestinationRow(row, value.mode || "copy");
    }

    function hydrateDestinationRows(container, values = []) {
        if (!container) return;
        container.innerHTML = "";
        const list = values.length ? values : [{}];
        list.forEach((value) => addDestinationRow(container, value));
    }

    function collectDestinations(container) {
        return [...container.querySelectorAll("[data-transfer-destination-row]")].map((row) => {
            const providerCode = row.querySelector("[data-destination-provider]").value;
            const provider = transferProviders.find((item) => item.code === providerCode);
            return {
                provider_code: providerCode,
                provider_account_id: provider?.requires_account
                    ? Number(row.querySelector("[data-destination-account]").value)
                    : null,
                destination_ref: row.querySelector("[data-destination-ref]").value.trim(),
                mode: row.querySelector("[data-destination-mode]").value,
            };
        });
    }

    async function loadTransferProviders() {
        const editors = [...document.querySelectorAll(".transfer-destinations-list")].map((container) => ({
            container,
            values: container.children.length ? collectDestinations(container) : [],
        }));
        const data = await api("/api/v2/transfer-providers");
        transferProviders = data.providers || [];
        editors.forEach(({ container, values }) => hydrateDestinationRows(container, values));
    }

    function extractionCard(item) {
        const state = String(item.status || "draft");
        return `
            <article class="v2-job-card operations-job-card">
                <div class="v2-job-title">
                    <strong>${esc(item.name || `استخراج #${item.id}`)}</strong>
                    <small class="ltr">${esc(item.source_ref || "—")}</small>
                </div>
                <div class="v2-job-metric"><span>محتوا</span><strong>${number(item.content_count)}</strong></div>
                <div class="v2-job-metric"><span>اجرا</span><strong>${number(item.run_count)}</strong></div>
                <div class="v2-job-metric"><span>Cursor</span><strong class="cursor-value">${esc(item.cursor_external_id || "—")}</strong></div>
                <span class="status-chip ${esc(state)}">${esc(statusNames[state] || state)}</span>
                <div class="operations-job-actions">
                    <button class="btn soft" data-op-view-extraction="${item.id}"><i class="fa-regular fa-eye"></i> مشاهده</button>
                    <button class="btn secondary" data-op-edit-extraction="${item.id}"><i class="fa-regular fa-pen-to-square"></i> ویرایش</button>
                    <button class="btn secondary" data-op-repeat-extraction="${item.id}"><i class="fa-solid fa-copy"></i> تکرار</button>
                    <button class="btn primary" data-op-run-extraction="${item.id}"><i class="fa-solid fa-play"></i> اجرا</button>
                </div>
            </article>
        `;
    }

    async function loadExtractionJobs() {
        const box = document.getElementById("extractionJobsList");
        if (!box) return;
        box.innerHTML = '<div class="loading-box">در حال دریافت جاب‌های استخراج...</div>';
        try {
            const data = await api("/api/v2/operations/extraction-jobs");
            extractionJobs = data.jobs || [];
            box.innerHTML = extractionJobs.length ? extractionJobs.map(extractionCard).join("") : '<div class="empty-inline">هنوز جاب استخراجی وجود ندارد.</div>';
            const select = document.getElementById("transferExtractionJob");
            if (select) {
                select.innerHTML = `<option value="">انتخاب جاب استخراج</option>${extractionJobs.map((item) => `<option value="${item.id}">${esc(item.name)} (${number(item.content_count)} محتوا)</option>`).join("")}`;
            }
        } catch (error) {
            box.innerHTML = `<div class="empty-inline">${esc(error.message)}</div>`;
        }
    }

    function extractionEditForm(data) {
        const job = data.job;
        return `
            <form class="operation-edit-form" data-edit-extraction-form="${job.id}">
                <label>نام جاب<input name="name" value="${esc(job.name || "")}" required></label>
                <label>اکانت<select name="source_account_id" required>${accountOptions(job.source_account_id)}</select></label>
                <label class="full">منبع<input name="source_ref" dir="ltr" value="${esc(job.source_ref || "")}" required></label>
                <label>روش شروع<select name="start_mode">
                    ${["all", "date", "message_id", "incremental", "legacy"].map((mode) => `<option value="${mode}" ${job.start_mode === mode ? "selected" : ""}>${esc(modeNames[mode] || mode)}</option>`).join("")}
                </select></label>
                <label>حداکثر پیام<input name="max_items" type="number" min="1" max="5000" value="${esc(job.config?.max_items || 250)}"></label>
                <label>تاریخ شمسی جدید<input name="start_date_jalali" placeholder="۱۴۰۵/۰۷/۱۴"></label>
                <label>Message ID<input name="start_external_id" type="number" min="1" value="${esc(job.start_external_id || "")}"></label>
                <div class="form-actions"><button class="btn primary" type="submit">ذخیره تغییرات</button></div>
            </form>
        `;
    }

    async function openExtractionWorkspace(id, tab = "summary") {
        const workspace = document.getElementById("extractionJobWorkspace");
        const body = document.getElementById("extractionWorkspaceBody");
        if (!workspace || !body) return;
        workspace.hidden = false;
        body.innerHTML = '<div class="loading-box">در حال ساخت داشبورد جاب...</div>';
        workspace.scrollIntoView({ behavior: "smooth", block: "start" });
        try {
            const data = await api(`/api/v2/operations/extraction-jobs/${id}/dashboard`);
            document.getElementById("extractionWorkspaceTitle").textContent = data.job.name || `جاب استخراج #${id}`;
            const stats = data.stats || {};
            body.innerHTML = `
                <div class="job-stat-grid">
                    <article><span>کل محتوا</span><strong>${number(stats.total)}</strong></article>
                    <article><span>متن</span><strong>${number(stats.text)}</strong></article>
                    <article><span>تصویر</span><strong>${number(stats.photo)}</strong></article>
                    <article><span>ویدئو</span><strong>${number(stats.video)}</strong></article>
                    <article><span>تعداد اجرا</span><strong>${number((data.runs || []).length)}</strong></article>
                </div>
                ${workspaceTabs("extraction", [
                    { key: "summary", label: "مشخصات" }, { key: "items", label: `پست‌ها (${number(stats.total)})` },
                    { key: "logs", label: "لاگ جاب" }, { key: "edit", label: "ویرایش" },
                ])}
                <div class="workspace-panel" data-workspace-panel="extraction:summary">
                    <div class="settings-row"><span>منبع</span><code>${esc(data.job.source_ref || "—")}</code></div>
                    <div class="settings-row"><span>روش شروع</span><strong>${esc(modeNames[data.job.start_mode] || data.job.start_mode)}</strong></div>
                    <div class="settings-row"><span>Cursor</span><code>${esc(data.job.cursor_external_id || "—")}</code></div>
                    <div class="settings-row"><span>آخرین موفقیت</span><strong>${esc(data.job.last_success_at || "—")}</strong></div>
                </div>
                <div class="workspace-panel" data-workspace-panel="extraction:items" hidden>
                    <div class="job-content-list">${(data.items || []).length ? data.items.map((item) => contentRow(item)).join("") : '<div class="empty-inline">محتوایی برای این جاب نیست.</div>'}</div>
                </div>
                <div class="workspace-panel" data-workspace-panel="extraction:logs" hidden>${logRows(data.logs)}</div>
                <div class="workspace-panel" data-workspace-panel="extraction:edit" hidden>${extractionEditForm(data)}</div>
            `;
            activateTab(`extraction:${tab}`);
        } catch (error) {
            body.innerHTML = `<div class="empty-inline">${esc(error.message)}</div>`;
        }
    }

    function transferCard(item) {
        const state = String(item.status || "draft");
        const counts = item.counts || {};
        const destinations = item.destinations || [];
        const providerText = destinations.length
            ? destinations.map((destination) => destination.provider_label).join("، ")
            : "بدون مقصد";
        return `
            <article class="v2-job-card operations-job-card">
                <div class="v2-job-title">
                    <strong>${esc(item.name || `انتقال #${item.id}`)}</strong>
                    <small>${number(destinations.length)} مقصد · ${esc(providerText)}</small>
                </div>
                <div class="v2-job-metric"><span>در فهرست</span><strong>${number(counts.listed)}</strong></div>
                <div class="v2-job-metric"><span>در حال انتقال</span><strong>${number(counts.transferring)}</strong></div>
                <div class="v2-job-metric"><span>منتقل‌شده</span><strong>${number(counts.transferred)}</strong></div>
                <span class="status-chip ${esc(state)}">${esc(statusNames[state] || state)}</span>
                <div class="operations-job-actions">
                    <button class="btn soft" data-op-view-transfer="${item.id}"><i class="fa-regular fa-eye"></i> مشاهده</button>
                    <button class="btn secondary" data-op-edit-transfer="${item.id}"><i class="fa-regular fa-pen-to-square"></i> ویرایش</button>
                    <button class="btn secondary" data-op-repeat-transfer="${item.id}"><i class="fa-solid fa-copy"></i> تکرار</button>
                    <button class="btn primary" data-op-run-transfer="${item.id}"><i class="fa-solid fa-play"></i> اجرا / ادامه</button>
                </div>
            </article>
        `;
    }

    async function loadTransferJobs() {
        const box = document.getElementById("transferJobsList");
        if (!box) return;
        box.innerHTML = '<div class="loading-box">در حال دریافت جاب‌های انتقال...</div>';
        try {
            const data = await api("/api/v2/operations/transfer-jobs");
            transferJobs = data.jobs || [];
            box.innerHTML = transferJobs.length ? transferJobs.map(transferCard).join("") : '<div class="empty-inline">هنوز جاب انتقالی وجود ندارد.</div>';
        } catch (error) {
            box.innerHTML = `<div class="empty-inline">${esc(error.message)}</div>`;
        }
    }

    function transferEditForm(data) {
        const job = data.job;
        return `
            <form class="operation-edit-form" data-edit-transfer-form="${job.id}">
                <label>نام جاب<input name="name" value="${esc(job.name || "")}" required></label>
                <div class="transfer-destinations-editor full">
                    <div class="transfer-destinations-head">
                        <div><strong>پروایدرها و مقصدهای جاب</strong><small>ویرایش مقصدها صف انتقال را بازسازی می‌کند.</small></div>
                        <button type="button" class="btn secondary" data-add-edit-destination>اضافه‌کردن پروایدر</button>
                    </div>
                    <div class="transfer-destinations-list" data-edit-destinations-list></div>
                </div>
                <div class="form-actions"><button class="btn primary" type="submit">ذخیره و بازنشانی صف</button></div>
            </form>
        `;
    }

    function destinationSummary(destinations) {
        if (!(destinations || []).length) return '<div class="empty-inline">مقصدی ثبت نشده است.</div>';
        return `<div class="destination-summary-list">${destinations.map((item) => `
            <div class="destination-summary-card">
                <strong>${esc(item.provider_label || item.provider_code)}</strong>
                <code dir="ltr">${esc(item.destination_ref || "—")}</code>
                <small>فهرست: ${number(item.counts?.listed)}</small>
                <small>در حال انتقال: ${number(item.counts?.transferring)}</small>
                <small>منتقل: ${number(item.counts?.transferred)}</small>
                <small>خطا: ${number(item.counts?.failed)}</small>
            </div>
        `).join("")}</div>`;
    }

    async function openTransferWorkspace(id, tab = "summary") {
        const workspace = document.getElementById("transferJobWorkspace");
        const body = document.getElementById("transferWorkspaceBody");
        if (!workspace || !body) return;
        workspace.hidden = false;
        body.innerHTML = '<div class="loading-box">در حال ساخت داشبورد انتقال...</div>';
        workspace.scrollIntoView({ behavior: "smooth", block: "start" });
        try {
            const data = await api(`/api/v2/operations/transfer-jobs/${id}/dashboard`);
            document.getElementById("transferWorkspaceTitle").textContent = data.job.name || `جاب انتقال #${id}`;
            const counts = data.counts || {};
            body.innerHTML = `
                <div class="job-stat-grid">
                    <article><span>کل فهرست</span><strong>${number(counts.total)}</strong></article>
                    <article><span>در فهرست</span><strong>${number(counts.listed)}</strong></article>
                    <article><span>در حال انتقال</span><strong>${number(counts.transferring)}</strong></article>
                    <article><span>منتقل‌شده</span><strong>${number(counts.transferred)}</strong></article>
                    <article><span>خطادار</span><strong>${number(counts.failed)}</strong></article>
                </div>
                ${workspaceTabs("transfer", [
                    { key: "summary", label: "مشخصات" }, { key: "items", label: `وضعیت پست‌ها (${number(counts.total)})` },
                    { key: "logs", label: "لاگ جاب" }, { key: "edit", label: "ویرایش" },
                ])}
                <div class="workspace-panel" data-workspace-panel="transfer:summary">
                    <div class="settings-row"><span>وضعیت</span><strong>${esc(statusNames[data.job.status] || data.job.status)}</strong></div>
                    <div class="settings-row"><span>تعداد مقصدها</span><strong>${number((data.destinations || []).length)}</strong></div>
                    <div class="settings-row"><span>تعداد اجرا</span><strong>${number((data.runs || []).length)}</strong></div>
                    ${destinationSummary(data.destinations)}
                </div>
                <div class="workspace-panel" data-workspace-panel="transfer:items" hidden>
                    <div class="job-content-list">${(data.items || []).length ? data.items.map((item) => contentRow(item, true)).join("") : '<div class="empty-inline">هنوز پستی وارد فهرست انتقال نشده است.</div>'}</div>
                </div>
                <div class="workspace-panel" data-workspace-panel="transfer:logs" hidden>${logRows(data.logs)}</div>
                <div class="workspace-panel" data-workspace-panel="transfer:edit" hidden>${transferEditForm(data)}</div>
            `;
            hydrateDestinationRows(body.querySelector("[data-edit-destinations-list]"), data.destinations || []);
            activateTab(`transfer:${tab}`);
        } catch (error) {
            body.innerHTML = `<div class="empty-inline">${esc(error.message)}</div>`;
        }
    }

    function activateTab(key) {
        const [kind] = key.split(":");
        document.querySelectorAll(`[data-workspace-tab^="${kind}:"]`).forEach((button) => button.classList.toggle("active", button.dataset.workspaceTab === key));
        document.querySelectorAll(`[data-workspace-panel^="${kind}:"]`).forEach((panel) => { panel.hidden = panel.dataset.workspacePanel !== key; });
    }

    async function loadContentLibrary() {
        const box = document.getElementById("contentLibraryList");
        if (!box) return;
        const query = document.getElementById("contentSearch")?.value.trim() || "";
        box.innerHTML = '<div class="loading-box">در حال دریافت کتابخانه محتوا...</div>';
        try {
            const data = await api(`/api/v2/content-library${query ? `?q=${encodeURIComponent(query)}` : ""}`);
            const items = data.items || [];
            document.getElementById("contentLibraryCount").textContent = number(items.length);
            document.getElementById("contentHashtagCount").textContent = number(items.filter((item) => item.hashtags?.length).length);
            document.getElementById("contentMediaCount").textContent = number(items.filter((item) => item.content_type !== "text").length);
            box.innerHTML = items.length ? items.map((item) => contentRow(item)).join("") : '<div class="empty-inline">محتوایی پیدا نشد.</div>';
        } catch (error) {
            box.innerHTML = `<div class="empty-inline">${esc(error.message)}</div>`;
        }
    }

    async function repeatJob(kind, id, button) {
        setBusy(button, true, "در حال تکرار...");
        try {
            const result = await api(`/api/v2/operations/${kind}-jobs/${id}/repeat`, { method: "POST", body: "{}" });
            notify(`${result.message} شماره ${number(result.job_id)}`);
            await (kind === "extraction" ? loadExtractionJobs() : loadTransferJobs());
        } catch (error) { notify(error.message, "error"); }
        finally { setBusy(button, false); }
    }

    async function runExtraction(id, button) {
        setBusy(button, true, "در حال استخراج...");
        try {
            const result = await api(`/api/v2/extraction-jobs/${id}/run`, { method: "POST", body: "{}" });
            notify(`${result.message} ${number(result.inserted)} جدید و ${number(result.updated)} بروزرسانی.`);
        } catch (error) { notify(error.message, "error"); }
        finally { setBusy(button, false); await loadExtractionJobs(); }
    }

    async function runTransfer(id, button) {
        setBusy(button, true, "در حال انتقال...");
        try {
            const result = await api(`/api/v2/operations/transfer-jobs/${id}/run`, { method: "POST", body: "{}" });
            notify(`${result.message} ${number(result.counts?.transferred)} منتقل شد.`);
        } catch (error) { notify(error.message, "error"); }
        finally { setBusy(button, false); await loadTransferJobs(); }
    }

    async function createTransfer(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const button = document.getElementById("createTransferJob");
        const payload = Object.fromEntries(new FormData(form).entries());
        payload.extraction_job_id = Number(payload.extraction_job_id);
        const container = document.getElementById("transferDestinationsBuilder");
        payload.destinations = collectDestinations(container);
        if (!payload.destinations.length) {
            notify("حداقل یک پروایدر و مقصد اضافه کنید.", "error");
            return;
        }
        setBusy(button, true, "در حال ساخت...");
        try {
            const result = await api("/api/v2/operations/transfer-jobs", { method: "POST", body: JSON.stringify(payload) });
            notify(`${result.message} شماره ${number(result.job_id)}`);
            form.reset();
            hydrateDestinationRows(container);
            document.getElementById("transferBuilder").hidden = true;
            await loadTransferJobs();
        } catch (error) { notify(error.message, "error"); }
        finally { setBusy(button, false); }
    }

    async function loadTelegramBotSettings() {
        const form = document.getElementById("telegramBotSettingsForm");
        if (!form) return;
        try {
            const data = await api("/api/settings/telegram-bot");
            document.getElementById("telegramBotChatId").value = data.chat_id || "";
            document.getElementById("telegramBotTokenCurrent").textContent = data.token_masked
                ? `ذخیره‌شده: ${data.token_masked}`
                : "توکن ربات تلگرام ذخیره نشده است.";
            const badge = document.getElementById("telegramBotStatusBadge");
            badge.textContent = data.configured ? "آماده" : "تنظیم نشده";
            badge.className = data.configured ? "badge success" : "badge warning";
        } catch (error) {
            notify(error.message, "error");
        }
    }

    async function saveTelegramBotSettings(event) {
        event.preventDefault();
        const button = document.getElementById("saveTelegramBotSettings");
        setBusy(button, true, "در حال ذخیره...");
        try {
            const result = await api("/api/settings/telegram-bot", {
                method: "POST",
                body: JSON.stringify({
                    token: document.getElementById("telegramBotToken").value.trim(),
                    chat_id: document.getElementById("telegramBotChatId").value.trim(),
                }),
            });
            document.getElementById("telegramBotToken").value = "";
            notify(result.message);
            await loadTelegramBotSettings();
            await loadTransferProviders();
        } catch (error) {
            notify(error.message, "error");
        } finally {
            setBusy(button, false);
        }
    }

    async function testTelegramBotSettings(button) {
        setBusy(button, true, "در حال تست...");
        try {
            const result = await api("/api/settings/telegram-bot/test", {
                method: "POST",
                body: JSON.stringify({ chat_id: document.getElementById("telegramBotChatId").value.trim() }),
            });
            notify(result.message);
        } catch (error) {
            notify(error.message, "error");
        } finally {
            setBusy(button, false);
        }
    }

    document.getElementById("openExtractorBuilder")?.addEventListener("click", () => { document.getElementById("extractorBuilder").hidden = false; });
    document.getElementById("closeExtractorBuilder")?.addEventListener("click", () => { document.getElementById("extractorBuilder").hidden = true; });
    document.getElementById("openTransferBuilder")?.addEventListener("click", () => {
        document.getElementById("transferBuilder").hidden = false;
        const container = document.getElementById("transferDestinationsBuilder");
        if (container && !container.children.length) hydrateDestinationRows(container);
    });
    document.getElementById("closeTransferBuilder")?.addEventListener("click", () => { document.getElementById("transferBuilder").hidden = true; });
    document.getElementById("transferBuilderForm")?.addEventListener("submit", createTransfer);
    document.getElementById("telegramBotSettingsForm")?.addEventListener("submit", saveTelegramBotSettings);
    document.getElementById("testTelegramBotSettings")?.addEventListener("click", function () { testTelegramBotSettings(this); });
    document.getElementById("addTransferDestination")?.addEventListener("click", () => {
        addDestinationRow(document.getElementById("transferDestinationsBuilder"));
    });
    document.getElementById("reloadExtractionJobs")?.addEventListener("click", loadExtractionJobs);
    document.getElementById("reloadTransferJobs")?.addEventListener("click", loadTransferJobs);
    document.getElementById("reloadContentLibrary")?.addEventListener("click", loadContentLibrary);
    document.getElementById("contentSearch")?.addEventListener("keydown", (event) => { if (event.key === "Enter") loadContentLibrary(); });
    document.addEventListener("teltest:extraction-changed", loadExtractionJobs);

    document.addEventListener("submit", async (event) => {
        const extraction = event.target.closest("[data-edit-extraction-form]");
        if (extraction) {
            event.preventDefault();
            const id = extraction.dataset.editExtractionForm;
            const payload = Object.fromEntries(new FormData(extraction).entries());
            try {
                const result = await api(`/api/v2/operations/extraction-jobs/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
                notify(result.message); await loadExtractionJobs(); await openExtractionWorkspace(id, "summary");
            } catch (error) { notify(error.message, "error"); }
            return;
        }
        const transfer = event.target.closest("[data-edit-transfer-form]");
        if (transfer) {
            event.preventDefault();
            const id = transfer.dataset.editTransferForm;
            const payload = Object.fromEntries(new FormData(transfer).entries());
            payload.destinations = collectDestinations(transfer.querySelector("[data-edit-destinations-list]"));
            if (!payload.destinations.length) {
                notify("حداقل یک پروایدر و مقصد لازم است.", "error");
                return;
            }
            try {
                const result = await api(`/api/v2/operations/transfer-jobs/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
                notify(result.message); await loadTransferJobs(); await openTransferWorkspace(id, "summary");
            } catch (error) { notify(error.message, "error"); }
        }
    });

    document.addEventListener("click", (event) => {
        const addEditDestination = event.target.closest("[data-add-edit-destination]");
        if (addEditDestination) {
            addDestinationRow(addEditDestination.closest("form")?.querySelector("[data-edit-destinations-list]"));
            return;
        }
        const removeDestination = event.target.closest("[data-remove-transfer-destination]");
        if (removeDestination) {
            const list = removeDestination.closest(".transfer-destinations-list");
            removeDestination.closest("[data-transfer-destination-row]")?.remove();
            if (list && !list.children.length) addDestinationRow(list);
            return;
        }
        const tab = event.target.closest("[data-workspace-tab]");
        if (tab) { activateTab(tab.dataset.workspaceTab); return; }
        const close = event.target.closest("[data-close-workspace]");
        if (close) { document.getElementById(`${close.dataset.closeWorkspace}JobWorkspace`).hidden = true; return; }
        const actions = [
            ["opViewExtraction", (id, btn) => openExtractionWorkspace(id, "summary")],
            ["opEditExtraction", (id, btn) => openExtractionWorkspace(id, "edit")],
            ["opRepeatExtraction", (id, btn) => repeatJob("extraction", id, btn)],
            ["opRunExtraction", runExtraction],
            ["opViewTransfer", (id, btn) => openTransferWorkspace(id, "summary")],
            ["opEditTransfer", (id, btn) => openTransferWorkspace(id, "edit")],
            ["opRepeatTransfer", (id, btn) => repeatJob("transfer", id, btn)],
            ["opRunTransfer", runTransfer],
        ];
        for (const [key, handler] of actions) {
            const attr = key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
            const button = event.target.closest(`[data-${attr}]`);
            if (button) { handler(button.dataset[key], button); break; }
        }
    });

    document.addEventListener("change", (event) => {
        const provider = event.target.closest("[data-destination-provider]");
        if (provider) configureDestinationRow(provider.closest("[data-transfer-destination-row]"), "copy");
    });

    Promise.all([loadMeta(), loadTransferProviders(), loadTelegramBotSettings()])
        .then(() => {
            const builder = document.getElementById("transferDestinationsBuilder");
            hydrateDestinationRows(builder);
            return Promise.all([loadExtractionJobs(), loadTransferJobs(), loadContentLibrary()]);
        })
        .catch((error) => notify(error.message, "error"));
})();
