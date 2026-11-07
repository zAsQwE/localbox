"use strict";

const tts = require("./tts.js");
const { plainText } = require("./tts-cache.js");

function rapBattle(room) { return /^rapbattle$/i.test(room.appTag || ""); }
const scopes = new WeakMap();
const sessions = new WeakMap();
function session(room, restart = false) {
    let owner = sessions.get(room);
    if (!owner || (restart && owner.closed)) { owner = tts.createSession(); sessions.set(room, owner); }
    return owner;
}
function start(room) { if (rapBattle(room)) session(room, true); }
function ended(room) {
    if (!rapBattle(room)) return Promise.resolve();
    const owner = session(room);
    const current = scopes.get(room);
    if (current) for (const { scope } of current.values()) tts.cancelPrefetch(scope);
    scopes.delete(room);
    return tts.endSession(owner);
}
function ownerForRequest(request, rooms) {
    const active = rooms.filter((room) => !room.closed && room.host && room.host.connected);
    const code = request.body && (request.body.roomCode || request.body.roomId || request.body.code);
    let room = code && active.find((item) => item.code === code);
    const address = (ip) => String(ip || "").replace(/^::ffff:/, "");
    if (!room) {
        const matches = active.filter((item) => address(item.host.client && item.host.client._socket && item.host.client._socket.remoteAddress) === address(request.socket.remoteAddress));
        if (matches.length === 1) room = matches[0];
        else if (active.length === 1) room = active[0];
    }
    return room && rapBattle(room) ? session(room) : null;
}
function scopeFor(room, key, blob) {
    let current = scopes.get(room);
    if (!current) { current = new Map(); scopes.set(room, current); }
    const signature = JSON.stringify([blob.entryId, knownLine(blob), blob.textKey]);
    const previous = current.get(key);
    if (!previous || previous.signature !== signature) {
        if (previous) tts.cancelPrefetch(previous.scope);
        current.set(key, { signature, scope: { room, key, owner: session(room) } });
    }
    return current.get(key).scope;
}

/** MVC's FullLine controller prompt ends with a quoted, already chosen line.
 * Fill-in-the-blank prompts ("Give me a noun") expose no complete rap line.
 * Only use the current controller data, never the dictionary of possible words.
 */
function knownLine(blob) {
    if (!blob || blob.state !== "EnterSingleText") return null;
    const prompt = blob.prompt && (blob.prompt.html || blob.prompt.text);
    if (typeof prompt !== "string") return null;
    const rows = prompt.replace(/<br\s*\/?\s*>|<\/div\s*>|<\/p\s*>/gi, "\n").split(/\n/);
    for (const row of rows.reverse()) {
        if (/<blank>|_{2,}|\{[^}]+\}/i.test(row)) continue;
        const text = plainText(row);
        const match = /^["'‘“«]([\s\S]+)["'’”»]$/.exec(text);
        if (match && match[1].trim()) return match[1].trim();
    }
    return null;
}
function contextFor(room, player) {
    for (const key of ["bc:customer:" + player.userId, "player:" + player.profileId, "player:" + player.userId]) {
        const entity = room.entities[key];
        if (entity && knownLine(entity.val)) return { blob: entity.val, key };
    }
    return null;
}
function submission(room, player, message) {
    if (!rapBattle(room) || !player || player.role !== "player" || room.closed || room.muted.has(player.profileId)) return;
    const context = contextFor(room, player);
    if (!context || !message || !["write", "submit"].includes(message.action) || typeof message.entry !== "string") return;
    const { blob, key } = context;
    const text = plainText(message.entry);
    if (!text.trim() || text.length > Math.min(Number(blob.maxLength) || 900, 900)) return;
    tts.prefetch(text, scopeFor(room, key, blob), blob.rate);
}
function entity(room, key, value, from) {
    if (!rapBattle(room) || room.closed) return;
    // MVC's post-game room blob explicitly exposes gameFinished. A round's
    // scoreboard has no such flag and must retain audio for the next battle.
    if (["bc:room", "room"].includes(key) && value && value.gameFinished === true && (from == null || (room.host && from === room.host.profileId))) { ended(room);return; }
    if (value && value.state === "EnterSingleText") { start(room);scopeFor(room, key, value); }
    const line = knownLine(value);
    if (line) tts.prefetch(line, scopeFor(room, key, value), value.rate);
    // Ecast's textKey flow already passed the normal entity permission checks.
    if (typeof value === "string" && from != null) {
        const player = room.players[from], context = player && contextFor(room, player);
        if (context && context.blob.textKey === key) submission(room, player, { action: "write", entry: value });
    }
}
function forwarded(room, profileId, message) {
    if (room.host && profileId === room.host.profileId && message.opcode === "client/send" && message.result)
        submission(room, room.players[message.result.from], message.result.body);
}
function close(room) {
    return ended(room);
}

module.exports = { knownLine, entity, forwarded, close, start, ended, ownerForRequest };
