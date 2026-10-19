#!/usr/bin/env python3
"""Общие операции установки для Windows и Linux. GUI находится в wizard.py."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from client_ru import install_client as install_russian_client, release_info as russian_release_info
from client_download import install_client as install_web_client

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "launcher"))
from setup.dodo import songs_directory, import_dodo
from setup.npm import invocation as npm_invocation
PIPER_VOICES = ("ru_RU-denis-medium", "ru_RU-dmitri-medium", "ru_RU-irina-medium", "ru_RU-ruslan-medium")
ROOT_FILES = ("LICENSE", "README.md", "start-server.sh", "start-server.bat", "setup.sh", "install.bat", "version.json")


def payload_files(source=SOURCE):
    for name in ROOT_FILES:
        if (source / name).is_file():
            yield Path(name)
    for folder in ("launcher", "server", "installer", "tools", "docs"):
        for path in sorted((source / folder).rglob("*")):
            relative = path.relative_to(source)
            if any(part in (".git", "__pycache__", "node_modules", "storage", "cache", "render", "build", "dist") for part in relative.parts):
                continue
            if relative.parts[:3] == ("server", "tts", "piper"):
                continue
            if any(part in ("test", "tests") for part in relative.parts) or path.name.startswith("test_") or path.name == "testing.md":
                continue
            if path.name in ("config.json", "localbox-settings.json", "install-paths.json", "setup-options.ini"):
                continue
            if path.is_file() and not path.is_symlink() and path.suffix in (".py", ".js", ".json", ".md", ".txt", ".ps1", ".sh", ".nsi"):
                yield relative


def read_json(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Ожидался объект JSON: {path}")
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def deploy(source, target, log=print):
    source, target = Path(source).resolve(), Path(target).expanduser().resolve()
    if target == source:
        return
    if target.exists() and any(target.iterdir()) and not (target / "server" / "server.js").is_file():
        raise ValueError("Выберите пустую папку или существующую установку LocalBox.")
    target.mkdir(parents=True, exist_ok=True)
    for relative in payload_files(source):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)
    for obsolete in ("launcher/setup/porthole.py", "launcher/test_porthole.py", "docs/porthole.md"):
        (target / obsolete).unlink(missing_ok=True)
    for name in ("start-server.sh", "setup.sh", "installer/linux-deps.sh", "installer/askpass.sh"):
        if (target / name).exists():
            (target / name).chmod(0o755)
    log(f"Файлы LocalBox: {target}")



def run(command, log=print, cwd=None, env=None, input_text=None):
    log("→ " + " ".join(str(part) for part in command))
    # npm.cmd требует cmd.exe; остальные программы запускаются без оболочки.
    shell = os.name == "nt" and str(command[0]).lower().endswith((".cmd", ".bat"))
    if input_text is not None:
        result = subprocess.run([str(c) for c in command], cwd=cwd, env=env, shell=shell,
                                input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace")
        log(result.stdout)
        if result.stderr:
            log(result.stderr)
        if result.returncode:
            raise RuntimeError(f"Команда завершилась с ошибкой {result.returncode}: {command[0]}")
        return
    process = subprocess.Popen([str(c) for c in command], cwd=cwd, env=env, shell=shell,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace")
    for line in process.stdout:
        log(line.rstrip())
    if process.wait() != 0:
        raise RuntimeError(f"Команда завершилась с ошибкой {process.returncode}: {command[0]}")


def download(url, target, log=print):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    log("Загрузка: " + url)
    partial = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
        if not partial.stat().st_size:
            raise RuntimeError("Скачан пустой файл: " + url)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def tts_install(target, runtime_dir, tts, voices, python=sys.executable, log=print):
    if tts in ("none", "espeak"):
        return {"tts_engine": "silent" if tts == "none" else "espeak", "tts_voice": "" if tts == "none" else "ru"}
    invalid = set(voices) - set(PIPER_VOICES)
    if invalid or (tts in ("piper", "both") and not voices):
        raise ValueError("Выберите хотя бы один поддерживаемый голос Piper.")
    venv = runtime_dir / "tts"
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    if not py.is_file():
        run([python, "-m", "venv", str(venv)], log, env=env)
    run([str(py), "-m", "pip", "install", "--upgrade", "pip"], log, env=env)
    folder = target / "server" / "tts"
    if tts in ("silero", "both"):
        run([str(py), "-m", "pip", "install", "torch", "--index-url", "https://download.pytorch.org/whl/cpu"], log, env=env)
        run([str(py), "-m", "pip", "install", "numpy"], log, env=env)
        model = folder / "v4_ru.pt"
        if not model.is_file():
            download("https://models.silero.ai/models/tts/ru/v4_ru.pt", model, log)
    if tts in ("piper", "both"):
        run([str(py), "-m", "pip", "install", "piper-tts>=1.3,<2"], log, env=env)
        for voice in voices:
            run([str(py), "-m", "piper.download_voices", voice, "--data-dir", str(folder / "piper")], log, env=env)
    # Проверяем настоящим синтезом до записи настроек. Модель и библиотеки должны работать офлайн.
    with tempfile.TemporaryDirectory(prefix="localbox-tts-check-") as temp:
        sample = Path(temp) / "sample.wav"
        if tts in ("silero", "both"):
            run([str(py), str(folder / "silero_worker.py"), "--sample", "eugene", str(sample)], log, env=env)
            if not sample.exists() or sample.stat().st_size < 100:
                raise RuntimeError("Silero не создал тестовый звук.")
        if tts in ("piper", "both"):
            for voice in voices:
                sample.unlink(missing_ok=True)
                run([str(py), "-m", "piper", "-m", voice, "--data-dir", str(folder / "piper"), "-f", str(sample)],
                    log, env=env, input_text="Привет, это LocalBox.\n")
                if not sample.exists() or sample.stat().st_size < 100:
                    raise RuntimeError(f"Piper {voice} не создал тестовый звук.")
    return {"tts_engine": "piper" if tts in ("piper", "both") else "silero",
            "tts_voice": voices[0] if tts in ("piper", "both") else "eugene", "tts_python": str(py)}


def install(target, runtime_dir=None, tts="piper", voices=None, game=None, dodo=False,
            russian=False, source=SOURCE, system_deps=True, log=print, cheat_content=None):
    target = Path(target).expanduser().resolve()
    runtime_dir = Path(runtime_dir).expanduser().resolve() if runtime_dir else target / "runtime"
    voices = list(voices if voices is not None else [PIPER_VOICES[0]])
    if tts not in ("none", "piper", "silero", "both", "espeak"):
        raise ValueError("Неизвестный движок TTS.")
    if tts in ("piper", "both") and (not voices or set(voices) - set(PIPER_VOICES)):
        raise ValueError("Выберите хотя бы один поддерживаемый голос Piper.")
    if game:
        songs_directory(game)  # Проверяем путь до загрузки зависимостей.
        dodo = True
    if cheat_content:
        cheat_content = str(Path(cheat_content).expanduser().resolve())
        if not Path(cheat_content).is_dir():
            raise ValueError("Папка с играми для читов не найдена.")
    russian_release = russian_release_info() if russian else None
    deploy(source, target, log)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_json(target / "launcher" / "install-paths.json")
    manifest.update(runtime=str(runtime_dir))
    write_json(target / "launcher" / "install-paths.json", manifest)
    if system_deps:
        if os.name == "nt":
            raise RuntimeError("Windows-зависимости устанавливает windows-bootstrap.ps1 до запуска Python.")
        run(["bash", str(target / "installer" / "linux-deps.sh"), "--full", tts], log,
            env={**os.environ, "LOCALBOX_SOURCE": str(target), "LOCALBOX_RUNTIME": str(runtime_dir)})
        manifest = read_json(target / "launcher" / "install-paths.json")
    extra = [runtime_dir, runtime_dir / "bin", runtime_dir / "node", runtime_dir / "git" / "cmd",
             runtime_dir / "git" / "ucrt64" / "bin", runtime_dir / "git" / "mingw64" / "bin",
             runtime_dir / "ffmpeg" / "bin"]
    selected = [Path(manifest[name]).parent for name in ("node", "npm", "git", "ffmpeg", "openssl", "mkcert")
                if manifest.get(name) and Path(manifest[name]).is_file()]
    extra = selected + extra
    env = {**os.environ, "PATH": os.pathsep.join(str(p) for p in extra) + os.pathsep + os.environ.get("PATH", ""),
           "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm", path=env["PATH"])
    git = shutil.which("git", path=env["PATH"])
    if (not npm and not manifest.get('npm_cli')) or not git:
        raise RuntimeError("Не найдены npm или git после установки зависимостей.")
    for name in ("node", "npm", "git", "ffmpeg", "openssl", "mkcert"):
        found = shutil.which("npm.cmd" if name == "npm" and os.name == "nt" else name, path=env["PATH"])
        if found:
            manifest[name] = found
    manifest.setdefault("python", sys.executable)
    write_json(target / "launcher" / "install-paths.json", manifest)
    command = "ci" if (target / "server" / "package-lock.json").is_file() else "install"
    npm_command = npm_invocation(manifest.get('node'), npm, manifest.get('npm_cli'))
    run([*npm_command, command, "--omit=dev"], log, cwd=str(target / "server"), env=env)
    install_web_client(target, runtime_dir, source=source, log=log)
    if russian:
        install_russian_client(target, russian_release, log=log)
    if game:
        import_dodo(game, target, log)
    options = read_json(target / "launcher" / "localbox-settings.json")
    options.update(tts_install(target, runtime_dir, tts, voices, log=log))
    options.update(dodo_render=bool(dodo))
    if cheat_content is not None:
        options["cheat_content_dir"] = cheat_content
    if game:
        options["jackbox10_path"] = str(Path(game).expanduser().resolve())
    write_json(target / "launcher" / "localbox-settings.json", options)
    if os.name != "nt":
        applications = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications"
        applications.mkdir(parents=True, exist_ok=True)
        # Desktop Exec имеет свою грамматику: экранируем кавычки, обратную косую черту и %.
        executable = str(target / "start-server.sh").replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
        (applications / "localbox.desktop").write_text(
            f'[Desktop Entry]\nType=Application\nName=LocalBox\nExec="{executable}"\nTerminal=true\nCategories=Game;\n', encoding="utf-8")
    log(f"Готово. Запуск: {target / ('start-server.bat' if os.name == 'nt' else 'start-server.sh')}")
    return target


def main():
    parser = argparse.ArgumentParser(description="Установщик LocalBox")
    parser.add_argument("--target", required=True)
    parser.add_argument("--runtime")
    parser.add_argument("--tts", choices=("none", "piper", "silero", "both", "espeak"), default="piper")
    parser.add_argument("--voices", default=PIPER_VOICES[0])
    parser.add_argument("--game")
    parser.add_argument("--cheat-content", help="Папка со всеми играми Jackbox; пустое значение — поиск в Steam")
    parser.add_argument("--dodo", action="store_true")
    parser.add_argument("--ru", action="store_true")
    parser.add_argument("--skip-system-deps", action="store_true")
    args = parser.parse_args()
    try:
        install(args.target, args.runtime, args.tts, [v for v in args.voices.split(",") if v], args.game,
                args.dodo, args.ru, system_deps=not args.skip_system_deps, cheat_content=args.cheat_content)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Установка не завершена: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
