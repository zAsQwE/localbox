"use strict";

// Ecast StackEntity (Jackbox 12: Debate). A LIFO list: the host pushes values,
// controllers learn only its size from notifications and fetch new values with
// stack/peek. peek returns the newest values first, as the web client expects.
const u = require("./util.js");

const MAX_ELEMENTS = 10000;

module.exports = function stack(client, room, msg) {
    const p = msg.params;
    const action = msg.opcode.slice("stack/".length);
    const fail = (code, text) => client.sendError(msg.seq, code, text);
    if (!["create", "push", "pushbulk", "peek", "pop"].includes(action)) return fail(2003);
    const key = p.key;
    if (typeof key !== "string" || !key || key.length > 512) return fail(2004);
    const e = room.entities[key];

    if (action === "create") {
        if (!client.isHost) return fail(2023);
        if (e) return fail(2006);
        if (p.acl != null && (!Array.isArray(p.acl) || p.acl.some(rule => typeof rule !== "string"))) return fail(2004);
        room.createEntity("stack", key, p.acl, { elements: [] });
        room.notify(key, false, client.profileId);
        return client.sendOk(msg.seq);
    }

    if (!e) return fail(2005, "no known entity with key " + key);
    if (e.type !== "stack") return fail(2004);
    const role = client.role, profileId = client.profileId;

    if (action === "peek") {
        if (!client.isHost && !(u.aclVisible(e.acl, role, profileId) && u.aclReadable(e.acl, role, profileId))) return fail(2023);
        const size = p.size == null ? 1 : p.size;
        if (!Number.isSafeInteger(size) || size < 0) return fail(2004);
        const vals = e.elements.slice(Math.max(0, e.elements.length - size)).reverse();
        return client.sendEcast({ opcode: "stack/elements", result: { key, vals } }, msg.seq);
    }

    if (!client.isHost && (e.locked || u.aclLockedFor(e.acl, role, profileId))) return fail(2028);
    if (action === "pop") {
        if (!e.elements.length) return fail(2004, "stack " + key + " is empty");
        const val = e.elements.pop();
        e.version += 1; e.from = profileId;
        client.sendEcast({ opcode: "stack/element", result: { key, val } }, msg.seq);
        room.notify(key, !client.isHost, profileId);
        return;
    }

    if (room.muted.has(profileId)) return client.sendOk(msg.seq);
    const vals = action === "push" ? [p.val] : p.vals;
    if (!Array.isArray(vals) || vals.some(value => value === undefined)) return fail(2004);
    if (e.elements.length + vals.length > MAX_ELEMENTS) return fail(2004, "stack " + key + " is full");
    e.elements.push(...vals);
    e.version += 1; e.from = profileId;
    room.notify(key, !client.isHost, profileId);
    client.sendOk(msg.seq);
};
