(() => {

    "use strict";


    const BASE = "/teltest";


    const csrf = (
        document
            .querySelector(
                'meta[name="csrf-token"]'
            )
            ?.getAttribute(
                "content"
            )
        || ""
    );


    const navItems = [
        ...document.querySelectorAll(
            "[data-panel]"
        )
    ];


    const panels = [
        ...document.querySelectorAll(
            "[data-panel-content]"
        )
    ];


    const titles = {

        dashboard:
            "داشبورد",

        jobs:
            "جاب‌ها",

        posts:
            "پست‌های استخراجی",

        accounts:
            "اکانت‌های تلگرام",

        channels:
            "کانال‌ها",

        logs:
            "لاگ‌ها",

        settings:
            "تنظیمات",

    };


    const pageTitle =
        document.getElementById(
            "pageTitle"
        );


    const sidebar =
        document.getElementById(
            "sidebar"
        );


    const menuButton =
        document.getElementById(
            "menuButton"
        );


    let accountsCache = [];


    // ========================================================
    // HELPERS
    // ========================================================

    function escapeHtml(value) {

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


    function toast(
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
            () => {
                item.classList.add(
                    "hide"
                );
            },
            4200
        );


        window.setTimeout(
            () => {
                item.remove();
            },
            4700
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

            const error =
                new Error(
                    data.error
                    || `HTTP ${response.status}`
                );

            error.status =
                response.status;

            error.data =
                data;

            throw error;

        }


        return data;

    }


    function setBusy(
        button,
        busy,
        busyText = "در حال انجام..."
    ) {

        if (!button) {
            return;
        }


        if (busy) {

            if (
                !button.dataset.originalText
            ) {

                button.dataset.originalText =
                    button.textContent;

            }

            button.disabled = true;

            button.textContent =
                busyText;

        } else {

            button.disabled = false;

            if (
                button.dataset.originalText
            ) {

                button.textContent =
                    button.dataset.originalText;

            }

        }

    }


    // ========================================================
    // NAV
    // ========================================================

    function openPanel(name) {

        navItems.forEach(
            (item) => {

                item.classList.toggle(
                    "active",
                    item.dataset.panel === name
                );

            }
        );


        panels.forEach(
            (panel) => {

                panel.classList.toggle(
                    "active",
                    panel.dataset.panelContent === name
                );

            }
        );


        if (pageTitle) {

            pageTitle.textContent =
                titles[name]
                || "TelTest";

        }


        if (
            window.innerWidth <= 900
            && sidebar
        ) {

            sidebar.classList.remove(
                "open"
            );

        }


        history.replaceState(
            null,
            "",
            `#${name}`
        );


        if (name === "accounts") {
            loadAccounts();
        }


        if (name === "channels") {
            loadChannels();
        }


        if (name === "settings") {
            loadTelegramSettings();
            loadBaleSettings();
            loadExternalMirrorSettings();
        }

    }


    navItems.forEach(
        (item) => {

            item.addEventListener(
                "click",
                () => openPanel(
                    item.dataset.panel
                )
            );

        }
    );


    document
        .querySelectorAll(
            "[data-open-panel]"
        )
        .forEach(
            (item) => {

                item.addEventListener(
                    "click",
                    () => openPanel(
                        item.dataset.openPanel
                    )
                );

            }
        );


    if (
        menuButton
        && sidebar
    ) {

        menuButton.addEventListener(
            "click",
            () => {

                sidebar.classList.toggle(
                    "open"
                );

            }
        );

    }


    // ========================================================
    // OVERVIEW
    // ========================================================

    async function loadOverview() {

        try {

            const data =
                await api(
                    "/api/overview"
                );


            const mapping = {

                statAccounts:
                    data.accounts,

                statConnected:
                    data.connected,

                statChannels:
                    data.channels,

                accountCountMini:
                    data.accounts,

                connectedCountMini:
                    data.connected,

            };


            Object.entries(
                mapping
            ).forEach(
                ([id, value]) => {

                    const element =
                        document.getElementById(
                            id
                        );

                    if (element) {
                        element.textContent =
                            value;
                    }

                }
            );

        } catch (error) {

            console.error(
                error
            );

        }

    }


    // ========================================================
    // SETTINGS
    // ========================================================

    async function loadTelegramSettings() {

        try {

            const data =
                await api(
                    "/api/settings/telegram"
                );


            const idInput =
                document.getElementById(
                    "telegramApiId"
                );


            const hashCurrent =
                document.getElementById(
                    "apiHashCurrent"
                );


            const badge =
                document.getElementById(
                    "apiStatusBadge"
                );


            if (idInput) {

                idInput.value =
                    data.api_id
                    || "";

            }


            if (hashCurrent) {

                hashCurrent.textContent =
                    data.api_hash_masked
                    ? `ذخیره‌شده: ${data.api_hash_masked}`
                    : "API Hash هنوز ذخیره نشده است.";

            }


            if (badge) {

                badge.textContent =
                    data.configured
                    ? "آماده"
                    : "تنظیم نشده";

                badge.className =
                    data.configured
                    ? "badge success"
                    : "badge warning";

            }

        } catch (error) {

            toast(
                error.message,
                "error"
            );

        }

    }


    const telegramSettingsForm =
        document.getElementById(
            "telegramSettingsForm"
        );


    if (telegramSettingsForm) {

        telegramSettingsForm.addEventListener(
            "submit",
            async (event) => {

                event.preventDefault();


                const button =
                    document.getElementById(
                        "saveTelegramSettings"
                    );


                const apiId =
                    document.getElementById(
                        "telegramApiId"
                    ).value.trim();


                const apiHash =
                    document.getElementById(
                        "telegramApiHash"
                    ).value.trim();


                setBusy(
                    button,
                    true,
                    "در حال ذخیره..."
                );


                try {

                    const data =
                        await api(
                            "/api/settings/telegram",
                            {
                                method:
                                    "POST",

                                body:
                                    JSON.stringify(
                                        {
                                            api_id:
                                                apiId,

                                            api_hash:
                                                apiHash,
                                        }
                                    ),
                            }
                        );


                    toast(
                        data.message
                    );


                    document.getElementById(
                        "telegramApiHash"
                    ).value = "";


                    await loadTelegramSettings();


                } catch (error) {

                    toast(
                        error.message,
                        "error"
                    );

                } finally {

                    setBusy(
                        button,
                        false
                    );

                }

            }
        );

    }


    // ========================================================
    // BALE SETTINGS
    // ========================================================

    async function loadBaleSettings() {

        try {

            const data =
                await api(
                    "/api/settings/bale"
                );


            const chat =
                document.getElementById(
                    "baleChatId"
                );


            const current =
                document.getElementById(
                    "baleTokenCurrent"
                );


            const badge =
                document.getElementById(
                    "baleStatusBadge"
                );


            if (chat) {

                chat.value =
                    data.chat_id
                    || "";

            }


            if (current) {

                current.textContent =
                    data.token_masked
                    ? `ذخیره‌شده: ${data.token_masked}`
                    : "توکن ربات بله ذخیره نشده است.";

            }


            if (badge) {

                badge.textContent =
                    data.configured
                    ? "آماده"
                    : "تنظیم نشده";


                badge.className =
                    data.configured
                    ? "badge success"
                    : "badge warning";

            }


        } catch (error) {

            toast(
                error.message,
                "error"
            );

        }

    }


    const baleSettingsForm =
        document.getElementById(
            "baleSettingsForm"
        );


    if (baleSettingsForm) {

        baleSettingsForm.addEventListener(
            "submit",
            async (event) => {

                event.preventDefault();


                const button =
                    document.getElementById(
                        "saveBaleSettings"
                    );


                setBusy(
                    button,
                    true,
                    "در حال ذخیره..."
                );


                try {

                    const result =
                        await api(
                            "/api/settings/bale",
                            {
                                method:
                                    "POST",

                                body:
                                    JSON.stringify(
                                        {
                                            token:
                                                document
                                                    .getElementById(
                                                        "baleBotToken"
                                                    )
                                                    .value
                                                    .trim(),

                                            chat_id:
                                                document
                                                    .getElementById(
                                                        "baleChatId"
                                                    )
                                                    .value
                                                    .trim(),
                                        }
                                    ),
                            }
                        );


                    toast(
                        result.message
                    );


                    document
                        .getElementById(
                            "baleBotToken"
                        )
                        .value = "";


                    await loadBaleSettings();


                } catch (error) {

                    toast(
                        error.message,
                        "error"
                    );


                } finally {

                    setBusy(
                        button,
                        false
                    );

                }

            }
        );

    }


    document
        .getElementById(
            "testBaleSettings"
        )
        ?.addEventListener(
            "click",
            async function () {

                setBusy(
                    this,
                    true,
                    "در حال تست..."
                );


                try {

                    const result =
                        await api(
                            "/api/settings/bale/test",
                            {
                                method:
                                    "POST",

                                body:
                                    "{}",
                            }
                        );


                    toast(
                        result.message
                    );


                } catch (error) {

                    toast(
                        error.message,
                        "error"
                    );


                } finally {

                    setBusy(
                        this,
                        false
                    );

                }

            }
        );



    // ========================================================
    // EITAA / RUBIKA SETTINGS
    // ========================================================

    async function loadProviderSettings(
        provider
    ) {

        const data =
            await api(
                `/api/settings/${provider}`
            );


        const prefix =
            provider === "eitaa"
            ? "eitaa"
            : "rubika";


        const chat =
            document.getElementById(
                `${prefix}ChatId`
            );


        const current =
            document.getElementById(
                `${prefix}TokenCurrent`
            );


        const badge =
            document.getElementById(
                `${prefix}StatusBadge`
            );


        if (chat) {

            chat.value =
                data.chat_id
                || "";

        }


        if (current) {

            current.textContent =
                data.token_masked
                ? `ذخیره‌شده: ${data.token_masked}`
                : "توکن ذخیره نشده است.";

        }


        if (badge) {

            badge.textContent =
                data.configured
                ? "آماده"
                : "تنظیم نشده";


            badge.className =
                data.configured
                ? "badge success"
                : "badge warning";

        }

    }


    async function loadExternalMirrorSettings() {

        try {

            await Promise.all(
                [
                    loadProviderSettings(
                        "eitaa"
                    ),

                    loadProviderSettings(
                        "rubika"
                    ),
                ]
            );


        } catch (error) {

            toast(
                error.message,
                "error"
            );

        }

    }


    function bindProviderForm(
        provider
    ) {

        const prefix =
            provider === "eitaa"
            ? "eitaa"
            : "rubika";


        const form =
            document.getElementById(
                `${prefix}SettingsForm`
            );


        if (!form) {
            return;
        }


        form.addEventListener(
            "submit",
            async (event) => {

                event.preventDefault();


                const button =
                    document.getElementById(
                        provider === "eitaa"
                        ? "saveEitaaSettings"
                        : "saveRubikaSettings"
                    );


                setBusy(
                    button,
                    true,
                    "در حال ذخیره..."
                );


                try {

                    const result =
                        await api(
                            `/api/settings/${provider}`,
                            {
                                method:
                                    "POST",

                                body:
                                    JSON.stringify(
                                        {
                                            token:
                                                document
                                                    .getElementById(
                                                        provider === "eitaa"
                                                        ? "eitaaBotToken"
                                                        : "rubikaBotToken"
                                                    )
                                                    .value
                                                    .trim(),

                                            chat_id:
                                                document
                                                    .getElementById(
                                                        provider === "eitaa"
                                                        ? "eitaaChatId"
                                                        : "rubikaChatId"
                                                    )
                                                    .value
                                                    .trim(),
                                        }
                                    ),
                            }
                        );


                    toast(
                        result.message
                    );


                    document
                        .getElementById(
                            provider === "eitaa"
                            ? "eitaaBotToken"
                            : "rubikaBotToken"
                        )
                        .value = "";


                    await loadProviderSettings(
                        provider
                    );


                } catch (error) {

                    toast(
                        error.message,
                        "error"
                    );


                } finally {

                    setBusy(
                        button,
                        false
                    );

                }

            }
        );

    }


    bindProviderForm(
        "eitaa"
    );


    bindProviderForm(
        "rubika"
    );


    async function testProvider(
        provider,
        button
    ) {

        setBusy(
            button,
            true,
            "در حال تست..."
        );


        try {

            const result =
                await api(
                    `/api/settings/${provider}/test`,
                    {
                        method:
                            "POST",

                        body:
                            "{}",
                    }
                );


            toast(
                result.message
            );


        } catch (error) {

            toast(
                error.message,
                "error"
            );


        } finally {

            setBusy(
                button,
                false
            );

        }

    }


    document
        .getElementById(
            "testEitaaSettings"
        )
        ?.addEventListener(
            "click",
            function () {

                testProvider(
                    "eitaa",
                    this
                );

            }
        );


    document
        .getElementById(
            "testRubikaSettings"
        )
        ?.addEventListener(
            "click",
            function () {

                testProvider(
                    "rubika",
                    this
                );

            }
        );



    // ========================================================
    // ACCOUNTS
    // ========================================================

    function statusBadge(status) {

        const labels = {

            new:
                "جدید",

            code_sent:
                "منتظر کد",

            password_required:
                "منتظر 2FA",

            connected:
                "متصل",

            disconnected:
                "قطع",

        };


        const cls =
            status === "connected"
            ? "success"
            : (
                status === "code_sent"
                || status === "password_required"
            )
            ? "warning"
            : "";


        return `
            <span class="badge ${cls}">
                ${escapeHtml(
                    labels[status]
                    || status
                )}
            </span>
        `;

    }


    function accountCard(account) {

        const username =
            account.username
            ? `@${escapeHtml(
                account.username
            )}`
            : "—";


        const displayName =
            account.display_name
            || "Telegram Account";


        let actionBody = "";


        if (
            account.status
            === "code_sent"
        ) {

            actionBody = `
                <div class="verify-box">

                    <label>
                        کد وریفای
                    </label>

                    <div class="input-action">

                        <input
                            class="text-input ltr"
                            id="verifyCode-${account.id}"
                            placeholder="12345"
                            inputmode="numeric"
                        >

                        <button
                            class="btn primary"
                            onclick="window.teltestVerifyCode(${account.id}, this)"
                        >
                            تأیید کد
                        </button>

                    </div>

                </div>
            `;

        }


        if (
            account.status
            === "password_required"
        ) {

            actionBody = `
                <div class="verify-box">

                    <label>
                        رمز 2FA تلگرام
                    </label>

                    <div class="input-action">

                        <input
                            class="text-input ltr"
                            id="verifyPassword-${account.id}"
                            type="password"
                            placeholder="Telegram 2FA password"
                        >

                        <button
                            class="btn primary"
                            onclick="window.teltestVerifyPassword(${account.id}, this)"
                        >
                            تأیید 2FA
                        </button>

                    </div>

                </div>
            `;

        }


        const errorBody =
            account.last_error
            ? `
                <div class="account-error">
                    ${escapeHtml(
                        account.last_error
                    )}
                </div>
            `
            : "";


        return `
            <article class="account-card">

                <div class="account-card-top">

                    <div>

                        <h3>
                            ${escapeHtml(
                                displayName
                            )}
                        </h3>

                        <div class="account-phone ltr">
                            ${escapeHtml(
                                account.phone
                            )}
                        </div>

                    </div>

                    ${statusBadge(
                        account.status
                    )}

                </div>


                <div class="account-meta">

                    <div>
                        <span>
                            Username
                        </span>
                        <strong class="ltr">
                            ${username}
                        </strong>
                    </div>

                    <div>
                        <span>
                            Telegram ID
                        </span>
                        <strong class="ltr">
                            ${escapeHtml(
                                account.telegram_user_id
                                || "—"
                            )}
                        </strong>
                    </div>

                    <div>
                        <span>
                            کانال / گروه
                        </span>
                        <strong>
                            ${account.channel_count}
                        </strong>
                    </div>

                </div>


                ${actionBody}

                ${errorBody}


                <div class="account-actions">

                    <button
                        class="btn secondary"
                        onclick="window.teltestRefreshAccount(${account.id}, this)"
                    >
                        دریافت کانال‌ها
                    </button>

                    <button
                        class="btn danger"
                        onclick="window.teltestDeleteAccount(${account.id}, this)"
                    >
                        حذف اتصال
                    </button>

                </div>

            </article>
        `;

    }


    async function loadAccounts() {

        const container =
            document.getElementById(
                "accountsList"
            );


        try {

            const data =
                await api(
                    "/api/accounts"
                );


            accountsCache =
                data.accounts;


            if (container) {

                if (
                    data.accounts.length
                    === 0
                ) {

                    container.innerHTML = `
                        <div class="empty-inline">

                            هنوز هیچ اکانتی
                            اضافه نشده است.

                        </div>
                    `;

                } else {

                    container.innerHTML =
                        data.accounts
                            .map(
                                accountCard
                            )
                            .join("");

                }

            }


            populateAccountFilter();

            await loadOverview();


        } catch (error) {

            if (container) {

                container.innerHTML = `
                    <div class="account-error">
                        ${escapeHtml(
                            error.message
                        )}
                    </div>
                `;

            }

        }

    }


    const phoneForm =
        document.getElementById(
            "phoneForm"
        );


    if (phoneForm) {

        phoneForm.addEventListener(
            "submit",
            async (event) => {

                event.preventDefault();


                const phone =
                    document.getElementById(
                        "phoneInput"
                    ).value.trim();


                const button =
                    document.getElementById(
                        "sendCodeButton"
                    );


                setBusy(
                    button,
                    true,
                    "ارسال..."
                );


                try {

                    const data =
                        await api(
                            "/api/accounts/send-code",
                            {
                                method:
                                    "POST",

                                body:
                                    JSON.stringify(
                                        {
                                            phone,
                                        }
                                    ),
                            }
                        );


                    toast(
                        data.message
                    );


                    await loadAccounts();


                } catch (error) {

                    toast(
                        error.message,
                        "error"
                    );

                } finally {

                    setBusy(
                        button,
                        false
                    );

                }

            }
        );

    }


    window.teltestVerifyCode =
        async (
            accountId,
            button
        ) => {

            const input =
                document.getElementById(
                    `verifyCode-${accountId}`
                );


            const code =
                input?.value.trim()
                || "";


            setBusy(
                button,
                true,
                "تأیید..."
            );


            try {

                const data =
                    await api(
                        `/api/accounts/${accountId}/verify-code`,
                        {
                            method:
                                "POST",

                            body:
                                JSON.stringify(
                                    {
                                        code,
                                    }
                                ),
                        }
                    );


                toast(
                    data.message
                );


                await loadAccounts();

                await loadChannels();


            } catch (error) {

                toast(
                    error.message,
                    "error"
                );

            } finally {

                setBusy(
                    button,
                    false
                );

            }

        };


    window.teltestVerifyPassword =
        async (
            accountId,
            button
        ) => {

            const input =
                document.getElementById(
                    `verifyPassword-${accountId}`
                );


            const password =
                input?.value
                || "";


            setBusy(
                button,
                true,
                "تأیید..."
            );


            try {

                const data =
                    await api(
                        `/api/accounts/${accountId}/verify-password`,
                        {
                            method:
                                "POST",

                            body:
                                JSON.stringify(
                                    {
                                        password,
                                    }
                                ),
                        }
                    );


                toast(
                    data.message
                );


                await loadAccounts();

                await loadChannels();


            } catch (error) {

                toast(
                    error.message,
                    "error"
                );

            } finally {

                setBusy(
                    button,
                    false
                );

            }

        };


    window.teltestRefreshAccount =
        async (
            accountId,
            button
        ) => {

            setBusy(
                button,
                true,
                "دریافت..."
            );


            try {

                const data =
                    await api(
                        `/api/accounts/${accountId}/refresh`,
                        {
                            method:
                                "POST",

                            body:
                                "{}",
                        }
                    );


                toast(
                    `${data.message} (${data.channels})`
                );


                await loadAccounts();

                await loadChannels();


            } catch (error) {

                toast(
                    error.message,
                    "error"
                );

            } finally {

                setBusy(
                    button,
                    false
                );

            }

        };


    window.teltestDeleteAccount =
        async (
            accountId,
            button
        ) => {

            const confirmed =
                window.confirm(
                    "Session محلی این اکانت حذف شود؟"
                );


            if (!confirmed) {
                return;
            }


            setBusy(
                button,
                true,
                "حذف..."
            );


            try {

                const data =
                    await api(
                        `/api/accounts/${accountId}`,
                        {
                            method:
                                "DELETE",
                        }
                    );


                toast(
                    data.message
                );


                await loadAccounts();

                await loadChannels();


            } catch (error) {

                toast(
                    error.message,
                    "error"
                );

            } finally {

                setBusy(
                    button,
                    false
                );

            }

        };


    // ========================================================
    // CHANNELS
    // ========================================================

    function populateAccountFilter() {

        const select =
            document.getElementById(
                "channelAccountFilter"
            );


        if (!select) {
            return;
        }


        const selected =
            select.value;


        select.innerHTML = `
            <option value="">
                همه اکانت‌ها
            </option>
        `;


        accountsCache
            .filter(
                (account) =>
                    account.status
                    === "connected"
            )
            .forEach(
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
                            || "Telegram"
                        }`;


                    select.appendChild(
                        option
                    );

                }
            );


        if (
            [
                ...select.options
            ].some(
                (item) =>
                    item.value
                    === selected
            )
        ) {

            select.value =
                selected;

        }

    }


    function channelKind(kind) {

        const labels = {

            channel:
                "کانال",

            supergroup:
                "سوپرگروه",

            group:
                "گروه",

        };


        return labels[kind]
            || kind;

    }


    async function loadChannels() {

        const tbody =
            document.getElementById(
                "channelsTableBody"
            );


        if (!tbody) {
            return;
        }


        const filter =
            document.getElementById(
                "channelAccountFilter"
            );


        const accountId =
            filter?.value
            || "";


        try {

            const suffix =
                accountId
                ? `?account_id=${encodeURIComponent(accountId)}`
                : "";


            const data =
                await api(
                    `/api/channels${suffix}`
                );


            if (
                data.channels.length
                === 0
            ) {

                tbody.innerHTML = `
                    <tr>
                        <td
                            colspan="5"
                            class="table-empty"
                        >
                            کانال یا گروهی ثبت نشده است.
                        </td>
                    </tr>
                `;

                return;

            }


            tbody.innerHTML =
                data.channels
                    .map(
                        (channel) => {

                            const username =
                                channel.username
                                ? `@${escapeHtml(
                                    channel.username
                                )}`
                                : "Private";


                            let access =
                                "عضو";


                            if (
                                channel.is_creator
                            ) {
                                access =
                                    "مالک";
                            } else if (
                                channel.is_admin
                            ) {
                                access =
                                    "ادمین";
                            }


                            return `
                                <tr>

                                    <td>

                                        <div class="channel-title">
                                            ${escapeHtml(
                                                channel.title
                                            )}
                                        </div>

                                        <small class="ltr">
                                            ID:
                                            ${escapeHtml(
                                                channel.entity_id
                                            )}
                                        </small>

                                    </td>

                                    <td class="ltr">
                                        ${username}
                                    </td>

                                    <td>
                                        ${escapeHtml(
                                            channelKind(
                                                channel.kind
                                            )
                                        )}
                                    </td>

                                    <td class="ltr">
                                        ${escapeHtml(
                                            channel.account_phone
                                        )}
                                    </td>

                                    <td>
                                        ${access}
                                    </td>

                                </tr>
                            `;

                        }
                    )
                    .join("");


        } catch (error) {

            tbody.innerHTML = `
                <tr>
                    <td
                        colspan="5"
                        class="table-empty error-text"
                    >
                        ${escapeHtml(
                            error.message
                        )}
                    </td>
                </tr>
            `;

        }

    }


    const accountFilter =
        document.getElementById(
            "channelAccountFilter"
        );


    if (accountFilter) {

        accountFilter.addEventListener(
            "change",
            loadChannels
        );

    }


    const refreshSelected =
        document.getElementById(
            "refreshSelectedAccount"
        );


    if (refreshSelected) {

        refreshSelected.addEventListener(
            "click",
            async () => {

                const id =
                    document.getElementById(
                        "channelAccountFilter"
                    ).value;


                if (!id) {

                    toast(
                        "ابتدا یک اکانت را انتخاب کنید.",
                        "error"
                    );

                    return;

                }


                window.teltestRefreshAccount(
                    Number(id),
                    refreshSelected
                );

            }
        );

    }


    // ========================================================
    // BOOT
    // ========================================================

    const initial =
        location.hash.replace(
            "#",
            ""
        );


    if (titles[initial]) {

        openPanel(
            initial
        );

    }


    Promise.all([
        loadOverview(),
        loadAccounts(),
        loadTelegramSettings(),
    ]).then(
        () => {

            loadChannels();

        }
    );

})();
