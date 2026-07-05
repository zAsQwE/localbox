"use strict";
//
// LocalBox server — обработка WebSocket-соединений Ecast (роли, welcome, диспетчер опкодов).
// Собственная реализация LocalBox.
//

const u = require("./util.js");
const mgr = require("./room.js");
const artifacts = require("./artifacts.js");

const DEBUG = process.env.LOCALBOX_DEBUG === "1";

const ERR = {
    1002: "unable to connect to room",
    2001: "parse error in ecast protocol",
    2002: "missing opcode",
    2003: "invalid opcode",
    2004: "invalid arguments",
    2005: "entity not found",
    2006: "an entity already exists with that key",
    2009: "room is locked",
    2010: "room is full",
    2013: "room not found",
    2014: "requested role does not exist",
    2019: "missing name",
    2023: "permission denied",
    2024: "not connected to a room",
    2028: "the entity is locked",
};

let nextId = 1000000;

// не отвечаем "ok" на эти опкоды (они сами шлют ответ)
const NO_OK = new Set(["object/get", "text/get", "number/get", "doodle/get", "room/get-audience", "room/exit", "echo"]);

function buildContent(type, action, p) {
    if (type === "object") return { val: p.val !== undefined ? p.val : {} };
    if (type === "text") {
        const c = { val: p.val !== undefined ? p.val : "" };
        if (action === "create" && p.accept !== undefined) c.accept = p.accept;
        return c;
    }
    if (type === "number") {
        if (action === "create" || action === "set")
            return { val: p.val || 0, restrictions: { increment: p.increment || 0, type: p.type || "int", max: p.max, min: p.min } };
        return { val: p.val };
    }
    if (type === "doodle" && action === "create")
        return { val: { colors: p.colors != null ? p.colors : null, lines: [], live: !!p.live, maxLayer: p.maxLayer || 0, maxPoints: p.maxPoints || 0, size: p.size || { width: 0, height: 0 }, weights: p.weights != null ? p.weights : null } };
    return { val: p.val };
}

function attach(client, roomCode) {
    client.id = nextId++;
    client.roomCode = roomCode;
    client.profileId = null;
    client.role = null;
    client.userId = null;
    client.sendEcast = (msg, re) => {
        const room = mgr.get(client.roomCode);
        const full = Object.assign({ pc: room ? room.nextPc() : 0, re }, msg);
        try { client.send(JSON.stringify(full)); } catch { /* закрыт */ }
    };
    client.sendOk = (re) => client.sendEcast({ opcode: "ok", result: {} }, re);
    client.sendError = (re, code, extra) => client.sendEcast({ opcode: "error", result: { code, msg: extra || ERR[code] || "error" } }, re);
}

// Вход по WebSocket. code — код комнаты из URL, query — разобранные параметры.
module.exports = function handleConnection(client, code, query) {
    attach(client, code);
    const room = mgr.get(code);
    if (!room) { client.sendError(undefined, 2013); return; }

    const role = query.role;
    if (["host", "player", "moderator", "audience"].indexOf(role) === -1) { client.sendError(undefined, 2014); return; }

    const userId = query["user-id"] || String(u.randInt(1000000, 9999999));
    client.userId = userId;
    client.role = role;

    if (role === "host") {
        if (query["host-token"] !== room.token) { client.sendError(undefined, 1002); return; }
        client.isHost = true;
    } else if (role === "player") {
        const reconnect = !!room.findByUserId(userId);
        if (!query.name) { client.sendError(undefined, 2019); return; }
        if (room.banned.indexOf(userId) !== -1) { client.sendError(undefined, 2023); return; }
        if (room.locked && !reconnect) { client.sendError(undefined, 2009); return; }
        if (room.isFull() && !reconnect) { client.sendError(undefined, 2010); return; }
    } else if (role === "audience") {
        if (!room.audienceEnabled) { client.sendError(undefined, 2023); return; }
    }

    room.connect(client, userId, query.name || "", role);
    // profileId вычислен внутри connect — подхватим для диспетчера
    const self = role === "host" ? room.host : room.findByUserId(userId);
    if (self) client.profileId = self.profileId;
    console.log("[ecast] " + role + " вошёл в комнату " + code + (query.name ? " (" + query.name + ")" : ""));

    client.on("message", (data) => {
        if (DEBUG) console.log("[ec< " + client.id + "] " + data.toString().slice(0, 240));
        let msg;
        try { msg = JSON.parse(data.toString()); } catch { return client.sendError(undefined, 2001); }
        if (!msg.opcode || typeof msg.opcode !== "string") return client.sendError(undefined, 2002);
        if (!msg.params || msg.params.constructor !== Object) return client.sendError(msg.seq, 2004);
        try { dispatch(client, msg); }
        catch (e) { console.log("[ws] ОШИБКА обработки '" + msg.opcode + "': " + (e && e.message)); client.sendError(msg.seq, 1000); }
    });

    client.on("close", (code, reason) => {
        console.log("[ws] " + (client.role || "?") + " закрыл соединение (code " + code + (reason && reason.length ? ", " + reason.toString().slice(0, 80) : "") + ")");
        const r = mgr.get(client.roomCode); if (r) r.disconnect(client);
    });
    client.on("error", (e) => console.log("[ws] ошибка сокета " + (client.role || "?") + ": " + (e && e.message)));
};

function dispatch(client, msg) {
    const room = mgr.get(client.roomCode);
    if (!room) return client.sendError(msg.seq, 2024);
    const op = msg.opcode;
    const type = op.split("/")[0];
    const action = op.split("/").pop();
    const p = msg.params;
    let ok = true;

    switch (op) {
        case "room/lock":
            if (!client.isHost) return client.sendError(msg.seq, 2023);
            room.locked = true; break;
        case "room/exit":
            if (!client.isHost) return client.sendError(msg.seq, 2023);
            client.sendEcast({ opcode: "room/exit", result: { cause: 5 } }, msg.seq);
            try { client.close(1000); } catch {}
            return;
        case "room/get-audience":
            if (!client.isHost) return client.sendError(msg.seq, 2023);
            client.sendEcast({ opcode: "room/get-audience", result: { connections: room.audienceCount } }, msg.seq);
            return;
        case "room/start-audience":
            if (!client.isHost) return client.sendError(msg.seq, 2023);
            room.audienceEnabled = true;
            if (!room.entities["audience"]) room.createEntity("audience/pn-counter", "audience", ["r *"], { count: room.audienceCount || 0 });
            break;
        case "client/send": {
            if (p.to == null) return client.sendError(msg.seq, 2004);
            // ctxUserId = userId ОТПРАВИТЕЛЯ — чтобы для Blobcast-хоста CustomerMessage нёс,
            // КТО прислал (иначе голос/ответ игрока не привязывается к нему).
            room.sendTo(Number(p.to), { opcode: "client/send", result: { from: p.from, body: p.body } }, undefined, client.userId);
            break;
        }
        case "client/kick": {
            if (!client.isHost) return client.sendError(msg.seq, 2023);
            const target = room.players[p.id];
            if (target) {
                if (p.ban) room.banned.push(target.userId);
                room.sendTo(target.profileId, { opcode: "room/exit", result: { cause: 5 } });
                room.sendToHost({ opcode: "client/kicked", result: { id: target.profileId, role: target.role, reason: p.reason, banned: !!p.ban } });
                delete room.players[target.profileId];
            }
            break;
        }
        case "drop": {
            if (!client.isHost) return client.sendError(msg.seq, 2023);
            const e = room.entities[p.key];
            if (!e) return client.sendError(msg.seq, 2005, "no known entity with key " + p.key);
            const acl = e.acl; room.drop(p.key);
            room.sendByAcl(acl, { opcode: "drop", result: { key: p.key } });
            break;
        }
        case "echo":
            if (!client.isHost) return client.sendError(msg.seq, 2023);
            room.sendToAll({ opcode: "echo", result: { message: p.message } });
            break;
        case "lock": {
            const e = room.entities[p.key];
            if (!e) return client.sendError(msg.seq, 2005, "no known entity with key " + p.key);
            e.locked = true;
            room.sendByAcl(e.acl, { opcode: "lock", result: { key: p.key, from: room.host ? room.host.profileId : null } });
            break;
        }
        case "game/started": case "game/metric": case "game/ended": case "text/filter":
            if (!client.isHost) return client.sendError(msg.seq, 2023);
            break;
        case "artifact/create": {
            if (!p.blob || !p.appId || !p.categoryId) return client.sendError(msg.seq, 2004);
            const artifactId = artifacts.create(p.categoryId, { appId: p.appId, categoryId: p.categoryId, blob: p.blob, isProfane: false, isTextFlagged: false });
            const resp = { opcode: "artifact", result: { artifactId, categoryId: p.categoryId, rootId: "jbg-blobcast-artifacts", key: p.key || "", isProfane: false, isTextFlagged: false } };
            client.sendEcast(resp, msg.seq);
            room.sendByAcl([{ to: "all" }], resp, false); // остальным (кроме отправителя-хоста)
            return;
        }
        case "text-map/create": {
            if (!client.isHost) return client.sendError(msg.seq, 2023);
            if (!p.key) return client.sendError(msg.seq, 2004);
            if (room.entities[p.key]) return client.sendError(msg.seq, 2006);
            room.createTextMap(p.key, p.acl, p.val);
            room.notify(p.key, !client.isHost, client.profileId);
            break;
        }
        case "text-map/sync": {
            const e = room.entities[p.key];
            if (!e || e.type !== "text-map") return client.sendError(msg.seq, 2005, "no text-map " + p.key);
            room.syncTextMap(p.key, p.msg, client.profileId);
            room.notify(p.key, true, client.profileId); // разослать актуальное состояние остальным (+ хосту)
            break;
        }
        case "text-map/get": {
            const e = room.entities[p.key];
            if (!e || e.type !== "text-map") return client.sendError(msg.seq, 2005, "no text-map " + p.key);
            client.sendEcast({ opcode: "text-map/state", result: room.getTextMap(p.key, p.includeNodes) }, msg.seq);
            return;
        }
        default:
            if (["object", "text", "number", "doodle"].indexOf(type) !== -1) {
                ok = handleEntity(client, room, msg, type, action);
                if (ok === undefined) return; // ошибка уже отправлена
            } else {
                console.log("[ws] НЕИЗВЕСТНЫЙ опкод от " + (client.role || "?") + ": " + op);
                return client.sendError(msg.seq, 2003);
            }
    }
    if (ok && !NO_OK.has(op)) client.sendOk(msg.seq);
}

function handleEntity(client, room, msg, type, action) {
    const p = msg.params;
    const key = p.key;
    if (!key) { client.sendError(msg.seq, 2004); return undefined; }
    const role = client.role;
    const profileId = client.profileId;
    let e = room.entities[key];

    if (action === "get") {
        if (!e) { client.sendError(msg.seq, 2005, "no known entity with key " + key); return undefined; }
        if (!client.isHost && !(u.aclVisible(e.acl, role, profileId) && u.aclReadable(e.acl, role, profileId))) { client.sendError(msg.seq, 2023); return undefined; }
        client.sendEcast({ opcode: type, result: room.getBody(key) }, msg.seq);
        return true;
    }

    if (action === "create" || action === "set") {
        if (!client.isHost) { client.sendError(msg.seq, 2023); return undefined; }
        if (action === "create" && e) { client.sendError(msg.seq, 2006); return undefined; }
        const content = buildContent(type, action, p);
        if (action === "create") room.createEntity(type, key, p.acl, content);
        else room.setEntity(type, key, p.acl, content);
    } else {
        // update / increment / decrement / stroke / undo
        if (!e) { client.sendError(msg.seq, 2005, "no known entity with key " + key); return undefined; }
        if (!client.isHost && u.aclLockedFor(e.acl, role, profileId)) { client.sendError(msg.seq, 2028); return undefined; }
        if (type === "doodle" && action === "stroke") {
            e.val.lines.push({ color: p.color || "#ffffff", weight: p.weight || 0, layer: p.layer || 0, points: p.points || [], brush: p.brush });
            e.version += 1; e.from = profileId;
        } else if (type === "doodle" && action === "undo") {
            e.val.lines.pop(); e.version += 1; e.from = profileId;
        } else if (action === "increment") {
            room.incrementEntity(key, p.times != null ? p.times : p.val, profileId);
        } else if (action === "decrement") {
            room.decrementEntity(key, p.times != null ? p.times : p.val, profileId);
        } else if (action === "update") {
            room.updateEntity(key, buildContent(type, action, p), profileId);
        } else {
            client.sendError(msg.seq, 2003); return undefined;
        }
    }

    // оповещение (кроме doodle не-create — как на официальном сервере)
    if (!(type === "doodle" && action !== "create")) room.notify(key, !client.isHost, profileId);
    return true;
}
