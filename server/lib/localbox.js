"use strict";

// LocalBox-only helpers: public lobby status for the launcher QR overlay and
// optional automatic pressing of the VIP "Everybody's In" action.

const AUTO_START_FULL = process.env.LOCALBOX_AUTO_START_FULL === "1";
const u = require("./util.js");

function connectedPlayers(room) {
    return Object.values(room.players || {}).filter((player) =>
        player.role === "player" && player.connected && player.client && player.client.readyState === 1
    );
}

function roomStatus(room, serverUrl) {
    if (!room || room.closed) return null;
    const players = connectedPlayers(room);
    const code = String(room.code || "");
    return {
        code,
        appTag: room.appTag || "",
        playerCount: players.length,
        maxPlayers: room.maxPlayers,
        minPlayers: room.minPlayers,
        full: players.length >= room.maxPlayers,
        qrVisible: !room.locked && !room.gameStarted,
        joinUrl: `https://${serverUrl}/?code=${encodeURIComponent(code)}&ref=qr`,
    };
}

function playerIdFromEntity(room, entity) {
    if (!entity || !entity.val || typeof entity.val !== "object") return null;
    const ids = (entity.acl || []).filter((rule) => rule.to === "id" && rule.read).map((rule) => String(rule.id));
    return connectedPlayers(room).find((player) => ids.includes(String(player.profileId)))?.profileId ?? null;
}

function findStartAction(room) {
    for (const entity of Object.values(room.entities || {})) {
        if (!entity || !entity.val || typeof entity.val !== "object") continue;
        const value = entity.val;
        const id = playerIdFromEntity(room, entity);
        if (id == null) continue;
        // Party Pack 8+ controllers write {action:"start"} into responseKey.
        const response = typeof value.responseKey === "string" ? room.entities[value.responseKey] : null;
        if (value.hasControls === true && value.status === "canStart" && response?.type === "object" &&
            !response.locked && !u.aclLockedFor(response.acl || [], "player", id)) {
            return { player: room.players[id], responseKey: value.responseKey };
        }
        // Older controllers send the same action as a direct client message to the host.
        if (value.playerIsVIP === true && value.gameCanStart === true &&
            value.playerCanStartGame !== false && value.gameIsStarting !== true && value.gameFinished !== true) {
            return { player: room.players[id], responseKey: null };
        }
    }
    return null;
}

function findVip(room) { return findStartAction(room)?.player || null; }

function tryAutoStart(room, log = console.log) {
    if (!AUTO_START_FULL || !room || room.closed || room.locked || room.gameStarted || room._localboxAutoStarted) return false;
    const players = connectedPlayers(room);
    if (!room.host || room.host.profileId == null || players.length < room.maxPlayers) return false;
    const start = findStartAction(room);
    if (!start) return false;
    room._localboxAutoStarted = true;
    if (start.responseKey) {
        room.updateEntity(start.responseKey, { val: { action: "start" } }, start.player.profileId);
        room.notify(start.responseKey, true, start.player.profileId);
    } else {
        room.send(start.player.profileId, room.host.profileId, { action: "start" });
    }
    log(`[room] ${room.code}: все ${players.length}/${room.maxPlayers} игроков в сборе — запускаю игру`);
    return true;
}

function onRoomEvent(roomManager, code, _event) {
    const room = roomManager.get(code);
    if (room) tryAutoStart(room);
}

module.exports = { AUTO_START_FULL, connectedPlayers, roomStatus, findVip, findStartAction, tryAutoStart, onRoomEvent };
