"use strict";

const fs = require("node:fs");
const path = require("node:path");
const https = require("node:https");
const { mime } = require("./images.js");

function allowed(relative) {
    return /^reaction\/[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)?\.png$/.test(relative) ||
        /^twemoji\/assets\/72x72\/[a-f0-9-]+\.png$/.test(relative);
}
function fetchImage(relative) {
    return new Promise((resolve, reject) => {
        const request = https.get("https://cdn.jackboxgames.com/" + relative, response => {
            if (response.statusCode !== 200) { response.resume(); return reject(Error("Image CDN: " + response.statusCode)); }
            let size = 0;
            const chunks = [];
            response.on("error", reject);
            response.on("aborted", () => reject(Error("Image download interrupted")));
            response.on("data", chunk => {
                size += chunk.length;
                if (size > 8 * 1024 * 1024) { response.destroy(Error("Image too large")); return; }
                chunks.push(chunk);
            });
            response.on("end", () => resolve(Buffer.concat(chunks)));
        });
        const timer = setTimeout(() => request.destroy(Error("Image CDN timeout")), 15000);
        request.once("close", () => clearTimeout(timer));
        request.on("error", reject);
    });
}
function mount(app, directory = path.join(__dirname, "../cache/image-cdn"), fetch = fetchImage) {
    const pending = new Map();
    // A screen can request more than four different photos at once. Queue those
    // downloads instead of returning a fatal 429 to the controller's loader.
    const queue = [];
    let active = 0;
    function download(task) {
        return new Promise((resolve, reject) => {
            const run = () => {
                active++;
                Promise.resolve().then(task).then(resolve, reject).finally(() => {
                    active--;
                    if (queue.length) queue.shift()();
                });
            };
            if (active < 4) run();
            else queue.push(run);
        });
    }
    app.get("/localbox/cdn/*", async (req, res) => {
        const relative = req.params[0];
        // Failed loads must be retryable after enabling downloads or reconnecting.
        res.set("Cache-Control", "no-store");
        if (!allowed(relative)) return res.sendStatus(404);
        const file = path.join(directory, relative);
        try {
            let bytes;
            if (fs.existsSync(file)) bytes = await fs.promises.readFile(file);
            else {
                // DOWNLOAD_MISSING controls optional jackbox.ru textures, not
                // Game stock images (absent from client archives).
                if (process.env.LOCALBOX_DOWNLOAD_GAME_IMAGES === "0") {
                    console.warn("[cdn] Нет в кэше: " + relative + ". Включите «Скачивать изображения игр и emoji» в настройках сервера.");
                    return res.status(503).send("Изображения нет в кэше. Включите «Скачивать изображения игр и emoji» в настройках сервера и перезапустите сервер.");
                }
                if (!pending.has(relative)) {
                    if (pending.size >= 128) return res.set("Retry-After", "2").sendStatus(503);
                    const transfer = download(async () => {
                        const data = await fetch(relative);
                        if (!mime(data)) throw Error("CDN returned invalid image data");
                        await fs.promises.mkdir(path.dirname(file), { recursive: true });
                        const temporary = file + ".part";
                        try { await fs.promises.writeFile(temporary, data); await fs.promises.rename(temporary, file); }
                        finally { await fs.promises.unlink(temporary).catch(() => {}); }
                        return data;
                    });
                    pending.set(relative, transfer);
                    transfer.finally(() => pending.delete(relative)).catch(() => {});
                }
                bytes = await pending.get(relative);
            }
            const type = mime(bytes);
            if (!type) return res.sendStatus(502);
            res.type(type).set({ "Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff" }).send(bytes);
        } catch (error) {
            console.warn("[cdn] Не удалось загрузить " + relative + ": " + error.message);
            res.status(502).send("Не удалось загрузить изображение Jackbox. Проверьте интернет и повторите.");
        }
    });
}
module.exports = { allowed, fetchImage, mount };
