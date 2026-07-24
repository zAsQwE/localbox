"use strict";
//
// LocalBox server — точка входа. Свой сервер, совместимый с играми Jackbox по протоколам
// Ecast (API v2, современные игры) и Blobcast (socket.io, старые игры). Порты 80/443/38202/38203.
//

const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");
const express = require("express");
const { WebSocketServer } = require("ws");

const mgr = require("./lib/room.js");
const handleConnection = require("./lib/ws.js");
const handleBlobcast = require("./lib/blobcast-ws.js");
const blobcastRouter = require("./lib/blobcast.js");
const state = require("./lib/state.js");
const tts = require("./lib/tts.js");
const render = require("./lib/render.js");
const admin = require("./lib/admin.js");

const config = JSON.parse(fs.readFileSync(__dirname + "/config.json", "utf8"));
state.serverUrl = config.serverUrl || "localhost";
render.setState(state);
render.logStatus();   // печатает статус Додо Ре Ми (ffmpeg/бэкинги), если поддержка включена
mgr.setAdminHook(admin.onRoomEvent);   // God view: события комнат → админ-панель
if (admin.enabled()) console.log("[admin] читы включены для ников: " + admin.adminList().join(", ") + " · панель: https://" + state.serverUrl + "/admin");
// Таблица игр appId<->appTag + лимиты (нужна, чтобы комната сообщала клиенту верный appTag).
try {
    const gj = JSON.parse(fs.readFileSync(__dirname + "/games.json", "utf8"));
    for (const k of ["appTags", "appIds", "maxPlayers", "minPlayers"]) Object.assign(state.games[k], gj[k] || {});
} catch { /* нет таблицы — неизвестные игры регистрируются на лету */ }
if (config.games) for (const k of ["appTags", "appIds", "maxPlayers", "minPlayers"]) Object.assign(state.games[k], config.games[k] || {});
const serverUrl = state.serverUrl;

const app = express();
app.use(express.json({ limit: "10mb" }));

// CORS: эхо-возврат origin страницы (иначе локальная игра режется по CORS).
app.use((req, res, next) => {
    // Логируем только значимое (API/комнаты/сокеты), а не каждую картинку/скрипт — иначе спам и лаги.
    const pth = req.path;
    if (process.env.LOCALBOX_DEBUG === "1" || req.method !== "GET" || /^\/(api|room|socket\.io|artifact|storage|accessToken|render|tts)/.test(pth))
        console.log(req.method, req.originalUrl, req.body && Object.keys(req.body).length ? JSON.stringify(req.body).slice(0, 300) : "");
    const origin = req.headers.origin;
    if (origin) res.header("Access-Control-Allow-Origin", origin);
    res.header("Access-Control-Allow-Credentials", "true");
    res.header("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
    res.header("Access-Control-Allow-Headers", "content-type,x-jbg-secret,x-internal-token");
    if (req.method === "OPTIONS") return res.status(200).end();
    next();
});

// POST /api/v2/rooms — создать комнату.
app.post("/api/v2/rooms", (req, res) => {
    const p = req.body || {};
    if (!p.userId) return res.status(400).send({ ok: false, error: "missing required field userId" });
    if (!p.appTag) return res.status(400).send({ ok: false, error: "missing required field appTag" });
    state.register(p);
    const room = new mgr.Room(p, serverUrl, state.games);
    mgr.add(room);
    console.log("[room] created", room.code, "for", room.appTag, "(" + room.appId + ")");
    res.send({ ok: true, body: { host: serverUrl, code: room.code, token: room.token } });
});

// GET /api/v2/app-configs/:appTag — настройки игры (если заданы; иначе клиент берёт свои дефолты).
app.get("/api/v2/app-configs/:appTag", (req, res) => {
    const tag = req.params.appTag;
    const settings = config.appConfigs && config.appConfigs[tag];
    if (!settings) return res.status(404).send({ ok: false, error: "no app config for " + tag });
    res.send({ ok: true, body: { appId: state.games.appTags[tag] || tag, appTag: tag, settings } });
});

// GET /api/v2/rooms/:code — информация о комнате (клиент проверяет перед входом).
app.get("/api/v2/rooms/:code", (req, res) => {
    const room = mgr.get(req.params.code);
    if (!room) return res.status(404).send({ ok: false, error: "no such room" });
    res.send({
        ok: true,
        body: {
            appId: room.appId, appTag: room.appTag,
            audienceEnabled: room.audienceEnabled,
            code: room.code, host: serverUrl, audienceHost: serverUrl,
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
        const name = await tts.generate(b.text, b.voice, b.rate);
        res.send({ success: true, url: "https://" + serverUrl + "/tts/" + name });
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
    const [reqPath, qs] = request.url.split("?");
    console.log("[ws] апгрейд:", reqPath, qs ? "?" + qs : "");
    // Админ-панель: /admin/ws?nick=...
    if (reqPath === "/admin/ws") {
        const q = {};
        (qs || "").split("&").forEach((kv) => { const i = kv.indexOf("="); if (i > 0) q[decodeURIComponent(kv.slice(0, i))] = decodeURIComponent(kv.slice(i + 1)); });
        wss.handleUpgrade(request, socket, head, (client) => admin.handleWs(client, q));
        return;
    }
    // Blobcast: socket.io 0.9 — /socket.io/1/websocket/<token>
    if (/^\/socket\.io\/1\/websocket\/[0-9a-f]+$/.test(reqPath)) {
        wss.handleUpgrade(request, socket, head, (client) => handleBlobcast(client));
        return;
    }
    // Ecast: /api/v2/rooms/CODE/play
    const m = reqPath.match(/^\/api\/v2\/(?:rooms|audience)\/([A-Z]{4})\/play$/);
    if (!m) { console.log("[ws] апгрейд ОТКЛОНЁН (путь не распознан):", reqPath); socket.destroy(); return; }
    const query = {};
    (qs || "").split("&").forEach((kv) => {
        const i = kv.indexOf("=");
        if (i > 0) query[decodeURIComponent(kv.slice(0, i))] = decodeURIComponent(kv.slice(i + 1));
    });
    wss.handleUpgrade(request, socket, head, (client) => handleConnection(client, m[1], query));
}

let servers = [];
try {
    const ssl = { cert: fs.readFileSync(__dirname + "/" + config.ssl.cert), key: fs.readFileSync(__dirname + "/" + config.ssl.key) };
    servers = [
        { s: http.createServer(app), port: 80 },
        { s: https.createServer(ssl, app), port: 443 },
        { s: http.createServer(app), port: 38202 },
        { s: https.createServer(ssl, app), port: 38203 },
    ];
} catch (e) {
    console.error("Не удалось прочитать сертификаты (" + config.ssl.cert + "). Запустите «Сертификат» в лаунчере.");
    process.exit(1);
}

let boundPorts = 0;
servers.forEach(({ s, port }) => {
    s.on("upgrade", onUpgrade);
    // Диагностика: если хост/клиент пытается подключиться, но рвётся на TLS (недоверенный
    // самоподписанный серт) — обычный лог запросов это не покажет. Логируем такие обрывы.
    s.on("tlsClientError", (err, sock) => {
        const ip = sock && sock.remoteAddress;
        if (err && !/ECONNRESET|EPIPE/.test(err.code || "")) console.error("[tls] обрыв на TLS (порт " + port + ", от " + ip + "): " + (err.message || err.code));
    });
    s.on("clientError", (err, sock) => { try { sock.destroy(); } catch { /* ignore */ } });
    s.on("error", (err) => {
        // НЕ падаем: пропускаем недоступный порт, сервер продолжит на остальных.
        // На Android/Termux без root порты 80/443 недоступны (EACCES) — останутся 38202/38203.
        if (err.code === "EACCES") console.error("порт " + port + " без прав недоступен (Android без root / нет setcap) — пропускаю");
        else if (err.code === "EADDRINUSE") console.error("порт " + port + " занят — пропускаю");
        else console.error("порт " + port + ": " + err.message + " — пропускаю");
    });
    s.listen(port, () => { boundPorts++; console.log("LocalBox server: порт " + port); });
});
// Если через 3с не занялся ни один порт — сообщаем внятно.
setTimeout(() => {
    if (boundPorts === 0) console.error("Ни один порт не занят. На Android без root дайте права (setcap) или используйте другой порт.");
}, 3000);
