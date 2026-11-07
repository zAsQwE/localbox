/* Runs before the downloaded controller. Keep room entry recoverable when that
 * build predates the requested game. No dependency on its Vue/React version. */
(() => {
    "use strict";
    const address = new URL(location.href);
    if (address.searchParams.has("localbox-client")) {
        address.searchParams.delete("localbox-client");
        history.replaceState(history.state, "", address.pathname + address.search + address.hash);
    }
    const originalFetch = window.fetch.bind(window);
    const makeId = () => window.crypto?.randomUUID?.() || Array.from(window.crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, "0")).join("");
    // Jackbox normally keeps uuid/reconnect in shared localStorage. Two tabs
    // would then replace the same server profile. Keep only player session keys
    // in tab storage; preferences, achievements and other browser data stay shared.
    let identityReady = Promise.resolve();
    try {
        const local = window.localStorage, session = window.sessionStorage;
        const proto = Storage.prototype;
        const get = proto.getItem, set = proto.setItem, remove = proto.removeItem;
        const namespace = new URL(location.href).searchParams.get("namespace") || new URL(location.href).searchParams.get("ns") || "tv";
        const scoped = key => {
            const parts = String(key).split(":");
            return parts[0] === namespace && ["uuid", "reconnect", "name", "code"].includes(parts[1]);
        };
        let tab = get.call(session, "localbox:tab") || makeId();
        set.call(session, "localbox:tab", tab);
        const keyFor = key => "localbox:player:" + tab + ":" + key;
        proto.getItem = function (key) { return this === local && scoped(key) ? get.call(session, keyFor(key)) : get.call(this, key); };
        proto.setItem = function (key, value) { return this === local && scoped(key) ? set.call(session, keyFor(key), value) : set.call(this, key, value); };
        proto.removeItem = function (key) { return this === local && scoped(key) ? remove.call(session, keyFor(key)) : remove.call(this, key); };
        const fork = () => {
            const previous = tab;
            tab = makeId();
            set.call(session, "localbox:tab", tab);
            const inherited = [];
            for (let index = 0; index < session.length; index++) {
                const key = session.key(index), prefix = "localbox:player:" + previous + ":";
                if (key?.startsWith(prefix)) {
                    const original = key.slice(prefix.length);
                    if (["code", "name"].includes(original.split(":")[1])) inherited.push([original, get.call(session, key)]);
                }
            }
            for (const [key, value] of inherited) set.call(session, keyFor(key), value);
        };
        // Opening/duplicating a tab may copy sessionStorage. A live tab claims
        // its ID; the copy forks before its first room lookup can reconnect.
        if (navigator.locks?.request) {
            identityReady = new Promise(resolve => {
                const claim = () => navigator.locks.request("localbox-player:" + tab, { ifAvailable: true }, lock => {
                    if (!lock) { fork(); claim(); return; }
                    resolve();
                    return new Promise(() => {}); // released automatically with this document
                }).catch(() => resolve());
                claim();
            });
        } else if (window.BroadcastChannel) {
            const channel = new BroadcastChannel("localbox-player-tabs");
            const documentId = makeId();
            let ready = false;
            channel.onmessage = ({ data }) => {
                if (!data || data.tab !== tab || data.document === documentId) return;
                if (data.type === "probe" && (ready || documentId < data.document)) {
                    channel.postMessage({ type: "claimed", tab, document: documentId, target: data.document });
                } else if (data.type === "claimed" && data.target === documentId && !ready) {
                    fork();
                }
            };
            identityReady = new Promise(resolve => setTimeout(() => { ready = true; resolve(); }, 120));
            channel.postMessage({ type: "probe", tab, document: documentId });
        }
    } catch { /* Storage-disabled/incognito clients keep their native handling. */ }

    let catalog = {};
    try { catalog = JSON.parse(document.getElementById("localbox-controllers")?.textContent || "{}"); } catch { /* invalid local metadata */ }
    let boundRuntime;
    function installControllers() {
        const tv = window.tv;
        if (!tv?.manifest?.branches || !Array.isArray(tv.games)) return;
        for (const [tag, entry] of Object.entries(catalog)) {
            if (!entry?.bundle || !entry?.game) continue;
            for (const branch of Object.values(tv.manifest.branches)) {
                if (branch?.bundles) branch.bundles[tag] = entry.bundle;
            }
            if (!tv.games.some(game => game.tag === tag)) tv.games.push(entry.game);
        }
        if (boundRuntime !== tv && typeof tv.connect === "function") {
            boundRuntime = tv;
            const connect = tv.connect;
            tv.connect = async function (options) {
                await identityReady;
                if (options?.role !== "host") {
                    try {
                        const key = (tv.storage?.namespace || "tv") + ":uuid";
                        const uuid = localStorage.getItem(key) || makeId();
                        localStorage.setItem(key, uuid);
                        options = { ...options, userId: uuid };
                        if (options.secret && options.secret !== uuid) { delete options.id; delete options.secret; }
                    } catch { /* native incognito identity */ }
                }
                return connect.call(this, options);
            };
        }
    }
    let checking = "", box, message, button, code = "";
    function reload() {
        // An explicit client update can refresh this page; room entry itself
        // never navigates or swaps the site's connect screen.
        try { localStorage.setItem((window.tv?.storage?.namespace || "tv") + ":code", code); } catch { /* storage disabled */ }
        location.reload();
    }
    function show(text) {
        if (!box) {
            box = document.createElement("aside");
            box.setAttribute("role", "alert");
            Object.assign(box.style, { position: "fixed", inset: "auto 12px 12px", zIndex: "2147483647", background: "#171c24", color: "#f4f6fa", padding: "18px", border: "1px solid #52647a", borderRadius: "12px", font: "16px/1.5 system-ui", boxShadow: "0 8px 32px #0009" });
            message = document.createElement("div");
            button = document.createElement("button");
            button.type = "button";
            button.textContent = "Обновить клиент";
            Object.assign(button.style, { marginTop: "12px", padding: "12px 18px", background: "#8bb5ff", color: "#101620", border: "0", borderRadius: "8px", font: "inherit", cursor: "pointer" });
            button.onclick = update;
            box.append(message, button);
            (document.body || document.documentElement).append(box);
        }
        message.textContent = text;
    }
    async function state() {
        const result = await originalFetch("/localbox/client/status?code=" + encodeURIComponent(code), { cache: "no-store" });
        if (!result.ok) throw Error("Не удалось проверить client. Повторите попытку.");
        return result.json();
    }
    async function watchUpdate() {
        try {
            const status = await state();
            show(status.error || status.message || "Загружаю client…");
            if (status.running) { setTimeout(watchUpdate, 1500); return; }
            if (!status.error && status.available) { reload(); return; }
            if (!status.error) show("В последнем client пока нет этой игры. Обновление можно повторить позже.");
        } catch (error) { show(error.message); }
        button.disabled = false;
    }
    async function update() {
        button.disabled = true;
        try {
            const response = await originalFetch("/localbox/client/update", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) });
            const result = await response.json();
            if (!response.ok) throw Error(result.error || "Не удалось обновить client.");
            show("Загружаю обновлённый client с GitHub…");
            watchUpdate();
        } catch (error) { show(error.message); button.disabled = false; }
    }
    async function inspect(url, data) {
        if (!data?.ok || !data.body?.appTag) return;
        const match = url.pathname.match(/^\/api\/v2\/rooms\/([^/]+)$/);
        if (!match || checking === match[1]) return;
        checking = match[1];
        code = decodeURIComponent(match[1]);
        try {
            const status = await state();
            if (status.available) {
                installControllers();
                return;
            }
            show("В установленном client нет этой игры. Обновите клиент с GitHub — код комнаты сохранится.");
            if (status.running) { button.disabled = true; watchUpdate(); }
        } catch { checking = ""; }
    }
    window.fetch = function (...args) {
        installControllers();
        let roomRequest = false;
        let requestURL;
        try {
            const url = new URL(typeof args[0] === "string" || args[0] instanceof URL ? args[0] : args[0].url, location.href);
            roomRequest = url.origin === location.origin && /^\/api\/v2\/rooms\/[^/]+$/.test(url.pathname);
            requestURL = url;
        } catch { /* A Request unsupported by this browser is handled by fetch. */ }
        const result = roomRequest ? identityReady.then(() => { installControllers(); return originalFetch(...args); }) : originalFetch(...args);
        if (roomRequest) result.then(response => response.clone().json()).then(data => inspect(requestURL, data)).catch(() => {});
        return result;
    };
    const originalOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, address, ...rest) {
        installControllers();
        try {
            const url = new URL(address, location.href);
            if (url.origin === location.origin && /^\/api\/v2\/rooms\/[^/]+$/.test(url.pathname)) this.addEventListener("load", () => {
                try { inspect(url, this.responseType === "json" ? this.response : JSON.parse(this.responseText)); } catch { /* non-JSON error */ }
            }, { once: true });
        } catch { /* handled by the original open */ }
        return originalOpen.call(this, method, address, ...rest);
    };
})();
