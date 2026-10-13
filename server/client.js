/*
    LocalBox — раздача статического веб-клиента (клон jackbox.tv / jackbox.ru) прямо из сервера.
    Подключается одной строкой в server.js.

    Клиент кладётся в каталог LOCALBOX_CLIENT_DIR (по умолчанию ../client относительно server/).
    В текстовых файлах адреса API Jackbox подменяются на адрес нашего сервера, чтобы клиент
    обращался к НАШЕМУ серверу.
*/

"use strict";

const fs = require("fs");
const path = require("path");
const https = require("https");
const admin = require("./lib/admin.js");
const { layoutPaths } = require("./lib/client-paths.js");

const CLIENT_DIR = path.resolve(__dirname, process.env.LOCALBOX_CLIENT_DIR || "../client");
// Сначала выбранный клиент, затем явно заданный фоллбэк, затем соседние client/ и client-ru/.
// Дополнительные картинки и другие ассеты доступны из обеих папок даже без настройки окружения.
const FALLBACK_DIRS = [...new Set([
    process.env.LOCALBOX_CLIENT_FALLBACK
        ? path.resolve(__dirname, process.env.LOCALBOX_CLIENT_FALLBACK) : null,
    path.resolve(CLIENT_DIR, "../client"),
    path.resolve(CLIENT_DIR, "../client-ru"),
].filter((dir) => dir && dir !== CLIENT_DIR))];
const TEXT_EXT = new Set([".html", ".js", ".mjs", ".css", ".json", ".jet", ".webmanifest", ".map", ".svg"]);
// Онлайн-докачка: если файла нет ни в основном каталоге, ни в фоллбэке — тянем его с LOCALBOX_FETCH_ORIGIN
// (напр. https://jackbox.ru) по тому же пути и кэшируем на диск. Так подтягиваются ФИРМЕННЫЕ ассеты
// jackbox.ru (задники, логотипы, «ячейки»), которых нет в англ. клиенте. Один раз онлайн — дальше офлайн.
const FETCH_ORIGIN = (process.env.LOCALBOX_FETCH_ORIGIN || "").replace(/\/+$/, "") || null;
const ASSET_EXT = new Set([
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".ogg", ".wav", ".m4a", ".mp4", ".webm",
    ".css", ".js", ".mjs", ".json", ".jet", ".map", ".webmanifest",
]);
const MIME = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".jet": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8", ".map": "application/json; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".svg": "image/svg+xml", ".webp": "image/webp", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf", ".eot": "application/vnd.ms-fontobject",
    ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".mp4": "video/mp4", ".webm": "video/webm",
};

// Хосты, которые в клиенте надо завернуть на наш сервер (и API-бэкенды, и КАНОНИЧЕСКИЕ домены
// клиента — иначе клиент редиректит на свой сайт типа `if(host!='jackbox.ru') location.href=...`).
// Порядок ВАЖЕН: более длинные/специфичные строки идут раньше, чтобы не побить подстроки
// (например api.jackbox.tv до jackbox.tv).
const REWRITE_HOSTS = [
    // API/бэкенды
    "ecast-prod-use2.jackboxgames.com", "ecast.jackboxgames.com",
    "jb-ecast.klucva.ru", "server.rujackbox.loamfy.com", "jack.nevpn2.fenst4r.live", "jack.fenst4r.live",
    "api.jackbox.tv",
    // канонические домены клиентов (гасят редирект на «настоящий» сайт)
    "dev.jackbox.tv", "www.jackbox.tv", "jackbox.tv",
    "www.jackbox.ru", "jackbox.ru",
    "www.jackbox.fun", "jackbox.fun",
    "www.jackbox.su", "jackbox.su",
];

// Кастомный код комнаты (в т.ч. русский, любой длины). Клиент по умолчанию требует РОВНО 4 символа
// (codeLength) — при заданном LOCALBOX_ROOM_CODE ослабляем это в раздаваемом клиенте, чтобы можно
// было ввести код другой длины. Новый клиент дополнительно удаляет кириллицу при вводе.
const ANY_CODE = !!(process.env.LOCALBOX_ROOM_CODE || "").trim();
function patchRoomCode(text) {
    if (!ANY_CODE || text.indexOf("this.codeLength") === -1) return text;
    return text
        // The new connect bundle sanitizes code before checking codeLength. Limit this patch
        // to onCodeInput; disable its Latin-only filter for custom codes.
        .replace(/(onCodeInput\s*\(\)\s*\{[^{}]*?)(?=this\.code\.length)/g,
            (prefix) => prefix.replace(/\/\[\^A-Z\]\/g/g, "/$^/g"))
        .replace(/\bmaxlength:\s*[A-Za-z_$][\w$]*\.codeLength\b/g, "maxlength: 24")
        .replace(/this\.code\.length\s*!==\s*this\.codeLength/g, "this.code.length < 2")
        .replace(/this\.code\.length\s*===\s*this\.codeLength/g, "this.code.length >= 2")
        // Имена переменных различаются в русском и английском клиентах.
        .replace(/\b([A-Za-z_$][\w$]*)\.length\s*===\s*this\.codeLength/g, "$1.length >= 2");
}

// LOCALBOX_NO_CLIENT=1 — не раздавать веб-клиент (режим -no-web для серверов).
const noWeb = process.env.LOCALBOX_NO_CLIENT === "1";
const enabled = !noWeb && fs.existsSync(CLIENT_DIR);
if (noWeb) console.log("[localbox] режим -no-web: веб-клиент не раздаётся");
else if (enabled) console.log("[localbox] раздаю клиент из", CLIENT_DIR);
else console.log("[localbox] каталог клиента не найден (", CLIENT_DIR, ") — клиент не раздаётся");
for (const dir of FALLBACK_DIRS) {
    if (fs.existsSync(dir)) console.log("[localbox] фоллбэк ассетов:", dir);
}
if (FETCH_ORIGIN) console.log("[localbox] докачка недостающего с", FETCH_ORIGIN, "→ кэш в", CLIENT_DIR);

// Ищет файл в выбранном клиенте, затем в дополнительных каталогах. Возвращает путь или null.
function resolveInDir(base, urlPath) {
    if (!base) return null;
    const full = clientPath(base, urlPath);
    if (!full) return null;
    try { return fs.statSync(full).isFile() ? full : null; } catch { return null; }
}

function clientPath(base, urlPath) {
    let clean;
    try { clean = decodeURIComponent(urlPath.split("?")[0]); } catch { return null; }
    const parts = clean.split("/").filter(Boolean);
    if (/[\\\0:]/.test(clean) || parts.some((part) => part.startsWith("."))) return null;
    let full = base;
    for (const part of parts) {
        full = path.join(full, part);
        try { if (fs.lstatSync(full).isSymbolicLink()) return null; } catch (e) { if (e.code !== "ENOENT") return null; }
    }
    return full;
}

function resolveFile(urlPath) {
    for (const dir of [CLIENT_DIR, ...FALLBACK_DIRS]) {
        for (const candidate of layoutPaths(urlPath.replace(/^\/+/, ""))) {
            const file = resolveInDir(dir, candidate);
            if (file) return file;
        }
    }
    return null;
}

function rewrite(text, host, secure) {
    // host = тот же адрес, с которого открыта страница, чтобы API-запросы были same-origin
    // (иначе браузер режет их по CORS). Fallback — serverUrl движка.
    const target = host || (global.jbg && global.jbg.serverUrl) || "localhost";
    let hostname = target;
    try { hostname = new URL("https://" + target).hostname; } catch { /* некорректный Host не должен останавливать сервер */ }
    // location.hostname не содержит порт. Иначе канонический редирект русского
    // клиента зацикливается на нестандартном порту и теряет ?code= из QR-ссылки.
    let out = text.replace(
        /((?:window|document)\.location\.hostname\s*(?:===?|!==?)\s*)(["'])([^"']+)\2/g,
        (match, prefix, quote, value) => REWRITE_HOSTS.includes(value)
            ? prefix + quote + hostname + quote : match
    );
    for (const h of REWRITE_HOSTS) out = out.split(h).join(target);
    out = out.replace(/\sintegrity=("|')[^"']*\1/gi, "");
    if (!secure) {
        // Страница открыта по http → понижаем API/ws на нашем хосте до http/ws. Иначе браузер
        // режет http→https по CORS, а самоподписанный серт не доверен (игрок «не может зайти»).
        out = out.split("https://" + target).join("http://" + target)
                 .split("wss://" + target).join("ws://" + target);
        // APIClient и WebSocket-клиент также задают протокол отдельным параметром.
        out = out.replace(/(\bscheme\s*:\s*|this\.scheme\s*=\s*)(["'])https\2/g, "$1$2http$2")
                 .replace(/(\bscheme\s*:\s*|this\.scheme\s*=\s*)(["'])wss\2/g, "$1$2ws$2");
    }
    return out;
}

// Отдаёт содержимое буфера с нужным MIME; текстовые файлы прогоняются через rewrite (подмена хостов).
function sendBuffer(buf, ext, req, res) {
    res.setHeader("Content-Type", MIME[ext] || "application/octet-stream");
    res.setHeader("Access-Control-Allow-Origin", "*");
    if (TEXT_EXT.has(ext)) {
        const reqHost = req.headers.host || null;
        const secure = !!(req.socket && req.socket.encrypted); // страница отдана по https?
        let html = rewrite(buf.toString("utf8"), reqHost, secure);
        if (ext === ".js" || ext === ".mjs") html = patchRoomCode(html);   // гибкая длина кода комнаты (русский/кастомный)
        // Вставляем админ-оверлей (панельку читов) в HTML-страницы, если включены админы.
        if (ext === ".html" && admin.enabled()) {
            const tag = '<script src="/admin/overlay.js"></script>';
            html = /<head(?:\s[^>]*)?>/i.test(html) ? html.replace(/<head(?:\s[^>]*)?>/i, (head) => head + tag) : tag + html;
        }
        res.end(html);
    } else {
        res.end(buf);
    }
}

// Докачивает недостающий ассет с FETCH_ORIGIN по тому же пути, кэширует на диск и отдаёт.
function fetchAndCache(urlPath, req, res, next) {
    const cleanUrl = urlPath.split("?")[0];
    const dest = clientPath(CLIENT_DIR, urlPath);
    if (!dest) return next();
    const src = FETCH_ORIGIN + (cleanUrl.startsWith("/") ? cleanUrl : "/" + cleanUrl);
    let finished = false;
    const fail = () => { if (!finished) { finished = true; next(); } };
    const upstream = https.get(src, { headers: { "user-agent": "Mozilla/5.0", "accept": "*/*" } }, (up) => {
        if (up.statusCode !== 200) { up.resume(); return fail(); }
        const chunks = [];
        up.on("error", fail);
        up.on("aborted", fail);
        up.on("data", (c) => chunks.push(c));
        up.on("end", () => {
            if (finished) return;
            const buf = Buffer.concat(chunks);
            // не кэшировать html-страницу ошибки/редиректа вместо ассета
            const head = buf.slice(0, 40).toString("utf8").toLowerCase();
            if (head.includes("<!doctype") || head.includes("<html")) return fail();
            finished = true;
            const tmp = dest + "." + require("crypto").randomBytes(8).toString("hex") + ".part";
            fs.mkdir(path.dirname(dest), { recursive: true }, (err) => {
                if (err) return;
                fs.writeFile(tmp, buf, (writeErr) => {
                    if (writeErr) return fs.unlink(tmp, () => {});
                    fs.rename(tmp, dest, (renameErr) => { if (renameErr) fs.unlink(tmp, () => {}); });
                });
            });
            sendBuffer(buf, path.extname(dest).toLowerCase(), req, res);
        });
    }).on("error", fail);
    upstream.setTimeout(20000, () => upstream.destroy(new Error("asset download timeout")));
}

module.exports = function localboxClient(req, res, next) {
    if (!enabled || !["GET", "HEAD"].includes(req.method)) return next();

    // New connect clients request this JSON endpoint despite its .png suffix.
    // Keep their browser identity local and stable across page reloads.
    if (req.url.split("?")[0] === "/uuid/image.png") {
        const previous = (req.headers.cookie || "").match(/(?:^|;\s*)jbg_id=([a-f0-9-]{36})(?:;|$)/i)?.[1];
        const id = previous && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(previous)
            ? previous : require("crypto").randomUUID();
        res.setHeader("Cache-Control", "no-store");
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        res.setHeader("Set-Cookie", `jbg_id=${id}; Path=/; Max-Age=31536000; SameSite=Lax${req.socket.encrypted ? "; Secure" : ""}`);
        res.end(JSON.stringify({ jbg_id: id }));
        return;
    }

    const urlPath = req.url === "/" ? "/index.html" : req.url;
    if (!clientPath(CLIENT_DIR, urlPath)) return next();
    let file = resolveFile(urlPath);

    // SPA-маршрут без расширения -> index.html (из основного каталога)
    if (!file && path.extname(urlPath.split("?")[0]) === "") {
        file = resolveFile("/index.html");
    }

    if (file) {
        const ext = path.extname(file).toLowerCase();
        if (TEXT_EXT.has(ext)) {
            fs.readFile(file, (err, data) => err ? next() : sendBuffer(data, ext, req, res));
        } else {
            res.setHeader("Content-Type", MIME[ext] || "application/octet-stream");
            res.setHeader("Access-Control-Allow-Origin", "*");
            fs.createReadStream(file).on("error", () => next()).pipe(res);
        }
        return;
    }

    // Нет ни в client-ru, ни в client -> пробуем докачать фирменный ассет с jackbox.ru и закэшировать.
    const ext0 = path.extname(urlPath.split("?")[0]).toLowerCase();
    if (FETCH_ORIGIN && ASSET_EXT.has(ext0)) return fetchAndCache(urlPath, req, res, next);
    return next();
};
