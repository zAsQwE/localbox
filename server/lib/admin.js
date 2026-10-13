"use strict";
//
// LocalBox — читы для приватной игры в LAN (оверлей прямо в игре, без отдельной веб-страницы).
//
// Доступ по нику из LOCALBOX_ADMINS (список ников через запятую). Читы встраиваются в игровой
// клиент оверлеем (вкладка справа). Возможности:
//   • God view — видеть ВСЕ сущности комнаты в реальном времени (секретные ответы/голоса/рисунки);
//   • правильный ответ — подсветка (для викторин/Бредовухи); включается LOCALBOX_CHEAT_ANSWER;
//   • подмена — менять значение любой сущности (напр. изменить ответ игрока в Бредовухе);
//   • модерация — кик/бан/мьют/переименование игроков.
//
// Правила игр считает Steam-хост, так что «форснуть победу/очки» нельзя — но текст ответов и
// прочие сущности хост просто хранит, поэтому подмена «прилипает». Только для игры с друзьями.
//

const mgr = require("./room.js");
const cheats = require("./cheat-answers.js");
let contentIndex;
function hintsOf(r) {
    if (!contentIndex) {
        contentIndex = cheats.loadInstalledContent();
        console.log("[admin] найдено вопросов с ответами в установленных играх: " + contentIndex.count);
    }
    return cheats.analyze(entitiesOf(r), r.appTag, contentIndex);
}

const ADMINS = new Set((process.env.LOCALBOX_ADMINS || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean));
// Показывать в оверлее «правильный ответ» (подсветка для викторин/Бредовухи). Выкл: LOCALBOX_CHEAT_ANSWER=0.
const SHOW_ANSWER = process.env.LOCALBOX_CHEAT_ANSWER !== "0";
// Показывать цену картины (Дуракцион/Bidiots) пульсирующим ценником у картины. Выкл: LOCALBOX_CHEAT_PRICE=0.
const SHOW_PRICE = process.env.LOCALBOX_CHEAT_PRICE !== "0";
// Подсвечивать найденные правильные варианты на кнопках. Выкл: LOCALBOX_CHEAT_HIGHLIGHT=0.
const SHOW_HIGHLIGHT = process.env.LOCALBOX_CHEAT_HIGHLIGHT !== "0";
function isAdmin(nick) { return ADMINS.has(String(nick || "").trim().toLowerCase()); }
function enabled() { return ADMINS.size > 0; }
function adminList() { return [...ADMINS]; }

// Подписчики панели: ws -> код комнаты (или null, пока не выбрана).
const subs = new Map();

function playersOf(r) {
    const out = [];
    if (r.host && r.host.profileId != null) out.push({ id: r.host.profileId, name: r.host.name || "(хост)", role: "host" });
    Object.values(r.players).forEach((p) => out.push({
        id: p.profileId, userId: p.userId, name: p.name, role: p.role,
        muted: !!(r.muted && r.muted.has(p.profileId)), banned: !!p.banned,
    }));
    return out;
}
function entitiesOf(r) {
    const out = Object.create(null);
    for (const k of Object.keys(r.entities)) {
        try { out[k] = { type: r.entities[k].type, body: r.getBody(k) }; } catch { /* skip */ }
    }
    return out;
}
function roomsSummary() {
    return mgr.list().map((r) => ({ code: r.code, appTag: r.appTag, players: Object.keys(r.players).length }));
}
function send(ws, obj) { try { ws.send(JSON.stringify(obj)); } catch { /* закрыт */ } }

function snapshot(ws, code) {
    const r = mgr.get(code);
    if (!r) return send(ws, { t: "err", msg: "нет комнаты " + code });
    send(ws, { t: "snapshot", code, appTag: r.appTag, players: playersOf(r), entities: entitiesOf(r), hints: hintsOf(r) });
}

// Хук из room.js — событие по комнате (рассылаем подписчикам этой комнаты).
function onRoomEvent(code, ev) {
    let hints;
    for (const [ws, c] of subs) {
        if (c !== code) continue;
        if (ev.t === "entity") send(ws, { t: "entity", key: ev.body.key, type: ev.type, body: ev.body });
        else if (ev.t === "drop") send(ws, { t: "drop", key: ev.key });
        else if (ev.t === "players") { const r = mgr.get(code); if (r) send(ws, { t: "players", players: playersOf(r) }); }
        if (ev.t === "entity" || ev.t === "drop") {
            const r = mgr.get(code);
            if (r) { hints ||= hintsOf(r); send(ws, { t: "hints", hints }); }
        }
    }
}

function handleWs(ws, query) {
    if (!isAdmin(query.nick)) { send(ws, { t: "err", msg: "ник «" + (query.nick || "") + "» не в списке админов" }); try { ws.close(); } catch { /* ignore */ } return; }
    subs.set(ws, null);
    send(ws, { t: "ok", nick: query.nick, rooms: roomsSummary() });
    ws.on("message", (data) => {
        let m; try { m = JSON.parse(data.toString()); } catch { return; }
        if (!m || typeof m !== "object" || Array.isArray(m)) return;
        if (m.cmd === "rooms") return send(ws, { t: "rooms", rooms: roomsSummary() });
        if (m.cmd === "watch") {
            if (!mgr.get(m.code)) return send(ws, { t: "err", msg: "нет комнаты " + m.code });
            subs.set(ws, m.code); return snapshot(ws, m.code);
        }
        const code = m.code || subs.get(ws);
        const r = code && mgr.get(code);
        if (!r) return send(ws, { t: "err", msg: "комната не выбрана/не найдена" });
        try { doCmd(r, m, ws); } catch (e) { send(ws, { t: "err", msg: String((e && e.message) || e) }); }
    });
    ws.on("close", () => subs.delete(ws));
    ws.on("error", () => subs.delete(ws));
}

function doCmd(r, m, ws) {
    switch (m.cmd) {
        case "set": {
            const e = r.entities[m.key];
            if (e) {
                r.updateEntity(m.key, { val: m.val }, m.from != null ? Number(m.from) : e.from);
            } else {
                r.setEntity(m.type || "object", m.key, m.acl || ["rw *"], { val: m.val });
            }
            r.notify(m.key, true, null);
            send(ws, { t: "info", msg: "✔ сущность " + m.key + " обновлена" });
            break;
        }
        case "players": send(ws, { t: "players", players: playersOf(r) }); break;   // авто-обновление ростера
        case "kick": r.kick(Number(m.id), !!m.ban); send(ws, { t: "info", msg: "игрок #" + m.id + (m.ban ? " забанен" : " кикнут") }); break;
        case "mute": r.setMute(Number(m.id), !!m.on); onRoomEvent(r.code, { t: "players" }); send(ws, { t: "info", msg: "мьют #" + m.id + ": " + (m.on ? "вкл" : "выкл") }); break;
        case "rename": r.renamePlayer(Number(m.id), String(m.name || "")); onRoomEvent(r.code, { t: "players" }); send(ws, { t: "info", msg: "переименован #" + m.id }); break;
        default: send(ws, { t: "err", msg: "неизвестная команда " + m.cmd });
    }
}

function mountHttp(app) {
    // Отдельной веб-страницы /admin больше нет — только оверлей, встраиваемый в игровой клиент.
    // В начало оверлея подставляем конфиг (показывать ли «правильный ответ»).
    app.get("/admin/overlay.js", (_req, res) =>
        res.type("application/javascript").send("window.__lbxCfg={showAnswer:" + SHOW_ANSWER + ",showPrice:" + SHOW_PRICE + ",highlight:" + SHOW_HIGHLIGHT + "};\n" + OVERLAY_JS));
}

// Оверлей-панелька, встраиваемая в игровой клиент (client.js вставляет <script src="/admin/overlay.js">).
// Появляется вкладка справа; вводишь ник → если админ, открывается панель с читами прямо в игре.
const OVERLAY_JS = require("node:fs").readFileSync(require("node:path").join(__dirname, "admin-overlay.js"), "utf8");

module.exports = { isAdmin, enabled, adminList, handleWs, mountHttp, onRoomEvent };
