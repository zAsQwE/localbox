"use strict";
//
// LocalBox server — HTTP-маршруты Blobcast (старые игры): socket.io-handshake, комнаты,
// токены доступа, артефакты и пользовательский контент. Собственная реализация LocalBox.
//

const express = require("express");
const fs = require("fs");
const path = require("path");
const u = require("./util.js");
const mgr = require("./room.js");
const state = require("./state.js");
const artifacts = require("./artifacts.js");

const router = express.Router();
const CONTENT_DIR = path.join(__dirname, "..", "storage", "content");

function contentId() {
    const A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    let s = ""; for (let i = 0; i < 7; i++) s += A[Math.floor(Math.random() * A.length)];
    return s;
}

router.get("/crossdomain.xml", (req, res) => {
    res.type("application/xml").send(
        '<!DOCTYPE cross-domain-policy SYSTEM "http://www.macromedia.com/xml/dtds/cross-domain-policy.dtd">\n' +
        '<cross-domain-policy>\n\t<allow-access-from domain="*" to-ports="*" />\n</cross-domain-policy>');
});

// socket.io 0.9 handshake: <sessionId>:<heartbeat>:<closeTimeout>:<transports>
// Отвечаем на ЛЮБОЙ метод и со слэшем/без: Steam-хост шлёт GET, а Android/AIR-версия
// (напр. Word Spud «Слово Блуд») — POST /socket.io/1/ . Иначе хост не открывает сокет.
router.all(["/socket.io/1", "/socket.io/1/"], (req, res) => {
    const token = u.makeToken();
    res.type("text/plain").set("Set-Cookie", "socket.io.sid=" + token + "; Max-Age=3600");
    res.send(token + ":60:60:websocket");
});

router.get("/room", (req, res) => res.send({ create: true, server: state.serverUrl }));

router.get("/room/:roomId", (req, res) => {
    const room = mgr.get(req.params.roomId);
    if (!room) return res.status(404).send({ success: false, error: "Invalid Room Code" });
    let joinAs = "player";
    if (room.isFull() || room.locked) joinAs = room.findByUserId(req.query.userId) ? "player" : (room.audienceEnabled ? "audience" : "full");
    res.send({
        roomid: room.code, server: state.serverUrl, apptag: room.appTag, appid: room.appId,
        numAudience: room.audienceCount, audienceEnabled: room.audienceEnabled, joinAs,
        requiresPassword: !!room.password,
    });
});

router.post("/accessToken", (req, res) => {
    const b = req.body || {};
    for (const f of ["roomId", "appId", "userId"]) if (b[f] == null) return res.status(400).send({ success: false, error: "missing required parameter: " + f });
    const room = mgr.get(b.roomId);
    if (!room) return res.status(400).send({ success: false, error: "can't create access token for non-existent room" });
    // Проверку «владельца» намеренно смягчаем (локальный сервер): некоторые игры шлют другой userId
    // при запросе токена, чем при создании комнаты — из-за строгой проверки хост зависал на подключении.
    if (String(room.hostUserId) !== String(b.userId))
        console.log("[accessToken] userId не совпал (host=" + room.hostUserId + ", req=" + b.userId + ") — токен всё равно выдан");
    res.send({ success: true, accessToken: room.token });
});

// --- артефакты (рисунки/песни) ---
router.post("/artifact", (req, res) => {
    const b = req.body || {};
    for (const f of ["appId", "categoryId", "userId", "blob"]) if (b[f] == null) return res.status(400).send({ success: false, error: "missing required parameter: " + f });
    const artifactId = artifacts.create(b.categoryId, b.blob);
    res.send({ success: true, artifactId, categoryId: b.categoryId, rootId: "jbg-blobcast-artifacts" });
});
router.get("/artifact/:categoryId/:artifactId", (req, res) => {
    const blob = artifacts.get(req.params.categoryId, req.params.artifactId);
    if (blob) res.send(blob); else res.status(404).send({ success: false, error: "The specified key does not exist." });
});

// --- пользовательский контент (галереи и т.п.) ---
router.post("/storage/content", (req, res) => {
    const b = req.body || {};
    for (const f of ["appId", "categoryId", "userId"]) if (b[f] == null) return res.status(400).send({ success: false, error: "missing required parameter: " + f });
    fs.mkdirSync(CONTENT_DIR, { recursive: true });
    let id; do { id = contentId(); } while (fs.existsSync(path.join(CONTENT_DIR, id + ".json")));
    const doc = { appId: b.appId, blob: b.blob, categoryId: b.categoryId, creator: b.creator || {}, metadata: b.metadata || {}, userId: b.userId, createdTime: Date.now(), downloads: 0 };
    fs.writeFileSync(path.join(CONTENT_DIR, id + ".json"), JSON.stringify(doc), "utf8");
    res.send(Object.assign({ success: true, contentId: id }, doc));
});
router.get("/storage/content/:id", (req, res) => {
    const f = path.join(CONTENT_DIR, req.params.id + ".json");
    if (!fs.existsSync(f)) return res.status(404).send({ success: false, error: "Invalid User Content ID", error_code: 2005 });
    const c = JSON.parse(fs.readFileSync(f, "utf8"));
    res.send(Object.assign({ success: true, contentId: req.params.id }, c));
});

module.exports = router;
