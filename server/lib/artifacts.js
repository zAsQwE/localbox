"use strict";
//
// LocalBox server — хранение «артефактов»: рисунки, песни и прочие блобы, которые игра
// создаёт в конце (галереи Drawful/Tee K.O., выступления Dodo Re Mi и т.п.) и потом
// забирает обратно для показа. Собственная реализация LocalBox.
//

const fs = require("fs");
const path = require("path");
const u = require("./util.js");

const DIR = path.join(__dirname, "..", "storage", "artifacts");

function fileFor(categoryId, artifactId) {
    // безопасные компоненты пути (только буквы/цифры/-/_)
    const safe = (s) => String(s).replace(/[^A-Za-z0-9_-]/g, "");
    return path.join(DIR, safe(categoryId) + "_" + safe(artifactId) + ".json");
}

module.exports = {
    // Сохраняет блоб, возвращает artifactId.
    create(categoryId, blob) {
        fs.mkdirSync(DIR, { recursive: true });
        let id = u.makeToken(32);
        while (fs.existsSync(fileFor(categoryId, id))) id = u.makeToken(32);
        fs.writeFileSync(fileFor(categoryId, id), JSON.stringify(blob), "utf8");
        return id;
    },
    // Возвращает сохранённый блоб или null.
    get(categoryId, artifactId) {
        const f = fileFor(categoryId, artifactId);
        return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : null;
    },
};
