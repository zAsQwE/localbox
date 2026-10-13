"use strict";
//
// LocalBox server — синтез речи (TTS) для игр вроде Mad Verse City. Полностью локально/офлайн.
// Движок выбирается через LOCALBOX_TTS_ENGINE: silero | espeak | silent | auto (по умолчанию).
//   silero  — нейросетевой русский голос (Python-воркер tts/silero_worker.py, нужен torch), лучшее качество;
//   espeak  — робо-голос (espeak-ng), лёгкий;
//   silent  — тишина нужной длины (игра не падает, но без голоса);
//   auto    — silero, если получилось; иначе espeak; иначе тишина.
// LOCALBOX_TTS_VOICE — голос Silero (eugene/baya/kseniya/xenia/aidar/random).
//

const fs = require("fs");
const path = require("path");
const { execFile, execFileSync, spawn } = require("child_process");
const u = require("./util.js");

const DIR = path.join(__dirname, "..", "storage", "tts");
// Кросс-платформенная проверка «команда есть в PATH» (см. пояснение в render.js — sh нет на Windows).
function has(cmd) {
    try {
        if (process.platform === "win32") execFileSync("where", [cmd], { stdio: "ignore" });
        else execFileSync(cmd, ["-version"], { stdio: "ignore" });
        return true;
    } catch (e) {
        if (process.platform === "win32") return false;
        return !!(e && Number.isInteger(e.status));
    }
}
const ESPEAK = has("espeak-ng") ? "espeak-ng" : (has("espeak") ? "espeak" : null);
// FFMPEG — путь к бинарнику (свой в runtime/, иначе из PATH) или null. См. server/lib/ffmpeg.js.
const FFMPEG = require("./ffmpeg.js").FFMPEG;

const ENGINE = (process.env.LOCALBOX_TTS_ENGINE || "auto").toLowerCase();
const VOICE = process.env.LOCALBOX_TTS_VOICE || "eugene";
const PYTHON = process.env.LOCALBOX_PYTHON || "python3";
const PIPER_DIR = path.join(__dirname, "..", "tts", "piper");
const SILERO_SET = new Set(["aidar", "baya", "kseniya", "xenia", "eugene", "random"]);
const PIPER_SET = new Set(["ru_RU-denis-medium", "ru_RU-dmitri-medium", "ru_RU-irina-medium", "ru_RU-ruslan-medium"]);
function sileroSpeaker() { return SILERO_SET.has(VOICE) ? VOICE : "eugene"; }
function piperVoice() { return PIPER_SET.has(VOICE) ? VOICE : "ru_RU-denis-medium"; }

console.log("[tts] движок:", ENGINE, "| голос:", VOICE, "| espeak:", ESPEAK || "нет", "| ffmpeg:", FFMPEG ? "да" : "нет");

function run(cmd, args) { return new Promise((res) => execFile(cmd, args, { timeout: 120000 }, (err) => res(!err))); }

// Python на Windows по умолчанию открывает stdin/stdout в кодировке консоли/системной локали,
// НЕ в UTF-8 (в отличие от Linux, где локаль обычно и так UTF-8). Мы пишем кириллический текст
// в stdin процессов Piper/Silero как UTF-8 — без этих переменных Python на Windows декодирует его
// неверно (текст превращается в мусор/пусто), из-за чего Piper синтезирует НОЛЬ аудио-чанков и
// падает с непонятной "wave.Error: # channels not specified" (сам файл при этом даже не открыт
// с нужными параметрами). PYTHONUTF8=1 включает Python UTF-8 mode целиком (PEP 540).
const PY_ENV = Object.assign({}, process.env, { PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" });

// ---- Piper (piper1-gpl): быстрый нейро-TTS; голос-модель качается один раз в tts/piper/ ----
// Piper НЕ докачивает голос сам — сначала piper.download_voices, потом синтез.
// Голос — ДВА файла (.onnx + .onnx.json с конфигом sample rate/каналов и т.п.) — если скачивание
// прервалось (сеть моргнула, сон устройства) и остался только .onnx без .onnx.json, Piper падает
// на синтезе с непонятной внутренней ошибкой (напр. "wave.Error: # channels not specified"),
// а наша проверка "уже скачано" раньше смотрела только на .onnx и не замечала неполную загрузку.
function piperVoiceReady(voice) {
    return fs.existsSync(path.join(PIPER_DIR, voice + ".onnx")) && fs.existsSync(path.join(PIPER_DIR, voice + ".onnx.json"));
}
function piperEnsure(voice) {
    return new Promise((resolve) => {
        if (piperVoiceReady(voice)) return resolve(true);
        console.log("[tts] Piper: скачиваю голос " + voice + " (один раз)…");
        let p;
        try { p = spawn(PYTHON, ["-m", "piper.download_voices", voice, "--data-dir", PIPER_DIR], { env: PY_ENV, timeout: 600000 }); }
        catch { return resolve(false); }
        let err = "";
        p.stderr.on("data", (d) => { err += d.toString(); });
        p.on("error", () => resolve(false));
        p.stdout.resume();
        p.on("close", (code) => {
            const ok = code === 0 && piperVoiceReady(voice);
            if (!ok && err) console.log("[tts] Piper: не скачался голос (нет .onnx/.onnx.json): " + err.trim().split("\n").pop().slice(0, 200));
            resolve(ok);
        });
    });
}
async function piperSynth(text, voice, out) {
    fs.mkdirSync(PIPER_DIR, { recursive: true });
    if (!(await piperEnsure(voice))) return false;
    return new Promise((resolve) => {
        let p;
        try { p = spawn(PYTHON, ["-m", "piper", "-m", voice, "--data-dir", PIPER_DIR, "-f", out], { env: PY_ENV, timeout: 120000 }); }
        catch (e) { console.log("[tts] Piper: не запустить (" + e.message + ")"); return resolve(false); }
        let err = "";
        p.stderr.on("data", (d) => { err += d.toString(); });
        p.stdout.resume();
        p.stdin.on("error", () => resolve(false));
        try { p.stdin.write(String(text || " ").slice(0, 900)); p.stdin.end(); } catch { /* ignore */ }
        p.on("error", () => resolve(false));
        p.on("close", (code) => {
            const ok = code === 0 && fs.existsSync(out) && fs.statSync(out).size > 100;
            if (!ok && err) console.log("[tts] Piper: " + err.trim().split("\n").pop().slice(0, 200));
            resolve(ok);
        });
    });
}

// ---- Общий Python-воркер (модель грузится один раз, запросы по stdin/stdout JSON) ----
// Используется для Silero. synth(payload) → Promise<bool>, поля payload идут воркеру.
function makeWorker(scriptRel, label) {
    let proc = null, ready = null;
    const pend = new Map();
    let rid = 0;
    function start() {
        if (ready) return ready;
        ready = new Promise((resolve) => {
            let p;
            try { p = spawn(PYTHON, [path.join(__dirname, "..", "tts", scriptRel)], { env: PY_ENV }); }
            catch { resolve(false); return; }
            proc = p;
            let buf = "", failed = false;
            const fail = () => {
                if (failed) return;
                failed = true;
                clearTimeout(timer);
                resolve(false);
                if (proc === p) { proc = null; ready = null; }
                for (const finish of pend.values()) finish(false);
                pend.clear();
                p.kill();
            };
            const timer = setTimeout(() => {
                console.log("[tts] " + label + ": таймаут загрузки модели");
                fail();
            }, 600000);
            p.stdout.setEncoding("utf8");
            p.stdout.on("data", (d) => {
                if (failed) return;
                buf += d;
                let i;
                while ((i = buf.indexOf("\n")) >= 0) {
                    const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
                    let m; try { m = JSON.parse(line); } catch { continue; }
                    if (!m || typeof m !== "object") continue;
                    if (m.info) { console.log("[tts] " + m.info); continue; }
                    if (m.ready !== undefined) {
                        clearTimeout(timer);
                        if (m.ready) {
                            console.log("[tts] " + label + " готов" + (m.device ? " (" + m.device + ")" : ""));
                            resolve(true);
                        } else {
                            console.log("[tts] " + label + " недоступен: " + m.error);
                            fail();
                        }
                    } else if (m.id != null && pend.has(m.id)) {
                        const finish = pend.get(m.id); pend.delete(m.id); finish(!!m.ok);
                    }
                }
            });
            p.stderr.resume();
            p.on("error", fail);
            p.on("close", fail);
            p.stdin.on("error", fail);
        });
        return ready;
    }
    function synth(payload) {
        return new Promise((resolve) => {
            if (!proc) return resolve(false);
            const id = ++rid;
            const timer = setTimeout(() => { pend.delete(id); resolve(false); }, 120000);
            pend.set(id, (ok) => { clearTimeout(timer); resolve(ok); });
            try { proc.stdin.write(JSON.stringify(Object.assign({ id }, payload)) + "\n"); }
            catch { clearTimeout(timer); pend.delete(id); resolve(false); }
        });
    }
    return { start, synth };
}

const silero = makeWorker("silero_worker.py", "Silero");

// wav -> mp3 (если есть ffmpeg), иначе оставляем wav. Возвращает имя файла в DIR или null.
async function toAudio(id) {
    const wav = path.join(DIR, id + ".wav");
    if (!fs.existsSync(wav)) return null;
    if (FFMPEG) {
        const mp3 = path.join(DIR, id + ".mp3");
        // громче + выровнять громкость (Silero/espeak часто тихие). loudnorm с запасом.
        const ok = await run(FFMPEG, ["-y", "-i", wav, "-af", "loudnorm=I=-11:TP=-1.5:LRA=11,volume=1.5", mp3]);
        if (ok && fs.existsSync(mp3) && fs.statSync(mp3).size > 0) { try { fs.unlinkSync(wav); } catch { /* ignore */ } return id + ".mp3"; }
    }
    return id + ".wav";
}

function espeakVoice(voice) {
    const v = String(voice || "").trim();
    // прямое имя голоса espeak (напр. "ru", "ru+m5", "ru+f3") — используем как есть
    if (/^[a-z]{2,3}(\+[mf]\d{1,2})?$/i.test(v)) return v;
    if (/fem|жен|kseniya|xenia|baya/i.test(v)) return "ru+f3";
    if (/max|male|муж|aidar|eugene/i.test(v)) return "ru+m3";
    return "ru";
}

async function silence(id, text) {
    const dur = Math.min(Math.max(String(text || "").length * 0.07, 1), 12);
    if (FFMPEG) {
        const mp3 = path.join(DIR, id + ".mp3");
        const ok = await run(FFMPEG, ["-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", dur.toFixed(1), mp3]);
        if (ok && fs.existsSync(mp3) && fs.statSync(mp3).size > 0) return id + ".mp3";
    }
    const sr = 8000, n = Math.floor(sr * dur), data = Buffer.alloc(n * 2), b = Buffer.alloc(44 + data.length);
    b.write("RIFF", 0); b.writeUInt32LE(36 + data.length, 4); b.write("WAVE", 8);
    b.write("fmt ", 12); b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22);
    b.writeUInt32LE(sr, 24); b.writeUInt32LE(sr * 2, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34);
    b.write("data", 36); b.writeUInt32LE(data.length, 40); data.copy(b, 44);
    fs.writeFileSync(path.join(DIR, id + ".wav"), b);
    return id + ".wav";
}

// Возвращает имя аудиофайла в DIR (mp3 или wav). Голос из игры (Polly) игнорируем — берём из настроек.
async function generate(text, gameVoice, rate) {
    text = String(text || " ").slice(0, 900);
    fs.mkdirSync(DIR, { recursive: true });
    const id = u.makeToken(16);
    const wav = path.join(DIR, id + ".wav");
    const order = ENGINE === "auto" ? ["silero", "piper", "espeak"] : [ENGINE];

    for (const eng of order) {
        if (eng === "silero") {
            if (await silero.start() && await silero.synth({ text, speaker: sileroSpeaker(), out: wav })) { const n = await toAudio(id); if (n) return n; }
        } else if (eng === "piper") {
            if (await piperSynth(text, piperVoice(), wav)) { const n = await toAudio(id); if (n) return n; }
        } else if (eng === "espeak" && ESPEAK) {
            let speed = 175; const m = /(\d+)%/.exec(String(rate || ""));
            if (m) speed = Math.max(80, Math.min(400, Math.round(175 * parseInt(m[1], 10) / 100)));
            const ok = await run(ESPEAK, ["-v", espeakVoice(VOICE), "-s", String(speed), "-w", wav, text || " "]);
            if (ok) { const n = await toAudio(id); if (n) return n; }
        }
    }
    return silence(id, text);
}

module.exports = { generate, DIR };
