(() => {

    "use strict";


    const BASE =
        "/teltest";


    const csrf =
        document
            .querySelector(
                'meta[name="csrf-token"]'
            )
            ?.getAttribute(
                "content"
            )
        || "";


    let metaCache = {
        accounts: [],
        channels: [],
    };


    let jobsCache = [];


    function esc(value) {

        const div =
            document.createElement(
                "div"
            );

        div.textContent =
            String(
                value ?? ""
            );

        return div.innerHTML;

    }


    function notify(
        message,
        type = "success"
    ) {

        const container =
            document.getElementById(
                "toastContainer"
            );


        if (!container) {
            alert(message);
            return;
        }


        const item =
            document.createElement(
                "div"
            );


        item.className =
            `toast ${type}`;


        item.textContent =
            message;


        container.appendChild(
            item
        );


        setTimeout(
            () => {
                item.classList.add(
                    "hide"
                );
            },
            4500
        );


        setTimeout(
            () => {
                item.remove();
            },
            5000
        );

    }


    async function api(
        path,
        options = {}
    ) {

        const method =
            (
                options.method
                || "GET"
            ).toUpperCase();


        const headers = {
            Accept:
                "application/json",
            ...(options.headers || {}),
        };


        if (
            method !== "GET"
            && method !== "HEAD"
        ) {

            headers[
                "Content-Type"
            ] = "application/json";

            headers[
                "X-CSRF-Token"
            ] = csrf;

        }


        const response =
            await fetch(
                `${BASE}${path}`,
                {
                    ...options,
                    method,
                    headers,
                }
            );


        let data;


        try {

            data =
                await response.json();

        } catch (_error) {

            data = {
                ok: false,
                error:
                    `HTTP ${response.status}`,
            };

        }


        if (!response.ok) {

            throw new Error(
                data.error
                || `HTTP ${response.status}`
            );

        }


        return data;

    }


    function busy(
        button,
        state,
        text = "در حال اجرا..."
    ) {

        if (!button) {
            return;
        }


        if (state) {

            button.dataset.oldText =
                button.textContent;

            button.disabled = true;

            button.textContent =
                text;

        } else {

            button.disabled = false;

            button.textContent =
                button.dataset.oldText
                || "اجرا";

        }

    }


    function installJobPanel() {

        const panel =
            document.querySelector(
                '[data-panel-content="jobs"]'
            );


        if (!panel) {
            return;
        }


        panel.innerHTML = `

            <div class="stage03-grid">

                <article class="surface">

                    <div class="surface-head">

                        <div>

                            <h2>
                                جاب جدید
                            </h2>

                            <p>
                                Source → Extract → Destination
                            </p>

                        </div>

                        <span class="badge success">
                            Stage 03
                        </span>

                    </div>


                    <form
                        id="jobForm"
                        class="stack-form"
                    >

                        <label>
                            اکانت Telethon
                        </label>

                        <select
                            id="jobAccount"
                            class="select-input"
                            required
                        ></select>


                        <label>
                            نام Job
                        </label>

                        <input
                            id="jobName"
                            class="text-input"
                            placeholder="اختیاری"
                        >


                        <label>
                            کانال مبدأ
                        </label>

                        <input
                            id="jobSource"
                            class="text-input ltr"
                            list="stage03ChannelRefs"
                            placeholder="@source یا https://t.me/source یا ID"
                            required
                        >


                        <p class="help-text">

                            اگر اکانت عضو Source نباشد،
                            برای کانال عمومی یا لینک دعوت
                            Join خودکار انجام می‌شود.

                        </p>


                        <label>
                            کانال مقصد
                        </label>

                        <input
                            id="jobDestination"
                            class="text-input ltr"
                            list="stage03ChannelRefs"
                            placeholder="@destination یا ID"
                            required
                        >


                        <label>
                            تعداد آخرین پیام‌ها
                        </label>

                        <input
                            id="jobLimit"
                            class="text-input ltr"
                            type="number"
                            value="100"
                            min="1"
                            max="5000"
                            required
                        >


                        <label>
                            ذخیره پست استخراجی
                        </label>

                        <div class="stage03-radio-row">

                            <label>

                                <input
                                    type="radio"
                                    name="storageMode"
                                    value="save"
                                    checked
                                >

                                ذخیره در دیتابیس

                            </label>


                            <label>

                                <input
                                    type="radio"
                                    name="storageMode"
                                    value="nosave"
                                >

                                عدم ذخیره

                            </label>

                        </div>


                        <button
                            id="createRunJob"
                            class="btn primary"
                            type="submit"
                        >
                            ساخت و اجرای Job
                        </button>

                    </form>


                    <datalist
                        id="stage03ChannelRefs"
                    ></datalist>

                </article>


                <article class="surface">

                    <div class="surface-head">

                        <div>

                            <h2>
                                Stage 03
                            </h2>

                            <p>
                                وضعیت موتور استخراج
                            </p>

                        </div>

                    </div>


                    <div class="stage03-info">

                        <div>

                            <span>
                                Resolve
                            </span>

                            <strong>
                                فعال
                            </strong>

                        </div>

                        <div>

                            <span>
                                Auto Join
                            </span>

                            <strong>
                                فعال
                            </strong>

                        </div>

                        <div>

                            <span>
                                Extract
                            </span>

                            <strong>
                                تا 5000
                            </strong>

                        </div>

                        <div>

                            <span>
                                Forward
                            </span>

                            <strong>
                                Stage 04
                            </strong>

                        </div>

                    </div>

                </article>

            </div>


            <article class="surface stage03-jobs-box">

                <div class="surface-head">

                    <div>

                        <h2>
                            Job History
                        </h2>

                        <p>
                            آخرین 200 جاب
                        </p>

                    </div>

                    <button
                        id="reloadJobs"
                        class="btn secondary"
                        type="button"
                    >
                        بروزرسانی
                    </button>

                </div>


                <div class="table-wrap">

                    <table class="data-table">

                        <thead>

                            <tr>
                                <th>ID</th>
                                <th>نام</th>
                                <th>Source</th>
                                <th>Destination</th>
                                <th>Mode</th>
                                <th>Extract</th>
                                <th>زمان</th>
                                <th>Status</th>
                                <th>عملیات</th>
                            </tr>

                        </thead>

                        <tbody
                            id="jobsTableBody"
                        >

                            <tr>
                                <td
                                    colspan="9"
                                    class="table-empty"
                                >
                                    در حال دریافت...
                                </td>
                            </tr>

                        </tbody>

                    </table>

                </div>

            </article>
        `;

    }


    function installPostsPanel() {

        const panel =
            document.querySelector(
                '[data-panel-content="posts"]'
            );


        if (!panel) {
            return;
        }


        panel.innerHTML = `

            <article class="surface">

                <div class="surface-head stage03-post-head">

                    <div>

                        <h2>
                            پست‌های استخراجی
                        </h2>

                        <p>
                            پیام‌هایی که Storage Mode آنها Save بوده
                        </p>

                    </div>


                    <div class="channel-actions">

                        <select
                            id="postJobFilter"
                            class="select-input"
                        >

                            <option value="">
                                همه Jobها
                            </option>

                        </select>


                        <button
                            id="reloadPosts"
                            class="btn secondary"
                            type="button"
                        >
                            بروزرسانی
                        </button>

                    </div>

                </div>


                <div
                    id="postsSummary"
                    class="help-text"
                ></div>


                <div class="table-wrap">

                    <table class="data-table">

                        <thead>

                            <tr>
                                <th>Job</th>
                                <th>Message ID</th>
                                <th>تاریخ</th>
                                <th>نوع</th>
                                <th>متن</th>
                                <th>Views</th>
                            </tr>

                        </thead>

                        <tbody
                            id="postsTableBody"
                        >

                            <tr>

                                <td
                                    colspan="6"
                                    class="table-empty"
                                >
                                    هنوز پستی استخراج نشده است.
                                </td>

                            </tr>

                        </tbody>

                    </table>

                </div>

            </article>
        `;

    }


    async function loadMeta() {

        const data =
            await api(
                "/api/jobs/meta"
            );


        metaCache = data;


        const accountSelect =
            document.getElementById(
                "jobAccount"
            );


        if (accountSelect) {

            accountSelect.innerHTML = "";


            data.accounts.forEach(
                (account) => {

                    const option =
                        document.createElement(
                            "option"
                        );


                    option.value =
                        account.id;


                    option.textContent =
                        `${account.phone} — ${
                            account.display_name
                            || account.username
                            || "Telegram"
                        }`;


                    accountSelect.appendChild(
                        option
                    );

                }
            );


            if (
                data.accounts.length
                === 0
            ) {

                accountSelect.innerHTML = `
                    <option value="">
                        اکانت متصل وجود ندارد
                    </option>
                `;

            }

        }


        const datalist =
            document.getElementById(
                "stage03ChannelRefs"
            );


        if (datalist) {

            datalist.innerHTML = "";


            data.channels.forEach(
                (channel) => {

                    const option =
                        document.createElement(
                            "option"
                        );


                    option.value =
                        channel.username
                        ? `@${channel.username}`
                        : channel.entity_id;


                    option.label =
                        `${channel.title} — ${channel.kind}`;


                    datalist.appendChild(
                        option
                    );

                }
            );

        }

    }


    function statusBadge(
        status
    ) {

        const classes = {

            completed:
                "success",

            running:
                "warning",

            failed:
                "danger-badge",

            pending:
                "",

        };


        const labels = {

            completed:
                "کامل",

            running:
                "در حال اجرا",

            failed:
                "خطا",

            pending:
                "آماده",

        };


        return `
            <span class="badge ${
                classes[status]
                || ""
            }">
                ${
                    labels[status]
                    || esc(status)
                }
            </span>
        `;

    }


    function duration(
        value
    ) {

        if (
            value === null
            || value === undefined
        ) {
            return "—";
        }


        return (
            Number(value).toFixed(2)
            + "s"
        );

    }


    async function loadJobs() {

        const data =
            await api(
                "/api/jobs"
            );


        jobsCache =
            data.jobs;


        const tbody =
            document.getElementById(
                "jobsTableBody"
            );


        if (tbody) {

            if (
                data.jobs.length
                === 0
            ) {

                tbody.innerHTML = `
                    <tr>
                        <td
                            colspan="9"
                            class="table-empty"
                        >
                            هنوز Job ساخته نشده است.
                        </td>
                    </tr>
                `;

            } else {

                tbody.innerHTML =
                    data.jobs.map(
                        (job) => `

                        <tr>

                            <td class="ltr">
                                #${job.id}
                            </td>

                            <td>
                                ${esc(job.name)}
                            </td>

                            <td>

                                <strong>
                                    ${esc(
                                        job.source_title
                                        || job.source_ref
                                    )}
                                </strong>

                                ${
                                    job.joined_source
                                    ? '<small class="stage03-joined">JOINED</small>'
                                    : ""
                                }

                            </td>

                            <td>
                                ${esc(
                                    job.destination_title
                                    || job.destination_ref
                                )}
                            </td>

                            <td>
                                ${
                                    job.storage_mode
                                    === "save"
                                    ? "DB"
                                    : "No Save"
                                }
                            </td>

                            <td>
                                ${job.extracted_count}
                                / ${job.limit_count}
                            </td>

                            <td class="ltr">
                                ${duration(
                                    job.extraction_seconds
                                )}
                            </td>

                            <td>

                                ${statusBadge(
                                    job.status
                                )}

                                ${
                                    job.last_error
                                    ? `
                                        <div
                                            class="stage03-error"
                                            title="${esc(job.last_error)}"
                                        >
                                            ${esc(job.last_error)}
                                        </div>
                                    `
                                    : ""
                                }

                            </td>

                            <td>

                                <button
                                    class="btn secondary stage03-run-button"
                                    onclick="window.stage03RunJob(${job.id}, this)"
                                >
                                    ${
                                        job.status
                                        === "completed"
                                        ? "اجرای مجدد"
                                        : "اجرا"
                                    }
                                </button>

                            </td>

                        </tr>
                    `
                    ).join("");

            }

        }


        const filter =
            document.getElementById(
                "postJobFilter"
            );


        if (filter) {

            const current =
                filter.value;


            filter.innerHTML = `
                <option value="">
                    همه Jobها
                </option>
            `;


            data.jobs
                .filter(
                    (job) =>
                        job.storage_mode
                        === "save"
                )
                .forEach(
                    (job) => {

                        const option =
                            document.createElement(
                                "option"
                            );


                        option.value =
                            job.id;


                        option.textContent =
                            `#${job.id} — ${job.name}`;


                        filter.appendChild(
                            option
                        );

                    }
                );


            if (
                [
                    ...filter.options
                ].some(
                    (item) =>
                        item.value
                        === current
                )
            ) {

                filter.value =
                    current;

            }

        }

    }


    async function loadPosts() {

        const tbody =
            document.getElementById(
                "postsTableBody"
            );


        if (!tbody) {
            return;
        }


        const filter =
            document.getElementById(
                "postJobFilter"
            );


        const jobId =
            filter?.value
            || "";


        const suffix =
            jobId
            ? `?job_id=${encodeURIComponent(jobId)}`
            : "";


        const data =
            await api(
                `/api/posts${suffix}`
            );


        const summary =
            document.getElementById(
                "postsSummary"
            );


        if (summary) {

            summary.textContent =
                `${data.count} پست نمایش داده می‌شود.`;

        }


        if (
            data.posts.length
            === 0
        ) {

            tbody.innerHTML = `
                <tr>
                    <td
                        colspan="6"
                        class="table-empty"
                    >
                        پستی برای نمایش وجود ندارد.
                    </td>
                </tr>
            `;

            return;

        }


        tbody.innerHTML =
            data.posts.map(
                (post) => {

                    let text =
                        post.text
                        || "";


                    if (
                        text.length
                        > 180
                    ) {

                        text =
                            text.slice(
                                0,
                                180
                            )
                            + "…";

                    }


                    return `

                        <tr>

                            <td>
                                #${post.job_id}
                            </td>

                            <td class="ltr">
                                ${post.message_id}
                            </td>

                            <td class="ltr">
                                ${esc(
                                    post.message_date
                                    || "—"
                                )}
                            </td>

                            <td>
                                ${esc(
                                    post.media_type
                                )}
                            </td>

                            <td class="stage03-post-text">
                                ${esc(text)}
                            </td>

                            <td class="ltr">
                                ${
                                    post.views
                                    ?? "—"
                                }
                            </td>

                        </tr>
                    `;

                }
            ).join("");

    }


    window.stage03RunJob =
        async (
            jobId,
            button
        ) => {

            busy(
                button,
                true,
                "در حال استخراج..."
            );


            try {

                const result =
                    await api(
                        `/api/jobs/${jobId}/run`,
                        {
                            method:
                                "POST",

                            body:
                                "{}",
                        }
                    );


                notify(
                    result.message
                );


                if (
                    result.joined_source
                ) {

                    notify(
                        "اکانت با موفقیت عضو Source شد."
                    );

                }


                await loadMeta();

                await loadJobs();

                await loadPosts();


            } catch (error) {

                notify(
                    error.message,
                    "error"
                );


                await loadJobs();


            } finally {

                busy(
                    button,
                    false
                );

            }

        };


    async function createAndRun(
        event
    ) {

        event.preventDefault();


        const button =
            document.getElementById(
                "createRunJob"
            );


        const accountId =
            document.getElementById(
                "jobAccount"
            ).value;


        const sourceRef =
            document.getElementById(
                "jobSource"
            ).value.trim();


        const destinationRef =
            document.getElementById(
                "jobDestination"
            ).value.trim();


        const name =
            document.getElementById(
                "jobName"
            ).value.trim();


        const limit =
            Number(
                document.getElementById(
                    "jobLimit"
                ).value
            );


        const storageMode =
            document.querySelector(
                'input[name="storageMode"]:checked'
            )?.value
            || "save";


        if (
            !accountId
            || !sourceRef
            || !destinationRef
        ) {

            notify(
                "اکانت، Source و Destination را کامل کن.",
                "error"
            );

            return;

        }


        busy(
            button,
            true,
            "ساخت Job..."
        );


        try {

            const created =
                await api(
                    "/api/jobs",
                    {
                        method:
                            "POST",

                        body:
                            JSON.stringify(
                                {
                                    account_id:
                                        accountId,

                                    source_ref:
                                        sourceRef,

                                    destination_ref:
                                        destinationRef,

                                    name,

                                    limit_count:
                                        limit,

                                    storage_mode:
                                        storageMode,
                                }
                            ),
                    }
                );


            notify(
                created.message
            );


            busy(
                button,
                true,
                "در حال استخراج..."
            );


            const result =
                await api(
                    `/api/jobs/${created.job_id}/run`,
                    {
                        method:
                            "POST",

                        body:
                            "{}",
                    }
                );


            notify(
                result.message
            );


            await loadMeta();

            await loadJobs();

            await loadPosts();


        } catch (error) {

            notify(
                error.message,
                "error"
            );


            await loadJobs();


        } finally {

            busy(
                button,
                false
            );

        }

    }


    function bind() {

        document
            .getElementById(
                "jobForm"
            )
            ?.addEventListener(
                "submit",
                createAndRun
            );


        document
            .getElementById(
                "reloadJobs"
            )
            ?.addEventListener(
                "click",
                async () => {

                    await loadMeta();
                    await loadJobs();

                }
            );


        document
            .getElementById(
                "reloadPosts"
            )
            ?.addEventListener(
                "click",
                loadPosts
            );


        document
            .getElementById(
                "postJobFilter"
            )
            ?.addEventListener(
                "change",
                loadPosts
            );

    }


    async function boot() {

        installJobPanel();

        installPostsPanel();

        bind();


        try {

            await loadMeta();

            await loadJobs();

            await loadPosts();


        } catch (error) {

            console.error(
                error
            );

            notify(
                error.message,
                "error"
            );

        }

    }


    if (
        document.readyState
        === "loading"
    ) {

        document.addEventListener(
            "DOMContentLoaded",
            boot
        );

    } else {

        boot();

    }

})();
