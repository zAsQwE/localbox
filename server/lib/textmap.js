"use strict";
//
// LocalBox — text-map (совместное редактирование текста, игра «ПравьОтвет» / risky-text).
// Реализовано на настоящем CRDT Yjs: клиент шлёт Yjs-обновления (base64), сервер их мержит
// в общий документ и рассылает актуальное состояние (root) остальным.
//

const Y = require("yjs");

const TYPE = "ecast"; // имя Y.Text внутри документа (видно в бинарном формате risky-text)

function create(initialText) {
    const doc = new Y.Doc();
    if (initialText) doc.getText(TYPE).insert(0, String(initialText));
    return doc;
}

// применить обновление от клиента (base64 Yjs update). Возвращает true при успехе.
function applyUpdate(doc, b64) {
    try { Y.applyUpdate(doc, Buffer.from(String(b64 || ""), "base64")); return true; }
    catch { return false; }
}

// полное состояние документа (base64) — то, что клиент применяет у себя
function root(doc) {
    return Buffer.from(Y.encodeStateAsUpdate(doc)).toString("base64");
}

// текущий текст (для text-map/get с текстом)
function text(doc) {
    const t = doc.getText(TYPE);
    return { text: t.toString(), attributions: [] };
}

module.exports = { create, applyUpdate, root, text };
