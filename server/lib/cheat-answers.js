"use strict";

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");

function text(value) {
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (!value || typeof value !== "object") return "";
    for (const key of ["text", "html", "label", "title", "name", "answer"]) {
        if (typeof value[key] === "string" || typeof value[key] === "number") return String(value[key]);
    }
    return "";
}
function normalize(value) {
    return text(value).replace(/<blank\s*\/?\s*>|\[blank\]|_{2,}/gi, " BLANK ")
        .replace(/<[^>]*>|\[\/?(?:i|b|u|s|br|color|size)(?:=[^\]]*)?\]/gi, "")
        .replace(/&(?:#(x[0-9a-f]+|\d+)|([a-z]+));/gi, (all, num, name) => {
            if (num) { const n = num[0].toLowerCase() === "x" ? parseInt(num.slice(1), 16) : Number(num); return n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : all; }
            return ({ amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " })[name.toLowerCase()] || all;
        }).replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/\s+/g, " ").trim().normalize("NFKC").toUpperCase();
}
function marked(choice) {
    return choice && typeof choice === "object" && ["correct", "isCorrect", "isTrue", "right"].some((k) => choice[k] === true);
}
const DIRECT = /^(correcttext|correctanswer|correctanswers|rightanswer|realanswer|truth|solution)$/i;
function explicitAnswers(obj) {
    const out = [];
    for (const [key, value] of Object.entries(obj)) {
        if (!DIRECT.test(key)) continue;
        for (const item of Array.isArray(value) ? value : [value]) { const t = text(item); if (t) out.push(t); }
    }
    const choices = obj.choices || obj.answers || obj.options;
    if (Array.isArray(choices)) {
        for (const choice of choices) if (marked(choice) && text(choice)) out.push(text(choice));
        // Only explicitly named zero-based index fields, never ambiguous "answer" or "correct" numbers.
        for (const key of ["correctIndex", "correctAnswerIndex", "correctChoiceIndex", "correctIndices"]) {
            for (const index of Array.isArray(obj[key]) ? obj[key] : [obj[key]]) {
                if (Number.isInteger(index) && index >= 0 && index < choices.length && text(choices[index])) out.push(text(choices[index]));
            }
        }
    }
    if (marked(obj) && text(obj)) out.push(text(obj));
    return [...new Map(out.map((t) => [normalize(t), t])).values()];
}
function family(tag) {
    tag = String(tag || "").toLowerCase();
    if (/fibbage|fourbage/.test(tag)) return "fibbage";
    if (/triviadeath/.test(tag)) return "trivia";
    if (/auction|bidiots/.test(tag)) return "auction";
    return "other";
}

class ContentIndex {
    constructor() { this.questions = new Map(); this.ids = new Map(); this.count = 0; }
    add(game, record) {
        const answers = explicitAnswers(record);
        const question = text(record.question || record.questionText || record.QuestionText || record.prompt || record.text);
        if (!answers.length || !normalize(question)) return;
        const item = { question, answers, choices: Array.isArray(record.choices) ? record.choices.map(text).filter(Boolean) : [] };
        const add = (map, key) => { if (!map.has(key)) map.set(key, []); map.get(key).push(item); };
        add(this.questions, game + ":" + normalize(question));
        if (record.id != null) add(this.ids, game + ":" + record.id);
        this.count++;
    }
    loadGame(directory, game) {
        const content = path.join(directory, "content");
        let files; try { files = fs.readdirSync(content, { withFileTypes: true }); } catch { return; }
        for (const file of files) {
            if (file.isFile() && /^(?:TDQuestion.*|TDFinalRound|fibbageshortie|fibbagespecial|finalfibbage)\.jet$/i.test(file.name)) {
                try {
                    const data = JSON.parse(fs.readFileSync(path.join(content, file.name), "utf8"));
                    for (const record of data.content || []) this.add(game, record);
                } catch { /* Missing or unsupported content does not stop the server. */ }
            }
            if (game !== "fibbage" || !file.isDirectory() || !/^(fibbageshortie|fibbagespecial|finalfibbage)$/i.test(file.name)) continue;
            const dir = path.join(content, file.name);
            let entries; try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { continue; }
            for (const entry of entries) {
                if (!entry.isDirectory()) continue;
                try {
                    const data = JSON.parse(fs.readFileSync(path.join(dir, entry.name, "data.jet"), "utf8"));
                    const fields = Object.fromEntries((data.fields || []).map((f) => [f.n, f.v]));
                    this.add(game, { id: entry.name, question: fields.QuestionText, correctText: fields.CorrectText });
                } catch { /* Some entries contain only audio or personal questions. */ }
            }
        }
    }
    lookup(game, obj) {
        const question = text(obj.question || obj.questionText || obj.prompt || obj.text);
        const q = normalize(question);
        let candidates = q ? this.questions.get(game + ":" + q) || [] : [];
        // IDs alone are not enough: a translated game can reuse the English question's ID.
        if (!candidates.length && q && obj.questionId != null) candidates = (this.ids.get(game + ":" + obj.questionId) || []).filter((c) => normalize(c.question) === q);
        const visible = (Array.isArray(obj.choices) ? obj.choices : []).map(text).filter(Boolean);
        const visibleSet = new Set(visible.map(normalize));
        candidates = candidates.filter((c) => !visible.length || !c.choices.length || visible.every((v) => c.choices.some((t) => normalize(t) === normalize(v))));
        const results = candidates.map((c) => c.answers.filter((a) => !visible.length || visibleSet.has(normalize(a))));
        const signatures = new Set(results.map((r) => r.map(normalize).sort().join("\n")));
        return signatures.size === 1 && results.length ? results[0] : [];
    }
}

function steamRoots(env = process.env) {
    if (env.LOCALBOX_CHEAT_CONTENT) return [path.resolve(env.LOCALBOX_CHEAT_CONTENT)];
    const home = os.homedir();
    const roots = [env.LOCALBOX_CHEAT_CONTENT, env.STEAM_PATH,
        path.join(home, ".local/share/Steam"), path.join(home, ".steam/steam"),
        path.join(home, ".var/app/com.valvesoftware.Steam/.local/share/Steam"),
        path.join(home, "Library/Application Support/Steam")];
    for (const key of ["ProgramFiles(x86)", "ProgramFiles"]) if (env[key]) roots.push(path.join(env[key], "Steam"));
    const libs = [...roots.filter(Boolean)];
    for (const root of libs) {
        try {
            const vdf = fs.readFileSync(path.join(root, "steamapps/libraryfolders.vdf"), "utf8");
            for (const match of vdf.matchAll(/"path"\s*"([^"]+)"/g)) roots.push(match[1].replace(/\\\\/g, "\\"));
        } catch { /* Not a Steam installation. */ }
    }
    return [...new Set(roots.filter(Boolean).map((r) => path.resolve(r)))];
}
function loadInstalledContent(roots = steamRoots()) {
    const index = new ContentIndex(), loaded = new Set();
    const load = (dir) => {
        if (loaded.has(dir)) return; loaded.add(dir);
        const game = family(path.basename(dir));
        if (game === "fibbage" || game === "trivia") index.loadGame(dir, game);
    };
    const games = (root) => {
        for (const dir of [root, path.join(root, "games")]) {
            load(dir);
            try { for (const entry of fs.readdirSync(dir, { withFileTypes: true })) if (entry.isDirectory()) load(path.join(dir, entry.name)); } catch { /* optional */ }
        }
    };
    for (const root of roots) {
        games(root);
        for (const common of [root, path.join(root, "steamapps/common")]) {
            try {
                for (const entry of fs.readdirSync(common, { withFileTypes: true })) {
                    if (entry.isDirectory()) games(path.join(common, entry.name));
                }
            } catch { /* optional */ }
        }
    }
    return index;
}

function analyze(entities, appTag, index = new ContentIndex()) {
    const answers = [], prices = [], game = family(appTag);
    for (const [entity, entry] of Object.entries(entities)) {
        const body = entry.body || entry;
        const value = body.val;
        const walk = (obj, source, depth) => {
            if (!obj || typeof obj !== "object" || depth > 16) return;
            if (Array.isArray(obj)) { obj.forEach((v, i) => walk(v, source + "[" + i + "]", depth + 1)); return; }
            const direct = explicitAnswers(obj);
            const fromContent = !direct.length && (game === "fibbage" || game === "trivia") ? index.lookup(game, obj) : [];
            if (direct.length || fromContent.length) answers.push({ entity, source, question: text(obj.question || obj.prompt || obj.text), texts: direct.length ? direct : fromContent, method: direct.length ? "game" : "content" });
            if (game === "auction") {
                // Bidiots sends each player appraisals as info: [{title, value}]. Collect all of them.
                const title = text(obj.title || obj.artworkTitle || obj.paintingTitle);
                const amount = obj.realPrice ?? obj.actualPrice ?? obj.artworkValue ?? obj.value;
                if (title && typeof amount === "number" && Number.isFinite(amount) && amount >= 0) prices.push({ entity, title, value: amount });
            }
            for (const [key, v] of Object.entries(obj)) {
                if (direct.length && ["choices", "answers", "options"].includes(key)) continue;
                walk(v, source + "." + key, depth + 1);
            }
        };
        // Primitive entities named explicitly as an answer are also supported.
        if (DIRECT.test(entity.split(":").at(-1)) && text(value)) answers.push({ entity, source: entity, question: "", texts: [text(value)], method: "game" });
        walk(value, entity, 0);
    }
    const uniquePrices = new Map();
    for (const price of prices) {
        const key = normalize(price.title);
        if (!uniquePrices.has(key)) uniquePrices.set(key, price);
        else if (uniquePrices.get(key).value !== price.value) uniquePrices.set(key, { ...price, conflicting: true });
    }
    return { answers, prices: [...uniquePrices.values()].filter((p) => !p.conflicting), contentCount: index.count };
}

module.exports = { text, normalize, explicitAnswers, ContentIndex, steamRoots, loadInstalledContent, analyze };
