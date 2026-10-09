(() => {
    "use strict";

    const BASE = "/teltest";
    const csrf =
        document.querySelector(
            'meta[name="csrf-token"]'
        )?.content || "";


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


    function lines(value) {

        return String(
            value || ""
        )
            .split(/\r?\n/)
            .map(
                (item) =>
                    item.trim()
            )
            .filter(Boolean);

    }


    function normalizedRules(
        value = {}
    ) {

        return {
            remove_all_links:
                Boolean(
                    value.remove_all_links
                ),

            remove_links_containing:
                Array.isArray(
                    value.remove_links_containing
                )
                    ? value.remove_links_containing
                    : [],

            exclude_text_containing:
                Array.isArray(
                    value.exclude_text_containing
                )
                    ? value.exclude_text_containing
                    : [],

            exclude_hashtags:
                Array.isArray(
                    value.exclude_hashtags
                )
                    ? value.exclude_hashtags
                    : [],

            exclude_links_containing:
                Array.isArray(
                    value.exclude_links_containing
                )
                    ? value.exclude_links_containing
                    : [],

            prefix_text:
                String(
                    value.prefix_text || ""
                ),

            suffix_text:
                String(
                    value.suffix_text || ""
                ),

            prefix_link:
                String(
                    value.prefix_link || ""
                ),

            suffix_link:
                String(
                    value.suffix_link || ""
                ),
        };

    }


    async function api(
        path,
        options = {}
    ) {

        const method =
            String(
                options.method || "GET"
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


    // --------------------------------------------------------
    // EXTRACTION BUILDER RULES
    // --------------------------------------------------------

    window.teltestCollectContentRules =
        function collectContentRules(
            type
        ) {

            if (
                type !== "extraction"
            ) {

                return normalizedRules();

            }


            return normalizedRules(
                {
                    remove_all_links:
                        document
                            .getElementById(
                                "ruleRemoveAllLinks"
                            )
                            ?.checked
                        || false,

                    remove_links_containing:
                        lines(
                            document
                                .getElementById(
                                    "ruleRemoveLinksContaining"
                                )
                                ?.value
                        ),

                    exclude_text_containing:
                        lines(
                            document
                                .getElementById(
                                    "ruleExcludeText"
                                )
                                ?.value
                        ),

                    exclude_hashtags:
                        lines(
                            document
                                .getElementById(
                                    "ruleExcludeHashtags"
                                )
                                ?.value
                        ),

                    exclude_links_containing:
                        lines(
                            document
                                .getElementById(
                                    "ruleExcludeLinks"
                                )
                                ?.value
                        ),

                    prefix_text:
                        document
                            .getElementById(
                                "rulePrefixText"
                            )
                            ?.value
                        || "",

                    suffix_text:
                        document
                            .getElementById(
                                "ruleSuffixText"
                            )
                            ?.value
                        || "",

                    prefix_link:
                        document
                            .getElementById(
                                "rulePrefixLink"
                            )
                            ?.value
                        || "",

                    suffix_link:
                        document
                            .getElementById(
                                "ruleSuffixLink"
                            )
                            ?.value
                        || "",
                }
            );

        };


    window.teltestResetContentRules =
        function resetContentRules(
            type
        ) {

            if (
                type !== "extraction"
            ) {
                return;
            }


            [
                "ruleRemoveLinksContaining",
                "ruleExcludeText",
                "ruleExcludeHashtags",
                "ruleExcludeLinks",
                "rulePrefixText",
                "ruleSuffixText",
                "rulePrefixLink",
                "ruleSuffixLink",
            ].forEach(
                (id) => {

                    const node =
                        document.getElementById(
                            id
                        );

                    if (node) {
                        node.value = "";
                    }

                }
            );


            const checkbox =
                document.getElementById(
                    "ruleRemoveAllLinks"
                );


            if (checkbox) {
                checkbox.checked =
                    false;
            }

        };


    // --------------------------------------------------------
    // DESTINATION INLINE RULES
    // --------------------------------------------------------

    function destinationEditorHtml(
        rules
    ) {

        rules =
            normalizedRules(
                rules
            );


        const join =
            (items) =>
                (items || [])
                    .join(
                        "\n"
                    );


        return `
            <details class="destination-rules-editor">
                <summary>
                    <span>
                        <i class="fa-solid fa-sliders"></i>
                        قوانین این مقصد
                    </span>
                    <small>اختیاری</small>
                </summary>

                <div class="destination-rules-grid">

                    <label class="rule-check full">
                        <input
                            type="checkbox"
                            data-dest-rule="remove_all_links"
                            ${rules.remove_all_links ? "checked" : ""}
                        >
                        حذف همه لینک‌ها
                    </label>

                    <label>
                        حذف لینک اگر شامل
                        <textarea
                            rows="2"
                            data-dest-rule="remove_links_containing"
                        >${esc(join(rules.remove_links_containing))}</textarea>
                    </label>

                    <label>
                        عدم ارسال اگر متن شامل
                        <textarea
                            rows="2"
                            data-dest-rule="exclude_text_containing"
                        >${esc(join(rules.exclude_text_containing))}</textarea>
                    </label>

                    <label>
                        عدم ارسال اگر هشتگ
                        <textarea
                            rows="2"
                            data-dest-rule="exclude_hashtags"
                        >${esc(join(rules.exclude_hashtags))}</textarea>
                    </label>

                    <label>
                        عدم ارسال اگر لینک شامل
                        <textarea
                            rows="2"
                            data-dest-rule="exclude_links_containing"
                        >${esc(join(rules.exclude_links_containing))}</textarea>
                    </label>

                    <label>
                        متن قبل
                        <textarea
                            rows="2"
                            data-dest-rule="prefix_text"
                        >${esc(rules.prefix_text)}</textarea>
                    </label>

                    <label>
                        لینک قبل
                        <input
                            type="text"
                            dir="ltr"
                            data-dest-rule="prefix_link"
                            value="${esc(rules.prefix_link)}"
                        >
                    </label>

                    <label>
                        متن بعد
                        <textarea
                            rows="2"
                            data-dest-rule="suffix_text"
                        >${esc(rules.suffix_text)}</textarea>
                    </label>

                    <label>
                        لینک بعد
                        <input
                            type="text"
                            dir="ltr"
                            data-dest-rule="suffix_link"
                            value="${esc(rules.suffix_link)}"
                        >
                    </label>

                </div>

                <p class="rule-help">
                    در Forward واقعی تلگرام، متن اصلی قابل تغییر نیست؛
                    Ruleهای عدم ارسال همچنان اعمال می‌شوند.
                </p>
            </details>
        `;

    }


    window.teltestHydrateDestinationRules =
        function hydrateDestinationRules(
            row,
            rules = {}
        ) {

            if (!row) {
                return;
            }


            let host =
                row.querySelector(
                    "[data-stage09-destination-rules]"
                );


            if (!host) {

                host =
                    document.createElement(
                        "div"
                    );

                host.dataset.stage09DestinationRules =
                    "1";

                host.className =
                    "destination-rules-host";

                row.appendChild(
                    host
                );

            }


            host.innerHTML =
                destinationEditorHtml(
                    rules
                );

        };


    window.teltestReadDestinationRules =
        function readDestinationRules(
            row
        ) {

            const value =
                (key) =>
                    row.querySelector(
                        `[data-dest-rule="${key}"]`
                    );


            return normalizedRules(
                {
                    remove_all_links:
                        value(
                            "remove_all_links"
                        )?.checked
                        || false,

                    remove_links_containing:
                        lines(
                            value(
                                "remove_links_containing"
                            )?.value
                        ),

                    exclude_text_containing:
                        lines(
                            value(
                                "exclude_text_containing"
                            )?.value
                        ),

                    exclude_hashtags:
                        lines(
                            value(
                                "exclude_hashtags"
                            )?.value
                        ),

                    exclude_links_containing:
                        lines(
                            value(
                                "exclude_links_containing"
                            )?.value
                        ),

                    prefix_text:
                        value(
                            "prefix_text"
                        )?.value
                        || "",

                    suffix_text:
                        value(
                            "suffix_text"
                        )?.value
                        || "",

                    prefix_link:
                        value(
                            "prefix_link"
                        )?.value
                        || "",

                    suffix_link:
                        value(
                            "suffix_link"
                        )?.value
                        || "",
                }
            );

        };


    // --------------------------------------------------------
    // EXTRACTION JOB RULE MODAL
    // --------------------------------------------------------

    function ensureModal() {

        let modal =
            document.getElementById(
                "contentRulesModal"
            );


        if (modal) {
            return modal;
        }


        modal =
            document.createElement(
                "div"
            );


        modal.id =
            "contentRulesModal";

        modal.className =
            "rule-modal";

        modal.hidden =
            true;


        modal.innerHTML = `
            <div
                class="rule-modal-backdrop"
                data-close-content-rules
            ></div>

            <article class="rule-modal-card">

                <div class="rule-modal-head">

                    <div>
                        <span class="eyebrow">
                            CONTENT RULES
                        </span>

                        <h3 id="contentRulesModalTitle">
                            قوانین محتوا
                        </h3>
                    </div>

                    <button
                        type="button"
                        class="btn ghost"
                        data-close-content-rules
                    >
                        <i class="fa-solid fa-xmark"></i>
                        بستن
                    </button>

                </div>


                <form
                    id="contentRulesModalForm"
                    class="modal-rules-grid"
                >

                    <input
                        id="modalRuleJobId"
                        type="hidden"
                    >


                    <label class="rule-check full">
                        <input
                            id="modalRemoveAllLinks"
                            type="checkbox"
                        >
                        حذف همه لینک‌ها از متن پردازش‌شده
                    </label>


                    <label>
                        حذف لینک اگر شامل
                        <textarea
                            id="modalRemoveLinks"
                            rows="3"
                        ></textarea>
                    </label>


                    <label>
                        فیلتر پیام اگر متن شامل
                        <textarea
                            id="modalExcludeText"
                            rows="3"
                        ></textarea>
                    </label>


                    <label>
                        فیلتر پیام اگر هشتگ دارد
                        <textarea
                            id="modalExcludeHashtags"
                            rows="3"
                        ></textarea>
                    </label>


                    <label>
                        فیلتر پیام اگر لینک شامل
                        <textarea
                            id="modalExcludeLinks"
                            rows="3"
                        ></textarea>
                    </label>


                    <label>
                        متن قبل
                        <textarea
                            id="modalPrefixText"
                            rows="2"
                        ></textarea>
                    </label>


                    <label>
                        لینک قبل
                        <input
                            id="modalPrefixLink"
                            type="text"
                            dir="ltr"
                        >
                    </label>


                    <label>
                        متن بعد
                        <textarea
                            id="modalSuffixText"
                            rows="2"
                        ></textarea>
                    </label>


                    <label>
                        لینک بعد
                        <input
                            id="modalSuffixLink"
                            type="text"
                            dir="ltr"
                        >
                    </label>


                    <div class="modal-rule-actions full">

                        <button
                            type="submit"
                            class="btn primary"
                        >
                            ذخیره قوانین
                        </button>

                        <button
                            type="button"
                            class="btn secondary"
                            id="reapplyContentRules"
                        >
                            اعمال دوباره روی محتوای موجود
                        </button>

                    </div>

                </form>

            </article>
        `;


        document.body.appendChild(
            modal
        );


        modal.querySelectorAll(
            "[data-close-content-rules]"
        ).forEach(
            (button) => {

                button.addEventListener(
                    "click",
                    () => {
                        modal.hidden =
                            true;
                    }
                );

            }
        );


        modal
            .querySelector(
                "#contentRulesModalForm"
            )
            .addEventListener(
                "submit",
                saveModalRules
            );


        modal
            .querySelector(
                "#reapplyContentRules"
            )
            .addEventListener(
                "click",
                reapplyModalRules
            );


        return modal;

    }


    function modalRules() {

        return normalizedRules(
            {
                remove_all_links:
                    document
                        .getElementById(
                            "modalRemoveAllLinks"
                        )
                        ?.checked
                    || false,

                remove_links_containing:
                    lines(
                        document
                            .getElementById(
                                "modalRemoveLinks"
                            )
                            ?.value
                    ),

                exclude_text_containing:
                    lines(
                        document
                            .getElementById(
                                "modalExcludeText"
                            )
                            ?.value
                    ),

                exclude_hashtags:
                    lines(
                        document
                            .getElementById(
                                "modalExcludeHashtags"
                            )
                            ?.value
                    ),

                exclude_links_containing:
                    lines(
                        document
                            .getElementById(
                                "modalExcludeLinks"
                            )
                            ?.value
                    ),

                prefix_text:
                    document
                        .getElementById(
                            "modalPrefixText"
                        )
                        ?.value
                    || "",

                suffix_text:
                    document
                        .getElementById(
                            "modalSuffixText"
                        )
                        ?.value
                    || "",

                prefix_link:
                    document
                        .getElementById(
                            "modalPrefixLink"
                        )
                        ?.value
                    || "",

                suffix_link:
                    document
                        .getElementById(
                            "modalSuffixLink"
                        )
                        ?.value
                    || "",
            }
        );

    }


    function fillModal(
        rules
    ) {

        rules =
            normalizedRules(
                rules
            );


        document.getElementById(
            "modalRemoveAllLinks"
        ).checked =
            rules.remove_all_links;


        document.getElementById(
            "modalRemoveLinks"
        ).value =
            rules
                .remove_links_containing
                .join(
                    "\n"
                );


        document.getElementById(
            "modalExcludeText"
        ).value =
            rules
                .exclude_text_containing
                .join(
                    "\n"
                );


        document.getElementById(
            "modalExcludeHashtags"
        ).value =
            rules
                .exclude_hashtags
                .join(
                    "\n"
                );


        document.getElementById(
            "modalExcludeLinks"
        ).value =
            rules
                .exclude_links_containing
                .join(
                    "\n"
                );


        document.getElementById(
            "modalPrefixText"
        ).value =
            rules.prefix_text;


        document.getElementById(
            "modalSuffixText"
        ).value =
            rules.suffix_text;


        document.getElementById(
            "modalPrefixLink"
        ).value =
            rules.prefix_link;


        document.getElementById(
            "modalSuffixLink"
        ).value =
            rules.suffix_link;

    }


    async function openRulesModal(
        jobId
    ) {

        const modal =
            ensureModal();


        modal.hidden =
            false;


        document.getElementById(
            "contentRulesModalTitle"
        ).textContent =
            `قوانین جاب استخراج #${jobId}`;


        document.getElementById(
            "modalRuleJobId"
        ).value =
            jobId;


        try {

            const data =
                await api(
                    `/api/v2/operations/extraction-jobs/${jobId}/rules`
                );


            document.getElementById(
                "contentRulesModalTitle"
            ).textContent =
                data.name
                || `قوانین جاب #${jobId}`;


            fillModal(
                data.rules
            );


        } catch (error) {

            notify(
                error.message,
                "error"
            );

            modal.hidden =
                true;

        }

    }


    async function saveModalRules(
        event
    ) {

        event.preventDefault();


        const jobId =
            Number(
                document.getElementById(
                    "modalRuleJobId"
                ).value
            );


        try {

            const data =
                await api(
                    `/api/v2/operations/extraction-jobs/${jobId}/rules`,
                    {
                        method:
                            "PATCH",

                        body:
                            JSON.stringify(
                                {
                                    rules:
                                        modalRules(),
                                }
                            ),
                    }
                );


            notify(
                data.message
            );


        } catch (error) {

            notify(
                error.message,
                "error"
            );

        }

    }


    async function reapplyModalRules(
        event
    ) {

        const button =
            event.currentTarget;


        const jobId =
            Number(
                document.getElementById(
                    "modalRuleJobId"
                ).value
            );


        const original =
            button.innerHTML;


        button.disabled =
            true;

        button.textContent =
            "در حال پردازش...";


        try {

            await api(
                `/api/v2/operations/extraction-jobs/${jobId}/rules`,
                {
                    method:
                        "PATCH",

                    body:
                        JSON.stringify(
                            {
                                rules:
                                    modalRules(),
                            }
                        ),
                }
            );


            const data =
                await api(
                    `/api/v2/operations/extraction-jobs/${jobId}/rules/reapply`,
                    {
                        method:
                            "POST",

                        body:
                            "{}",
                    }
                );


            notify(
                `${data.included} فعال، ${data.excluded} فیلتر شد.`
            );


            document.dispatchEvent(
                new CustomEvent(
                    "teltest:extraction-changed"
                )
            );


        } catch (error) {

            notify(
                error.message,
                "error"
            );


        } finally {

            button.disabled =
                false;

            button.innerHTML =
                original;

        }

    }


    // --------------------------------------------------------
    // EVENTS
    // --------------------------------------------------------

    document.addEventListener(
        "click",
        (event) => {

            const button =
                event.target.closest(
                    "[data-stage09-rules], [data-op-rules-extraction]"
                );


            if (!button) {
                return;
            }


            const jobId =
                button.dataset.stage09Rules
                || button.dataset.opRulesExtraction;


            if (jobId) {

                openRulesModal(
                    Number(
                        jobId
                    )
                );

            }

        }
    );


    ensureModal();

})();
