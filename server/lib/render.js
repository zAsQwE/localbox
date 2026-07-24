"use strict";
//
// LocalBox — рендер выступления Додо Ре Ми (nopus-opus). ЭКСПЕРИМЕНТАЛЬНО.
//
// Игра-хост шлёт external-request/create key "render:N" + payload:
//   { duration, hash, songSlug, instruments:[{slug, chains:[{nodes:[{options:{urls,volume}}]}...]}],
//     performances:[{ instrumentSlug, inputs:[[timeMs,[[offset,durMs,midiNote],...]],...], flubs:[t,...] }] }
// Оригинал рендерит на серверах Jackbox → mp3; клиент играет его как аудио (renderUrl), птиц рисует сам.
//
// Мы делаем этот mp3 локально: раскладываем сэмплы инструмента по временам нот (+ бэкинг песни),
// сводим через ffmpeg. Сэмплы берём из server/render/nopus-opus/instruments/<slug>/<name>.ogg,
// недостающие качаем с cdn.jackboxgames.com и кэшируем.
//
// Готовый mp3 кладём в server/render/out/<id>.mp3 (отдаётся маршрутом GET /render/:file в server.js),
// затем обновляем сущность render:N значением с renderUrl — хост подхватывает и играет.
//

const fs = require("fs");
const path = require("path");
const https = require("https");
const { execFile } = require("child_process");

const RENDER_DIR = path.join(__dirname, "..", "render");
const OUT_DIR = path.join(RENDER_DIR, "out");
const ASSETS = path.join(RENDER_DIR, "nopus-opus");
const INSTR_DIR = path.join(ASSETS, "instruments");
const SONGS_DIR = path.join(ASSETS, "songs");
const CDN = "https://cdn.jackboxgames.com/nopus-opus/instruments";
const EXT = ".ogg";

let state = null; // выставляется из server.js: { serverUrl }
function setState(s) { state = s; }

const NOTE_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];
function midiToName(m) { return NOTE_NAMES[((m % 12) + 12) % 12] + (Math.floor(m / 12) - 1); }
function nameToMidi(name) {
    const mt = /^([A-G]b?)(-?\d+)$/.exec(name); if (!mt) return null;
    const i = NOTE_NAMES.indexOf(mt[1]); if (i < 0) return null;
    return i + (parseInt(mt[2], 10) + 1) * 12;
}

function has(cmd) { try { require("child_process").execFileSync("sh", ["-lc", "command -v " + cmd], { stdio: "ignore" }); return true; } catch { return false; } }
const FFMPEG = has("ffmpeg");

// ---- сэмплы ----

// Скачивает файл с cdn в dest (если ещё нет). Возвращает Promise<bool>.
function fetchSample(slug, name, dest) {
    return new Promise((resolve) => {
        if (fs.existsSync(dest)) return resolve(true);
        const url = CDN + "/" + slug + "/" + name + EXT;
        https.get(url, (res) => {
            if (res.statusCode !== 200) { res.resume(); return resolve(false); }
            fs.mkdirSync(path.dirname(dest), { recursive: true });
            const tmp = dest + ".part";
            const ws = fs.createWriteStream(tmp);
            res.pipe(ws);
            ws.on("finish", () => ws.close(() => { try { fs.renameSync(tmp, dest); resolve(true); } catch { resolve(false); } }));
            ws.on("error", () => resolve(false));
        }).on("error", () => resolve(false));
    });
}

// Локальный путь к сэмплу; если нет — качает. Возвращает Promise<path|null>.
async function ensureSample(slug, name) {
    const dest = path.join(INSTR_DIR, slug, name + EXT);
    if (fs.existsSync(dest)) return dest;
    return (await fetchSample(slug, name, dest)) ? dest : null;
}

// Главный сэмплер инструмента: {urls:{noteName:[names]}, volume}. urls может быть массивом (flub).
function mainSampler(instr) {
    const chain = (instr.chains || []).find((c) => c.type === "main") || (instr.chains || [])[0];
    return chain && chain.nodes && chain.nodes[0] ? chain.nodes[0].options : null;
}
function flubSampler(instr) {
    const chain = (instr.chains || []).find((c) => c.type === "flub");
    return chain && chain.nodes && chain.nodes[0] ? chain.nodes[0].options : null;
}
// Барабанный инструмент? (drumRackSampler / capabilities Drums) — тогда ноты = удары, не высота.
function mainIsDrum(instr) {
    const chain = (instr.chains || []).find((c) => c.type === "main") || (instr.chains || [])[0];
    const node = chain && chain.nodes && chain.nodes[0];
    return !!(node && /drum/i.test(node.type || "")) || (instr.capabilities || []).includes("Drums");
}

// GM-маппинг MIDI-ноты барабана -> имя удара (ключи urls барабанного сэмплера).
const GM_DRUM = {
    35: "kick", 36: "kick", 37: "sidestick", 38: "snare", 39: "snare", 40: "snare",
    41: "floortom", 43: "floortom", 42: "closedhh", 44: "pedalhh", 46: "openhh",
    45: "lowtom", 47: "midtom", 48: "hitom", 50: "hitom",
    49: "crash", 52: "crash", 55: "crash", 57: "crash", 51: "ride", 53: "ride", 59: "ride",
};
// Для барабана: MIDI -> удар -> случайный сэмпл. Без сдвига высоты.
function pickDrum(urls, midi) {
    const keys = Object.keys(urls);
    let key = GM_DRUM[midi];
    if (!key || !urls[key]) key = keys.includes("snare") ? "snare" : keys[0];
    const arr = urls[key];
    if (!Array.isArray(arr) || !arr.length) return null;
    return { name: arr[Math.floor(Math.random() * arr.length)], shift: 0 };
}

// Для midi-ноты выбирает сэмпл: точный noteName или ближайший + сдвиг в полутонах.
function pickSample(urls, midi) {
    const want = midiToName(midi);
    if (urls[want] && urls[want].length) return { name: urls[want][0], shift: 0 };
    // ближайший по midi среди доступных имён-нот
    let best = null, bestD = 1e9;
    for (const key of Object.keys(urls)) {
        const km = nameToMidi(key); if (km == null) continue;
        const d = Math.abs(km - midi);
        if (d < bestD && urls[key] && urls[key].length) { bestD = d; best = { name: urls[key][0], shift: midi - km }; }
    }
    return best;
}

// ---- сборка mp3 через ffmpeg ----

function pow2(semi) { return Math.pow(2, semi / 12); }
// atempo принимает фактор [0.5, 100]; для сдвига высоты >12 полутонов вверх фактор <0.5 —
// разбиваем на цепочку (иначе ffmpeg падает "tempo out of range").
function atempoChain(f) {
    if (!(f > 0)) return "atempo=1.0";
    const parts = [];
    while (f < 0.5) { parts.push("atempo=0.5"); f /= 0.5; }
    while (f > 100) { parts.push("atempo=100"); f /= 100; }
    parts.push("atempo=" + f.toFixed(5));
    return parts.join(",");
}

// Собирает список нот -> ffmpeg. Возвращает Promise<mp3path|null>.
// Приводит один input выступления к списку нот [[offset,durMs,midi],...]. Устойчив к форматам:
//   discrete (высотные/барабаны): [timeMs, [[offset,durMs,midi],...]]
//   continuous (флейта): [timeMs, durMs, [[offset,level],...]] — БЕЗ midi (высота из мелодии
//     песни, inp[1]=длительность, inp[2]=огибающая громкости) — такие партии пропускаем выше.
function normalizeNotes(inp) {
    const second = inp[1];
    if (Array.isArray(second)) {
        return second.map((n) => Array.isArray(n) ? [n[0] || 0, n[1] || 300, n[2]]
            : (typeof n === "number" ? [0, 300, n] : [0, 300, undefined]));
    }
    return [];   // continuous или неизвестный формат — без нот (нет midi)
}

async function synth(payload, id) {
    if (!FFMPEG) { console.log("[render] нет ffmpeg — рендер невозможен"); return null; }
    const perfs = payload.performances || [];
    if (!perfs.length) return null;
    const instruments = payload.instruments || [];

    // 1) события НОТ по ВСЕМ партиям (каждый игрок = своя партия/инструмент), sep "slug|name".
    const events = [];
    const parts = [];
    for (const perf of perfs) {
        const instr = instruments.find((i) => i.slug === perf.instrumentSlug);
        if (!instr) { console.log("[render] пропуск партии: нет инструмента " + perf.instrumentSlug); continue; }
        const main = mainSampler(instr);
        if (!main) continue;
        const slug = instr.slug;
        const mainVol = typeof main.volume === "number" ? main.volume : -9;
        const isDrum = mainIsDrum(instr);
        const isSynth = !main.urls;   // синтезатор без сэмплов -> тон (sine)
        // Continuous-инструменты (флейта и т.п.): высоты в нотах нет — её задаёт позиция level
        // (0..1) огибающей ВНУТРИ диапазона perf.limits [timeMs, lowMidi, highMidi] в этот момент.
        // pitch = low + level*(high-low). inputs: [startMs, durMs, [[offset, level],...]].
        const isContinuous = !isSynth && (/continuous/i.test(String(perf.beatmapType || ""))
            || (perf.inputs || []).some((x) => Array.isArray(x) && typeof x[1] === "number" && Array.isArray(x[2])));
        if (isContinuous) {
            const limits = Array.isArray(perf.limits) ? perf.limits : [];
            let added = 0;
            for (const inp of perf.inputs || []) {
                if (!Array.isArray(inp)) continue;
                const start = inp[0] || 0;
                const dur = typeof inp[1] === "number" ? inp[1] : 400;
                const env = (Array.isArray(inp[2]) ? inp[2] : []).filter((p) => Array.isArray(p) && typeof p[1] === "number");
                const level = env.length ? env.reduce((a, p) => a + p[1], 0) / env.length : 0.5;   // средний уровень
                let seg = limits[0];
                for (const L of limits) { if (Array.isArray(L) && L[0] <= start) seg = L; else break; }   // активный диапазон
                if (!seg) continue;
                const midi = Math.round(seg[1] + level * (seg[2] - seg[1]));
                const s = pickSample(main.urls, midi);
                if (s && Math.abs(s.shift || 0) <= 36) { events.push({ startMs: start, durMs: dur, slug, name: s.name, shift: s.shift, volDb: mainVol }); added++; }
            }
            const flubC = flubSampler(instr);
            if (flubC && Array.isArray(flubC.urls) && flubC.urls.length) {
                const fvol = typeof flubC.volume === "number" ? flubC.volume : -12;
                for (const t of perf.flubs || []) events.push({ startMs: t, durMs: 400, slug, name: flubC.urls[Math.floor(Math.random() * flubC.urls.length)], shift: 0, volDb: fvol });
            }
            parts.push(slug + "(continuous," + added + ")");
            continue;
        }
        parts.push(slug + (isDrum ? "(бар)" : isSynth ? "(синт)" : ""));
        for (const inp of perf.inputs || []) {
            if (!Array.isArray(inp)) continue;
            const t = inp[0] || 0;
            for (const n of normalizeNotes(inp)) {
                const offset = n[0] || 0, durMs = n[1] || 300, midi = n[2];
                if (typeof midi !== "number") continue;
                if (isSynth) {
                    events.push({ startMs: t + offset, durMs, synth: true, freq: 440 * Math.pow(2, (midi - 69) / 12), volDb: mainVol });
                } else {
                    const s = isDrum ? pickDrum(main.urls, midi) : pickSample(main.urls, midi);
                    if (s && Math.abs(s.shift || 0) <= 36) events.push({ startMs: t + offset, durMs, slug, name: s.name, shift: s.shift, volDb: mainVol });
                }
            }
        }
        // флабы этой партии
        const flub = flubSampler(instr);
        if (flub && Array.isArray(flub.urls) && flub.urls.length) {
            const fvol = typeof flub.volume === "number" ? flub.volume : -12;
            for (const t of perf.flubs || []) {
                events.push({ startMs: t, durMs: 400, slug, name: flub.urls[Math.floor(Math.random() * flub.urls.length)], shift: 0, volDb: fvol });
            }
        }
    }
    console.log("[render] партий: " + perfs.length + " [" + parts.join(", ") + "], нот: " + events.length);
    if (!events.length) return null;

    // 2) качаем недостающие сэмплы ПАРАЛЛЕЛЬНО (по паре slug|name, т.к. инструменты разные).
    const uniq = [...new Set(events.filter((e) => e.name).map((e) => e.slug + "|" + e.name))];
    const paths = {};
    const t0 = Date.now();
    await Promise.all(uniq.map((key) => { const i = key.indexOf("|"); return ensureSample(key.slice(0, i), key.slice(i + 1)).then((p) => { paths[key] = p; }); }));
    if (uniq.length) console.log("[render] сэмплов:", uniq.length, "готово за", ((Date.now() - t0) / 1000).toFixed(1) + "с");
    const usable = events.filter((e) => e.synth || paths[e.slug + "|" + e.name]);
    if (!usable.length) { console.log("[render] ни один сэмпл не доступен (нет локально и не скачались)"); return null; }

    // 3) бэкинг песни (локаль-специфичный, иначе базовый)
    const locale = payload.locale || "en";
    const songDir = path.join(SONGS_DIR, payload.songSlug || (perfs[0] && perfs[0].songSlug) || "");
    let backing = null;
    for (const cand of ["backing_" + locale + ".ogg", "backing.ogg", "backing_en.ogg"]) {
        if (fs.existsSync(path.join(songDir, cand))) { backing = path.join(songDir, cand); break; }
    }

    // 4) ffmpeg: каждый сэмпл -> обрезка/сдвиг/громкость/задержка -> amix (+ бэкинг)
    fs.mkdirSync(OUT_DIR, { recursive: true });
    const out = path.join(OUT_DIR, id + ".mp3");
    const inputs = [];
    const filters = [];
    let idx = 0;
    for (const e of usable) {
        const durSec = Math.max(0.05, (e.durMs || 300) / 1000);
        let f;
        if (e.synth) {
            // тон-генератор: sine нужной частоты, короткий fade-in (от щелчка) + fade-out (release)
            inputs.push("-f", "lavfi", "-i", `sine=frequency=${e.freq.toFixed(2)}:duration=${durSec.toFixed(3)}:sample_rate=44100`);
            const rel = Math.min(0.15, durSec * 0.5);
            f = `[${idx}:a]afade=t=in:d=0.005,afade=t=out:st=${(durSec - rel).toFixed(3)}:d=${rel.toFixed(3)}` +
                `,volume=${dbToLin(e.volDb).toFixed(4)},adelay=${e.startMs}|${e.startMs}[a${idx}]`;
        } else {
            inputs.push("-i", paths[e.slug + "|" + e.name]);
            f = `[${idx}:a]atrim=0:${durSec.toFixed(3)}`;
            if (e.shift) { const r = pow2(e.shift); f += `,asetrate=44100*${r.toFixed(5)},aresample=44100,${atempoChain(1 / r)}`; }
            f += `,volume=${dbToLin(e.volDb).toFixed(4)},adelay=${e.startMs}|${e.startMs}[a${idx}]`;
        }
        filters.push(f);
        idx++;
    }
    // Громкость: инструменты бустим (иначе почти не слышно на фоне бэкинга), бэкинг тише,
    // финальный alimiter спасает от клиппинга. Настраивается через env.
    const INSTR_GAIN = parseFloat(process.env.LOCALBOX_RENDER_INSTR || "4") || 4;
    const BACK_VOL = parseFloat(process.env.LOCALBOX_RENDER_BACKING || "0.45") || 0.45;
    let mixLabels = usable.map((_, i) => `[a${i}]`).join("");
    let last = "[mix]";
    filters.push(`${mixLabels}amix=inputs=${usable.length}:normalize=0:dropout_transition=0,volume=${INSTR_GAIN}[mix]`);
    if (backing) {
        inputs.push("-i", backing);
        filters.push(`[${idx}:a]volume=${BACK_VOL}[bk]`);
        filters.push(`[mix][bk]amix=inputs=2:normalize=0,alimiter=limit=0.95[out]`);
        last = "[out]";
    } else {
        filters.push(`[mix]alimiter=limit=0.95[out]`);
        last = "[out]";
    }
    const args = [...inputs, "-filter_complex", filters.join(";"), "-map", last,
        "-ac", "2", "-ar", "44100", "-b:a", "192k", "-y", out];

    return new Promise((resolve) => {
        console.log(`[render] ffmpeg: ${usable.length} нот${backing ? " + бэкинг" : ""} → ${id}.mp3`);
        execFile("ffmpeg", args, { maxBuffer: 64 * 1024 * 1024 }, (err, _stdout, stderr) => {
            if (err || !fs.existsSync(out) || fs.statSync(out).size < 200) {
                const tail = (stderr ? String(stderr).trim().split("\n").slice(-3).join(" | ") : (err && err.message)) || "?";
                console.log("[render] ffmpeg не собрал mp3: " + tail);
                return resolve(null);
            }
            resolve(out);
        });
    });
}

function dbToLin(db) { return Math.pow(10, db / 20); }

// ---- точка входа: external-request/create ----

// Поддержка Додо Ре Ми включается флагом окружения LOCALBOX_DODO=1 (из настроек лаунчера или
// из start-server.bat). Без него запросы рендера просто подтверждаются и пропускаются.
function dodoEnabled() { return process.env.LOCALBOX_DODO === "1"; }

// Что есть для рендера: ffmpeg + сколько песенных бэкингов лежит локально.
function readiness() {
    let backings = 0;
    try {
        for (const slug of fs.readdirSync(SONGS_DIR)) {
            const d = path.join(SONGS_DIR, slug);
            try { if (fs.statSync(d).isDirectory() && fs.readdirSync(d).some((f) => /^backing.*\.ogg$/i.test(f))) backings++; } catch { /* skip */ }
        }
    } catch { /* нет папки songs */ }
    return { enabled: dodoEnabled(), ffmpeg: FFMPEG, backings };
}

// Печатает статус/инструкцию при старте (только если поддержка включена).
function logStatus(log) {
    log = log || console.log;
    const r = readiness();
    if (!r.enabled) return;
    log("[dodo] Додо Ре Ми: поддержка ВКЛючена.");
    if (!r.ffmpeg) {
        log("[dodo] ⚠ ffmpeg НЕ найден — рендер выступления невозможен. Поставь ffmpeg (в PATH) и перезапусти.");
        return;
    }
    log("[dodo] ffmpeg: ок · бэкингов песен найдено: " + r.backings + " (инструменты докачаются сами).");
    if (r.backings === 0) {
        log("[dodo] ⚠ Нет бэкингов песен — выступление соберётся БЕЗ музыки (только ноты игрока + промахи).");
        log("[dodo]   Чтобы была музыка, положи бэкинг каждой песни сюда:");
        log("[dodo]     server/render/nopus-opus/songs/<slug>/backing.ogg");
        log("[dodo]   Взять из установленной игры: .../games/NopusOpus/songs/<slug>/  (<slug> виден в логе рендера).");
    }
}

let counter = 0, warnedOff = false;
function handleExternalRequest(client, room, msg) {
    const p = msg.params || {};
    const key = String(p.key || "");

    client.sendOk(msg.seq);
    if (!key.startsWith("render") || !p.payload) return;

    if (!dodoEnabled()) {
        if (!warnedOff) { console.log("[dodo] пришёл запрос рендера, но поддержка Додо Ре Ми ВЫКЛючена — пропускаю. Включи её в настройках лаунчера или запусти сервер «с поддержкой Додо Ре Ми» (start-server.bat)."); warnedOff = true; }
        return;
    }
    if (!FFMPEG) { console.log("[dodo] ⚠ нет ffmpeg — рендер невозможен. Поставь ffmpeg (в PATH)."); return; }

    console.log("[render] запрос: key=" + key + " service=" + (p.service || "?") + " acl=" + JSON.stringify(p.acl || null));

    try { fs.mkdirSync(RENDER_DIR, { recursive: true }); fs.writeFileSync(path.join(RENDER_DIR, "last-render-payload.json"), JSON.stringify(p.payload, null, 2)); } catch {}

    const acl = p.acl && p.acl.length ? p.acl : ["rw role:host"];
    // ВАЖНО (разобрано из NopusOpus.swf): хост парсит апдейт как ecast-сообщение с opcode
    // "external-request" → new ExternalRequest(key, from, val.service, val.status, val.response,
    // val.progress). А в Playback: if status=="success" -> берёт response.gameRenderUrl и качает.
    // Поэтому: тип сущности "external-request" (notify отдаёт нужный opcode), а в val —
    // {service, status, response:{gameRenderUrl}, progress}. Статусы: pending/success/error.
    room.setEntity("external-request", key, acl, { val: { service: p.service, status: "pending", progress: 0, response: null } });
    room.notify(key, true, null);

    const id = "r" + Date.now() + "_" + (++counter);
    synth(p.payload, id).then((mp3) => {
        if (!mp3) {
            console.log("[render] рендер не удался — статус error");
            room.setEntity("external-request", key, acl, { val: { service: p.service, status: "error", progress: 1, response: null } });
            room.notify(key, true, null);
            return;
        }
        const url = "https://" + (state && state.serverUrl || "localhost") + "/render/" + path.basename(mp3);
        console.log("[render] готово: " + url + "  (жду GET /render — хост качает mp3)");
        const val = {
            service: p.service, status: "success", progress: 1,
            response: { gameRenderUrl: url },
        };
        room.setEntity("external-request", key, acl, { val });
        room.notify(key, true, null);
    }).catch((e) => console.log("[render] исключение: " + (e && e.message)));
}

module.exports = { handleExternalRequest, setState, synth, readiness, logStatus, OUT_DIR, RENDER_DIR };
