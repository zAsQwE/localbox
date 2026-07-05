"use strict";
//
// LocalBox server — перевод внутренних сообщений (entity-store, Ecast-стиль) в события Blobcast
// (старый протокол): RoomBlobChanged, CustomerJoinedRoom, CustomerMessage и т.п.
// Собственная реализация LocalBox (описывает лишь формат событий Blobcast).
//
// ctxUserId — userId, относящийся к событию (для JoinRoom — входящий игрок; для CustomerMessage —
// отправитель; для CustomerLeftRoom — ушедший). Пустой объект = нечего слать этому клиенту.
//

module.exports = function translate(msg, roomId, ctxUserId, hostUserId) {
    const r = msg.result || {};
    switch (msg.opcode) {
        case "client/connected":
            if (r.role !== "player") return {};
            return {
                type: "Event", event: r.reconnect ? "CustomerRejoinedRoom" : "CustomerJoinedRoom",
                roomId, customerUserId: r.userId, customerName: r.name,
                options: { roomcode: "", name: r.name, email: "", phone: "" },
            };
        case "client/disconnected":
        case "client/kicked":
            if (r.role !== "player") return {};
            return { type: "Event", event: "CustomerLeftRoom", roomId, customerUserId: ctxUserId };
        case "client/send":
            return { type: "Event", event: "CustomerMessage", roomId, userId: ctxUserId, message: r.body };
        case "client/welcome":
            if (ctxUserId === hostUserId) return {}; // хосту JoinRoom не нужен
            return {
                type: "Result", action: "JoinRoom", success: true, initial: !r.reconnect,
                roomId, joinType: r.profile ? "player" : "audience", userId: ctxUserId,
                options: { roomcode: "", name: r.name, email: "", phone: "" },
            };
        case "room/exit":
            return { type: "Event", event: "RoomDestroyed", roomId };
        case "object":
            if (r.key && r.key.indexOf("bc:") === 0)
                return { type: "Event", event: r.key === "bc:room" ? "RoomBlobChanged" : "CustomerBlobChanged", roomId, blob: r.val };
            return {};
        default:
            return {};
    }
};
