"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { layoutPaths } = require("./client-paths.js");

// Read the downloaded build's literal {file, css, base} registry. Game directory
// names and entry-point hashes must come from the client, never guessed IDs.
const registries = new Map();
const availability = require("./game-availability.js");
function literal(source, name) {
    return source.match(new RegExp('(?:^|[,\\s{])["\']?' + name + '["\']?\\s*:\\s*(["\'])([^"\']+)\\1'))?.[2];
}
function registry(directory) {
    const empty = { bundles: new Map(), games: new Map() };
    let files, stamp;
    try {
        if (!fs.statSync(path.join(directory, "index.html")).isFile()) return empty;
        files = fs.readdirSync(directory).filter(name => /\.(?:m?js)$/.test(name));
        stamp = files.map(name => { const stat = fs.statSync(path.join(directory, name)); return name + ":" + stat.size + ":" + stat.mtimeMs; }).join("|");
    } catch { return empty; }
    if (registries.get(directory)?.stamp === stamp) return registries.get(directory).data;
    const data = empty;
    for (const file of files) {
        let source;
        try { source = fs.readFileSync(path.join(directory, file), "utf8"); } catch { continue; }
        for (const match of source.matchAll(/(?:^|[,{}])\s*(?:"([^"\n]+)"|'([^'\n]+)'|([\w$-]+))\s*:\s*\{([^{}]{1,1600})\}/g)) {
            const tag = match[1] || match[2] || match[3], body = match[4];
            const base = literal(body, "base"), entry = literal(body, "file");
            if (!base?.startsWith("main/") || !entry) continue;
            const css = body.match(/\bcss["']?\s*:\s*\[([^\]]*)\]/)?.[1] || "";
            data.bundles.set(tag, { base, file: entry, css: [...css.matchAll(/["']([^"']+)["']/g)].map(item => item[1]), version: literal(body, "version") || "" });
        }
        for (const match of source.matchAll(/\{[^{}]{1,1400}\}/g)) {
            const body = match[0], tag = literal(body, "tag"), name = literal(body, "name"), directory = literal(body, "directory");
            if (!tag || !name || !directory) continue;
            const features = body.match(/\bfeatures["']?\s*:\s*\[([^\]]*)\]/)?.[1] || "";
            const game = { name, tag, directory, wrapper: literal(body, "wrapper") || "vue", isPublic: true,
                features: [...features.matchAll(/["']([^"']+)["']/g)].map(item => item[1]) };
            for (const key of ["categoryId", "galleryId"]) { const value = literal(body, key); if (value) game[key] = value; }
            data.games.set(tag, game);
        }
    }
    registries.set(directory, { stamp, data });
    return data;
}
function validBundle(directory, bundle) {
    const exists = relative => !/[\\\0:]/.test(relative) && !relative.split("/").some(part => part.startsWith(".")) &&
        layoutPaths(relative).some(candidate => { try { return fs.statSync(path.join(directory, candidate)).isFile(); } catch { return false; } });
    return !!bundle && exists(bundle.base + "/" + bundle.file) && bundle.css.every(file => exists(bundle.base + "/" + file));
}
function supports(directory, tag) {
    return typeof tag === "string" && !!tag && !availability.isDisabled(tag) && validBundle(directory, registry(directory).bundles.get(tag));
}
function controllerCatalog(english, selected) {
    const result = Object.create(null), source = registry(english), preferred = registry(selected);
    for (const [tag, bundle] of source.bundles) {
        if (availability.isDisabled(tag)) continue;
        if (tag.startsWith("@") || !source.games.has(tag) || validBundle(selected, preferred.bundles.get(tag)) || !validBundle(english, bundle)) continue;
        result[tag] = { bundle, game: source.games.get(tag) };
    }
    return result;
}

class ClientUpdates {
    constructor(root, selected, rooms, launch = spawn) {
        this.root = root;
        this.selected = selected;
        this.english = path.join(root, "client");
        this.rooms = rooms;
        this.launch = launch;
        this.job = { running: false, message: "", error: "" };
    }
    status(tag) {
        if (availability.isDisabled(tag)) return { running: false, available: false, disabled: true, error: availability.message };
        const preferred = supports(this.selected, tag);
        const english = preferred || supports(this.english, tag);
        return { ...this.job, available: english, mode: preferred ? "preferred" : "english" };
    }
    catalog() { return controllerCatalog(this.english, this.selected); }
    start() {
        if (this.job.running) return;
        this.job = { running: true, message: "Проверяю client на GitHub…", error: "" };
        const job = this.job;
        const embedded = path.join(this.root, "runtime/python/python.exe");
        const python = process.env.LOCALBOX_PYTHON || (fs.existsSync(embedded) ? embedded : process.platform === "win32" ? "python" : "python3");
        const processJob = this.launch(python, [path.join(this.root, "installer/client_download.py"), "--update", "--target", this.root], {
            cwd: this.root, windowsHide: true, env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" },
            stdio: ["ignore", "pipe", "pipe"],
        });
        let lastError = "";
        processJob.stdout.setEncoding("utf8");
        processJob.stderr.setEncoding("utf8");
        processJob.stdout.on("data", data => {
            const line = data.trim().split(/[\r\n]+/).at(-1);
            if (line) job.message = line.slice(0, 500);
        });
        processJob.stderr.on("data", data => { lastError = (lastError + data).slice(-1000); });
        processJob.on("error", error => {
            job.running = false;
            job.error = "Не удалось запустить обновление client: " + error.message;
        });
        processJob.on("close", code => {
            job.running = false;
            if (code !== 0) job.error ||= lastError.trim() || "Загрузка client прервалась. Можно повторить.";
            else job.message = "Клиент обновлён.";
        });
    }
    mount(app) {
        app.get("/localbox/client/bridge.js", (_req, res) => res.type("js").set("Cache-Control", "no-store").sendFile(path.join(__dirname, "client-update-ui.js")));
        app.get("/localbox/client/catalog", (_req, res) => res.set("Cache-Control", "no-store").send(this.catalog()));
        app.get("/localbox/client/status", (req, res) => {
            const room = this.rooms.get(String(req.query.code || ""));
            res.set("Cache-Control", "no-store").send(this.status(room?.appTag));
        });
        app.post("/localbox/client/update", (req, res) => {
            // The browser button is same-origin; cross-site pages cannot request
            // an installation even though the Ecast API itself permits CORS.
            if (req.headers.origin) {
                try { if (new URL(req.headers.origin).host !== req.headers.host) return res.sendStatus(403); }
                catch { return res.sendStatus(403); }
            }
            const room = this.rooms.get(String(req.body?.code || ""));
            if (!room || room.closed) return res.status(404).send({ error: "Комната не найдена." });
            if (availability.isDisabled(room.appTag)) return res.status(422).send({ error: availability.message });
            if (this.rooms.list().some(item => !item.closed && (item.gameStarted || item.locked) && !item.gameFinished)) return res.status(409).send({ error: "Обновите client после завершения текущей игры." });
            this.start();
            res.status(202).send(this.status(room.appTag));
        });
    }
}

const root = path.resolve(__dirname, "../..");
const selected = path.resolve(__dirname, "..", process.env.LOCALBOX_CLIENT_DIR || "../client");
const updates = new ClientUpdates(root, selected, require("./room.js"));
module.exports = updates;
module.exports.ClientUpdates = ClientUpdates;
module.exports.supports = supports;
module.exports.controllerCatalog = controllerCatalog;
