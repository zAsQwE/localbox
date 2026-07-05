#!/usr/bin/env python3
#
#   LocalBox - local private server for Jackbox games
#   Copyright (C) 2026 LocalBox contributors
#   Licensed under the GNU Affero General Public License v3 or later.
#
"""GUI-лаунчер LocalBox: один экран — задать адрес сервера, выдать сертификат/права, запустить движок.

Движок (server/server.js) обслуживает все игры. Запуск:
    python3 launcher/localbox_launcher.py        # GUI
    ./localbox                                    # из корня проекта (обёртка)
    python3 launcher/localbox_launcher.py --check # проверка окружения без GUI
"""

import os
import queue
import sys
import threading

from setup import platform as plat
from setup import certs, engine, settings, tts_preview


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
    st.configure("Card.TCheckbutton", background=CARD, foreground=FG, indicatorcolor="#2a2440")
    st.map("Card.TCheckbutton", background=[("active", CARD)], foreground=[("!disabled", FG)],
           indicatorcolor=[("selected", ACC)])
    st.configure("TCombobox", fieldbackground="#2a2440", background=CARD, foreground=FG,
                 arrowcolor=FG, bordercolor="#3a3352", padding=4)
    st.map("TCombobox", fieldbackground=[("readonly", "#2a2440")], foreground=[("readonly", FG)],
           selectbackground=[("readonly", "#2a2440")], selectforeground=[("readonly", FG)])
    root.option_add("*TCombobox*Listbox.background", "#2a2440")
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACC)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

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
    settings_btn = ttk.Button(btns, text="⚙ Настройки")
    settings_btn.pack(side="left", padx=(12, 0))

    # Лог
    log_w = scrolledtext.ScrolledText(outer, height=16, wrap="word", state="disabled",
                                      bg="#0f0d18", fg="#cfc8e6", insertbackground=FG,
                                      relief="flat", font=("monospace", 9))
    log_w.grid(row=4, column=0, sticky="nsew", pady=(6, 0))
    outer.rowconfigure(4, weight=1)

    def drain():
        if not log_q.empty():
            log_w.configure(state="normal")
            n = 0
            while not log_q.empty() and n < 300:  # не больше 300 строк за тик — чтобы GUI не вис
                log_w.insert("end", log_q.get_nowait() + "\n")
                n += 1
            # ограничиваем историю лога (иначе виджет разрастается и всё лагает)
            total = int(log_w.index("end-1c").split(".")[0])
            if total > 600:
                log_w.delete("1.0", f"{total - 600}.0")
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

    def open_settings():
        win = tk.Toplevel(root)
        win.title("Настройки LocalBox")
        win.configure(bg=BG)
        win.geometry("560x520")
        win.minsize(520, 480)
        win.transient(root)
        cfg = settings.load()
        dl_var = tk.BooleanVar(value=cfg.get("download_missing", True))
        tts_var = tk.StringVar(value=cfg.get("tts_engine", "auto"))
        voice_var = tk.StringVar(value=cfg.get("tts_voice", "eugene"))
        tts_python_var = tk.StringVar(value=cfg.get("tts_python", ""))
        WRAP = 496

        outer = ttk.Frame(win, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Настройки", style="Title.TLabel").pack(anchor="w", pady=(0, 10))

        # --- сеть / локальный режим ---
        card = ttk.Frame(outer, style="Card.TFrame", padding=14)
        card.pack(fill="x")
        ttk.Checkbutton(card, text="Скачивать недостающие текстуры с jackbox.ru",
                        variable=dl_var, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Label(card, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text="Выключено = полностью локальный режим (только 127.0.0.1 и локальные файлы): "
                       "движок не подключается к jackbox.ru даже при наличии интернета."
                  ).pack(anchor="w", pady=(6, 0))

        # --- озвучка (TTS) ---
        card2 = ttk.Frame(outer, style="Card.TFrame", padding=14)
        card2.pack(fill="x", pady=(12, 0))
        ttk.Label(card2, text="Озвучка (Mad Verse City и др.)", style="Card.TLabel",
                  font=("", 11, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        ttk.Label(card2, text="Движок:", style="Card.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=3)
        ttk.Combobox(card2, textvariable=tts_var, state="readonly", width=18,
                     values=settings.TTS_ENGINES).grid(row=1, column=1, columnspan=2, sticky="w", pady=3)
        ttk.Label(card2, text="Голос:", style="Card.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=3)
        voice_cb = ttk.Combobox(card2, textvariable=voice_var, state="readonly", width=18,
                                values=settings.voices_for(tts_var.get()))
        voice_cb.grid(row=2, column=1, sticky="w", pady=3)

        def on_engine_change(*_):
            vs = settings.voices_for(tts_var.get())
            voice_cb.configure(values=vs)
            if voice_var.get() not in vs:
                voice_var.set(vs[0])
        tts_var.trace_add("write", on_engine_change)

        listen_btn = ttk.Button(card2, text="▶ Прослушать")
        listen_btn.grid(row=2, column=2, sticky="w", padx=(10, 0), pady=3)

        def on_listen():
            listen_btn.configure(state="disabled")
            eng, voi = tts_var.get(), voice_var.get()

            def w():
                try:
                    tts_preview.preview(eng, voi, log=log)
                finally:
                    root.after(0, lambda: listen_btn.configure(state="normal"))
            threading.Thread(target=w, daemon=True).start()
        listen_btn.configure(command=on_listen)

        ttk.Label(card2, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text="silero — нейроголос (офлайн; pip install torch numpy). "
                       "piper — нейроголос, легче/быстрее (pip install piper-tts). "
                       "espeak — робо-голос. silent — без голоса. auto — silero → piper → espeak."
                  ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Label(card2, text="Python для TTS:", style="Card.TLabel").grid(row=4, column=0, sticky="w", padx=(0, 10), pady=(8, 2))
        ttk.Entry(card2, textvariable=tts_python_var).grid(row=4, column=1, columnspan=3, sticky="ew", pady=(8, 2))
        ttk.Label(card2, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text="Пусто = python лаунчера. Укажи путь к python из venv (напр. 3.11/3.12), если "
                       "основной python слишком новый и ML-библиотеки (torch/coqui) не ставятся."
                  ).grid(row=5, column=0, columnspan=4, sticky="w")

        def save_close():
            cfg["download_missing"] = dl_var.get()
            cfg["tts_engine"] = tts_var.get()
            cfg["tts_voice"] = voice_var.get()
            cfg["tts_python"] = tts_python_var.get().strip()
            settings.save(cfg)
            log(f"Настройки сохранены (озвучка: {tts_var.get()} / {voice_var.get()}). "
                "Применятся при следующем запуске сервера.")
            win.destroy()

        bar = ttk.Frame(outer)
        bar.pack(fill="x", side="bottom", pady=(16, 0))
        ttk.Button(bar, text="Сохранить", style="Accent.TButton", command=save_close).pack(side="right")
        ttk.Button(bar, text="Отмена", command=win.destroy).pack(side="right", padx=8)

    cert_btn.configure(command=on_cert)
    ports_btn.configure(command=on_ports)
    start_btn.configure(command=on_start)
    stop_btn.configure(command=on_stop)
    settings_btn.configure(command=open_settings)

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
    o = {"check": False, "server": False, "no_web": False, "ip": None, "local": None, "tts": None, "voice": None}
    for a in argv:
        if a == "--check":
            o["check"] = True
        elif a in ("--server", "--no-gui", "-no-gui", "--headless"):
            o["server"] = True
        elif a in ("-no-web", "--no-web"):
            o["no_web"] = True
            o["server"] = True
        elif a in ("-local", "--local", "-offline", "--offline"):
            o["local"] = True  # полностью локально: не докачивать с jackbox.ru
            o["server"] = True
        elif a in ("-online", "--online"):
            o["local"] = False
        elif a.startswith("-tts=") or a.startswith("--tts="):
            o["tts"] = a.split("=", 1)[1]
            o["server"] = True
        elif a.startswith("-voice=") or a.startswith("--voice="):
            o["voice"] = a.split("=", 1)[1]
            o["server"] = True
        elif a.startswith("-ip=") or a.startswith("--ip="):
            o["ip"] = a.split("=", 1)[1]
            o["server"] = True
    return o


def run_server_cli(ip, no_web, local=None, tts=None, voice=None):
    """Серверный режим без GUI: серт + права на порты + запуск движка, лог в терминал."""
    import time
    ip = ip or plat.local_ip()
    if local is not None or tts is not None or voice is not None:
        cfg = settings.load()
        if local is not None:
            cfg["download_missing"] = not local
        if tts is not None:
            cfg["tts_engine"] = tts
        if voice is not None:
            cfg["tts_voice"] = voice
        settings.save(cfg)
    fully_local = not settings.load().get("download_missing", True)
    print(f"== LocalBox (сервер) == адрес: {ip} | веб-клиент: {'выкл' if no_web else 'вкл'}"
          f" | режим: {'полностью локально' if fully_local else 'докачка вкл'}")

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
        run_server_cli(o["ip"], o["no_web"], o["local"], o["tts"], o["voice"])
        return
    try:
        run_gui()
    except Exception as e:  # noqa: BLE001
        print(f"Не удалось открыть GUI ({e}). Перехожу в серверный режим.")
        print("Подсказка: GUI требует tkinter (Arch: sudo pacman -S tk) и дисплей.")
        run_server_cli(o["ip"], o["no_web"], o["local"], o["tts"], o["voice"])


if __name__ == "__main__":
    main()
