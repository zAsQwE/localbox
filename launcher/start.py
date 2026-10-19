#!/usr/bin/env python3
"""Общее меню start-server.bat / start-server.sh."""

import os
import subprocess
import sys
from pathlib import Path

from setup import settings, runtime, tts_catalog, console


def choose(title, options, default=0, read=input, write=print):
    write("\n" + title)
    for index, text in enumerate(options, 1):
        write(f"  [{index}] {text}")
    while True:
        value = read(f"Выберите 1–{len(options)} [Enter = {default+1}]: ").strip()
        if not value:
            return default
        if value.isdecimal() and 1 <= int(value) <= len(options):
            return int(value) - 1
        write("Введите номер из списка.")


def menu(cfg, read=input, write=print):
    gui = choose("Запускать GUI?", ["Да — открыть лаунчер", "Нет — сервер в консоли"], read=read, write=write) == 0
    dodo = choose("Поддержка Додо Ре Ми", ["Без поддержки", "С поддержкой"],
                  default=int(bool(cfg.get("dodo_render"))), read=read, write=write) == 1
    write("\nПроверяю установленные голоса…")
    voices = tts_catalog.installed_voices(cfg)
    choices = [{"engine": "silent", "voice": "", "label": "Без озвучки"}, *voices]
    default = next((i for i, voice in enumerate(choices)
                    if (voice["engine"], voice["voice"]) == (cfg.get("tts_engine"), cfg.get("tts_voice"))),
                   1 if voices else 0)
    if not voices:
        write("Готовых голосов нет. Установите TTS через setup; запуск доступен без озвучки.")
    selected = choices[choose("Озвучка для Города злых рифм и других игр", [v["label"] for v in choices],
                              default=default, read=read, write=write)]
    cfg.update(dodo_render=dodo, tts_engine=selected["engine"], tts_voice=selected["voice"])
    return gui


def main(argv=None):
    runtime.activate()
    console.configure()
    args = list(sys.argv[1:] if argv is None else argv)
    interactive = "--interactive" in args or (not args and sys.stdin.isatty())
    args = [arg for arg in args if arg != "--interactive"]
    env = os.environ.copy()
    if interactive:
        cfg = settings.load()
        try:
            gui = menu(cfg)
        except (EOFError, KeyboardInterrupt):
            print("\nЗапуск отменён.")
            return 0
        if not settings.save(cfg):
            print("Не удалось сохранить настройки запуска.")
            return 1
        env["LOCALBOX_DODO"] = "1" if cfg["dodo_render"] else "0"
        if not any(arg in ("--gui", "--server", "--headless", "--no-gui") or arg.startswith(("-ip=", "--ip=")) for arg in args):
            args.append("--gui" if gui else "--server")
    launcher = Path(__file__).with_name("localbox_launcher.py")
    try:
        return subprocess.call([sys.executable, str(launcher), *args], env=env)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
