"use strict";
//
// LocalBox — поиск ffmpeg. Раньше искали ТОЛЬКО в PATH системы, что на Windows оказалось хрупко
// (winget иногда ставит его так, что PATH-детект не срабатывает). Теперь сначала смотрим свой
// портативный бинарник в repo-root/runtime/ (тот же каталог, куда можно положить портативный
// node — см. launcher/setup/engine.py find_node()), и только потом — PATH.
//
// Кладётся руками: скачай ffmpeg (https://ffmpeg.org/download.html, для Windows — сборка с
// gyan.dev/ffmpeg/builds), возьми ffmpeg.exe (Windows) / ffmpeg (Linux/macOS) из bin/ архива и
// положи в runtime/ffmpeg.exe (или runtime/ffmpeg) в корне проекта.
//

const fs = require("fs");
const path = require("path");
const cp = require("child_process");

const REPO_ROOT = path.join(__dirname, "..", "..");
const RUNTIME_DIR = path.join(REPO_ROOT, "runtime");
const EXE = process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg";

const BUNDLED_CANDIDATES = [path.join(RUNTIME_DIR, EXE), path.join(RUNTIME_DIR, "bin", EXE)];

function bundledPath() {
    for (const p of BUNDLED_CANDIDATES) {
        if (fs.existsSync(p)) return p;
    }
    return null;
}

// Находит ffmpeg в PATH системы и возвращает ПОЛНЫЙ АБСОЛЮТНЫЙ путь к нему (не просто true/false
// и не голое имя "ffmpeg"!). Это важно: server/lib/render.js спавнит ffmpeg с опцией cwd (батчи
// рендера — короткие относительные пути к сэмплам). Если передать execFile ГОЛОЕ имя "ffmpeg"
// вместе с cwd, отличным от того, где реально лежит бинарник, Node/Windows временами не могут его
// разрешить и падают с малопонятным "spawn UNKNOWN" (замечено на реальном железе пользователя).
// Абсолютный путь снимает всю двусмысленность — cwd тогда влияет только на относительные
// аргументы команды, а не на поиск самого исполняемого файла.
function resolveOnPath() {
    try {
        if (process.platform === "win32") {
            const out = cp.execFileSync("where", ["ffmpeg"], { encoding: "utf8" });
            return out.split(/\r?\n/).map((s) => s.trim()).find(Boolean) || null;
        }
        // Linux/macOS: "command -v" — единственный переносимый способ узнать сразу и "есть ли
        // команда", и её полный путь одной проверкой (sh есть — не Windows).
        const out = cp.execFileSync("sh", ["-lc", "command -v ffmpeg"], { encoding: "utf8" });
        return out.trim() || null;
    } catch {
        return null; // не найден (или, на Unix, найден, но без прав запуска — тоже null, это ОК)
    }
}

// Приоритет выбора:
//   1) системный ffmpeg из PATH, если его путь ЧИСТЫЙ (без не-ASCII/кириллицы) — берём его;
//   2) иначе (путь с кириллицей ЛИБО в PATH не найден) — берём свой runtime/ffmpeg[.exe];
//   3) если runtime-бинарника нет — откатываемся на PATH (пусть даже путь не-ASCII: на Windows
//      запуск идёт через cmd.exe, см. render.js, что обходит проблему не-ASCII пути), либо null.
const bundled = bundledPath();
const onPath = resolveOnPath();                                   // абсолютный путь из PATH или null
const onPathAscii = onPath && !/[^\x00-\x7F]/.test(onPath);       // путь без кириллицы/не-ASCII?

let FFMPEG, SOURCE;
if (onPathAscii) {
    FFMPEG = onPath; SOURCE = "системный (PATH, " + onPath + ")";
} else if (bundled) {
    FFMPEG = bundled; SOURCE = "свой (" + bundled + ")" + (onPath ? " — путь системного не-ASCII" : " — в PATH не найден");
} else if (onPath) {
    FFMPEG = onPath; SOURCE = "системный (PATH, не-ASCII путь → запуск через cmd, " + onPath + ")";
} else {
    FFMPEG = null; SOURCE = null;
}

// Подробный отчёт — печатаем при старте, чтобы при жалобе "не находит" не пришлось гадать:
// видно, какие именно пути проверялись и что там реально есть на диске.
function diagnose() {
    const lines = [];
    lines.push("[dodo] диагностика ffmpeg (server/lib/ffmpeg.js, платформа " + process.platform + "):");
    lines.push("[dodo]   REPO_ROOT = " + REPO_ROOT);
    for (const p of BUNDLED_CANDIDATES) {
        lines.push("[dodo]   " + p + " — " + (fs.existsSync(p) ? "ЕСТЬ" : "нет"));
    }
    lines.push("[dodo]   поиск в PATH (" + (process.platform === "win32" ? "where ffmpeg" : "command -v ffmpeg") + "): "
        + (onPath ? (onPath + (onPathAscii ? "" : " — не-ASCII путь!")) : "НЕ найден"));
    lines.push("[dodo]   итог: " + (FFMPEG ? ("используется " + SOURCE + " → \"" + FFMPEG + "\"") : "ffmpeg НЕ найден нигде"));
    return lines;
}

module.exports = { FFMPEG, SOURCE, RUNTIME_DIR, diagnose };
