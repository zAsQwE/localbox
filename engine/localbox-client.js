/*
    LocalBox addition — раздача статического веб-клиента (клон jackbox.tv) прямо из движка.
    Это НЕ часть оригинального jackbox-private-server; подключается одной строкой в server.js.
    Файлы движка (lib/*) не изменяются.

    Клиент кладётся в каталог LOCALBOX_CLIENT_DIR (по умолчанию ../client относительно engine/).
    В текстовых файлах адреса API Jackbox подменяются на global.jbg.serverUrl, чтобы клиент
    обращался к НАШЕМУ серверу.
*/

"use strict";

const fs = require("fs");
const path = require("path");
const https = require("https");

const CLIENT_DIR = path.resolve(__dirname, process.env.LOCALBOX_CLIENT_DIR || "../client");
// Фоллбэк-каталог: если файла нет в основном (напр. русская тонкая оболочка) — берём отсюда
// (англ. клиент с полными ассетами; хеши совпадают с jackbox.fun, поэтому ассеты сходятся).
const FALLBACK_DIR = process.env.LOCALBOX_CLIENT_FALLBACK
    ? path.resolve(__dirname, process.env.LOCALBOX_CLIENT_FALLBACK) : null;
const TEXT_EXT = new Set([".html", ".js", ".mjs", ".css", ".json", ".jet", ".webmanifest", ".map", ".svg"]);
// Онлайн-докачка: если файла нет ни в основном каталоге, ни в фоллбэке — тянем его с LOCALBOX_FETCH_ORIGIN
// (напр. https://jackbox.ru) по тому же пути и кэшируем на диск. Так подтягиваются ФИРМЕННЫЕ ассеты
// jackbox.ru (задники, логотипы, «ячейки»), которых нет в англ. клиенте. Один раз онлайн — дальше офлайн.
const FETCH_ORIGIN = (process.env.LOCALBOX_FETCH_ORIGIN || "").replace(/\/+$/, "") || null;
const ASSET_EXT = new Set([
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".ogg", ".wav", ".m4a", ".mp4", ".webm",
    ".css", ".js", ".mjs", ".json", ".jet", ".map", ".webmanifest",
]);
const MIME = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".jet": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8", ".map": "application/json; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".svg": "image/svg+xml", ".webp": "image/webp", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
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
    "jb-ecast.klucva.ru", "server.rujackbox.loamfy.com", "jack.fenst4r.live",
    "api.jackbox.tv",
    // канонические домены клиентов (гасят редирект на «настоящий» сайт)
    "dev.jackbox.tv", "www.jackbox.tv", "jackbox.tv",
    "www.jackbox.ru", "jackbox.ru",
    "www.jackbox.fun", "jackbox.fun",
    "www.jackbox.su", "jackbox.su",
];

// LOCALBOX_NO_CLIENT=1 — не раздавать веб-клиент (режим -no-web для серверов).
const noWeb = process.env.LOCALBOX_NO_CLIENT === "1";
const enabled = !noWeb && fs.existsSync(CLIENT_DIR);
if (noWeb) console.log("[localbox] режим -no-web: веб-клиент не раздаётся");
else if (enabled) console.log("[localbox] раздаю клиент из", CLIENT_DIR);
else console.log("[localbox] каталог клиента не найден (", CLIENT_DIR, ") — клиент не раздаётся");
if (FALLBACK_DIR && fs.existsSync(FALLBACK_DIR)) console.log("[localbox] фоллбэк ассетов:", FALLBACK_DIR);
if (FETCH_ORIGIN) console.log("[localbox] докачка недостающего с", FETCH_ORIGIN, "→ кэш в", CLIENT_DIR);

// Ищет файл по пути сначала в основном каталоге, затем в фоллбэке. Возвращает путь или null.
function resolveInDir(base, urlPath) {
    if (!base) return null;
    const clean = path.normalize(decodeURIComponent(urlPath.split("?")[0])).replace(/^(\.\.[/\\])+/, "");
    const full = path.join(base, clean);
    if (!full.startsWith(base)) return null;
    return (fs.existsSync(full) && fs.statSync(full).isFile()) ? full : null;
}

function resolveFile(urlPath) {
    return resolveInDir(CLIENT_DIR, urlPath) || resolveInDir(FALLBACK_DIR, urlPath);
}

function rewrite(text, host) {
    // host = тот же адрес, с которого открыта страница, чтобы API-запросы были same-origin
    // (иначе браузер режет их по CORS). Fallback — serverUrl движка.
    const target = host || (global.jbg && global.jbg.serverUrl) || "localhost";
    let out = text;
    for (const h of REWRITE_HOSTS) out = out.split(h).join(target);
    out = out.replace(/\sintegrity=("|')[^"']*\1/gi, "");
    return out;
}

// Отдаёт содержимое буфера с нужным MIME; текстовые файлы прогоняются через rewrite (подмена хостов).
function sendBuffer(buf, ext, req, res) {
    res.setHeader("Content-Type", MIME[ext] || "application/octet-stream");
    res.setHeader("Access-Control-Allow-Origin", "*");
    if (TEXT_EXT.has(ext)) {
        const reqHost = (req.headers.host || "").split(":")[0] || null;
        res.end(rewrite(buf.toString("utf8"), reqHost));
    } else {
        res.end(buf);
    }
}

// Докачивает недостающий ассет с FETCH_ORIGIN по тому же пути, кэширует на диск и отдаёт.
function fetchAndCache(urlPath, req, res, next) {
    const cleanUrl = urlPath.split("?")[0];
    const clean = path.normalize(decodeURIComponent(cleanUrl)).replace(/^(\.\.[/\\])+/, "");
    const dest = path.join(CLIENT_DIR, clean);
    if (!dest.startsWith(CLIENT_DIR)) return next();
    const src = FETCH_ORIGIN + (cleanUrl.startsWith("/") ? cleanUrl : "/" + cleanUrl);
    https.get(src, { headers: { "user-agent": "Mozilla/5.0", "accept": "*/*" } }, (up) => {
        if (up.statusCode !== 200) { up.resume(); return next(); }
        const chunks = [];
        up.on("data", (c) => chunks.push(c));
        up.on("end", () => {
            const buf = Buffer.concat(chunks);
            // не кэшировать html-страницу ошибки/редиректа вместо ассета
            const head = buf.slice(0, 40).toString("utf8").toLowerCase();
            if (head.includes("<!doctype") || head.includes("<html")) return next();
            fs.mkdir(path.dirname(dest), { recursive: true }, () => fs.writeFile(dest, buf, () => {}));
            sendBuffer(buf, path.extname(dest).toLowerCase(), req, res);
        });
    }).on("error", () => next());
}

module.exports = function localboxClient(req, res, next) {
    if (!enabled || req.method !== "GET") return next();

    const urlPath = req.url === "/" ? "/index.html" : req.url;
    let file = resolveFile(urlPath);

    // SPA-маршрут без расширения -> index.html (из основного каталога)
    if (!file && path.extname(urlPath.split("?")[0]) === "") {
        file = resolveInDir(CLIENT_DIR, "/index.html");
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
