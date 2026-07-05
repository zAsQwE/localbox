"use strict";
//
// LocalBox server — вспомогательные функции протокола Ecast.
// Собственная реализация LocalBox (не производная от чужого кода): описывает лишь
// формат «провода» Jackbox (ACL, генерация кодов, тела сущностей), который сам по себе
// не является объектом авторского права.
//

const CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const HEX = "0123456789abcdef";

function randInt(min, max) { return Math.floor(Math.random() * (max - min) + min); }

function makeCode() {
    let s = "";
    for (let i = 0; i < 4; i++) s += CODE_ALPHABET[Math.floor(Math.random() * CODE_ALPHABET.length)];
    return s;
}

function makeToken(len = 24) {
    let s = "";
    for (let i = 0; i < len; i++) s += HEX[Math.floor(Math.random() * HEX.length)];
    return s;
}

// ACL — список строк: "rw *", "r role:audience", "rw id:5".
// Возвращает распарсенные правила [{read, write, to, id}].
function parseAcl(list) {
    const rules = [];
    (list || []).forEach((item) => {
        const parts = String(item).split(" ");
        if (parts.length !== 2) return;
        const flags = parts[0], target = parts[1];
        const rule = { read: flags.indexOf("r") !== -1, write: flags.indexOf("w") !== -1, to: "", id: null };
        if (target === "*") rule.to = "all";
        else if (target.indexOf("role:") === 0) rule.to = target.slice(5);
        else if (target.indexOf("id:") === 0) { rule.to = "id"; rule.id = target.slice(3); }
        else return;
        rules.push(rule);
    });
    return rules;
}

function ruleHits(rule, role, profileId) {
    return rule.to === "all" || rule.to === role || (rule.to === "id" && String(rule.id) === String(profileId));
}

// Виден ли объект игроку (есть хоть одно подходящее правило).
function aclVisible(acl, role, profileId) {
    return acl.some((r) => ruleHits(r, role, profileId));
}
// Может ли игрок читать.
function aclReadable(acl, role, profileId) {
    return acl.some((r) => ruleHits(r, role, profileId) && r.read);
}
// Заблокирован ли для записи этому игроку (нет ни одного write-правила).
function aclLockedFor(acl, role, profileId) {
    return !acl.some((r) => ruleHits(r, role, profileId) && r.write);
}

function isJsonSerializable(v) {
    try { JSON.stringify(v); return true; } catch { return false; }
}

module.exports = {
    randInt, makeCode, makeToken,
    parseAcl, aclVisible, aclReadable, aclLockedFor, isJsonSerializable,
};
