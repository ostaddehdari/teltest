(() => {
    "use strict";

    const BASE =
        "/teltest";

    const csrf =
        document.querySelector(
            'meta[name="csrf-token"]'
        )?.content || "";


    let selectorMeta = {
        sources: [],
        hashtags: [],
        saved_searches: [],
    };


    let capturedSearch =
        null;


    const manualIds =
        new Set();


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


        const data =
            await response.json();


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


        setTimeout(
            () =>
                item.classList.add(
                    "hide"
                ),
            4500
        );


        setTimeout(
            () =>
                item.remove(),
            5000
        );

    }


    function updateManualCount() {

        const count =
            manualIds.size;


        const a =
            document.getElementById(
                "manualContentSelectionCount"
            );


        if (a) {
            a.textContent =
                number(
                    count
                );
        }


        const b =
            document.getElementById(
                "transferManualCount"
            );


        if (b) {
            b.textContent =
                `${number(count)} مورد انتخاب شده`;
        }

    }


    window.teltestStage12IsSelected =
        function isSelected(id) {

            return manualIds.has(
                Number(id)
            );

        };


    function currentType() {

        return (
            document
                .getElementById(
                    "transferSelectorType"
                )
                ?.value
            || "extraction_job"
        );

    }


    function showSelectorPanel() {

        const type =
            currentType();


        document.querySelectorAll(
            "[data-transfer-selector-panel]"
        ).forEach(
            (panel) => {

                panel.hidden =
                    panel.dataset
                        .transferSelectorPanel
                    !== type;

            }
        );


        const preview =
            document.getElementById(
                "transferSelectorPreview"
            );


        if (preview) {

            preview.textContent =
                "هنوز بررسی نشده";

            preview.className =
                "badge";

        }

    }


    function searchSummary(
        filters
    ) {

        if (!filters) {
            return "فیلتر ثبت نشده است.";
        }


        const parts = [];


        if (filters.q) {
            parts.push(
                `متن: ${filters.q}`
            );
        }


        if (filters.source_key) {
            parts.push(
                "منبع انتخاب‌شده"
            );
        }


        if (filters.hashtag) {
            parts.push(
                `هشتگ: ${filters.hashtag}`
            );
        }


        if (filters.content_type) {
            parts.push(
                `نوع: ${filters.content_type}`
            );
        }


        if (filters.media) {
            parts.push(
                `رسانه: ${filters.media}`
            );
        }


        if (filters.has_link) {
            parts.push(
                `لینک: ${filters.has_link}`
            );
        }


        if (filters.from_jalali) {
            parts.push(
                `از ${filters.from_jalali}`
            );
        }


        if (filters.to_jalali) {
            parts.push(
                `تا ${filters.to_jalali}`
            );
        }


        return (
            parts.length
                ? parts.join(" · ")
                : "فیلتر خالی"
        );

    }


    window.teltestBuildTransferSelector =
        function buildTransferSelector() {

            const type =
                currentType();


            if (
                type === "extraction_job"
            ) {

                const id =
                    Number(
                        document
                            .getElementById(
                                "transferExtractionJob"
                            )
                            ?.value
                    );


                if (!id) {
                    throw new Error(
                        "جاب استخراج را انتخاب کنید."
                    );
                }


                return {
                    selector_type:
                        type,

                    selector: {
                        extraction_job_id:
                            id,
                    },
                };

            }


            if (
                type === "source"
            ) {

                const raw =
                    document
                        .getElementById(
                            "transferSourceSelector"
                        )
                        ?.value
                    || "";


                if (!raw) {
                    throw new Error(
                        "منبع را انتخاب کنید."
                    );
                }


                const [
                    connector,
                    sourceKey,
                ] = raw.split(
                    "::"
                );


                return {
                    selector_type:
                        type,

                    selector: {
                        connector:
                            connector,

                        source_key:
                            sourceKey,
                    },
                };

            }


            if (
                type === "hashtag"
            ) {

                const hashtag =
                    document
                        .getElementById(
                            "transferHashtagSelector"
                        )
                        ?.value
                        .trim()
                    || "";


                if (!hashtag) {
                    throw new Error(
                        "هشتگ را وارد کنید."
                    );
                }


                return {
                    selector_type:
                        type,

                    selector: {
                        hashtag:
                            hashtag,
                    },
                };

            }


            if (
                type === "search"
            ) {

                if (!capturedSearch) {

                    capturedSearch = (
                        window
                            .teltestStage11CurrentFilters
                        ? window
                            .teltestStage11CurrentFilters()
                        : null
                    );

                }


                if (!capturedSearch) {
                    throw new Error(
                        "فیلتر کتابخانه را انتخاب کنید."
                    );
                }


                return {
                    selector_type:
                        type,

                    selector: {
                        filters:
                            capturedSearch,
                    },
                };

            }


            if (
                type === "saved_search"
            ) {

                const id =
                    Number(
                        document
                            .getElementById(
                                "transferSavedSearchSelector"
                            )
                            ?.value
                    );


                if (!id) {
                    throw new Error(
                        "جستجوی ذخیره‌شده را انتخاب کنید."
                    );
                }


                return {
                    selector_type:
                        type,

                    selector: {
                        saved_search_id:
                            id,
                    },
                };

            }


            if (
                type === "manual"
            ) {

                const ids =
                    [
                        ...manualIds
                    ];


                if (!ids.length) {
                    throw new Error(
                        "هیچ محتوایی انتخاب نشده است."
                    );
                }


                return {
                    selector_type:
                        type,

                    selector: {
                        content_ids:
                            ids,
                    },
                };

            }


            throw new Error(
                "روش انتخاب معتبر نیست."
            );

        };


    async function previewSelector() {

        const badge =
            document.getElementById(
                "transferSelectorPreview"
            );


        try {

            const selector =
                window
                    .teltestBuildTransferSelector();


            if (badge) {

                badge.textContent =
                    "در حال بررسی...";

            }


            const data =
                await api(
                    "/api/v2/transfer-selectors/preview",
                    {
                        method:
                            "POST",

                        body:
                            JSON.stringify(
                                selector
                            ),
                    }
                );


            if (badge) {

                badge.textContent =
                    `${number(data.preview.count)} محتوا · ${number(data.preview.source_count)} منبع`;

                badge.className =
                    "badge success";

            }


            return data;


        } catch (error) {

            if (badge) {

                badge.textContent =
                    "انتخاب نامعتبر";

                badge.className =
                    "badge warning";

            }


            notify(
                error.message,
                "error"
            );


            throw error;

        }

    }


    async function loadMeta() {

        const data =
            await api(
                "/api/v2/transfer-selectors/meta"
            );


        selectorMeta =
            data;


        const sources =
            document.getElementById(
                "transferSourceSelector"
            );


        if (sources) {

            sources.innerHTML =
                `
                    <option value="">
                        انتخاب منبع
                    </option>
                `
                + (
                    data.sources
                    || []
                ).map(
                    (item) => `
                        <option
                            value="${esc(item.connector_code)}::${esc(item.source_key)}"
                        >
                            ${esc(
                                item.source_title
                                || item.source_ref
                                || item.source_key
                            )}
                            (${number(item.count)})
                        </option>
                    `
                ).join("");

        }


        const hashtags =
            document.getElementById(
                "transferHashtagOptions"
            );


        if (hashtags) {

            hashtags.innerHTML =
                (
                    data.hashtags
                    || []
                ).map(
                    (item) => `
                        <option
                            value="${esc(item.hashtag)}"
                        >
                            ${number(item.count)}
                        </option>
                    `
                ).join("");

        }


        const saved =
            document.getElementById(
                "transferSavedSearchSelector"
            );


        if (saved) {

            saved.innerHTML =
                `
                    <option value="">
                        انتخاب جستجوی ذخیره‌شده
                    </option>
                `
                + (
                    data.saved_searches
                    || []
                ).map(
                    (item) => `
                        <option value="${item.id}">
                            ${esc(item.name)}
                        </option>
                    `
                ).join("");

        }

    }


    document.addEventListener(
        "change",
        (event) => {

            const checkbox =
                event.target.closest(
                    "[data-library-select-content]"
                );


            if (checkbox) {

                const id =
                    Number(
                        checkbox.dataset
                            .librarySelectContent
                    );


                if (
                    checkbox.checked
                ) {

                    manualIds.add(
                        id
                    );

                } else {

                    manualIds.delete(
                        id
                    );

                }


                updateManualCount();

                return;

            }


            if (
                event.target.id
                === "transferSelectorType"
            ) {

                showSelectorPanel();

            }

        }
    );


    document
        .getElementById(
            "captureLibrarySearch"
        )
        ?.addEventListener(
            "click",
            () => {

                capturedSearch = (
                    window
                        .teltestStage11CurrentFilters
                    ? window
                        .teltestStage11CurrentFilters()
                    : null
                );


                const summary =
                    document.getElementById(
                        "transferSearchFilterSummary"
                    );


                if (summary) {

                    summary.textContent =
                        searchSummary(
                            capturedSearch
                        );

                }


                previewSelector()
                    .catch(
                        () => {}
                    );

            }
        );


    document
        .getElementById(
            "previewTransferSelector"
        )
        ?.addEventListener(
            "click",
            () => {

                previewSelector()
                    .catch(
                        () => {}
                    );

            }
        );


    document
        .getElementById(
            "createTransferFromSelected"
        )
        ?.addEventListener(
            "click",
            () => {

                if (
                    !manualIds.size
                ) {

                    notify(
                        "ابتدا محتواها را انتخاب کنید.",
                        "error"
                    );

                    return;

                }


                const selector =
                    document.getElementById(
                        "transferSelectorType"
                    );


                if (selector) {

                    selector.value =
                        "manual";

                    showSelectorPanel();

                }


                const builder =
                    document.getElementById(
                        "transferBuilder"
                    );


                if (builder) {

                    builder.hidden =
                        false;

                    builder.scrollIntoView(
                        {
                            behavior:
                                "smooth",

                            block:
                                "start",
                        }
                    );

                }


                previewSelector()
                    .catch(
                        () => {}
                    );

            }
        );


    updateManualCount();

    showSelectorPanel();


    loadMeta()
        .catch(
            (error) =>
                notify(
                    error.message,
                    "error"
                )
        );

})();
