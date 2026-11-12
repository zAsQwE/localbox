"use strict";
//
// LocalBox — точка входа. Свой сервер, совместимый с играми Jackbox по протоколам
// Ecast (API v2, современные игры) и Blobcast (socket.io, старые игры). Порты 80/443/38202/38203.
//

const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");
const crypto = require("crypto");
const express = require("express");
const { WebSocketServer } = require("ws");

const mgr = require("./lib/room.js");
const handleConnection = require("./lib/ws.js");
const handleBlobcast = require("./lib/blobcast-ws.js");
const blobcastRouter = require("./lib/blobcast.js");
const state = require("./lib/state.js");
const tts = require("./lib/tts.js");
const ttsPrewarm = require("./lib/tts-prewarm.js");
const render = require("./lib/render.js");
const admin = require("./lib/admin.js");
const localbox = require("./lib/localbox.js");
const network = require("./lib/network.js");
const availability = require("./lib/game-availability.js");
const QRCode = require("qrcode");

let config;
let activeTlsOptions;
const tlsReload = require("./lib/tls-reload.js");
try { config = JSON.parse(fs.readFileSync(path.join(__dirname, "config.json"), "utf8")); }
catch (e) { console.error("Не удалось прочитать server/config.json: " + e.message + ". Запустите лаунчер для настройки сервера."); process.exit(1); }
if (!config || !config.ssl || !config.ssl.cert || !config.ssl.key) {
    console.error("В server/config.json не заданы ssl.cert и ssl.key. Запустите лаунчер для настройки сервера."); process.exit(1);
}
state.serverUrl = config.serverUrl || "localhost";
render.setState(state);
render.logStatus();   // печатает статус Додо Ре Ми (ffmpeg/бэкинги), если поддержка включена
mgr.setAdminHook((code, event) => {
    admin.onRoomEvent(code, event);       // God view: события комнат → админ-панель
    localbox.onRoomEvent(mgr, code, event);
});
if (admin.enabled()) {
    console.log("[admin] читы включены для ников: " + admin.adminList().join(", ") + " · панель встроена в игровой клиент");
    if (!process.env.LOCALBOX_ADMIN_KEY) console.log("[admin] ключ доступа к читам: " + admin.key() + " (Ctrl+Shift+K в игре)");
}
// Таблица игр appId<->appTag + лимиты (нужна, чтобы комната сообщала клиенту верный appTag).
try {
    const gj = JSON.parse(fs.readFileSync(__dirname + "/games.json", "utf8"));
    for (const k of ["appTags", "appIds", "maxPlayers", "minPlayers"]) Object.assign(state.games[k], gj[k] || {});
} catch { /* нет таблицы — неизвестные игры регистрируются на лету */ }
if (config.games) for (const k of ["appTags", "appIds", "maxPlayers", "minPlayers"]) Object.assign(state.games[k], config.games[k] || {});
availability.registerGames(state.games);
if (!availability.enabled()) console.log("[games] Jackbox 12 выключен (LOCALBOX_ENABLE_PACK12=0).");
const serverUrl = state.serverUrl;
// Кастомный код комнаты (вместо случайного) — задаётся в лаунчере. Пусто = случайный код.
const ROOM_CODE = (process.env.LOCALBOX_ROOM_CODE || "").trim();
if (ROOM_CODE) console.log("[room] код комнаты фиксирован: " + ROOM_CODE);
if (localbox.AUTO_START_FULL) console.log("[room] автостарт включён: игра начнётся при заполнении комнаты");

// Кого пускать. Сервер в локальной сети (serverUrl — частный IP, localhost, *.local) принимает только
// локальные адреса; сервер с публичным адресом (VPS) — всех. LOCALBOX_ALLOW_PUBLIC=1/0 — принудительно.
const ALLOW_PUBLIC = process.env.LOCALBOX_ALLOW_PUBLIC ? process.env.LOCALBOX_ALLOW_PUBLIC === "1" : !network.isLocalHost(serverUrl);
const EXTRA_ORIGINS = new Set((process.env.LOCALBOX_ALLOWED_ORIGINS || "").split(",").map((v) => v.trim()).filter(Boolean));
function allowedPeer(socket) { return ALLOW_PUBLIC || network.isPrivateAddress(socket.remoteAddress); }
if (!ALLOW_PUBLIC) console.log("[net] принимаю только локальную сеть и VPN (Radmin, Hamachi, Tailscale); проброс портов — галочка «Пускать подключения не из локальной сети» или LOCALBOX_ALLOW_PUBLIC=1");

const app = express();
app.use((req, res, next) => {
    if (allowedPeer(req.socket)) return next();
    console.log("[net] отклонён внешний адрес " + req.socket.remoteAddress +
        " — чтобы пускать, включите «Пускать подключения не из локальной сети» в настройках или задайте LOCALBOX_ALLOW_PUBLIC=1");
    res.sendStatus(403);
});
// Большие тела нужны только рисункам и пользовательскому контенту.
app.use(["/artifact", "/storage/content"], express.json({ limit: "10mb" }));
app.use(express.json({ limit: "1mb" }));

// CORS: эхо-возврат origin только своим и локальным страницам (иначе локальная игра режется по CORS).
app.use((req, res, next) => {
    // Логируем только значимое (API/комнаты/сокеты), а не каждую картинку/скрипт — иначе спам и лаги.
    const pth = req.path;
    if (process.env.LOCALBOX_DEBUG === "1" || req.method !== "GET" || /^\/(api|room|socket\.io|artifact|storage|accessToken|render|tts)/.test(pth))
        console.log(req.method, req.originalUrl, req.body && Object.keys(req.body).length ? JSON.stringify(req.body).slice(0, 300) : "");
    const origin = req.headers.origin;
    if (origin && (ALLOW_PUBLIC || network.trustedOrigin(origin, req, EXTRA_ORIGINS))) {
        res.header("Access-Control-Allow-Origin", origin);
        res.header("Access-Control-Allow-Credentials", "true");
    }
    res.header("Vary", "Origin");
    res.header("Access-Control-Allow-Methods", "GET,HEAD,POST,PUT,OPTIONS");
    res.header("Access-Control-Allow-Headers", "content-type,if-none-match,x-jbg-secret,x-internal-token");
    if (req.method === "OPTIONS") return res.status(200).end();
    next();
});

require("./lib/images.js").mount(app);
require("./lib/image-cdn.js").mount(app);
require("./lib/client-updates.js").mount(app);

// POST /api/v2/rooms — создать комнату.
function disabledGame(req, res, tag, id) {
    console.warn("[games] HTTP 422 game_disabled: " + JSON.stringify({ appTag: tag, appId: id }) +
        " — Jackbox 12 выключен переменной LOCALBOX_ENABLE_PACK12=0.");
    return res.status(422).send({ ok: false, error: availability.message, errorCode: "game_disabled" });
}
app.post("/api/v2/rooms", (req, res) => {
    const p = req.body || {};
    if (availability.isDisabled(p.appTag, p.appId))
        return disabledGame(req, res, p.appTag, p.appId);
    if (!p.userId) return res.status(400).send({ ok: false, error: "missing required field userId" });
    // The Unreal Ecast client can identify its game by appId alone.
    if (!p.appTag && typeof p.appId === "string") p.appTag = state.games.appIds[p.appId];
    if (!p.appTag) return res.status(400).send({ ok: false, error: "missing required field appTag" });
    if (!state.register(p))
        return disabledGame(req, res, p.appTag, p.appId);
    if (ROOM_CODE) p.forceRoomId = ROOM_CODE;   // фиксированный код комнаты из настроек
    const room = new mgr.Room(p, serverUrl, state.games);
    // A game started with -jbg.config protocol=http (Jackbox 12 under Proton) must also
    // download our files over HTTP; its TLS stack would reject the LocalBox certificate.
    room.hostScheme = req.socket.encrypted ? "https" : "http";
    mgr.add(room);
    console.log("[room] created", room.code, "for", room.appTag, "(" + room.appId + ")");
    if (availability.isPack12(room.appTag, room.appId)) {
        const pending = setTimeout(() => {
            if (mgr.get(room.code) === room && !room.closed && !room.host?.connected)
                console.warn("[room] " + room.code + ": комната создана, но игра ещё не подключилась по WebSocket. Проверьте адрес serverUrl, доступ к TCP 443 и доверие CA LocalBox на компьютере с игрой (кнопка «Обновить сертификат»; для Proton — в его окружении).");
        }, 8000);
        pending.unref();
    }
    res.send({ ok: true, body: { host: serverUrl, code: room.code, token: room.token } });
});

// GET /api/v2/app-configs/:appTag — настройки игры (если заданы; иначе клиент берёт свои дефолты).
app.get("/api/v2/app-configs/:appTag", (req, res) => {
    const tag = req.params.appTag;
    if (availability.isDisabled(tag))
        return disabledGame(req, res, tag);
    const settings = config.appConfigs && config.appConfigs[tag];
    if (!settings) return res.status(404).send({ ok: false, error: "no app config for " + tag });
    res.send({ ok: true, body: { appId: state.games.appTags[tag] || tag, appTag: tag, settings } });
});

// GET /api/v2/ugc/list/:listId — официальные эпизоды. Локально список пуст; без ответа игры Party Starter висят на загрузке.
app.get("/api/v2/ugc/list/:listId", (req, res) => res.send({ ok: true, body: { listId: req.params.listId, entries: [] } }));

// GET /api/v2/rooms/:code — информация о комнате (клиент проверяет перед входом).
app.get("/api/v2/rooms/:code", (req, res) => {
    const room = mgr.get(req.params.code);
    if (!room) return res.status(404).send({ ok: false, error: "no such room" });
    // host — АДРЕС, ПО КОТОРОМУ ИГРОК К НАМ ДОСТУЧАЛСЯ (Host-заголовок), а не фиксированный serverUrl.
    // Клиент подключается к room.host, поэтому каждый должен идти туда, откуда пришёл: удалённый игрок —
    // на свой localhost (порт проброшен Steam-прокси), LAN-игрок — на LAN-IP, локальный — на localhost.
    const reqHost = (req.headers.host || serverUrl);
    res.send({
        ok: true,
        body: {
            appId: room.appId, appTag: room.appTag,
            audienceEnabled: room.audienceEnabled,
            code: room.code, host: reqHost, audienceHost: reqHost,
            locked: room.locked, full: room.isFull(),
            maxPlayers: room.maxPlayers, minPlayers: room.minPlayers,
            moderationEnabled: !!room.moderatorPassword,
            passwordRequired: !!room.password,
            twitchLocked: false, locale: "en", keepalive: false, controllerBranch: "",
        },
    });
});

// TTS: синтез речи (Mad Verse City и др.). Локально через espeak/ffmpeg, без AWS Polly.
app.post("/tts/generate", async (req, res) => {
    const b = req.body || {};
    if (!b.text) return res.status(400).send({ success: false, error: "missing required parameter: text" });
    try {
        const name = await tts.generate(b.text, b.voice, b.rate, ttsPrewarm.ownerForRequest(req, mgr.list()));
        res.send({ success: true, url: network.origin(req, serverUrl) + "/tts/" + name });
    } catch (e) {
        res.status(500).send({ success: false, error: String(e && e.message || e) });
    }
});
app.get("/tts/:file", (req, res) => {
    const f = path.join(tts.DIR, path.basename(req.params.file));
    if (!fs.existsSync(f)) return res.sendStatus(404);
    res.type(f.endsWith(".mp3") ? "audio/mpeg" : "audio/wav");
    fs.createReadStream(f).on("error", () => res.sendStatus(404)).pipe(res);
});

// Отрендеренные выступления Додо Ре Ми (mp3).
app.get("/render/:file", (req, res) => {
    const f = path.join(render.OUT_DIR, path.basename(req.params.file));
    if (!fs.existsSync(f)) return res.sendStatus(404);
    res.type("audio/mpeg");
    fs.createReadStream(f).on("error", () => res.sendStatus(404)).pipe(res);
});

// Read-only certificate information; trust installation requires explicit launcher consent.
function sendPublicCa(req, res) {
    const ca = activeTlsOptions && tlsReload.publicCa(activeTlsOptions);
    if (!ca) return res.sendStatus(404);
    const filename = req.path.endsWith(".crt") ? "localbox-ca.crt" : "localbox-ca.pem";
    res.type("application/x-x509-ca-cert").set("Content-Disposition", `attachment; filename="${filename}"`);
    res.set("Cache-Control", "no-store").send(ca);
}
app.get(["/localbox-ca.pem", "/localbox-ca.crt"], sendPublicCa);
app.get("/localbox-ca", (_req, res) => {
    const ca = activeTlsOptions && tlsReload.publicCa(activeTlsOptions);
    if (!ca) return res.sendStatus(404);
    const fingerprint = new crypto.X509Certificate(ca).fingerprint256;
    res.type("html").send(`<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>CA LocalBox</title><style>body{font:18px system-ui;max-width:720px;margin:40px auto;padding:0 20px;line-height:1.5}a{display:inline-block;padding:12px 18px;background:#6757e8;color:white;border-radius:8px;text-decoration:none}code{word-break:break-all}</style><h1>Сертификат LocalBox</h1><p>Это публичный корневой CA сервера. Скачивание файла не устанавливает доверие. В лаунчере кнопка «Обновить сертификат» добавляет CA в доверенные на компьютере с лаунчером только после предупреждения и подтверждения.</p><p><a href="/localbox-ca.crt">Скачать localbox-ca.crt</a></p><p>SHA-256: <code>${fingerprint || "недоступен"}</code></p><p>Закрытого ключа в этом файле нет.</p></html>`);
});

// Состояние активной комнаты для QR-оверлея лаунчера.
// QR открывает HTTPS-клиент с кодом комнаты в параметрах ссылки.
function activeRoom() {
    return mgr.list().filter((room) => !room.closed && room.host && room.host.connected)
        .sort((a, b) => b.createdAt - a.createdAt)[0] || null;
}
app.get("/localbox/status", (_req, res) => {
    res.set("Cache-Control", "no-store").send({ ok: true, room: localbox.roomStatus(activeRoom(), serverUrl), playerUrl: localbox.joinOrigin(serverUrl) });
});
app.get("/localbox/qr.png", async (req, res) => {
    const room = req.query.code ? mgr.get(String(req.query.code).toUpperCase()) : activeRoom();
    const status = localbox.roomStatus(room, serverUrl);
    if (!status) return res.status(404).send({ ok: false, error: "no active room" });
    try {
        const png = await QRCode.toBuffer(status.joinUrl, { type: "png", errorCorrectionLevel: "M", margin: 2, width: 256 });
        res.type("png").set("Cache-Control", "no-store").send(png);
    } catch (error) {
        res.status(500).send({ ok: false, error: String(error && error.message || error) });
    }
});

// прочие маршруты клиента
app.post("/api/v2/controller/state", (req, res) => res.sendStatus(200));
app.get("/api/v2/rooms/:code/play", (req, res) =>
    res.status(400).type("text/plain").send('Bad Request\n{"ok":false,"error":"the client is not using the websocket protocol"}'));

// Админ-панель (читы) — доступна по нику из LOCALBOX_ADMINS.
admin.mountHttp(app);

// Blobcast (старые игры): /room, /socket.io/1, /accessToken, /artifact, /storage/content, ...
app.use(blobcastRouter);

// раздача веб-клиента (моё middleware) и 404
app.use(require("./client.js"));
app.use((req, res) => {
    // Явно логируем НЕ найденные ассеты (картинки/шрифты/css/js) — чтобы видеть, какой файл
    // игра просит, но сервер не отдаёт (напр. пропавшая «ткань»/фон). Не спамим favicon и т.п.
    const p = (req.url.split("?")[0] || "");
    if (req.method === "GET" && /\.(png|jpe?g|gif|webp|svg|css|js|woff2?|ttf|ogg|mp3|json)$/i.test(p) && !/favicon|apple-touch/.test(p)) {
        console.log("[404] нет файла: " + p);
    }
    res.status(404).type("text/plain").send("404 page not found");
});

// ---- сервера + апгрейд WebSocket ----
const wss = new WebSocketServer({ noServer: true });

function onUpgrade(request, socket, head) {
    if (!allowedPeer(request.socket)) {
        console.log("[net] отклонено WebSocket-подключение с " + request.socket.remoteAddress + " — LOCALBOX_ALLOW_PUBLIC=1, чтобы пускать");
        socket.destroy(); return;
    }
    // WebSocket может открыть и чужой сайт в браузере игрока — проверяем Origin, если он есть.
    if (!ALLOW_PUBLIC && request.headers.origin && !network.trustedOrigin(request.headers.origin, request, EXTRA_ORIGINS)) {
        console.log("[ws] апгрейд отклонён (чужой Origin):", request.headers.origin); socket.destroy(); return;
    }
    const [reqPath, qs] = request.url.split("?");
    const query = Object.fromEntries(new URLSearchParams(qs || ""));
    console.log("[ws] апгрейд:", reqPath, qs ? "?" + qs : "");
    // Админ-панель: /admin/ws?nick=...
    if (reqPath === "/admin/ws") {
        wss.handleUpgrade(request, socket, head, (client) => admin.handleWs(client, query));
        return;
    }
    // Blobcast: socket.io 0.9 — /socket.io/1/websocket/<token>
    if (/^\/socket\.io\/1\/websocket\/[0-9a-f]+$/.test(reqPath)) {
        wss.handleUpgrade(request, socket, head, (client) => {
            client.localboxAddress = network.address(request, serverUrl);
            handleBlobcast(client);
        });
        return;
    }
    // Ecast: /api/v2/rooms/CODE/play. Код — не только 4 латинские буквы: поддерживаем кастомный
    // код комнаты (LOCALBOX_ROOM_CODE), в т.ч. не-ASCII (в URL он percent-encoded → декодируем).
    const m = reqPath.match(/^\/api\/v2\/(?:rooms|audience)\/([^/]+)\/play$/);
    if (!m) { console.log("[ws] апгрейд ОТКЛОНЁН (путь не распознан):", reqPath); socket.destroy(); return; }
    let code; try { code = decodeURIComponent(m[1]); } catch { socket.destroy(); return; }
    wss.handleUpgrade(request, socket, head, (client) => {
        client.localboxAddress = network.address(request, serverUrl);
        handleConnection(client, code, query);
    });
}

let servers = [];
try {
    const files = { cert: path.resolve(__dirname, config.ssl.cert), key: path.resolve(__dirname, config.ssl.key) };
    // After a long VPS outage the certificate may have expired. HTTP must still
    // start so Certbot's webroot challenge can renew it. New pairs are checked
    // for validity before hot reload; clients keep enforcing TLS validity too.
    const initial = tlsReload.read(files, { allowExpired: true });
    const ssl = initial.options;
    activeTlsOptions = ssl;
    const publicRoot = tlsReload.publicCa(ssl);
    if (publicRoot) console.log("[tls] CA работающего сервера SHA-256: " + new crypto.X509Certificate(publicRoot).fingerprint256);
    servers = [
        { s: http.createServer(app), port: 80 },
        { s: https.createServer(ssl, app), port: 443 },
        { s: http.createServer(app), port: 38202 },
        { s: https.createServer(ssl, app), port: 38203 },
    ];
    // Отдельный веб-порт для телефонов (LOCALBOX_PLAYER_PORT): 38202 остаётся всегда — он нужен
    // Blobcast-играм. Если порт занят, берётся следующий свободный; QR ведёт на фактический.
    const playerPort = Number(process.env.LOCALBOX_PLAYER_PORT || 0);
    if (Number.isInteger(playerPort) && playerPort >= 1024 && playerPort <= 65535 && playerPort !== 38202 && playerPort !== 38203) {
        servers.push({ s: http.createServer(app), port: playerPort, player: true });
    } else if (process.env.LOCALBOX_PLAYER_PORT) {
        console.error("[net] LOCALBOX_PLAYER_PORT=" + process.env.LOCALBOX_PLAYER_PORT + " не подходит: нужен 1024–65535, кроме 38202/38203");
    }
    // Porthole: an extra plain-HTTP web port for friends whose port 80 is taken (e.g. 9999).
    // Players get links back to whatever host:port they used, so nothing else changes.
    const portholePort = Number(process.env.LOCALBOX_PORTHOLE_PORT || 0);
    if (Number.isInteger(portholePort) && portholePort >= 1024 && portholePort <= 65535 &&
        !servers.some(({ port }) => port === portholePort)) {
        servers.push({ s: http.createServer(app), port: portholePort });
        console.log("[porthole] дополнительный веб-порт " + portholePort + ": у друга http://127.0.0.1:" + portholePort);
    } else if (process.env.LOCALBOX_PORTHOLE_PORT) {
        console.error("[porthole] порт " + process.env.LOCALBOX_PORTHOLE_PORT + " не подходит: нужен 1024–65535, кроме 38202/38203");
    }
    tlsReload.watch(servers.filter(({ s }) => s instanceof https.Server).map(({ s }) => s), files,
        { initial, onReload: next => { activeTlsOptions = next.options; } });
} catch (e) {
    console.error("Не удалось прочитать сертификаты (" + config.ssl.cert + "). Запустите «Сертификат» в лаунчере.");
    process.exit(1);
}

let boundPorts = 0;
const recentTlsErrors = new Map();
servers.forEach((entry) => {
    const { s } = entry;
    let { port } = entry;
    let tries = 0;
    s.on("upgrade", onUpgrade);
    // Диагностика: если хост/клиент пытается подключиться, но рвётся на TLS (недоверенный
    // самоподписанный серт) — обычный лог запросов это не покажет. Логируем такие обрывы.
    s.on("tlsClientError", (err, sock) => {
        const ip = sock && sock.remoteAddress;
        if (!err || /ECONNRESET|EPIPE/.test(err.code || "")) return;
        // Plain HTTP on an HTTPS port is a client typo/health probe, not a certificate failure.
        if (/http request/i.test(err.message || "")) return;
        // A game retries failed TLS handshakes several times per second. Keep one actionable
        // message per source/error instead of flooding the launcher log.
        const message = err.message || err.code;
        const key = `${port}:${ip || "unknown"}:${err.code || message}`;
        const now = Date.now();
        if (now - (recentTlsErrors.get(key) || 0) < 10000) return;
        recentTlsErrors.set(key, now);
        if (/unknown ca/i.test(message)) {
            console.error(`[tls] клиент ${ip || "?"} не доверяет сертификату сервера (порт ${port}). Если это браузер или телефон — откройте http://${serverUrl} (без https), сертификат там не нужен. Если это игра: на Windows один раз нажмите «Обновить сертификат» в LocalBox; на Linux скопируйте в Steam полную строку запуска из лаунчера (с -cafile и SSL_CERT_FILE).`);
        } else {
            console.error("[tls] обрыв на TLS (порт " + port + ", от " + ip + "): " + message);
        }
    });
    s.on("clientError", (err, sock) => { try { sock.destroy(); } catch { /* ignore */ } });
    s.on("error", (err) => {
        // НЕ падаем: пропускаем недоступный порт, сервер продолжит на остальных.
        // На Android/Termux без root порты 80/443 недоступны (EACCES) — останутся 38202/38203.
        if (err.code === "EACCES") console.error("порт " + port + " без прав недоступен (Android без root / нет setcap) — пропускаю");
        else if (err.code === "EADDRINUSE" && entry.player && ++tries <= 20) {
            const next = port + 1 + (port + 1 === 38202 ? 2 : port + 1 === 38203 ? 1 : 0);   // свои порты не трогаем
            console.error("порт " + port + " занят — пробую " + next);
            port = next; s.listen(port); return;
        }
        else if (err.code === "EADDRINUSE") console.error("порт " + port + " занят — пропускаю");
        else console.error("порт " + port + ": " + err.message + " — пропускаю");
    });
    s.on("listening", () => {   // один обработчик на все попытки
        boundPorts++;
        if (entry.player) state.playerPort = port;
        if (port === 80) state.port80 = true;
        if (port === 38202) state.port38202 = true;
        console.log("LocalBox: порт " + port + (entry.player ? " (для телефонов)" : ""));
    });
    s.listen(port);
});
// Если через 3с не занялся ни один порт — сообщаем внятно.
setTimeout(() => {
    if (boundPorts === 0) { console.error("Не удалось открыть ни один порт сервера. Проверьте права и занятые порты."); process.exit(1); }
}, 3000);
