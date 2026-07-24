"use strict";
//
// LocalBox server — комнаты и синхронизация сущностей (entity store) протокола Ecast.
// Собственная реализация LocalBox.
//

const u = require("./util.js");
const translate = require("./translate.js");
const textmap = require("./textmap.js");

// Хук админ-панели (устанавливается из server.js: mgr.setAdminHook). Событие: {t:"entity"|"drop"|"players", ...}.
let adminHook = null;
function emitAdmin(code, ev) { if (adminHook) { try { adminHook(code, ev); } catch { /* ignore */ } } }

// Тело сущности для отправки клиенту: {key, ...content, version, from}.
function entityContent(e) {
    switch (e.type) {
        case "number": return { val: e.val, restrictions: e.restrictions };
        case "object": return { val: e.val };
        case "text": return { val: e.val };
        case "doodle": return { val: e.val };
        case "text-map": return { root: textmap.root(e.doc) };
        default: return e.val !== undefined ? { val: e.val } : {};
    }
}

class Room {
    constructor(params, serverUrl, games) {
        const g = games || {};
        this.serverUrl = serverUrl;
        this.appTag = params.appTag;
        this.appId = (g.appTags && g.appTags[params.appTag]) || params.appId || params.appTag;
        this.code = params.forceRoomId || u.makeCode();
        this.token = u.makeToken();
        this.locked = false;
        this.audienceEnabled = !!params.audienceEnabled;
        this.password = params.password || null;
        this.moderatorPassword = params.moderatorPassword || null;
        const gMax = g.maxPlayers && g.maxPlayers[params.appTag];
        const gMin = g.minPlayers && g.minPlayers[params.appTag];
        this.maxPlayers = Math.min(params.maxPlayers || gMax || 8, gMax || 100);
        this.minPlayers = Math.max(params.minPlayers || gMin || 1, gMin || 0);
        this.hostUserId = params.userId || null;
        this.pc = 0;
        this.nextProfileId = 1;
        this.entities = {};      // key -> {type, acl:[parsed], version, from, ...content}
        this.host = null;        // {profileId, userId, name, client, connected}
        this.players = {};       // profileId -> {profileId, userId, name, role, client, connected, banned}
        this.audienceCount = 0;
        this.banned = [];
        this.createdAt = Date.now();
        this.audienceClients = {}; // clientId -> ws client
        this._audiencePush = {};   // key -> таймер троттлинга рассылки зрителям
        this.blobcast = false;     // true, если хост — старая игра (Blobcast): игрокам нужен bc:customer
        this.muted = new Set();    // profileId заглушённых игроков (админ-мьют) — их правки игнорируются
    }

    nextPc() { return this.pc++; }
    newProfileId() { return this.nextProfileId++; }

    playerCount() {
        return Object.values(this.players).filter((p) => p.role === "player").length;
    }
    isFull() { return this.playerCount() >= this.maxPlayers; }

    findByUserId(userId) {
        if (this.host && this.host.userId === userId) return this.host;
        return Object.values(this.players).find((p) => p.userId === userId) || null;
    }
    nameTaken(name) {
        if (this.host && this.host.name === name) return true;
        return Object.values(this.players).some((p) => p.name === name);
    }

    // ---- отправка ----
    _clientOf(profileId) {
        if (this.host && this.host.profileId === profileId) return this.host.client;
        return this.players[profileId] ? this.players[profileId].client : null;
    }
    _userIdOf(profileId) {
        if (this.host && this.host.profileId === profileId) return this.host.userId;
        return this.players[profileId] ? this.players[profileId].userId : null;
    }
    // ctxUserId — необязательный userId для перевода в Blobcast (по умолчанию = userId получателя).
    sendTo(profileId, msg, re, ctxUserId) {
        const c = this._clientOf(profileId);
        if (!c || c.readyState !== 1) return;
        if (c.server === "blobcast") {
            const ev = translate(msg, this.code, ctxUserId !== undefined ? ctxUserId : this._userIdOf(profileId), this.hostUserId);
            if (ev && Object.keys(ev).length) c.sendBlob(ev);
        } else {
            c.sendEcast(msg, re);
        }
    }
    // Тело сущности (для Blobcast-действий) или null.
    get(key) { return this.entities[key] ? this.getBody(key) : null; }
    // client/send между профилями (host<->player). ctxUserId = отправитель (для CustomerMessage).
    send(fromProfileId, toProfileId, body) {
        this.sendTo(toProfileId, { opcode: "client/send", result: { from: fromProfileId, body } }, undefined, this._userIdOf(fromProfileId));
        return true;
    }
    sendToHost(msg, re) { if (this.host && this.host.profileId != null) this.sendTo(this.host.profileId, msg, re); }
    // Разослать всем зрителям (они всегда ecast, без профиля — шлём напрямую).
    sendToAudience(msg) {
        Object.values(this.audienceClients).forEach((c) => {
            if (c && c.readyState === 1) { try { c.sendEcast(msg); } catch { /* закрыт */ } }
        });
    }
    sendToAll(msg) {
        this.sendToHost(msg);
        Object.keys(this.players).forEach((pid) => this.sendTo(Number(pid), msg));
        this.sendToAudience(msg);
    }
    sendByAcl(acl, msg, sendToHost = true) {
        if (sendToHost) this.sendToHost(msg);
        Object.values(this.players).forEach((p) => {
            if (u.aclVisible(acl, p.role, p.profileId)) this.sendTo(p.profileId, msg);
        });
        if (this.audienceCount > 0 && u.aclVisible(acl, "audience", null)) this.sendToAudience(msg);
    }

    // ---- сущности ----
    getBody(key) {
        const e = this.entities[key];
        return Object.assign({ key }, entityContent(e), { version: e.version, from: e.from });
    }
    notify(key, notifyHost, exceptProfileId) {
        const e = this.entities[key];
        if (!e) return;
        const msg = { opcode: e.type, result: this.getBody(key) };
        emitAdmin(this.code, { t: "entity", type: e.type, body: msg.result });   // God view: любая правка сущности
        if (notifyHost) this.sendToHost(msg);
        Object.values(this.players).forEach((p) => {
            if (p.profileId === exceptProfileId) return;
            if (u.aclVisible(e.acl, p.role, p.profileId) && u.aclReadable(e.acl, p.role, p.profileId)) this.sendTo(p.profileId, msg);
        });
        // Зрителей уведомляем троттлингом: 100 зрителей × частые правки = шторм, коалесцируем по ключу.
        if (this.audienceCount > 0 && u.aclVisible(e.acl, "audience", null) && u.aclReadable(e.acl, "audience", null))
            this._notifyAudience(key);
    }
    // Коалесцирующая рассылка сущности зрителям (не чаще ~7 раз/сек на ключ).
    _notifyAudience(key) {
        if (this._audiencePush[key]) return;
        this._audiencePush[key] = setTimeout(() => {
            delete this._audiencePush[key];
            const e = this.entities[key];
            if (!e || this.audienceCount === 0) return;
            if (u.aclVisible(e.acl, "audience", null) && u.aclReadable(e.acl, "audience", null))
                this.sendToAudience({ opcode: e.type, result: this.getBody(key) });
        }, 150);
    }

    createEntity(type, key, aclRaw, content) {
        this.entities[key] = Object.assign(
            { type, acl: u.parseAcl(aclRaw && aclRaw.length ? aclRaw : ["r *"]), version: 1, from: null },
            content
        );
        return true;
    }
    setEntity(type, key, aclRaw, content) {
        const prev = this.entities[key];
        const version = prev ? prev.version + 1 : 1;
        // ACL: если явно не задан при set — СОХРАНЯЕМ прежний (иначе сброс на "r *" делает
        // приватные сущности вроде audiencePlayer видимыми игрокам → игра считает игрока зрителем).
        const acl = (aclRaw && aclRaw.length) ? u.parseAcl(aclRaw)
            : (prev ? prev.acl : u.parseAcl(["r *"]));
        this.entities[key] = Object.assign(
            { type, acl, version, from: null },
            content
        );
        return true;
    }
    updateEntity(key, content, fromProfileId) {
        const e = this.entities[key];
        if (!e) return false;
        Object.assign(e, content);
        e.version += 1;
        e.from = fromProfileId != null ? fromProfileId : e.from;
        return true;
    }
    incrementEntity(key, times, fromProfileId) {
        const e = this.entities[key];
        if (!e || e.type !== "number") return false;
        const step = (times != null ? times : (e.restrictions && e.restrictions.increment)) || 1;
        e.val += step;
        if (e.restrictions && e.restrictions.max !== undefined && e.val > e.restrictions.max) e.val = e.restrictions.max;
        e.version += 1; e.from = fromProfileId != null ? fromProfileId : e.from;
        return true;
    }
    decrementEntity(key, times, fromProfileId) {
        const e = this.entities[key];
        if (!e || e.type !== "number") return false;
        const step = (times != null ? times : (e.restrictions && e.restrictions.increment)) || 1;
        e.val -= step;
        if (e.restrictions && e.restrictions.min !== undefined && e.val < e.restrictions.min) e.val = e.restrictions.min;
        e.version += 1; e.from = fromProfileId != null ? fromProfileId : e.from;
        return true;
    }
    drop(key) { delete this.entities[key]; emitAdmin(this.code, { t: "drop", key }); }

    // ---- админ-действия (читы) ----
    kick(profileId, ban) {
        const p = this.players[profileId];
        if (!p) return false;
        if (ban && p.userId && this.banned.indexOf(p.userId) === -1) this.banned.push(p.userId);
        try { this.sendTo(profileId, { opcode: "room/exit", result: { cause: ban ? 4 : 5 } }); } catch { /* ignore */ }
        try { if (p.client) p.client.close(1000); } catch { /* ignore */ }
        this.sendToHost({ opcode: "client/kicked", result: { id: profileId, role: p.role, reason: "admin", banned: !!ban } });
        this.sendToHost({ opcode: "client/disconnected", result: { id: profileId, role: p.role } });
        delete this.players[profileId];
        this.muted.delete(profileId);
        emitAdmin(this.code, { t: "players" });
        return true;
    }
    setMute(profileId, on) { if (on) this.muted.add(profileId); else this.muted.delete(profileId); return true; }
    renamePlayer(profileId, name) {
        const p = this.players[profileId];
        if (!p || !name) return false;
        p.name = name;
        const profile = { id: profileId, roles: {} }; profile.roles[p.role] = { name };
        this.sendToHost({ opcode: "client/connected", result: { id: profileId, userId: p.userId, name, role: p.role, reconnect: true, profile } });
        return true;
    }

    // ---- text-map (совместный текст, CRDT Yjs) ----
    createTextMap(key, aclRaw, initialText) {
        this.entities[key] = {
            type: "text-map",
            acl: u.parseAcl(aclRaw && aclRaw.length ? aclRaw : ["rw *"]),
            version: 1, from: null,
            doc: textmap.create(initialText),
        };
        return true;
    }
    syncTextMap(key, b64, fromProfileId) {
        const e = this.entities[key];
        if (!e || e.type !== "text-map") return false;
        const ok = textmap.applyUpdate(e.doc, b64);
        e.version += 1; e.from = fromProfileId != null ? fromProfileId : e.from;
        return ok;
    }
    getTextMap(key, wantText) {
        const e = this.entities[key];
        if (!e || e.type !== "text-map") return null;
        const body = wantText ? textmap.text(e.doc) : { root: textmap.root(e.doc) };
        return Object.assign({ key }, body, { version: e.version, from: e.from });
    }

    // ---- подключение / отключение ----
    // Возвращает welcome-объект (или null при неуспехе, тогда уже отправлена ошибка через client.sendError).
    connect(client, userId, name, role, server = "ecast") {
        client.server = server;
        if (role === "host" && server === "blobcast") this.blobcast = true;
        const reconnect = role === "host" ? !!(this.host && this.host.everConnected) : !!this.findByUserId(userId);
        let profileId, self;

        if (role === "host") {
            if (!this.host) this.host = {};
            profileId = this.host.profileId != null ? this.host.profileId : this.newProfileId();
            self = this.host;
            Object.assign(self, { profileId, userId, name: "", role: "host", client, connected: true, everConnected: true });
        } else if (role === "audience") {
            this.audienceCount++;
            this.audienceClients[client.id] = client;
            profileId = null; self = null;
        } else {
            const existing = this.findByUserId(userId);
            if (existing) {
                profileId = existing.profileId; self = existing;
                self.client = client; self.connected = true;
            } else {
                if (this.nameTaken(name)) { let i = 2; while (this.nameTaken(name + i)) i++; name = name + i; }
                profileId = this.newProfileId();
                self = { profileId, userId, name, role, client, connected: true, banned: false };
                this.players[profileId] = self;
                // Blobcast-игра: у каждого игрока свой блоб bc:customer:<userId> (виден только ему) —
                // создаём для ЛЮБОГО игрока такой комнаты, как бы он ни подключился.
                if (this.blobcast || server === "blobcast") this.setEntity("object", "bc:customer:" + userId, ["r id:" + profileId], { val: {} });
            }
        }

        // видимые сущности
        const entities = {};
        Object.keys(this.entities).forEach((key) => {
            const e = this.entities[key];
            if (role === "audience" ? u.aclVisible(e.acl, "audience", null) : u.aclVisible(e.acl, role, profileId)) {
                entities[key] = [e.type, this.getBody(key), { locked: u.aclLockedFor(e.acl, role, profileId) }];
            }
        });

        // список присутствующих (here) и профиль (profile)
        let here = null, profile = null;
        if (role !== "audience") {
            here = {};
            const roster = [];
            if (this.host && this.host.profileId != null) roster.push(this.host);
            Object.values(this.players).forEach((p) => roster.push(p));
            roster.forEach((p) => {
                const node = { id: p.profileId, roles: {} };
                node.roles[p.role] = {};
                if ((role === "player" || role === "moderator") && (p.role === "player" || p.role === "moderator")) node.roles[p.role].name = p.name;
                if (p.banned) node.banned = {};
                if (p.profileId === profileId) profile = node;
                else here[String(p.profileId)] = node;
            });
        }

        const welcome = {
            opcode: "client/welcome",
            result: {
                id: profileId, name, secret: role === "host" ? this.token : userId,
                reconnect, deviceId: "", entities, here, profile,
            },
        };
        if (role === "audience") client.sendEcast(welcome);
        else this.sendTo(profileId, welcome);

        // оповестить остальных
        if (role === "host") {
            const m = { opcode: "client/connected", result: { id: profileId, role, reconnect, profile } };
            Object.values(this.players).forEach((p) => this.sendTo(p.profileId, m));
        } else if (role !== "audience") {
            this.sendToHost({ opcode: "client/connected", result: { id: profileId, userId, name, role, reconnect, profile } });
        }
        emitAdmin(this.code, { t: "players" });   // обновить ростер в админ-панели
        return true;
    }

    disconnect(client) {
        if (this.host && this.host.client === client) {
            this.host.connected = false; this.host.client = null;
            // Хост ушёл (вышел из игры) → комната закрывается, игроков и зрителей выкидываем.
            Object.values(this.players).forEach((p) => this.sendTo(p.profileId, { opcode: "room/exit", result: { cause: 5 } }));
            this.sendToAudience({ opcode: "room/exit", result: { cause: 5 } });
            Object.values(this.audienceClients).forEach((c) => { try { c.close(1000); } catch { /* ignore */ } });
            Object.values(this._audiencePush).forEach((t) => clearTimeout(t));
            this._audiencePush = {};
            delete rooms[this.code];
            console.log("[room] закрыта (хост вышел):", this.code);
            return;
        }
        const p = Object.values(this.players).find((x) => x.client === client);
        if (p) {
            p.connected = false; p.client = null;
            // ctxUserId = userId ушедшего (для Blobcast CustomerLeftRoom)
            if (this.host && this.host.profileId != null)
                this.sendTo(this.host.profileId, { opcode: "client/disconnected", result: { id: p.profileId, role: p.role } }, undefined, p.userId);
            return;
        }
        if (this.audienceClients[client.id]) {
            delete this.audienceClients[client.id];
            this.audienceCount = Math.max(0, this.audienceCount - 1);
        }
    }
}

// ---- менеджер комнат ----
const rooms = {};
module.exports = {
    Room,
    rooms,
    get: (code) => rooms[code],
    add: (room) => { rooms[room.code] = room; return room; },
    remove: (code) => { delete rooms[code]; },
    list: () => Object.values(rooms),
    setAdminHook: (fn) => { adminHook = fn; },
};
