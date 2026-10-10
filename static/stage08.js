(() => {
    "use strict";

    const BASE = "/teltest";
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const monthNames = [
        "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
        "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
    ];
    const weekNames = ["ش", "ی", "د", "س", "چ", "پ", "ج"];
    const modeNames = {
        all: "آخرین پیام‌ها",
        date: "از تاریخ شمسی",
        message_id: "از Message ID",
        incremental: "افزایشی",
        legacy: "مهاجرت‌شده",
    };
    const statusNames = {
        draft: "پیش‌نویس",
        pending: "در انتظار",
        running: "در حال اجرا",
        completed: "تکمیل‌شده",
        watching: "در حال پایش",
        failed: "خطادار",
        paused: "متوقف",
    };

    let calendarYear;
    let calendarMonth;

    function esc(value) {
        const node = document.createElement("div");
        node.textContent = String(value ?? "");
        return node.innerHTML;
    }

    function number(value) {
        return Number(value || 0).toLocaleString("fa-IR");
    }

    function latin(value) {
        return String(value || "").replace(/[۰-۹٠-٩]/g, (digit) => {
            const fa = "۰۱۲۳۴۵۶۷۸۹".indexOf(digit);
            if (fa >= 0) return String(fa);
            return String("٠١٢٣٤٥٦٧٨٩".indexOf(digit));
        });
    }

    async function api(path, options = {}) {
        const method = String(options.method || "GET").toUpperCase();
        const headers = { Accept: "application/json", ...(options.headers || {}) };
        if (method !== "GET" && method !== "HEAD") {
            headers["Content-Type"] = "application/json";
            headers["X-CSRF-Token"] = csrf;
        }
        const response = await fetch(`${BASE}${path}`, { ...options, method, headers });
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
        window.setTimeout(() => item.classList.add("hide"), 4500);
        window.setTimeout(() => item.remove(), 5000);
    }

    function g2j(gy, gm, gd) {
        const offsets = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
        const gy2 = gm > 2 ? gy + 1 : gy;
        let days = 355666 + (365 * gy) + Math.floor((gy2 + 3) / 4)
            - Math.floor((gy2 + 99) / 100) + Math.floor((gy2 + 399) / 400)
            + gd + offsets[gm - 1];
        let jy = -1595 + (33 * Math.floor(days / 12053));
        days %= 12053;
        jy += 4 * Math.floor(days / 1461);
        days %= 1461;
        if (days > 365) {
            jy += Math.floor((days - 1) / 365);
            days = (days - 1) % 365;
        }
        const jm = days < 186 ? 1 + Math.floor(days / 31) : 7 + Math.floor((days - 186) / 30);
        const jd = days < 186 ? 1 + (days % 31) : 1 + ((days - 186) % 30);
        return [jy, jm, jd];
    }

    function j2g(jy, jm, jd) {
        jy += 1595;
        let days = -355668 + (365 * jy) + (Math.floor(jy / 33) * 8)
            + Math.floor(((jy % 33) + 3) / 4) + jd
            + (jm < 7 ? (jm - 1) * 31 : ((jm - 7) * 30) + 186);
        let gy = 400 * Math.floor(days / 146097);
        days %= 146097;
        if (days > 36524) {
            days -= 1;
            gy += 100 * Math.floor(days / 36524);
            days %= 36524;
            if (days >= 365) days += 1;
        }
        gy += 4 * Math.floor(days / 1461);
        days %= 1461;
        if (days > 365) {
            gy += Math.floor((days - 1) / 365);
            days = (days - 1) % 365;
        }
        let gd = days + 1;
        const leap = (gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0;
        const lengths = [0, 31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
        let gm = 1;
        while (gm <= 12 && gd > lengths[gm]) {
            gd -= lengths[gm];
            gm += 1;
        }
        return [gy, gm, gd];
    }

    function monthLength(year, month) {
        if (month <= 6) return 31;
        if (month <= 11) return 30;
        const [gy, gm, gd] = j2g(year, 12, 30);
        const back = g2j(gy, gm, gd);
        return back[0] === year && back[1] === 12 && back[2] === 30 ? 30 : 29;
    }

    function selectedDate() {
        const value = latin(document.getElementById("extractorPersianDate")?.value);
        const match = value.match(/^(\d{4})\/(\d{1,2})\/(\d{1,2})$/);
        return match ? match.slice(1).map(Number) : null;
    }

    function renderCalendar() {
        const box = document.getElementById("persianCalendar");
        if (!box) return;
        const [gy, gm, gd] = j2g(calendarYear, calendarMonth, 1);
        const firstDay = (new Date(Date.UTC(gy, gm - 1, gd)).getUTCDay() + 1) % 7;
        const count = monthLength(calendarYear, calendarMonth);
        const chosen = selectedDate();
        const now = new Date();
        const today = g2j(now.getFullYear(), now.getMonth() + 1, now.getDate());
        const cells = [];
        for (let index = 0; index < firstDay; index += 1) cells.push("<i></i>");
        for (let day = 1; day <= count; day += 1) {
            const isToday = today[0] === calendarYear && today[1] === calendarMonth && today[2] === day;
            const isSelected = chosen && chosen[0] === calendarYear && chosen[1] === calendarMonth && chosen[2] === day;
            cells.push(`<button type="button" class="${isToday ? "today" : ""} ${isSelected ? "selected" : ""}" data-persian-day="${day}">${number(day)}</button>`);
        }
        box.innerHTML = `
            <div class="persian-calendar-head">
                <button type="button" data-calendar-next aria-label="ماه بعد">‹</button>
                <div class="persian-calendar-title">${monthNames[calendarMonth - 1]} ${number(calendarYear)}</div>
                <button type="button" data-calendar-prev aria-label="ماه قبل">›</button>
            </div>
            <div class="persian-calendar-grid">
                ${weekNames.map((item) => `<span>${item}</span>`).join("")}
                ${cells.join("")}
            </div>
        `;
    }

    function openCalendar() {
        const box = document.getElementById("persianCalendar");
        if (!box) return;
        const chosen = selectedDate();
        if (chosen) {
            [calendarYear, calendarMonth] = chosen;
        } else {
            const now = new Date();
            [calendarYear, calendarMonth] = g2j(now.getFullYear(), now.getMonth() + 1, now.getDate());
        }
        renderCalendar();
        box.hidden = !box.hidden;
    }

    function chooseDate(day) {
        const input = document.getElementById("extractorPersianDate");
        const box = document.getElementById("persianCalendar");
        if (!input || !box) return;
        input.value = `${calendarYear}/${String(calendarMonth).padStart(2, "0")}/${String(day).padStart(2, "0")}`;
        box.hidden = true;
    }

    function updateWatchFields() {

        const enabled =
            document.getElementById(
                "extractorWatchEnabled"
            )?.checked || false;

        const field =
            document.getElementById(
                "watchIntervalField"
            );

        const input =
            document.getElementById(
                "extractorPollInterval"
            );

        if (field) {
            field.hidden = !enabled;
        }

        if (input) {
            input.required = enabled;
        }

    }


    function updateModeFields() {
        const mode = document.querySelector('input[name="start_mode"]:checked')?.value || "all";
        const dateField = document.getElementById("persianDateField");
        const messageField = document.getElementById("messageIdField");
        if (dateField) dateField.hidden = mode !== "date";
        if (messageField) messageField.hidden = mode !== "message_id";
        document.getElementById("extractorPersianDate")?.toggleAttribute("required", mode === "date");
        document.getElementById("extractorMessageId")?.toggleAttribute("required", mode === "message_id");
    }

    function updateConnectorFields() {
        const kind = document.getElementById("extractorConnector")?.value || "telegram";
        const account = document.getElementById("extractorAccount");
        if (account) {
            account.required = kind === "telegram";
            account.disabled = kind === "eitaa";
            account.closest(".form-field").hidden = kind === "eitaa";
        }
        const source = document.getElementById("extractorSource");
        if (source) source.placeholder = kind === "eitaa" ? "@channel یا https://eitaa.com/channel" : "@channel یا -1001234567890";
    }
    document.getElementById("extractorConnector")?.addEventListener("change", updateConnectorFields);
    updateConnectorFields();

    async function loadMeta() {
        const select = document.getElementById("extractorAccount");
        if (!select) return;
        const data = await api("/api/v2/telegram-extractor/meta");
        const accounts = data.accounts || [];
        select.innerHTML = accounts.length
            ? `<option value="">انتخاب اکانت</option>${accounts.map((item) => `<option value="${item.id}">${esc(item.display_name || item.username || item.phone || `اکانت ${item.id}`)}</option>`).join("")}`
            : '<option value="">اکانت متصل وجود ندارد</option>';

        const source = document.getElementById("extractorSource");
        if (source) {
            const listId = "telegramSourceOptions";
            let list = document.getElementById(listId);
            if (!list) {
                list = document.createElement("datalist");
                list.id = listId;
                source.after(list);
                source.setAttribute("list", listId);
            }
            list.innerHTML = (data.channels || []).map((item) => {
                const value = item.username ? `@${item.username}` : item.entity_id;
                return `<option value="${esc(value)}">${esc(item.title || value)}</option>`;
            }).join("");
        }
    }

    function jobCard(item) {
        const state = String(item.status || "draft");
        const config = item.config || {};
        const canRun = item.connector_code === "eitaa" || (item.connector_code === "telegram" && item.source_account_id);
        return `
            <article class="v2-job-card extractor-v2-card" data-extractor-job="${item.id}">
                <div class="v2-job-title">
                    <strong>${esc(item.name || `استخراج #${item.id}`)}</strong>
                    <small class="ltr">${esc(item.source_ref || "—")}</small>
                </div>
                <div class="v2-job-metric">
                    <span>شروع</span>
                    <strong>${esc(modeNames[item.start_mode] || item.start_mode)}</strong>
                </div>
                <div class="v2-job-metric">
                    <span>محتوا</span>
                    <strong>${number(item.content_count)}</strong>
                </div>
                <div class="v2-job-metric">
                    <span>Cursor</span>
                    <strong class="cursor-value">${esc(item.cursor_external_id || "—")}</strong>
                </div>
                <span class="status-chip ${esc(state)}">${esc(statusNames[state] || state)}</span>
                <div class="extractor-card-actions">
                    ${canRun ? `<button type="button" class="btn primary" data-run-extractor="${item.id}"><i class="fa-solid fa-play" aria-hidden="true"></i> اجرا</button>` : ""}
                    <button type="button" class="btn soft" data-show-content="${item.id}">محتوا</button>
                    <button type="button" class="btn soft" data-stage09-rules="${item.id}">
                        <i class="fa-solid fa-wand-magic-sparkles"></i>
                        قوانین
                    </button>
                </div>
                <div class="run-result" data-run-result="${item.id}" hidden>
                    <span>سقف اجرا: ${number(config.max_items || 250)}</span>
                    <span>آخرین موفقیت: ${esc(item.last_success_at || "—")}</span>
                    <span>
                        پایش:
                        ${item.watch_enabled
                            ? `هر ${number(item.poll_interval_minutes || 5)} دقیقه`
                            : "خاموش"}
                    </span>
                    ${item.watch_enabled
                        ? `<span>اجرای بعدی: ${esc(item.next_run_at || "در انتظار")}</span>`
                        : ""}
                </div>
            </article>
        `;
    }

    async function loadJobs() {
        const box = document.getElementById("extractionJobsList");
        if (!box) return;
        box.innerHTML = '<div class="loading-box">در حال دریافت جاب‌های استخراج...</div>';
        try {
            const data = await api("/api/v2/extraction-jobs");
            const jobs = data.jobs || [];
            box.innerHTML = jobs.length ? jobs.map(jobCard).join("") : '<div class="empty-v2">هنوز جاب استخراجی ثبت نشده است.</div>';
        } catch (error) {
            box.innerHTML = `<div class="empty-v2">${esc(error.message)}</div>`;
        }
    }

    async function createJob(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const button = document.getElementById("createExtractorJob");
        const data = Object.fromEntries(new FormData(form).entries());

        if (window.teltestCollectContentRules) {
            data.rules =
                window.teltestCollectContentRules(
                    "extraction"
                );
        }

        data.max_items = Number(latin(data.max_items));
        data.source_account_id = data.connector_code === "eitaa" ? null : Number(latin(data.source_account_id));
        if (data.start_external_id) data.start_external_id = Number(latin(data.start_external_id));
        if (button) {
            button.disabled = true;
            button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> در حال ساخت...';
        }
        try {
            const result = await api("/api/v2/extraction-jobs", {
                method: "POST",
                body: JSON.stringify(data),
            });
            notify(`${result.message} شماره ${number(result.job_id)}`);
            form.reset();
            updateConnectorFields();

            document.getElementById(
                "extractorLimit"
            ).value = "250";

            document.getElementById(
                "extractorPollInterval"
            ).value = "5";

            updateModeFields();
            updateWatchFields();
            document.dispatchEvent(new CustomEvent("teltest:extraction-changed"));
        } catch (error) {
            notify(error.message, "error");
        } finally {
            if (button) {
                button.disabled = false;
                button.innerHTML = '<i class="fa-solid fa-plus"></i> ساخت جاب';
            }
        }
    }

    async function runJob(id, button) {
        const original = button.innerHTML;
        button.disabled = true;
        button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> استخراج...';
        try {
            const result = await api(`/api/v2/extraction-jobs/${id}/run`, {
                method: "POST",
                body: "{}",
            });
            notify(`${result.message} ${number(result.inserted)} جدید، ${number(result.updated)} بروزرسانی.`);
            await loadJobs();
        } catch (error) {
            notify(error.message, "error");
            await loadJobs();
        } finally {
            if (button.isConnected) {
                button.disabled = false;
                button.innerHTML = original;
            }
        }
    }

    async function showContent(id, button) {
        const card = button.closest("[data-extractor-job]");
        const resultBox = card?.querySelector(`[data-run-result="${id}"]`);
        if (!resultBox) return;
        button.disabled = true;
        try {
            const data = await api(`/api/v2/extraction-jobs/${id}/content`);
            const preview = (data.items || []).slice(0, 3).map((item) => {
                const text = String(item.raw_text || `[${item.content_type}]`).slice(0, 90);
                return `<span>#${esc(item.external_id)} · ${esc(text)}</span>`;
            }).join("");
            resultBox.innerHTML = preview || "<span>هنوز محتوایی ذخیره نشده است.</span>";
            resultBox.hidden = false;
        } catch (error) {
            notify(error.message, "error");
        } finally {
            button.disabled = false;
        }
    }

    document.querySelectorAll('input[name="start_mode"]').forEach((item) => {
        item.addEventListener("change", updateModeFields);
    });
    document.getElementById(
        "extractorWatchEnabled"
    )?.addEventListener(
        "change",
        updateWatchFields
    );

    document.getElementById("openPersianDatePicker")?.addEventListener("click", openCalendar);
    document.getElementById("telegramExtractorForm")?.addEventListener("submit", createJob);
    document.getElementById("refreshExtractorMeta")?.addEventListener("click", async () => {
        try {
            await loadMeta();
            notify("اکانت‌ها و منابع تلگرام بروزرسانی شدند.");
        } catch (error) {
            notify(error.message, "error");
        }
    });

    document.addEventListener("click", (event) => {
        const day = event.target.closest("[data-persian-day]");
        if (day) {
            chooseDate(Number(day.dataset.persianDay));
            return;
        }
        if (event.target.closest("[data-calendar-prev]")) {
            calendarMonth -= 1;
            if (calendarMonth < 1) { calendarMonth = 12; calendarYear -= 1; }
            renderCalendar();
            return;
        }
        if (event.target.closest("[data-calendar-next]")) {
            calendarMonth += 1;
            if (calendarMonth > 12) { calendarMonth = 1; calendarYear += 1; }
            renderCalendar();
            return;
        }
        const run = event.target.closest("[data-run-extractor]");
        if (run) {
            runJob(run.dataset.runExtractor, run);
            return;
        }
        const content = event.target.closest("[data-show-content]");
        if (content) showContent(content.dataset.showContent, content);
    });

    updateModeFields();
    updateWatchFields();
    loadMeta().catch((error) => notify(error.message, "error"));
})();
