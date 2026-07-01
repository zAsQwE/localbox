#!/usr/bin/env python3
#
#   LocalBox - local private server for Jackbox games
#   Copyright (C) 2026 LocalBox contributors
#   Licensed under the GNU Affero General Public License v3 or later.
#
"""GUI-лаунчер LocalBox: один экран — задать адрес сервера, выдать сертификат/права, запустить движок.

Движок (engine/server.js) обслуживает все игры. Запуск:
    python3 launcher/localbox_launcher.py        # GUI
    ./localbox                                    # из корня проекта (обёртка)
    python3 launcher/localbox_launcher.py --check # проверка окружения без GUI
"""

import os
import queue
import sys
import threading

from setup import platform as plat
from setup import certs, engine


def run_gui():
    import tkinter as tk
    from tkinter import ttk, scrolledtext

    root = tk.Tk()
    root.title("LocalBox")
    root.geometry("680x560")
    root.minsize(620, 520)

    # --- стиль (тёмная палитра + аккуратные отступы) ---
    BG, CARD, FG, MUTED, ACC = "#15131f", "#221d33", "#f2f1f7", "#9c93b8", "#6a5bff"
    root.configure(bg=BG)
    st = ttk.Style()
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure(".", background=BG, foreground=FG, fieldbackground=CARD, font=("", 10))
    st.configure("Card.TFrame", background=CARD)
    st.configure("TLabel", background=BG, foreground=FG)
    st.configure("Card.TLabel", background=CARD, foreground=FG)
    st.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("", 9))
    st.configure("Title.TLabel", background=BG, foreground=FG, font=("", 22, "bold"))
    st.configure("TEntry", fieldbackground="#2a2440", foreground=FG, insertcolor=FG)
    st.configure("TButton", padding=8)
    st.configure("Accent.TButton", padding=10)
    st.map("Accent.TButton", background=[("!disabled", ACC), ("active", "#7c6cff")],
           foreground=[("!disabled", "#ffffff")])

    log_q: "queue.Queue[str]" = queue.Queue()
    log = lambda m: log_q.put(str(m))  # noqa: E731
    state = {"engine": None}

    outer = ttk.Frame(root, padding=18)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)

    # Заголовок
    ttk.Label(outer, text="LocalBox", style="Title.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(outer, text=f"Локальный сервер Jackbox · все игры · {plat.os_name()}",
              style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 12))

    # Карточка настроек
    card = ttk.Frame(outer, style="Card.TFrame", padding=14)
    card.grid(row=2, column=0, sticky="ew")
    card.columnconfigure(1, weight=1)

    ttk.Label(card, text="Адрес сервера:", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
    url_var = tk.StringVar(value=plat.local_ip())
    ttk.Entry(card, textvariable=url_var).grid(row=0, column=1, sticky="ew", pady=4)
    ttk.Label(card, text="localhost — играть на этом ПК; IP сети — играть с друзьями/телефонов.",
              style="Card.TLabel", foreground=MUTED).grid(row=1, column=1, sticky="w")

    status_var = tk.StringVar(value="● остановлен")
    status_lbl = ttk.Label(card, textvariable=status_var, style="Card.TLabel", foreground="#e23b6d")
    status_lbl.grid(row=0, column=2, sticky="e", padx=(12, 0))

    # Кнопки
    btns = ttk.Frame(outer)
    btns.grid(row=3, column=0, sticky="w", pady=12)
    cert_btn = ttk.Button(btns, text="1. Сертификат")
    cert_btn.pack(side="left")
    ports_btn = ttk.Button(btns, text="2. Разрешить порты")
    ports_btn.pack(side="left", padx=6)
    start_btn = ttk.Button(btns, text="▶ Запустить", style="Accent.TButton")
    start_btn.pack(side="left", padx=(12, 0))
    stop_btn = ttk.Button(btns, text="■ Остановить", state="disabled")
    stop_btn.pack(side="left", padx=6)

    # Лог
    log_w = scrolledtext.ScrolledText(outer, height=16, wrap="word", state="disabled",
                                      bg="#0f0d18", fg="#cfc8e6", insertbackground=FG,
                                      relief="flat", font=("monospace", 9))
    log_w.grid(row=4, column=0, sticky="nsew", pady=(6, 0))
    outer.rowconfigure(4, weight=1)

    def drain():
        while not log_q.empty():
            log_w.configure(state="normal")
            log_w.insert("end", log_q.get_nowait() + "\n")
            log_w.see("end")
            log_w.configure(state="disabled")
        root.after(150, drain)

    def in_thread(fn):
        threading.Thread(target=fn, daemon=True).start()

    def on_cert():
        cert_btn.configure(state="disabled")
        host = url_var.get().strip() or "localhost"
        def w():
            certs.ensure_cert(host, log=log, extra_names=[plat.local_ip()], force=True)
            root.after(0, lambda: cert_btn.configure(state="normal"))
        in_thread(w)

    def on_ports():
        ports_btn.configure(state="disabled")
        def w():
            engine.allow_privileged_ports(log=log)
            root.after(0, lambda: ports_btn.configure(state="normal"))
        in_thread(w)

    def on_start():
        host = url_var.get().strip() or "localhost"
        start_btn.configure(state="disabled")
        def w():
            if not engine.write_config(host, log=log):
                root.after(0, lambda: start_btn.configure(state="normal")); return
            if not engine.deps_installed() and not engine.install_deps(log=log):
                root.after(0, lambda: start_btn.configure(state="normal")); return
            proc = engine.EngineProcess(host, on_log=log)
            if proc.start():
                state["engine"] = proc
                root.after(0, lambda: (stop_btn.configure(state="normal"),
                                       status_var.set("● работает"), status_lbl.configure(foreground="#1fae8c")))
            else:
                root.after(0, lambda: start_btn.configure(state="normal"))
        in_thread(w)

    def on_stop():
        if state["engine"]:
            state["engine"].stop(); state["engine"] = None
        start_btn.configure(state="normal"); stop_btn.configure(state="disabled")
        status_var.set("● остановлен"); status_lbl.configure(foreground="#e23b6d")

    cert_btn.configure(command=on_cert)
    ports_btn.configure(command=on_ports)
    start_btn.configure(command=on_start)
    stop_btn.configure(command=on_stop)

    def on_close():
        on_stop(); root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)

    drain()
    log("Готово. Шаги: 1) Сертификат  2) Разрешить порты (один раз)  3) Запустить.")
    log("В игре Steam: параметр запуска  -jbg.config serverUrl=" + url_var.get())
    if not engine.engine_dir().exists():
        log("ВНИМАНИЕ: папка engine/ не найдена — движок не установлен.")
    root.mainloop()


def check_environment():
    print(f"ОС: {plat.os_name()}")
    print(f"node: {engine.find_node() or 'НЕ найден'}")
    print(f"Движок: {engine.engine_dir()} ({'есть' if engine.engine_dir().exists() else 'НЕТ'})")
    print(f"Зависимости движка: {'установлены' if engine.deps_installed() else 'нет (нужен npm i)'}")
    print(f"Клиент: {engine.client_dir()} ({'есть' if engine.client_dir().exists() else 'НЕТ'})")
    print(f"Локальный IP: {plat.local_ip()}")
    print(f"Права администратора: {plat.has_admin()}")


def parse_cli(argv):
    o = {"check": False, "server": False, "no_web": False, "ip": None}
    for a in argv:
        if a == "--check":
            o["check"] = True
        elif a in ("--server", "--no-gui", "-no-gui", "--headless"):
            o["server"] = True
        elif a in ("-no-web", "--no-web"):
            o["no_web"] = True
            o["server"] = True
        elif a.startswith("-ip=") or a.startswith("--ip="):
            o["ip"] = a.split("=", 1)[1]
            o["server"] = True
    return o


def run_server_cli(ip, no_web):
    """Серверный режим без GUI: серт + права на порты + запуск движка, лог в терминал."""
    import time
    ip = ip or plat.local_ip()
    print(f"== LocalBox (сервер) == адрес: {ip} | веб-клиент: {'выкл' if no_web else 'вкл'}")

    if not engine.engine_dir().exists():
        print("Движок не найден (engine/). Скачайте исходники целиком."); sys.exit(1)
    if not engine.find_node():
        print("Node.js не найден. Установите node или положите его в ./runtime/. См. README."); sys.exit(1)

    # 1) сертификат
    certs.ensure_cert(ip, log=print, extra_names=[plat.local_ip(), "localhost"], force=False)
    # 2) конфиг движка
    engine.write_config(ip, log=print)
    # 3) права на порты 80/443
    if not plat.has_admin():
        print("Порты 80/443 требуют прав. Выдаю node право (нужен sudo/pkexec)…")
        engine.allow_privileged_ports(log=print)
        print("Если не сработало — вручную: sudo setcap cap_net_bind_service=+ep \"$(command -v node)\"")
    # 4) зависимости
    if not engine.deps_installed() and not engine.install_deps(log=print):
        print("Не удалось установить зависимости движка."); sys.exit(1)
    # 5) запуск (блокирующе, до Ctrl+C)
    proc = engine.EngineProcess(ip, on_log=print, no_web=no_web)
    if not proc.start():
        sys.exit(1)
    print("Сервер запущен. Игра: -jbg.config serverUrl=" + ip + "   (Ctrl+C — остановить)")
    try:
        while proc.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nОстанавливаю…")
        proc.stop()


def _no_display():
    return plat.is_linux() and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")


def main():
    o = parse_cli(sys.argv[1:])
    if o["check"]:
        check_environment()
        return
    # Серверный/headless режим: явный флаг или нет графической сессии.
    if o["server"] or _no_display():
        run_server_cli(o["ip"], o["no_web"])
        return
    try:
        run_gui()
    except Exception as e:  # noqa: BLE001
        print(f"Не удалось открыть GUI ({e}). Перехожу в серверный режим.")
        print("Подсказка: GUI требует tkinter (Arch: sudo pacman -S tk) и дисплей.")
        run_server_cli(o["ip"], o["no_web"])


if __name__ == "__main__":
    main()
