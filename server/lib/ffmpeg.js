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

// Проверка "ffmpeg есть в PATH системы" — на Windows через where (то же самое, чем его находит
// start-server.bat), иначе прямым запуском (без шелла — на Windows нет sh).
function foundOnPath() {
    try {
        if (process.platform === "win32") cp.execFileSync("where", ["ffmpeg"], { stdio: "ignore" });
        else cp.execFileSync("ffmpeg", ["-version"], { stdio: "ignore" });
        return true;
    } catch (e) {
        if (process.platform === "win32") return false; // where ничего не нашёл
        return !!(e && e.code && e.code !== "ENOENT"); // запустился, но упал — команда есть
    }
}

const bundled = bundledPath();
const onPath = !bundled && foundOnPath(); // PATH проверяем, только если бандл не нашли (не нужно дважды)
// FFMPEG — что передавать в execFile/execFileSync как имя команды: путь к своему бинарнику,
// просто "ffmpeg" (если он в PATH), либо null (нигде не нашли).
const FFMPEG = bundled || (onPath ? "ffmpeg" : null);
const SOURCE = bundled ? "свой (" + bundled + ")" : (FFMPEG ? "системный (PATH)" : null);

// Подробный отчёт — печатаем при старте, чтобы при жалобе "не находит" не пришлось гадать:
// видно, какие именно пути проверялись и что там реально есть на диске.
function diagnose() {
    const lines = [];
    lines.push("[dodo] диагностика ffmpeg (server/lib/ffmpeg.js, платформа " + process.platform + "):");
    lines.push("[dodo]   REPO_ROOT = " + REPO_ROOT);
    for (const p of BUNDLED_CANDIDATES) {
        lines.push("[dodo]   " + p + " — " + (fs.existsSync(p) ? "ЕСТЬ" : "нет"));
    }
    lines.push("[dodo]   поиск в PATH (" + (process.platform === "win32" ? "where ffmpeg" : "ffmpeg -version") + "): "
        + (bundled ? "не проверялся (уже нашли свой)" : (onPath ? "найден" : "НЕ найден")));
    lines.push("[dodo]   итог: " + (FFMPEG ? ("используется " + SOURCE + " → \"" + FFMPEG + "\"") : "ffmpeg НЕ найден нигде"));
    return lines;
}

module.exports = { FFMPEG, SOURCE, RUNTIME_DIR, diagnose };
