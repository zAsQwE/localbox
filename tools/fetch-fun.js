/*
    LocalBox — загрузчик ассетов jackbox.fun.

    Читаем index.html и таблицу модулей самого скачиваемого клиента, затем CSS/JS/HTML.
    Поддерживаются старые вложенные пути и новые плоские пути с хешами в именах файлов.
    Имена и хеши русского клиента могут отличаться от английского.
    Так русский клиент (client-fun/) становится полным по всем частям (pp1..pp11, ppad, ...),
    с русскими версиями ассетов там, где они отличаются.

    Запуск (нужен интернет / доступ к jackbox.fun):
        node tools/fetch-fun.js                # client -> jackbox.fun -> client-fun
        node tools/fetch-fun.js --concurrency 16
        node tools/fetch-fun.js --host jackbox.fun --src client --dst client-fun
        node tools/fetch-fun.js --only main/pp5     # только часть пути (например один пак)
        node tools/fetch-fun.js --host jackbox.ru --dst client-ru --repair --only main/pp7/quiplash3

    Возобновляемый: уже скачанные в client-fun файлы пропускаются. DoH (1.1.1.1) используется,
    чтобы достучаться до НАСТОЯЩЕГО jackbox.fun даже если домен завёрнут через hosts.
*/

"use strict";

const https = require("https");
const fs = require("fs");
const path = require("path");
const { references, TEXT } = require("./asset-references.js");

const REPO = path.resolve(__dirname, "..");

function parseArgs(argv) {
    const a = { host: "jackbox.fun", src: "client", dst: "client-fun", concurrency: 8,
                only: null, doh: "https://1.1.1.1/dns-query",
                // режим диапазона:
                url: null, from: null, to: null, ext: ".ogg", pad: 0, dry: false, noDoh: false, repair: false };
    for (let i = 0; i < argv.length; i++) {
        const k = argv[i];
        if (k === "--host") a.host = argv[++i];
        else if (k === "--src") a.src = argv[++i];
        else if (k === "--dst") a.dst = argv[++i];
        else if (k === "--concurrency") a.concurrency = Number(argv[++i]);
        else if (k === "--only") a.only = argv[++i];
        else if (k === "--doh") a.doh = argv[++i];
        else if (k === "--url") a.url = argv[++i];
        else if (k === "--from") a.from = Number(argv[++i]);
        else if (k === "--to") a.to = Number(argv[++i]);
        else if (k === "--ext") a.ext = argv[++i];
        else if (k === "--pad") a.pad = Number(argv[++i]);
        else if (k === "--dry") a.dry = true;
        else if (k === "--no-doh") a.noDoh = true;
        else if (k === "--repair") a.repair = true;
    }
    if (!Number.isInteger(a.concurrency) || a.concurrency < 1 || a.concurrency > 128)
        throw new Error("--concurrency must be an integer from 1 to 128");
    for (const key of ["host", "src", "dst", "doh", "ext"])
        if (typeof a[key] !== "string" || !a[key]) throw new Error("Missing --" + key + " value");
    if (!Number.isSafeInteger(a.pad) || a.pad < 0 || a.pad > 1000) throw new Error("Invalid --pad");
    if (a.url && (!Number.isSafeInteger(a.from) || !Number.isSafeInteger(a.to) || a.to < a.from)) throw new Error("Invalid --from/--to range");
    return a;
}

// Резолвим реальный IP хоста через DoH (минуя /etc/hosts).
function resolveIp(host, dohUrl) {
    const u = new URL(dohUrl);
    return new Promise((resolve, reject) => {
        const opts = {
            host: u.hostname, port: 443,
            path: `${u.pathname}?name=${encodeURIComponent(host)}&type=A`,
            method: "GET", headers: { accept: "application/dns-json", host: u.hostname },
        };
        const r = https.request(opts, (res) => {
            res.on("error", reject);
            res.on("aborted", () => reject(new Error("DNS response interrupted")));
            let b = ""; res.on("data", (c) => (b += c));
            res.on("end", () => {
                try {
                    const ans = (JSON.parse(b).Answer || []).find((x) => x.type === 1);
                    ans ? resolve(ans.data) : reject(new Error("нет A-записи для " + host));
                } catch (e) { reject(e); }
            });
        });
        r.on("error", reject);
        r.setTimeout(20000, () => r.destroy(new Error("DNS timeout"))); r.end();
    });
}

// Рекурсивно собирает относительные пути всех файлов в каталоге.
function walk(dir, base = dir, out = []) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        if (e.name.startsWith(".") || e.name === "node_modules") continue;
        const full = path.join(dir, e.name);
        if (e.isDirectory()) walk(full, base, out);
        else if (e.isFile()) out.push(path.relative(base, full));
    }
    return out;
}

function download(host, ip, rel, dstFile) {
    return require("../server/lib/download.js")({
        host: ip || host, servername: host, port: 443,
        path: "/" + rel.split(path.sep).join("/").split("/").map(encodeURIComponent).join("/"),
        headers: { host, "user-agent": "LocalBox-fetch-fun" },
    }, dstFile);
}

// Режим диапазона: качает NNNNNN.ogg от --from до --to (включительно) с --url.
//   node tools/fetch-fun.js --url https://jackbox.ru/mods/pp2/earwax/sounds/ --from 111111 --to 112041
// Сохраняет по умолчанию в client-ru/<путь-из-URL>/, чтобы локальный сервер сразу их отдавал.
async function runRange(args) {
    const u = new URL(args.url);
    const host = u.hostname;
    const basePath = u.pathname.endsWith("/") ? u.pathname : u.pathname + "/"; // "/mods/pp2/earwax/sounds/"
    const dstBase = args.dst && args.dst !== "client-fun"
        ? path.resolve(REPO, args.dst)
        : path.join(REPO, "client-ru", basePath.replace(/^\//, ""));

    if (args.from == null || args.to == null || Number.isNaN(args.from) || Number.isNaN(args.to)) {
        console.error("Нужны --from и --to (числа)."); process.exit(1);
    }
    if (args.to < args.from) { console.error("--to меньше --from."); process.exit(1); }

    const name = (n) => (args.pad > 0 ? String(n).padStart(args.pad, "0") : String(n)) + args.ext;
    const total = args.to - args.from + 1;

    console.log(`Качаю диапазон: https://${host}${basePath}{${name(args.from)} … ${name(args.to)}}`);
    console.log(`Всего номеров:  ${total}`);
    console.log(`Сохраняю в:     ${dstBase}`);

    if (args.dry) {
        const sample = [];
        for (let n = args.from; n <= args.to && sample.length < 3; n++) sample.push(name(n));
        console.log(`\n[dry] Примеры первых: ${sample.join(", ")}`);
        console.log(`[dry] Последний:      ${name(args.to)}`);
        console.log(`[dry] Пример URL:     https://${host}${basePath}${name(args.from)}`);
        console.log(`[dry] Пример файла:   ${path.join(dstBase, name(args.from))}`);
        console.log(`\n[dry] Реального скачивания нет. Убери --dry, чтобы скачать ${total} файлов.`);
        return;
    }

    let ip = null;
    if (!args.noDoh) {
        try { ip = await resolveIp(host, args.doh); console.log(`Реальный IP ${host}: ${ip}`); }
        catch (e) { console.log(`DoH не смог (${e.message}) — подключаюсь напрямую по имени.`); }
    }
    console.log("");

    // список номеров, пропуская уже скачанные
    const todo = [];
    for (let n = args.from; n <= args.to; n++) {
        if (!fs.existsSync(path.join(dstBase, name(n)))) todo.push(n);
    }
    console.log(`К скачке: ${todo.length}, уже есть: ${total - todo.length}\n`);

    let done = 0, ok = 0, missing = 0, failed = 0, idx = 0;
    async function worker() {
        while (idx < todo.length) {
            const n = todo[idx++];
            const fname = name(n);
            const rel = basePath.replace(/^\//, "") + fname;
            const r = await download(host, ip, rel, path.join(dstBase, fname));
            done++;
            if (r.ok) ok++;
            else if (r.status === 404) missing++;
            else { failed++; if (failed <= 40) console.log(`  [${r.status || r.error}] ${fname}`); }
            if (done % 100 === 0) console.log(`  …${done}/${todo.length} (ok ${ok}, нет ${missing}, ошибок ${failed})`);
        }
    }
    await Promise.all(Array.from({ length: args.concurrency }, worker));

    console.log(`\nГотово. Скачано: ${ok}, отсутствуют(404): ${missing}, ошибок: ${failed}.`);
    console.log(`Файлы в ${dstBase}. Сервер отдаст их по пути ${basePath}.`);
}

async function main() {
    const args = parseArgs(process.argv.slice(2));
    if (args.url) return runRange(args);
    const srcDir = path.resolve(REPO, args.src);
    const dstDir = path.resolve(REPO, args.dst);
    if (args.repair && !fs.existsSync(dstDir)) {
        console.error(`Нет каталога: ${dstDir}.`);
        process.exit(1);
    }

    console.log(`Источник путей: ${args.repair ? dstDir : "index.html и модули скачиваемого клиента"}`);
    console.log(`Качаю с:        https://${args.host}/`);
    console.log(`Сохраняю в:     ${dstDir}`);
    if (args.only) console.log(`Только пути:    ${args.only}`);

    const result = await fetchAssets(args, { srcDir, dstDir });
    if (args.dry) {
        console.log(`[dry] Недостающих зависимостей: ${result.missing.length}. Реального скачивания нет.`);
        return;
    }
    console.log(`\nГотово. Скачано: ${result.ok}, ошибок: ${result.failed}, обработано: ${result.done}.`);
    console.log(`Русский клиент теперь в ${dstDir}. Запускай движок — он его подхватит.`);
}

async function fetchAssets(args, { srcDir, dstDir, fetch = download, resolve = resolveIp, log = console.log }) {
    const todo = [], seen = new Set();
    const nativeBuild = fs.existsSync(path.join(dstDir, "index.html")) ||
        fs.existsSync(path.join(srcDir, "index.html")) || !fs.existsSync(srcDir);
    // Filters use a canonical nested base so either spelling selects the same game/pack.
    const canonical = (rel) => rel.replace(/^main\/(pp\d+|ppad)-([^/]+)/, "main/$1/$2");
    const prefix = args.only ? canonical(args.only.replace(/\/+$/, "")) : null;
    const allowed = (rel) => {
        const name = canonical(rel);
        return !prefix || name === prefix || name.startsWith(prefix + "/") ||
            (!args.repair && nativeBuild && (!name.startsWith("main/") || name.startsWith("main/@")));
    };
    const inspect = (rel) => {
        if (!TEXT.has(path.posix.extname(rel).toLowerCase())) return;
        try {
            const content = fs.readFileSync(path.join(dstDir, rel), "utf8");
            for (const reference of references(content, rel, args.host)) enqueue(reference);
        } catch { /* A missing or unreadable file is handled by the download queue. */ }
    };
    const enqueue = (rel) => {
        rel = rel.split(path.sep).join("/");
        if (seen.has(rel) || !allowed(rel)) return;
        seen.add(rel);
        if (fs.existsSync(path.join(dstDir, rel))) inspect(rel);
        else todo.push(rel);
    };
    if (nativeBuild || args.repair) {
        if (fs.existsSync(dstDir)) {
            for (const relative of walk(dstDir)) {
                enqueue(relative);
                // A cached root manifest can discover missing game files even with --only.
                if (!relative.includes("/") && TEXT.has(path.posix.extname(relative))) inspect(relative);
            }
        }
        if (!args.repair) enqueue("index.html");
    } else {
        // Legacy partial exports without an HTML entry point still use the explicit source tree.
        for (const relative of walk(srcDir)) enqueue(relative);
        if (fs.existsSync(dstDir)) for (const relative of walk(dstDir)) enqueue(relative);
    }
    log(`Проверено путей: ${seen.size}; к скачке: ${todo.length}. Ссылки из CSS/JS проверяются и в кэше.`);
    if (args.dry) return { done: 0, ok: 0, failed: 0, missing: [...todo] };
    let ip = null;
    if (!args.noDoh && todo.length) {
        try { ip = await resolve(args.host, args.doh); }
        catch (e) { log(`DoH не смог: ${e.message} — подключаюсь напрямую.`); }
    }
    let done = 0, ok = 0, failed = 0, idx = 0;
    async function worker() {
        while (idx < todo.length) {
            const rel = todo[idx++];
            const r = await fetch(args.host, ip, rel, path.join(dstDir, rel));
            done++;
            if (r.ok) { ok++; inspect(rel); }
            else { failed++; if (failed <= 40) log(`  [${r.status || r.error}] ${rel}`); }
            if (done % 100 === 0) log(`  …${done}/${todo.length} (ok ${ok}, ошибок ${failed})`);
        }
    }
    await Promise.all(Array.from({ length: args.concurrency }, worker));

    return { done, ok, failed };
}

if (require.main === module) main().catch((e) => { console.error("Упал:", e); process.exit(1); });
module.exports = { parseArgs, walk, download, fetchAssets };
