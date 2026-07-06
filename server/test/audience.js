"use strict";
//
// Дымовой тест системы зрителей (audience) — без реальной игры Jackbox.
// Эмулируем host-клиент и audience-клиентов как мок-объекты с sendEcast,
// прогоняем: включение режима, вход зрителя (welcome), живые обновления сущностей,
// троттлинг, рассылку по ACL, счётчик, отключение.
//

const mgr = require("../lib/room.js");

let fails = 0;
function ok(cond, name) { console.log((cond ? "  ✓ " : "  ✗ ") + name); if (!cond) fails++; }

// Мок ws-клиента (как в attach: sendEcast складывает сообщения в inbox).
let idc = 1;
function mockClient() {
    const c = {
        id: idc++, readyState: 1, roomCode: null, inbox: [], server: "ecast",
        send() {}, close() { c.readyState = 3; },
    };
    c.sendEcast = (msg) => c.inbox.push(msg);
    return c;
}
function opcodes(c) { return c.inbox.map((m) => m.opcode); }
function last(c, opcode) { return [...c.inbox].reverse().find((m) => m.opcode === opcode); }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
    // --- комната + хост ---
    const room = new mgr.Room({ userId: "host1", appTag: "quiplash2", appId: "x" }, "localhost", {});
    mgr.add(room);
    const host = mockClient(); host.roomCode = room.code; host.isHost = true;
    room.connect(host, "host1", "", "host");
    ok(room.host && room.host.profileId != null, "хост подключился");

    // --- режим зрителей выключен → вход зрителя запрещён логикой ws (проверяем флаг) ---
    ok(room.audienceEnabled === false, "по умолчанию audience выключен");
    room.audienceEnabled = true; // эмулируем room/start-audience

    // хост создаёт сущность, видимую зрителям (вопрос для голосования)
    room.createEntity("object", "prompt", ["r *"], { val: { q: "Кто смешнее?" } });
    // и сущность НЕ для зрителей (только игроки)
    room.createEntity("object", "secret", ["r role:player"], { val: { s: 1 } });

    // --- зритель заходит ---
    const aud = mockClient(); aud.roomCode = room.code;
    room.connect(aud, "aud1", "", "audience");
    ok(room.audienceCount === 1, "счётчик зрителей = 1");
    const welcome = last(aud, "client/welcome");
    ok(!!welcome, "зритель получил client/welcome");
    ok(welcome && welcome.result.entities.prompt, "welcome содержит видимую зрителю 'prompt'");
    ok(welcome && !welcome.result.entities.secret, "welcome НЕ содержит 'secret' (только игроки)");
    ok(welcome && welcome.result.id === null, "у зрителя нет profileId");

    // --- живое обновление видимой сущности доходит до зрителя (троттлинг ~150мс) ---
    room.updateEntity("prompt", { val: { q: "Финал!" } }, null);
    room.notify("prompt", true, null);
    ok(opcodes(aud).filter((o) => o === "object").length === 0, "до троттла зритель ещё не получил апдейт");
    await sleep(200);
    const upd = last(aud, "object");
    ok(!!upd && upd.result.val.q === "Финал!", "после троттла зритель получил живое обновление 'prompt'");

    // --- обновление НЕвидимой зрителю сущности до него НЕ доходит ---
    const before = opcodes(aud).length;
    room.updateEntity("secret", { val: { s: 2 } }, null);
    room.notify("secret", true, null);
    await sleep(200);
    ok(opcodes(aud).length === before, "обновление 'secret' зрителю не пришло");

    // --- троттлинг: 50 быстрых правок → зритель получит немного сообщений, не 50 ---
    aud.inbox.length = 0;
    for (let i = 0; i < 50; i++) { room.updateEntity("prompt", { val: { q: "v" + i } }, null); room.notify("prompt", false, null); }
    await sleep(250);
    const got = opcodes(aud).filter((o) => o === "object").length;
    ok(got >= 1 && got <= 3, "троттлинг: 50 правок → " + got + " сообщений зрителю (коалесценция)");
    const latest = last(aud, "object");
    ok(latest && latest.result.val.q === "v49", "зритель получил ПОСЛЕДНЕЕ состояние (v49)");

    // --- второй зритель + broadcast всем (echo/sendToAll) ---
    const aud2 = mockClient(); aud2.roomCode = room.code;
    room.connect(aud2, "aud2", "", "audience");
    ok(room.audienceCount === 2, "счётчик зрителей = 2");
    aud.inbox.length = 0; aud2.inbox.length = 0;
    room.sendToAll({ opcode: "echo", result: { message: "hi" } });
    ok(!!last(aud, "echo") && !!last(aud2, "echo"), "sendToAll дошёл до обоих зрителей");

    // --- sendByAcl: только видимым зрителям ---
    aud.inbox.length = 0;
    room.sendByAcl([{ to: "player" }], { opcode: "drop", result: { key: "x" } });
    ok(opcodes(aud).filter((o) => o === "drop").length === 0, "sendByAcl(role:player) зрителю не пришёл");
    aud.inbox.length = 0;
    room.sendByAcl([{ to: "all" }], { opcode: "drop", result: { key: "y" } });
    ok(!!last(aud, "drop"), "sendByAcl(*) зрителю пришёл");

    // --- отключение зрителя уменьшает счётчик ---
    room.disconnect(aud2);
    ok(room.audienceCount === 1, "после отключения зрителя счётчик = 1");

    // --- закрытие комнаты (хост вышел): зрители получают room/exit и закрываются ---
    aud.inbox.length = 0;
    room.disconnect(host);
    ok(!!last(aud, "room/exit"), "при закрытии комнаты зритель получил room/exit");
    ok(aud.readyState === 3, "соединение зрителя закрыто");
    ok(!mgr.get(room.code), "комната удалена");

    console.log(fails === 0 ? "\nВСЕ ТЕСТЫ ПРОШЛИ" : "\nПРОВАЛЕНО: " + fails);
    process.exit(fails === 0 ? 0 : 1);
})();
