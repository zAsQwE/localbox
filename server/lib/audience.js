"use strict";

const u = require("./util.js");

module.exports = function audience(client, room, msg) {
    const p = msg.params;
    const pieces = msg.opcode.split("/");
    const type = pieces.slice(0, 2).join("/");
    const action = pieces[2];
    const key = p.name || p.key;
    const fail = (code) => client.sendError(msg.seq, code);
    if (!["audience/count-group", "audience/g-counter", "audience/pn-counter", "audience/text-ring"].includes(type) || pieces.length !== 3) return fail(2003);
    if (typeof key !== "string" || !key) return fail(2004);
    let e = room.entities[key];
    if (action === "create") {
        if (!client.isHost) return fail(2023);
        if (e) return fail(2006);
        if (p.acl != null && !Array.isArray(p.acl)) return fail(2004);
        let content;
        if (type === "audience/count-group") {
            const options = p.options;
            if (!options || typeof options !== "object") return fail(2004);
            const choices = Object.create(null);
            if (Array.isArray(options)) {
                if (!options.every((v) => typeof v === "string" || typeof v === "number")) return fail(2004);
                options.forEach((v) => { choices[v] = 0; });
            } else {
                if (!Object.values(options).every((v) => Number.isSafeInteger(v) && v >= 0)) return fail(2004);
                Object.assign(choices, options);
            }
            content = { choices };
        } else if (type === "audience/text-ring") {
            const limit = p.limit == null ? 1000 : p.limit;
            if (!Number.isSafeInteger(limit) || limit < 1) return fail(2004);
            content = { elements: [], limit };
        } else {
            const count = p.count == null ? 0 : p.count;
            if (!Number.isSafeInteger(count) || (type === "audience/g-counter" && count < 0)) return fail(2004);
            content = { count };
        }
        room.createEntity(type, key, p.acl == null ? ["rw role:audience"] : p.acl, content);
    } else {
        if (!e) return fail(2005);
        if (e.type !== type) return fail(2004);
        if (action === "get") {
            if (!client.isHost && !u.aclReadable(e.acl, client.role, client.profileId)) return fail(2023);
            return client.sendEcast({ opcode: type, result: room.getBody(key) }, msg.seq);
        }
        if (!client.isHost && (e.locked || u.aclLockedFor(e.acl, client.role, client.profileId))) return fail(2028);
        if (room.muted.has(client.profileId)) return client.sendOk(msg.seq);
        if (type === "audience/text-ring") {
            if (action !== "push") return fail(2003);
            if (typeof p.text !== "string") return fail(2004);
            e.elements.push(p.text);
            if (e.elements.length > e.limit) e.elements.splice(0, e.elements.length - e.limit);
        } else {
            const times = p.times == null ? 1 : p.times;
            if (!Number.isSafeInteger(times) || times < 0) return fail(2004);
            if (type === "audience/count-group") {
                if (action !== "increment") return fail(2003);
                if (!Object.hasOwn(e.choices, p.vote) || !Number.isSafeInteger(e.choices[p.vote] + times)) return fail(2004);
                e.choices[p.vote] += times;
            } else {
                if (action !== "increment" && !(action === "decrement" && type === "audience/pn-counter")) return fail(2003);
                const count = e.count + (action === "decrement" ? -times : times);
                if (!Number.isSafeInteger(count)) return fail(2004);
                e.count = count;
            }
        }
        e.version++;
        e.from = client.profileId;
    }
    room.notify(key, !client.isHost, client.profileId);
    client.sendOk(msg.seq);
};
