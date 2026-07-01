/*
    LocalBox — загрузчик ассетов jackbox.fun.

    Идея: английский клиент (client/) содержит ВСЕ пути файлов с теми же хешами, что и jackbox.fun.
    Берём этот список путей как «оглавление» и для каждого качаем файл с jackbox.fun в client-fun/.
    Так русский клиент (client-fun/) становится полным по всем частям (pp1..pp11, ppad, ...),
    с русскими версиями ассетов там, где они отличаются.

    Запуск (нужен интернет / доступ к jackbox.fun):
        node tools/fetch-fun.js                # client -> jackbox.fun -> client-fun
        node tools/fetch-fun.js --concurrency 16
        node tools/fetch-fun.js --host jackbox.fun --src client --dst client-fun
        node tools/fetch-fun.js --only main/pp5     # только часть пути (например один пак)

    Возобновляемый: уже скачанные в client-fun файлы пропускаются. DoH (1.1.1.1) используется,
    чтобы достучаться до НАСТОЯЩЕГО jackbox.fun даже если домен завёрнут через hosts.
*/

"use strict";

const https = require("https");
const fs = require("fs");
const path = require("path");

const REPO = path.resolve(__dirname, "..");

function parseArgs(argv) {
    const a = { host: "jackbox.fun", src: "client", dst: "client-fun", concurrency: 8,
                only: null, doh: "https://1.1.1.1/dns-query" };
    for (let i = 0; i < argv.length; i++) {
        const k = argv[i];
        if (k === "--host") a.host = argv[++i];
        else if (k === "--src") a.src = argv[++i];
        else if (k === "--dst") a.dst = argv[++i];
        else if (k === "--concurrency") a.concurrency = Number(argv[++i]) || a.concurrency;
        else if (k === "--only") a.only = argv[++i];
        else if (k === "--doh") a.doh = argv[++i];
    }
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
            let b = ""; res.on("data", (c) => (b += c));
            res.on("end", () => {
                try {
                    const ans = (JSON.parse(b).Answer || []).find((x) => x.type === 1);
                    ans ? resolve(ans.data) : reject(new Error("нет A-записи для " + host));
                } catch (e) { reject(e); }
            });
        });
        r.on("error", reject); r.end();
    });
}

// Рекурсивно собирает относительные пути всех файлов в каталоге.
function walk(dir, base = dir, out = []) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, e.name);
        if (e.isDirectory()) walk(full, base, out);
        else if (e.isFile()) out.push(path.relative(base, full));
    }
    return out;
}

function download(host, ip, rel, dstFile) {
    return new Promise((resolve) => {
        const opts = {
            host: ip, servername: host, port: 443,
            path: "/" + rel.split(path.sep).join("/"),
            method: "GET", headers: { host, "user-agent": "LocalBox-fetch-fun" },
        };
        const req = https.request(opts, (res) => {
            if (res.statusCode !== 200) { res.resume(); return resolve({ ok: false, status: res.statusCode }); }
            fs.mkdirSync(path.dirname(dstFile), { recursive: true });
            const tmp = dstFile + ".part";
            const ws = fs.createWriteStream(tmp);
            res.pipe(ws);
            ws.on("finish", () => { ws.close(() => { fs.renameSync(tmp, dstFile); resolve({ ok: true }); }); });
            ws.on("error", (e) => resolve({ ok: false, error: e.message }));
        });
        req.on("error", (e) => resolve({ ok: false, error: e.message }));
        req.setTimeout(20000, () => req.destroy(new Error("timeout")));
        req.end();
    });
}

async function main() {
    const args = parseArgs(process.argv.slice(2));
    const srcDir = path.resolve(REPO, args.src);
    const dstDir = path.resolve(REPO, args.dst);
    if (!fs.existsSync(srcDir)) {
        console.error(`Нет каталога-источника: ${srcDir} (это англ. клиент со всеми путями).`);
        process.exit(1);
    }

    console.log(`Источник путей: ${srcDir}`);
    console.log(`Качаю с:        https://${args.host}/`);
    console.log(`Сохраняю в:     ${dstDir}`);
    if (args.only) console.log(`Только пути:    ${args.only}`);

    let ip;
    try { ip = await resolveIp(args.host, args.doh); }
    catch (e) { console.error(`DoH не смог: ${e.message}`); process.exit(1); }
    console.log(`Реальный IP ${args.host}: ${ip}\n`);

    let files = walk(srcDir);
    if (args.only) files = files.filter((f) => f.split(path.sep).join("/").startsWith(args.only));
    // пропускаем уже скачанные
    const todo = files.filter((rel) => !fs.existsSync(path.join(dstDir, rel)));
    console.log(`Всего файлов: ${files.length}, к скачке: ${todo.length}, уже есть: ${files.length - todo.length}\n`);

    let done = 0, ok = 0, failed = 0, idx = 0;
    async function worker() {
        while (idx < todo.length) {
            const rel = todo[idx++];
            const r = await download(args.host, ip, rel, path.join(dstDir, rel));
            done++;
            if (r.ok) ok++;
            else { failed++; if (failed <= 40) console.log(`  [${r.status || r.error}] ${rel}`); }
            if (done % 100 === 0) console.log(`  …${done}/${todo.length} (ok ${ok}, ошибок ${failed})`);
        }
    }
    await Promise.all(Array.from({ length: args.concurrency }, worker));

    console.log(`\nГотово. Скачано: ${ok}, ошибок: ${failed}, обработано: ${done}.`);
    console.log(`Русский клиент теперь в ${dstDir}. Запускай движок — он его подхватит.`);
}

main().catch((e) => { console.error("Упал:", e); process.exit(1); });
