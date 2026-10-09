(() => {
    "use strict";

    const BASE =
        "/teltest";

    const csrf =
        document.querySelector(
            'meta[name="csrf-token"]'
        )?.content || "";


    const state = {
        page:
            1,

        pages:
            1,

        total:
            0,

        meta:
            null,

        loading:
            false,
    };


    function esc(value) {

        const node =
            document.createElement(
                "div"
            );

        node.textContent =
            String(
                value ?? ""
            );

        return node.innerHTML;

    }


    function number(value) {

        return Number(
            value || 0
        ).toLocaleString(
            "fa-IR"
        );

    }


    function clip(
        value,
        length = 330
    ) {

        const text =
            String(
                value || ""
            ).trim();

        return (
            text.length > length
                ? `${text.slice(0, length)}…`
                : text
        );

    }


    async function api(
        path,
        options = {}
    ) {

        const method =
            String(
                options.method
                || "GET"
            ).toUpperCase();


        const headers = {
            Accept:
                "application/json",

            ...(
                options.headers
                || {}
            ),
        };


        if (
            ![
                "GET",
                "HEAD",
            ].includes(
                method
            )
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
                ok:
                    false,

                error:
                    `HTTP ${response.status}`,
            };

        }


        if (
            !response.ok
            || data.ok === false
        ) {

            throw new Error(
                data.error
                || `HTTP ${response.status}`
            );

        }


        return data;

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


        window.setTimeout(
            () =>
                item.classList.add(
                    "hide"
                ),
            4500
        );


        window.setTimeout(
            () =>
                item.remove(),
            5000
        );

    }


    function filters() {

        return {
            q:
                document
                    .getElementById(
                        "contentSearch"
                    )
                    ?.value
                    .trim()
                || "",

            connector:
                document
                    .getElementById(
                        "contentConnectorFilter"
                    )
                    ?.value
                || "",

            source_key:
                document
                    .getElementById(
                        "contentSourceFilter"
                    )
                    ?.value
                || "",

            hashtag:
                document
                    .getElementById(
                        "contentHashtagFilter"
                    )
                    ?.value
                    .trim()
                || "",

            content_type:
                document
                    .getElementById(
                        "contentTypeFilter"
                    )
                    ?.value
                || "",

            media:
                document
                    .getElementById(
                        "contentMediaFilter"
                    )
                    ?.value
                || "",

            has_link:
                document
                    .getElementById(
                        "contentLinkFilter"
                    )
                    ?.value
                || "",

            from_jalali:
                document
                    .getElementById(
                        "contentFromDate"
                    )
                    ?.value
                    .trim()
                || "",

            to_jalali:
                document
                    .getElementById(
                        "contentToDate"
                    )
                    ?.value
                    .trim()
                || "",

            sort:
                document
                    .getElementById(
                        "contentSort"
                    )
                    ?.value
                || "newest",
        };

    }


    function applyFilters(
        value
    ) {

        value =
            value || {};


        const mapping = {
            contentSearch:
                "q",

            contentConnectorFilter:
                "connector",

            contentSourceFilter:
                "source_key",

            contentHashtagFilter:
                "hashtag",

            contentTypeFilter:
                "content_type",

            contentMediaFilter:
                "media",

            contentLinkFilter:
                "has_link",

            contentFromDate:
                "from_jalali",

            contentToDate:
                "to_jalali",

            contentSort:
                "sort",
        };


        for (
            const [
                id,
                key,
            ]
            of Object.entries(
                mapping
            )
        ) {

            const element =
                document.getElementById(
                    id
                );

            if (!element) {
                continue;
            }

            element.value =
                value[key]
                ?? (
                    key === "sort"
                        ? "newest"
                        : ""
                );

        }

    }


    function searchParams() {

        const params =
            new URLSearchParams();


        for (
            const [
                key,
                value,
            ]
            of Object.entries(
                filters()
            )
        ) {

            if (
                value !== ""
                && value !== null
                && value !== undefined
            ) {

                params.set(
                    key,
                    value
                );

            }

        }


        params.set(
            "page",
            String(
                state.page
            )
        );


        params.set(
            "per_page",
            document
                .getElementById(
                    "contentPageSize"
                )
                ?.value
            || "24"
        );


        return params;

    }


    function hashtagHtml(
        hashtags
    ) {

        if (
            !Array.isArray(
                hashtags
            )
            || !hashtags.length
        ) {
            return "";
        }


        return `
            <div class="hashtag-list">
                ${hashtags.map(
                    (tag) =>
                        `<button
                            type="button"
                            class="hashtag-chip stage11-hashtag"
                            data-library-hashtag="${esc(tag)}"
                        >${esc(tag)}</button>`
                ).join("")}
            </div>
        `;

    }


    function linksHtml(
        links
    ) {

        if (
            !Array.isArray(
                links
            )
            || !links.length
        ) {
            return "";
        }


        return `
            <div class="content-link-list">
                ${links.map(
                    (item) => `
                        <span
                            class="content-link-chip"
                            title="${esc(item.url)}"
                        >
                            <i class="fa-solid fa-link"></i>
                            ${esc(item.domain || item.url)}
                        </span>
                    `
                ).join("")}
            </div>
        `;

    }


    function contentCard(
        item
    ) {

        const text =
            item.processed_text
            ?? item.raw_text
            ?? "";


        const original = (
            item.original_url
                ? `
                    <a
                        class="btn soft"
                        href="${esc(item.original_url)}"
                        target="_blank"
                        rel="noopener"
                    >
                        <i class="fa-solid fa-arrow-up-right-from-square"></i>
                        پست اصلی
                    </a>
                `
                : `
                    <button
                        class="btn soft"
                        disabled
                    >
                        لینک عمومی ندارد
                    </button>
                `
        );


        return `
            <article class="content-row stage11-content-card">

                <div class="content-row-main">

                    <div class="content-row-head">

                        <button
                            type="button"
                            class="content-source-button"
                            data-library-source="${esc(item.source_key || "")}"
                        >
                            ${esc(
                                item.source_title
                                || item.source_ref
                                || item.connector_code
                            )}
                        </button>

                        <small class="ltr">
                            #${esc(item.external_id)}
                        </small>

                        <small>
                            ${esc(item.published_at || "بدون تاریخ")}
                        </small>

                        <span class="badge">
                            ${esc(item.connector_code)}
                        </span>

                        <span class="badge">
                            ${esc(item.content_type)}
                        </span>

                    </div>


                    <p class="content-row-text">
                        ${esc(
                            clip(text)
                            || `[${item.content_type || "محتوا"}]`
                        )}
                    </p>


                    ${hashtagHtml(item.hashtags)}

                    ${linksHtml(item.links)}

                </div>


                <div class="content-row-actions">

                    ${original}

                    <a
                        class="btn secondary"
                        href="${esc(item.download_url)}"
                    >
                        <i class="fa-solid fa-download"></i>
                        دانلود
                    </a>

                </div>

            </article>
        `;

    }


    function populateMeta(
        data
    ) {

        state.meta =
            data;


        const connector =
            document.getElementById(
                "contentConnectorFilter"
            );


        if (connector) {

            const current =
                connector.value;

            connector.innerHTML =
                `
                    <option value="">
                        همه منابع
                    </option>
                `
                + (
                    data.connectors
                    || []
                ).map(
                    (item) => `
                        <option value="${esc(item.code)}">
                            ${esc(item.name)}
                            (${number(item.count)})
                        </option>
                    `
                ).join("");

            connector.value =
                current;

        }


        const source =
            document.getElementById(
                "contentSourceFilter"
            );


        if (source) {

            const current =
                source.value;

            source.innerHTML =
                `
                    <option value="">
                        همه منابع
                    </option>
                `
                + (
                    data.sources
                    || []
                ).map(
                    (item) => `
                        <option value="${esc(item.source_key)}">
                            ${esc(
                                item.source_title
                                || item.source_ref
                                || item.source_key
                            )}
                            (${number(item.count)})
                        </option>
                    `
                ).join("");

            source.value =
                current;

        }


        const type =
            document.getElementById(
                "contentTypeFilter"
            );


        if (type) {

            const current =
                type.value;

            type.innerHTML =
                `
                    <option value="">
                        همه انواع
                    </option>
                `
                + (
                    data.types
                    || []
                ).map(
                    (item) => `
                        <option value="${esc(item.content_type)}">
                            ${esc(item.content_type)}
                            (${number(item.count)})
                        </option>
                    `
                ).join("");

            type.value =
                current;

        }


        const hashtagOptions =
            document.getElementById(
                "contentHashtagOptions"
            );


        if (hashtagOptions) {

            hashtagOptions.innerHTML =
                (
                    data.hashtags
                    || []
                ).map(
                    (item) => `
                        <option value="${esc(item.hashtag)}">
                            ${number(item.count)}
                        </option>
                    `
                ).join("");

        }


        const total =
            document.getElementById(
                "contentLibraryTotal"
            );


        if (total) {
            total.textContent =
                number(
                    data.total
                );
        }


        const sourceCount =
            document.getElementById(
                "contentSourceCount"
            );


        if (sourceCount) {
            sourceCount.textContent =
                number(
                    (
                        data.sources
                        || []
                    ).length
                );
        }


        const hashtagCount =
            document.getElementById(
                "contentHashtagCount"
            );


        if (hashtagCount) {
            hashtagCount.textContent =
                number(
                    (
                        data.hashtags
                        || []
                    ).length
                );
        }

    }


    async function loadMeta() {

        const data =
            await api(
                "/api/v2/content-library/meta"
            );


        populateMeta(
            data
        );


        return data;

    }


    function renderPagination(
        pagination
    ) {

        state.page =
            pagination.page;

        state.pages =
            pagination.pages;

        state.total =
            pagination.total;


        const count =
            document.getElementById(
                "contentLibraryCount"
            );


        if (count) {
            count.textContent =
                number(
                    pagination.total
                );
        }


        const indicator =
            document.getElementById(
                "contentPageIndicator"
            );


        if (indicator) {
            indicator.textContent =
                `${number(pagination.page)} / ${number(pagination.pages)}`;
        }


        const text =
            document.getElementById(
                "contentPaginationText"
            );


        if (text) {
            text.textContent =
                `صفحه ${number(pagination.page)} از ${number(pagination.pages)}`;
        }


        const previous =
            document.getElementById(
                "contentPreviousPage"
            );


        if (previous) {
            previous.disabled =
                !pagination.has_previous;
        }


        const next =
            document.getElementById(
                "contentNextPage"
            );


        if (next) {
            next.disabled =
                !pagination.has_next;
        }

    }


    async function loadLibrary() {

        if (state.loading) {
            return;
        }


        const box =
            document.getElementById(
                "contentLibraryList"
            );


        if (!box) {
            return;
        }


        state.loading =
            true;


        box.innerHTML =
            `
                <div class="loading-box">
                    در حال جستجو در آرشیو...
                </div>
            `;


        try {

            const params =
                searchParams();


            const data =
                await api(
                    `/api/v2/content-library/search?${params.toString()}`
                );


            renderPagination(
                data.pagination
            );


            const items =
                data.items || [];


            box.innerHTML = (
                items.length
                    ? items.map(
                        contentCard
                    ).join("")
                    : `
                        <div class="empty-inline">
                            محتوایی با این فیلترها پیدا نشد.
                        </div>
                    `
            );


        } catch (error) {

            box.innerHTML =
                `
                    <div class="empty-inline">
                        ${esc(error.message)}
                    </div>
                `;


            notify(
                error.message,
                "error"
            );


        } finally {

            state.loading =
                false;

        }

    }


    window.teltestStage11LoadLibrary =
        loadLibrary;


    function resetFilters() {

        applyFilters(
            {}
        );


        const pageSize =
            document.getElementById(
                "contentPageSize"
            );


        if (pageSize) {
            pageSize.value =
                "24";
        }


        state.page =
            1;


        loadLibrary();

    }


    async function loadSavedSearches() {

        const bar =
            document.getElementById(
                "savedSearchesBar"
            );


        if (!bar) {
            return;
        }


        try {

            const data =
                await api(
                    "/api/v2/content-library/saved-searches"
                );


            const searches =
                data.searches || [];


            bar.innerHTML = (
                searches.length
                    ? searches.map(
                        (item) => `
                            <div class="saved-search-chip">
                                <button
                                    type="button"
                                    data-saved-search='${esc(JSON.stringify(item.filters || {}))}'
                                >
                                    <i class="fa-regular fa-bookmark"></i>
                                    ${esc(item.name)}
                                </button>

                                <button
                                    type="button"
                                    class="delete"
                                    data-delete-saved-search="${item.id}"
                                    title="حذف"
                                >
                                    <i class="fa-solid fa-xmark"></i>
                                </button>
                            </div>
                        `
                    ).join("")
                    : ""
            );


        } catch (error) {

            bar.innerHTML =
                "";

        }

    }


    async function saveSearch() {

        const name =
            document
                .getElementById(
                    "savedSearchName"
                )
                ?.value
                .trim()
            || "";


        if (!name) {

            notify(
                "برای جستجوی ذخیره‌شده یک نام وارد کنید.",
                "error"
            );

            return;
        }


        try {

            const data =
                await api(
                    "/api/v2/content-library/saved-searches",
                    {
                        method:
                            "POST",

                        body:
                            JSON.stringify(
                                {
                                    name:
                                        name,

                                    filters:
                                        filters(),
                                }
                            ),
                    }
                );


            notify(
                data.message
            );


            document.getElementById(
                "savedSearchName"
            ).value =
                "";


            await loadSavedSearches();


        } catch (error) {

            notify(
                error.message,
                "error"
            );

        }

    }


    document
        .getElementById(
            "applyContentFilters"
        )
        ?.addEventListener(
            "click",
            () => {

                state.page =
                    1;

                loadLibrary();

            }
        );


    document
        .getElementById(
            "resetContentFilters"
        )
        ?.addEventListener(
            "click",
            resetFilters
        );


    document
        .getElementById(
            "saveCurrentSearch"
        )
        ?.addEventListener(
            "click",
            saveSearch
        );


    document
        .getElementById(
            "contentPreviousPage"
        )
        ?.addEventListener(
            "click",
            () => {

                if (
                    state.page > 1
                ) {

                    state.page -= 1;

                    loadLibrary();

                }

            }
        );


    document
        .getElementById(
            "contentNextPage"
        )
        ?.addEventListener(
            "click",
            () => {

                if (
                    state.page
                    < state.pages
                ) {

                    state.page += 1;

                    loadLibrary();

                }

            }
        );


    document
        .getElementById(
            "contentPageSize"
        )
        ?.addEventListener(
            "change",
            () => {

                state.page =
                    1;

                loadLibrary();

            }
        );


    [
        "contentConnectorFilter",
        "contentSourceFilter",
        "contentTypeFilter",
        "contentMediaFilter",
        "contentLinkFilter",
        "contentSort",
    ].forEach(
        (id) => {

            document
                .getElementById(
                    id
                )
                ?.addEventListener(
                    "change",
                    () => {

                        state.page =
                            1;

                        loadLibrary();

                    }
                );

        }
    );


    document.addEventListener(
        "click",
        async (event) => {

            const hashtag =
                event.target.closest(
                    "[data-library-hashtag]"
                );


            if (hashtag) {

                document.getElementById(
                    "contentHashtagFilter"
                ).value =
                    hashtag.dataset.libraryHashtag;

                state.page =
                    1;

                loadLibrary();

                return;

            }


            const source =
                event.target.closest(
                    "[data-library-source]"
                );


            if (source) {

                document.getElementById(
                    "contentSourceFilter"
                ).value =
                    source.dataset.librarySource;

                state.page =
                    1;

                loadLibrary();

                return;

            }


            const saved =
                event.target.closest(
                    "[data-saved-search]"
                );


            if (saved) {

                try {

                    applyFilters(
                        JSON.parse(
                            saved.dataset.savedSearch
                            || "{}"
                        )
                    );


                    state.page =
                        1;


                    loadLibrary();


                } catch (_error) {
                }


                return;

            }


            const remove =
                event.target.closest(
                    "[data-delete-saved-search]"
                );


            if (remove) {

                try {

                    const data =
                        await api(
                            `/api/v2/content-library/saved-searches/${remove.dataset.deleteSavedSearch}`,
                            {
                                method:
                                    "DELETE",

                                body:
                                    "{}",
                            }
                        );


                    notify(
                        data.message
                    );


                    await loadSavedSearches();


                } catch (error) {

                    notify(
                        error.message,
                        "error"
                    );

                }

            }

        }
    );


    Promise.all(
        [
            loadMeta(),
            loadSavedSearches(),
        ]
    )
        .then(
            () =>
                loadLibrary()
        )
        .catch(
            (error) =>
                notify(
                    error.message,
                    "error"
                )
        );

})();
