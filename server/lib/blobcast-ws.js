"use strict";
//
// LocalBox server — Blobcast (старый протокол, socket.io 0.9) поверх той же Room/entity-store.
// Транспорт socket.io: '1::' connect, '2:::' heartbeat, '5:::{json}' событие, '0::' disconnect.
// Собственная реализация LocalBox.
//

const mgr = require("./room.js");
const state = require("./state.js");
const network = require("./network.js");

const DEBUG = process.env.LOCALBOX_DEBUG === "1";
let nextId = 5000000;

module.exports = function handleBlobcast(client) {
    client.id = nextId++;
    client.server = "blobcast";
    client.roomCode = null;
    client.userId = null;
    client.isHost = false;
    client.isPlayer = false;

    client.sendBlob = (obj) => {
        if (!obj || Object.keys(obj).length === 0) return;
        if (DEBUG) console.log("[bc> " + client.id + "] " + JSON.stringify(obj).slice(0, 240));
        try { client.send("5:::" + network.stringify({ name: "msg", args: [obj] }, client, state.serverUrl)); } catch { /* закрыт */ }
    };

    client.send("1::"); // socket.io: соединение установлено
    const ping = setInterval(() => { try { client.send("2:::"); } catch {} }, 10000);

    function cleanup() {
        clearInterval(ping);
        const room = client.room;
        if (room) room.disconnect(client);
    }

    client.on("message", (data) => {
        const s = data.toString();
        if (DEBUG && s[0] === "5") console.log("[bc< " + client.id + "] " + s.slice(0, 240));
        const parts = s.split(":");
        if (parts.length < 3) return client.send("-1::");
        if (parts[0] === "0") { cleanup(); try { client.close(1000); } catch {} return; }
        if (parts[0] === "2") return; // heartbeat от клиента
        if (parts[0] !== "5") return client.send("-1::");
        const json = s.slice(4);
        let msg;
        try { msg = JSON.parse(json); } catch { return client.send("-1::"); }
        if (!msg || typeof msg !== "object" || Array.isArray(msg)) return client.send("-1::");
        if (client.room && !client.room.isCurrent(client)) return client.send("-1::");
        const args = Array.isArray(msg.args) ? msg.args : [msg.args];
        args.forEach((arg) => {
            const action = arg && arg.action;
            try {
                if (Object.hasOwn(actions, action) && !actions[action](client, arg)) client.send("-1::");
            } catch { client.send("-1::"); }
            // неизвестные действия молча игнорируем (не рвём соединение)
        });
    });
    client.on("close", cleanup);
    client.on("error", () => {});
};

const actions = {
    CreateRoom(c, msg) {
        if (c.isHost || c.isPlayer) return false;
        if (typeof msg.userId !== "string" || !msg.userId || typeof msg.appId !== "string" || !msg.appId) return false;
        const opts = msg.options || {};
        const tag = state.register({ appId: msg.appId, appTag: state.games.appIds[msg.appId] });
        const room = new mgr.Room({
            appTag: tag, appId: msg.appId, userId: msg.userId,
            forceRoomId: opts.forceRoomId || (process.env.LOCALBOX_ROOM_CODE || "").trim() || null,
            maxPlayers: opts.maxPlayers, minPlayers: opts.minPlayers,
            audienceEnabled: opts.audienceEnabled, password: opts.password,
        }, state.serverUrl, state.games);
        mgr.add(room);
        c.roomCode = room.code; c.userId = msg.userId; c.isHost = true;
        room.connect(c, msg.userId, "", "host", "blobcast");
        room.setEntity("object", "bc:room", ["r *"], { val: {} });
        c.sendBlob({ type: "Result", action: "CreateRoom", success: true, roomId: room.code });
        console.log("[blobcast] room", room.code, "for", tag, "host userId:", msg.userId);
        return true;
    },

    JoinRoom(c, msg) {
        if (c.isHost || c.isPlayer) return false;
        const room = mgr.get(msg.roomId);
        if (!room) return false;
        if (typeof msg.userId !== "string" || !msg.userId || room.banned.includes(msg.userId)) return false;
        if (room.password && msg.password !== room.password) return false;
        const existing = room.findByUserId(msg.userId);
        if (existing && existing.role !== "player") return false;
        c.userId = msg.userId;
        if ((msg.joinType || "player") !== "player") return false; // зрители — позже
        if (room.locked && !room.findByUserId(msg.userId)) return false;
        if (room.isFull() && !room.findByUserId(msg.userId)) return false;
        if (!room.connect(c, msg.userId, msg.name || "", "player", "blobcast")) return false;
        c.roomCode = msg.roomId; c.isPlayer = true;
        const self = room.findByUserId(msg.userId);
        console.log("[blobcast] игрок вошёл в комнату " + msg.roomId + " (" + (msg.name || "") + ")");
        if (self) {
            // начальные блобы игроку
            if (room.get("bc:room")) room.sendTo(self.profileId, { opcode: "object", result: room.get("bc:room") });
            const ckey = "bc:customer:" + msg.userId;
            if (room.get(ckey)) room.sendTo(self.profileId, { opcode: "object", result: room.get(ckey) });
        }
        return true;
    },

    SetRoomBlob(c, msg) {
        const room = mgr.get(c.roomCode);
        if (!c.isHost || !room) return false;
        room.updateEntity("bc:room", { val: msg.blob });
        room.notify("bc:room", false);
        c.sendBlob({ type: "Result", action: "SetRoomBlob", success: true });
        return true;
    },

    SetCustomerBlob(c, msg) {
        const room = mgr.get(c.roomCode);
        if (!c.isHost || !room) return false;
        const key = "bc:customer:" + msg.customerUserId;
        if (!room.get(key)) {
            // страховка: блоб ещё не создан — создаём с доступом только этому игроку.
            const target = room.findByUserId(msg.customerUserId);
            if (!target) return false;
            room.setEntity("object", key, ["r id:" + target.profileId], { val: {} });
        }
        room.updateEntity(key, { val: msg.blob });
        room.notify(key, false);
        c.sendBlob({ type: "Result", action: "SetCustomerBlob", success: true });
        return true;
    },

    LockRoom(c) {
        const room = mgr.get(c.roomCode);
        if (!c.isHost || !room) return false;
        room.locked = true;
        c.sendBlob({ type: "Result", action: "LockRoom", success: true, roomId: c.roomCode });
        return true;
    },

    // --- сессии аудитории/голосований (нужны YDKJ и др.; отвечаем, чтобы хост не висел) ---
    StartSession(c, msg) {
        const room = mgr.get(c.roomCode);
        if (!c.isHost || !room) return false;
        const opts = msg.options || {};
        if (msg.module === "audience") {
            room.audienceEnabled = true;
            if (!room.get("audience")) room.createEntity("audience/pn-counter", "audience", ["r *"], { count: room.audienceCount || 0 });
            c.sendBlob({ type: "Result", action: "StartSession", module: "audience", name: msg.name, success: true, response: { count: room.audienceCount || 0 } });
        } else if (msg.module === "vote") {
            const options = opts.choices || [];
            const choices = Object.assign(Object.create(null), Array.isArray(options) ? Object.fromEntries(options.map((v) => [v, 0])) : options);
            room.createEntity("audience/count-group", msg.name, ["rw role:audience"], { choices });
            c.sendBlob({ type: "Result", action: "StartSession", module: "vote", name: msg.name, success: true, response: {} });
        } else if (msg.module === "comment") {
            room.createEntity("audience/text-ring", msg.name, ["rw role:audience"], { elements: [], limit: opts.maxComments || 1000 });
            c.sendBlob({ type: "Result", action: "StartSession", module: "comment", name: msg.name, success: true, response: {} });
        } else {
            c.sendBlob({ type: "Result", action: "StartSession", module: msg.module, name: msg.name, success: true, response: {} });
        }
        return true;
    },
    GetSessionStatus(c, msg) {
        const room = mgr.get(c.roomCode);
        if (!c.isHost || !room) return false;
        let response = {};
        if (msg.module === "audience") response = { count: room.audienceCount || 0 };
        else if (msg.module === "vote") { const e = room.entities[msg.name]; response = e ? (e.choices || {}) : {}; }
        else if (msg.module === "comment") { const e = room.entities[msg.name]; response = { comments: e ? e.elements : [] }; }
        c.sendBlob({ type: "Result", action: "GetSessionStatus", module: msg.module, name: msg.name, success: true, response });
        return true;
    },
    StopSession(c, msg) {
        const room = mgr.get(c.roomCode);
        if (!c.isHost || !room) return false;
        let response = {};
        if (msg.module === "vote") { const e = room.entities[msg.name]; response = e ? (e.choices || {}) : {}; room.drop(msg.name); }
        else if (msg.module === "comment") { const e = room.entities[msg.name]; response = { comments: e ? e.elements : [] }; room.drop(msg.name); }
        c.sendBlob({ type: "Result", action: "StopSession", module: msg.module, name: msg.name, success: true, response });
        return true;
    },

    SendMessageToRoomOwner(c, msg) {
        const room = mgr.get(c.roomCode);
        if (!c.isPlayer || !room) return false;
        const self = room.findByUserId(c.userId);
        if (!self || !room.host) return false;
        if (room.muted.has(self.profileId)) return true;
        room.send(self.profileId, room.host.profileId, msg.message);
        return true;
    },
};
