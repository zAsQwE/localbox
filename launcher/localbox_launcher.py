#!/usr/bin/env python3
#
#   LocalBox - local private server for Jackbox games
#   Copyright (C) 2026 LocalBox contributors
#   Licensed under the GNU Affero General Public License v3 or later.
#
"""GUI-лаунчер LocalBox: запуск сервера, подключение игроков и настройки.

Движок (server/server.js) обслуживает все игры. Запуск:
    python3 launcher/localbox_launcher.py        # GUI
    ./localbox                                    # из корня проекта (обёртка)
    python3 launcher/localbox_launcher.py --check # проверка окружения без GUI
"""

import json
import os
import queue
import subprocess
import sys
import threading

from setup import platform as plat
from setup import certs, engine, settings, tts_preview, runtime, qr, dodo


def run_gui():
    import tkinter as tk
    from tkinter import font as tkfont, ttk

    root = tk.Tk()
    root.title("LocalBox")
    sw0, sh0 = root.winfo_screenwidth(), root.winfo_screenheight()
    main_w, main_h = min(660, sw0 - 40), min(780, sh0 - 80)
    root.geometry(f"{main_w}x{main_h}+{max(0, (sw0-main_w)//2)}+{max(0, (sh0-main_h)//2)}")
    root.minsize(min(540, sw0 - 40), min(700, sh0 - 80))

    # --- стиль ---
    BG, CARD, FIELD = "#090b0f", "#10141b", "#191f29"
    FG, MUTED, ACC, ACC_HOVER = "#f0f2f6", "#929bab", "#deb45c", "#edc878"
    GREEN, BORDER = "#75cba1", "#242c39"
    fonts = set(tkfont.families(root))
    FONT = next((name for name in ("Inter", "Segoe UI", "SF Pro Display", "DejaVu Sans")
                 if name in fonts), "TkDefaultFont")
    MONO = next((name for name in ("Cascadia Code", "Consolas", "DejaVu Sans Mono")
                 if name in fonts), "TkFixedFont")
    root.option_add("*Font", (FONT, 10))
    root.configure(bg=BG)
    st = ttk.Style()
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure(".", background=BG, foreground=FG, fieldbackground=FIELD, font=(FONT, 10))
    st.configure("Card.TFrame", background=CARD)
    st.configure("TLabel", background=BG, foreground=FG)
    st.configure("Card.TLabel", background=CARD, foreground=FG)
    st.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT, 10))
    st.configure("Title.TLabel", background=BG, foreground=FG, font=(FONT, 22, "bold"))
    st.configure("TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG,
                 bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=10)
    st.configure("TButton", padding=(12, 9), background=FIELD, foreground=FG,
                 borderwidth=0, focusthickness=1, focuscolor=ACC)
    st.map("TButton", background=[("disabled", CARD), ("active", BORDER)],
           foreground=[("disabled", MUTED)])
    st.configure("Accent.TButton", padding=10, background=ACC, foreground=BG)
    st.map("Accent.TButton", background=[("disabled", FIELD), ("active", ACC_HOVER)],
           foreground=[("disabled", MUTED), ("!disabled", BG)])
    st.configure("Card.TCheckbutton", background=CARD, foreground=FG, indicatorbackground=FIELD,
                 indicatorforeground=BG, indicatorbordercolor=BORDER, padding=(0, 4))
    st.map("Card.TCheckbutton", background=[("active", CARD)], foreground=[("!disabled", FG)],
           indicatorbackground=[("selected", ACC), ("!selected", FIELD)])
    st.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=FG,
                 arrowcolor=FG, bordercolor=BORDER, padding=8)
    st.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
           selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)])
    st.configure("Vertical.TScrollbar", background=BORDER, troughcolor=BG,
                 borderwidth=0, arrowsize=12)
    st.map("Vertical.TScrollbar", background=[("active", MUTED)])
    st.configure("Horizontal.TScale", background=CARD, troughcolor=FIELD,
                 borderwidth=0)
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACC)
    root.option_add("*TCombobox*Listbox.selectForeground", BG)

    class RoundedButton(tk.Canvas):
        """Canvas-кнопка без платформенных различий ttk."""
        def __init__(self, master, text, command=None, width=180, height=48, radius=16,
                     fill=FIELD, hover=None, foreground=FG, font=None,
                     shadow=False):
            self._width, self._height, self._radius = width, height, radius
            self._fill, self._hover = fill, hover or fill
            self._foreground, self._font = foreground, font or (FONT, 10, "bold")
            self._text, self._command, self._enabled, self._inside = text, command, True, False
            self._shadow = shadow
            super().__init__(master, width=width, height=height + (8 if shadow else 0),
                             bg=master.cget("bg"), highlightthickness=0, bd=0,
                             cursor="hand2", takefocus=1)
            for sequence in ("<Button-1>", "<Return>", "<space>"):
                self.bind(sequence, self._click)
            self.bind("<Enter>", lambda _e: self._hovered(True))
            self.bind("<Leave>", lambda _e: self._hovered(False))
            self.bind("<FocusIn>", lambda _e: self._render())
            self.bind("<FocusOut>", lambda _e: self._render())
            self.bind("<Configure>", self._resized)
            self._render()

        def _resized(self, event):
            self._width = event.width
            self._render()

        @staticmethod
        def _rounded_points(x1, y1, x2, y2, r):
            return (x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
                    x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
                    x1, y2, x1, y2-r, x1, y1+r, x1, y1)

        def _render(self):
            self.delete("all")
            h, r = self._height, self._radius
            if self._shadow:
                self.create_polygon(self._rounded_points(8, 8, self._width-8, h+7, r),
                                    smooth=True, fill="#58492e", outline="")
            fill = self._hover if self._inside and self._enabled else self._fill
            if not self._enabled:
                fill = FIELD
            self.create_polygon(self._rounded_points(1, 1, self._width-1, h-1, r),
                                smooth=True, fill=fill, outline="")
            if self.focus_get() is self:
                self.create_polygon(self._rounded_points(3, 3, self._width-3, h-3, max(2, r-2)),
                                    smooth=True, fill="", outline=self._foreground, width=1)
            self.create_text(self._width/2, h/2, text=self._text,
                             fill=self._foreground if self._enabled else MUTED, font=self._font)

        def _hovered(self, inside):
            self._inside = inside
            self._render()

        def _click(self, _event=None):
            if self._enabled and self._command:
                self._command()

        def set_enabled(self, enabled):
            self._enabled = bool(enabled)
            self.configure(cursor="hand2" if enabled else "arrow")
            self._render()

        def set_text(self, text):
            self._text = text
            self._render()

        def set_command(self, command):
            self._command = command

        def set_colors(self, fill, hover, foreground=FG):
            self._fill, self._hover, self._foreground = fill, hover, foreground
            self._render()

    ui_q = queue.Queue()
    closing = threading.Event()
    def call_ui(_delay, callback):
        if not closing.is_set():
            ui_q.put(callback)
    def log(message):
        print(str(message), flush=True)
        call_ui(0, lambda: feedback_var.set(str(message)))

    cfg0 = settings.load()
    url_var = tk.StringVar(value=(cfg0.get("server_url") or plat.local_ip()).strip())
    state = {"engine": None, "qr_window": None, "qr_image": None, "qr_code": None,
             "qr_busy": False, "qr_error": None, "settings_window": None, "starting": False}
    qr_client = qr.QRClient()
    lifecycle_lock = threading.Lock()

    outer = tk.Frame(root, bg=BG, padx=28, pady=20)
    outer.pack(fill="both", expand=True)
    header = tk.Frame(outer, bg=BG)
    header.pack(fill="x")
    brand = tk.Frame(header, bg=BG)
    brand.pack(side="left", anchor="nw")
    brand_copy = tk.Frame(brand, bg=BG)
    brand_copy.pack(side="left")
    tk.Label(brand_copy, text="LocalBox", bg=BG, fg=FG,
             font=(FONT, 21, "bold")).pack(anchor="w")
    tk.Label(brand_copy, text="Jackbox в вашей сети", bg=BG, fg=MUTED,
             font=(FONT, 10)).pack(anchor="w")

    settings_btn = RoundedButton(header, "Настройки", width=112, height=42, radius=12)
    settings_btn.pack(side="right", anchor="center")

    feedback_var = tk.StringVar(value="Готово к запуску")
    footer = tk.Frame(outer, bg=BG)
    footer.pack(fill="x", side="bottom", pady=(14, 0))
    feedback_lbl = tk.Label(footer, bg=BG, fg=MUTED, anchor="w", font=(FONT, 9))
    feedback_lbl.pack(fill="x")
    feedback_font = tkfont.Font(font=feedback_lbl.cget("font"))
    def render_feedback(*_):
        message = feedback_var.get().replace("\n", " ")
        width = max(200, footer.winfo_width() - 8)
        if feedback_font.measure(message) > width:
            while message and feedback_font.measure(message + "…") > width:
                message = message[:-1]
            message += "…"
        feedback_lbl.configure(text=message)
    feedback_var.trace_add("write", render_feedback)
    footer.bind("<Configure>", render_feedback)

    def panel(master, padding=20):
        border = tk.Frame(master, bg=BORDER, padx=1, pady=1)
        body = tk.Frame(border, bg=CARD, padx=padding, pady=padding)
        body.pack(fill="both", expand=True)
        return border, body

    hero_border, hero = panel(outer, 20)
    hero_border.pack(fill="both", expand=True, pady=(20, 12))
    hero_top = tk.Frame(hero, bg=CARD)
    hero_top.pack(fill="x")
    tk.Label(hero_top, text="ИГРОВОЙ СЕРВЕР", bg=CARD, fg=MUTED,
             font=(FONT, 9, "bold")).pack(side="left")
    status_var = tk.StringVar(value="●  Остановлен")
    status_lbl = tk.Label(hero_top, textvariable=status_var, bg=FIELD, fg=MUTED,
                          padx=10, pady=5, font=(FONT, 9))
    status_lbl.pack(side="right")
    hero_center = tk.Frame(hero, bg=CARD)
    hero_center.pack(expand=True, fill="x", pady=(10, 0))
    headline_var = tk.StringVar(value="Вечер начинается здесь")
    headline_lbl = tk.Label(hero_center, textvariable=headline_var, bg=CARD, fg=FG,
                            font=(FONT, 20, "bold"))
    headline_lbl.pack()
    subtitle_var = tk.StringVar(value="Запустите сервер и собирайте друзей в игре.")
    hero_subtitle = tk.Label(hero_center, textvariable=subtitle_var, bg=CARD, fg=MUTED,
                             font=(FONT, 10), wraplength=470, justify="center")
    hero_subtitle.pack(pady=(6, 14))
    start_btn = RoundedButton(hero_center, "Запустить сервер", width=290, height=54, radius=14,
                              fill=ACC, hover=ACC_HOVER, foreground=BG,
                              font=(FONT, 12, "bold"), shadow=True)
    start_btn.pack(pady=(0, 4))

    connection_border, connection = panel(outer, 14)
    connection_border.pack(fill="x", pady=(0, 12))
    connection.columnconfigure(0, weight=1)
    tk.Label(connection, text="АДРЕС ДЛЯ ИГРОКОВ", bg=CARD, fg=MUTED,
             font=(FONT, 9, "bold")).grid(row=0, column=0, sticky="w")
    player_url_var = tk.StringVar()
    command_var = tk.StringVar()
    def refresh_address(*_):
        host = url_var.get().strip() or "localhost"
        player_url_var.set("https://" + host)
        command_var.set("-jbg.config serverUrl=" + host)
    url_var.trace_add("write", refresh_address)
    refresh_address()
    address_label = tk.Label(connection, textvariable=player_url_var, bg=CARD, fg=FG,
                            font=(MONO, 13, "bold"), anchor="w", justify="left")
    address_label.grid(row=1, column=0, sticky="ew", pady=(5, 0))
    tk.Label(connection, text="Телефон и компьютер должны быть в одной сети.", bg=CARD, fg=MUTED,
             font=(FONT, 9), anchor="w", justify="left", wraplength=450).grid(
                 row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def copy_text(value, message):
        root.clipboard_clear()
        root.clipboard_append(value)
        feedback_var.set(message)

    copy_address_btn = RoundedButton(connection, "Копировать", width=110, height=38, radius=10,
                                     command=lambda: copy_text(player_url_var.get(), "Адрес для игроков скопирован"))
    copy_address_btn.grid(row=0, column=1, rowspan=2, padx=(12, 0))

    steam_border, steam = panel(outer, 14)
    steam_border.pack(fill="x")
    steam.columnconfigure(0, weight=1)
    tk.Label(steam, text="ПОДКЛЮЧЕНИЕ ИГРЫ В STEAM", bg=CARD, fg=MUTED,
             font=(FONT, 9, "bold")).grid(row=0, column=0, sticky="w")
    tk.Label(steam, text="Свойства игры → Параметры запуска", bg=CARD, fg=MUTED,
             font=(FONT, 9)).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 10))
    command_entry = tk.Entry(steam, textvariable=command_var, state="readonly", relief="flat",
                             readonlybackground=FIELD, fg=FG, selectbackground=ACC,
                             selectforeground=BG, font=(MONO, 10), bd=0, width=1,
                             highlightthickness=1, highlightbackground=FIELD, highlightcolor=ACC)
    command_entry.grid(row=2, column=0, sticky="ew", ipady=10, ipadx=8)
    copy_command_btn = RoundedButton(steam, "Копировать", width=110, height=38, radius=10,
                                     command=lambda: copy_text(command_var.get(), "Параметр запуска Steam скопирован"))
    copy_command_btn.grid(row=2, column=1, padx=(12, 0))

    def resize_main(event):
        hero_subtitle.configure(wraplength=max(240, event.width - 110))
        address_label.configure(wraplength=max(180, event.width - 220))
    outer.bind("<Configure>", resize_main)
    main_view = outer

    def server_appearance(phase):
        running = phase == "running"
        starting = phase == "starting"
        status_var.set("●  Работает" if running else "●  Подготовка" if starting else "●  Остановлен")
        status_lbl.configure(fg=GREEN if running else ACC if starting else MUTED)
        headline_var.set("Можно подключаться" if running else
                         "Готовим всё для игры" if starting else "Вечер начинается здесь")
        subtitle_var.set("Откройте игру в Steam, а на телефонах — адрес ниже." if running else
                         "Проверяем сертификат, порты и зависимости." if starting else
                         "Запустите сервер и собирайте друзей в игре.")
        start_btn.set_text("Остановить сервер" if running else "Запускаем…" if starting else "Запустить сервер")
        start_btn.set_colors(FIELD if running else ACC, BORDER if running else ACC_HOVER,
                             FG if running else BG)
        start_btn.set_enabled(not starting)

    def drain():
        while not ui_q.empty():
            try:
                ui_q.get_nowait()()
            except tk.TclError:
                pass  # A settings window may already have been closed.
        if state["engine"] and not state["engine"].is_running():
            on_stop()
        root.after(150, drain)

    def in_thread(fn, button=None):
        def enable_button():
            if isinstance(button, RoundedButton):
                button.set_enabled(True)
            elif button is not None:
                button.configure(state="normal")
            if button is start_btn and state["starting"] and not state["engine"]:
                state["starting"] = False
                server_appearance("stopped")
                feedback_var.set("Не удалось запустить сервер. Подробности — в консоли.")

        def work():
            try:
                fn()
            except Exception as e:
                log(f"Ошибка: {e}")
            finally:
                if button is not None and (button is not start_btn or not state["engine"]):
                    call_ui(0, enable_button)
        threading.Thread(target=work, daemon=True).start()

    def on_cert(button=None, host=None):
        if button:
            button.set_enabled(False) if isinstance(button, RoundedButton) else button.configure(state="disabled")
        host = (host or url_var.get()).strip() or "localhost"
        def w():
            certs.ensure_cert(host, log=log, extra_names=[plat.local_ip()], force=True)
        in_thread(w, button)

    def on_ports(button=None):
        if button:
            button.set_enabled(False) if isinstance(button, RoundedButton) else button.configure(state="disabled")
        def w():
            engine.allow_privileged_ports(log=log)
        in_thread(w, button)

    def hide_qr():
        win = state.get("qr_window")
        if win:
            try:
                win.withdraw()
            except tk.TclError:
                pass
        state["qr_code"] = None

    def show_qr(room, encoded_png, monitors, source_engine):
        if closing.is_set() or state.get("engine") is not source_engine or not settings.load().get("qr_overlay", True):
            return
        try:
            win = state.get("qr_window")
            if not win or not win.winfo_exists():
                win = tk.Toplevel(root)
                win.overrideredirect(True)
                win.configure(bg="#ffffff")
                try:
                    win.attributes("-topmost", True)
                except tk.TclError:
                    pass
                body = tk.Frame(win, bg="#ffffff", padx=10, pady=8)
                body.pack(fill="both", expand=True)
                code_label = tk.Label(body, bg="#ffffff", fg="#15131f", font=("", 18, "bold"))
                code_label.pack()
                image_label = tk.Label(body, bg="#ffffff", borderwidth=0)
                image_label.pack()
                count_label = tk.Label(body, bg="#ffffff", fg="#4d4661", font=("", 10))
                count_label.pack(pady=(1, 0))
                win._localbox_code_label = code_label
                win._localbox_image_label = image_label
                win._localbox_count_label = count_label
                state["qr_window"] = win
            if state["qr_code"] != (room["code"], room["joinUrl"]):
                state["qr_image"] = tk.PhotoImage(master=root, data=encoded_png)
            image = state["qr_image"]
            win._localbox_image_label.configure(image=image)
            win._localbox_code_label.configure(text=room["code"])
            win._localbox_count_label.configure(
                text=f"Отсканируйте для входа · {room['playerCount']}/{room['maxPlayers']}"
            )
            win.update_idletasks()
            width, height = win.winfo_reqwidth(), win.winfo_reqheight()
            fallback = qr.Monitor(root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height())
            anchor = (fallback.x + fallback.width // 2, fallback.y + fallback.height // 2)
            x, y = qr.overlay_position(width, height, monitors, anchor, fallback)
            win.geometry(f"{width}x{height}+{x}+{y}")
            win.deiconify()
            win.lift()
            try:
                win.attributes("-topmost", True)
            except tk.TclError:
                pass
            state["qr_code"] = (room["code"], room["joinUrl"])
        except tk.TclError as error:
            log(f"[qr] не удалось показать оверлей: {error}")

    def poll_qr():
        if closing.is_set():
            return
        qr_enabled = bool(settings.load().get("qr_overlay", True))
        if not state.get("engine") or not qr_enabled:
            hide_qr()
        elif not state["qr_busy"]:
            state["qr_busy"] = True
            source_engine = state["engine"]
            def fetch_status():
                try:
                    room, png = qr_client.fetch()
                    state["qr_error"] = None
                    if not room:
                        call_ui(0, lambda: hide_qr() if state.get("engine") is source_engine else None)
                    else:
                        monitors = qr.monitor_layout()
                        call_ui(0, lambda r=room, p=png, m=monitors: show_qr(r, p, m, source_engine))
                except Exception as error:
                    message = str(error)
                    if state.get("engine") is source_engine and state["qr_error"] != message:
                        state["qr_error"] = message
                        log("[qr] Не удалось получить QR-код: " + message)
                finally:
                    state["qr_busy"] = False
            threading.Thread(target=fetch_status, daemon=True).start()
        root.after(1000, poll_qr)

    def on_start():
        if state["engine"]:
            on_stop()
            return
        host = url_var.get().strip() or "localhost"
        state["starting"] = True
        server_appearance("starting")
        feedback_var.set("Подготавливаем сервер…")
        def w():
            if not engine.allow_privileged_ports(log=log):
                log("Без портов 80/443 игра не подключится к адресу без номера порта.")
                call_ui(0, lambda: start_btn.set_enabled(True)); return
            # серт должен покрывать этот адрес, иначе хост/телефон выдаёт «bad certificate»
            if not certs.cert_ok_for(host):
                log("Сертификат не подходит под этот адрес — подписываю новый через LocalBox CA…")
                if not certs.ensure_cert(host, log=log, extra_names=[plat.local_ip()], force=True):
                    call_ui(0, lambda: start_btn.set_enabled(True)); return
            if not engine.write_config(host, log=log):
                call_ui(0, lambda: start_btn.set_enabled(True)); return
            if not engine.deps_installed() and not engine.install_deps(log=log):
                call_ui(0, lambda: start_btn.set_enabled(True)); return
            with lifecycle_lock:
                if closing.is_set():
                    return
                proc = engine.EngineProcess(host, on_log=log)
                if proc.start():
                    state["engine"] = proc
                    log(f"Игрокам: https://{host}")
                    def started():
                        state["starting"] = False
                        server_appearance("running")
                        feedback_var.set("Сервер запущен. Откройте Jackbox и создайте комнату.")
                    call_ui(0, started)
        in_thread(w, start_btn)

    def on_stop():
        with lifecycle_lock:
            if state["engine"]:
                state["engine"].stop(); state["engine"] = None
        hide_qr()
        state["starting"] = False
        server_appearance("stopped")
        feedback_var.set("Сервер остановлен")

    def open_settings():
        current = state.get("settings_window")
        if current:
            try:
                if current.winfo_exists():
                    current.lift(); current.focus_force()
                    return
            except tk.TclError:
                pass
        main_view.pack_forget()
        win = tk.Frame(root, bg=BG)
        win.pack(fill="both", expand=True)
        state["settings_window"] = win
        cfg = settings.load()
        server_url_var = tk.StringVar(value=(cfg.get("server_url") or plat.local_ip()).strip())
        qr_var = tk.BooleanVar(value=cfg.get("qr_overlay", True))
        auto_start_var = tk.BooleanVar(value=cfg.get("auto_start_full", False))
        dl_var = tk.BooleanVar(value=cfg.get("download_missing", True))
        tts_var = tk.StringVar(value=cfg.get("tts_engine", "auto"))
        voice_var = tk.StringVar(value=cfg.get("tts_voice", "eugene"))
        tts_python_var = tk.StringVar(value=cfg.get("tts_python", ""))
        dodo_var = tk.BooleanVar(value=cfg.get("dodo_render", False))
        game_path_var = tk.StringVar(value=cfg.get("jackbox10_path", ""))
        instr_var = tk.DoubleVar(value=float(cfg.get("render_instr", 4.0)))
        back_var = tk.DoubleVar(value=float(cfg.get("render_backing", 0.45)))
        admin_var = tk.StringVar(value=cfg.get("admin_nicks", ""))
        cheat_content_var = tk.StringVar(value=cfg.get("cheat_content_dir", ""))
        cheat_answer_var = tk.BooleanVar(value=cfg.get("cheat_answer", True))
        cheat_highlight_var = tk.BooleanVar(value=cfg.get("cheat_highlight", True))
        cheat_price_var = tk.BooleanVar(value=cfg.get("cheat_price", True))
        room_code_var = tk.StringVar(value=cfg.get("room_code", ""))
        WRAP = 500

        outer = tk.Frame(win, bg=BG, padx=28, pady=24)
        outer.pack(fill="both", expand=True)
        settings_header = tk.Frame(outer, bg=BG)
        settings_header.pack(fill="x", pady=(0, 8))
        title_lbl = tk.Label(settings_header, text="Настройки", bg=BG, fg=FG,
                             font=(FONT, 22, "bold"))
        title_lbl.pack(side="left", anchor="w")
        close_btn = RoundedButton(settings_header, "← Назад", command=win.destroy,
                                  width=100, height=40, radius=12)
        close_btn.pack(side="right")
        tk.Label(outer, text="Настройте LocalBox под вашу компанию.", bg=BG, fg=MUTED,
                 font=(FONT, 10)).pack(anchor="w", pady=(0, 20))

        # Кнопки паркуем СНИЗУ и упаковываем РАНЬШЕ прокручиваемой области — тогда их место
        # всегда зарезервировано (не съедается контентом), и «Сохранить» не может пропасть
        # с экрана, даже если настроек слишком много для маленького/маленького-разрешения экрана.
        bar = tk.Frame(outer, bg=BG)
        bar.pack(fill="x", side="bottom", pady=(16, 0))
        settings_feedback = tk.StringVar(value="Изменения применятся после\nперезапуска сервера.")
        tk.Label(bar, textvariable=settings_feedback, bg=BG, fg=MUTED, justify="left",
                 font=(FONT, 9), wraplength=230).pack(side="left")
        save_btn = RoundedButton(bar, "Сохранить", command=lambda: save_close(),
                                 width=174, height=46, radius=12, fill=ACC,
                                 hover=ACC_HOVER, foreground=BG)
        save_btn.pack(side="right")

        tab_bar = tk.Frame(outer, bg=BG)
        tab_bar.pack(fill="x", pady=(0, 14))
        tab_buttons = []
        for index, name in enumerate(("Сервер", "Озвучка", "Додо Ре Ми", "Оверлей")):
            tab_bar.columnconfigure(index, weight=1, uniform="tabs")
            button = RoundedButton(tab_bar, name, width=120, height=40, radius=10,
                                   font=(FONT, 10))
            button.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 4, 0))
            tab_buttons.append(button)

        # Прокручиваемая область под настройки — если контент не помещается по высоте, появится
        # скролл (колесо мыши/трекпад), а не обрезанные/невидимые виджеты.
        scroll_holder = tk.Frame(outer, bg=BG)
        scroll_holder.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_holder, bg=BG, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(scroll_holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        cols = tk.Frame(canvas, bg=BG)
        cols_win = canvas.create_window((0, 0), window=cols, anchor="nw")

        def _on_cols_configure(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # показываем скроллбар, только если контент реально не влезает
            need = cols.winfo_reqheight() > canvas.winfo_height()
            if need and not vsb.winfo_ismapped():
                vsb.pack(side="right", fill="y")
            elif not need and vsb.winfo_ismapped():
                vsb.pack_forget()
        cols.bind("<Configure>", _on_cols_configure)

        def _on_canvas_configure(e):
            canvas.itemconfigure(cols_win, width=e.width)
            def wrap_labels(widget):
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Label) and str(child.cget("wraplength")) not in ("", "0"):
                        child.configure(wraplength=max(220, e.width - 40))
                    wrap_labels(child)
            wrap_labels(cols)
            _on_cols_configure()
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_wheel(e):
            if not vsb.winfo_ismapped():
                return
            delta = -1 if e.delta > 0 else 1
            if getattr(e, "num", None) == 4:
                delta = -1
            elif getattr(e, "num", None) == 5:
                delta = 1
            canvas.yview_scroll(delta, "units")
        WHEEL_SEQS = ("<MouseWheel>", "<Button-4>", "<Button-5>")
        def wheel_in_settings(event):
            widget = event.widget
            while widget is not None:
                if widget is scroll_holder:
                    _on_wheel(event)
                    break
                widget = getattr(widget, "master", None)
        wheel_bindings = {seq: root.bind(seq, wheel_in_settings, add="+") for seq in WHEEL_SEQS}
        def _settings_destroy(event):
            if event.widget is win:
                for sequence, binding in wheel_bindings.items():
                    root.unbind(sequence, binding)
                state["settings_window"] = None
                if not closing.is_set():
                    root.unbind("<Escape>")
                    root.unbind("<Control-s>")
                    main_view.pack(fill="both", expand=True)
        win.bind("<Destroy>", _settings_destroy)

        # В каждой вкладке один столбец; значения сохраняются при переключении.
        left = ttk.Frame(cols)
        left.pack(fill="both", expand=True)
        right = left

        # --- сеть / локальный режим ---
        card = ttk.Frame(left, style="Card.TFrame", padding=20)
        card.pack(fill="x")
        ttk.Label(card, text="Сервер и вход игроков", style="Card.TLabel",
                  font=(FONT, 14, "bold")).pack(anchor="w")
        ttk.Label(card, text="Адрес сервера (IP)", style="Card.TLabel").pack(anchor="w", pady=(12, 5))
        ttk.Entry(card, textvariable=server_url_var).pack(fill="x")
        ttk.Label(card, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text="Укажите локальный IP этого компьютера. Этот же адрес нужен в параметре "
                       "запуска игры в Steam. Команду можно скопировать на главном экране."
                  ).pack(anchor="w", pady=(4, 8))
        ttk.Checkbutton(card, text="Показывать QR-код комнаты справа внизу",
                        variable=qr_var, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(card, text="Автоматически начать игру, когда комната\nзаполнена",
                        variable=auto_start_var, style="Card.TCheckbutton").pack(anchor="w", pady=(3, 0))
        ttk.Label(card, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text="QR открывает локальный сайт по HTTPS с уже введённым кодом. Автостарт нажимает "
                       "действие VIP «Все в сборе», когда достигнут лимит игроков."
                  ).pack(anchor="w", pady=(5, 8))
        ttk.Checkbutton(card, text="Скачивать недостающие текстуры с jackbox.ru",
                        variable=dl_var, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Label(card, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text="Отключите для игры без интернета: будут использоваться только "
                       "локальные файлы. Телефоны подключаются по локальной сети."
                  ).pack(anchor="w", pady=(6, 0))
        service_buttons = ttk.Frame(card, style="Card.TFrame")
        service_buttons.pack(anchor="w", pady=(10, 0))
        cert_settings_btn = ttk.Button(service_buttons, text="Обновить сертификат")
        cert_settings_btn.pack(side="left")
        ports_settings_btn = ttk.Button(service_buttons, text="Права на порты")
        ports_settings_btn.pack(side="left", padx=(6, 0))
        cert_settings_btn.configure(command=lambda: on_cert(cert_settings_btn, server_url_var.get()))
        ports_settings_btn.configure(command=lambda: on_ports(ports_settings_btn))

        # --- озвучка (TTS) ---
        card2 = ttk.Frame(left, style="Card.TFrame", padding=20)
        card2.pack(fill="x", pady=(14, 0))
        card2.columnconfigure(0, weight=1)
        ttk.Label(card2, text="Голос вашей игры", style="Card.TLabel",
                  font=(FONT, 14, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 16))
        ttk.Label(card2, text="Движок", style="Card.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(0, 5))
        ttk.Combobox(card2, textvariable=tts_var, state="readonly", width=18,
                     values=settings.TTS_ENGINES).grid(row=2, column=0, columnspan=4, sticky="ew")
        ttk.Label(card2, text="Голос", style="Card.TLabel").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(10, 5))
        voice_cb = ttk.Combobox(card2, textvariable=voice_var, state="readonly", width=18,
                                values=settings.voices_for(tts_var.get()))
        voice_cb.grid(row=4, column=0, columnspan=3, sticky="ew")

        def on_engine_change(*_):
            vs = settings.voices_for(tts_var.get())
            voice_cb.configure(values=vs)
            if voice_var.get() not in vs:
                voice_var.set(vs[0])
        tts_var.trace_add("write", on_engine_change)

        listen_btn = ttk.Button(card2, text="▶ Прослушать")
        listen_btn.grid(row=4, column=3, sticky="e", padx=(8, 0))

        def on_listen():
            listen_btn.configure(state="disabled")
            eng, voi = tts_var.get(), voice_var.get()

            def w():
                try:
                    tts_preview.preview(eng, voi, log=log)
                finally:
                    call_ui(0, lambda: listen_btn.configure(state="normal"))
            threading.Thread(target=w, daemon=True).start()
        listen_btn.configure(command=on_listen)

        ttk.Label(card2, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text="silero — нейроголос (офлайн; pip install torch numpy). "
                       "piper — нейроголос, легче/быстрее (pip install piper-tts). "
                       "espeak — робо-голос. silent — без голоса. auto — silero → piper → espeak."
                  ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Label(card2, text="Python для TTS", style="Card.TLabel").grid(
            row=6, column=0, columnspan=4, sticky="w", pady=(12, 5))
        ttk.Entry(card2, textvariable=tts_python_var).grid(
            row=7, column=0, columnspan=4, sticky="ew")
        ttk.Label(card2, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text="Пусто = python лаунчера. Укажи путь к python из venv (напр. 3.11/3.12), если "
                       "основной python слишком новый и ML-библиотеки (torch/coqui) не ставятся."
                  ).grid(row=8, column=0, columnspan=4, sticky="w", pady=(5, 0))

        # --- Додо Ре Ми (nopus-opus) ---
        card3 = ttk.Frame(right, style="Card.TFrame", padding=20)
        card3.pack(fill="x", pady=(14, 0))
        ttk.Label(card3, text="Музыка в Додо Ре Ми", style="Card.TLabel",
                  font=(FONT, 14, "bold")).pack(anchor="w", pady=(0, 12))
        ttk.Checkbutton(card3, text="Собирать выступления на этом компьютере",
                        variable=dodo_var, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Label(card3, text="Папка Jackbox 10 или games/NopusOpus/songs:", style="Card.TLabel").pack(anchor="w", pady=(10, 2))
        game_row = ttk.Frame(card3, style="Card.TFrame")
        game_row.pack(fill="x")
        ttk.Entry(game_row, textvariable=game_path_var).pack(side="left", fill="x", expand=True)
        def select_dodo_game():
            from tkinter import filedialog
            directory = filedialog.askdirectory(parent=root, title="Папка Jackbox 10 или songs",
                                                initialdir=game_path_var.get() or str(plat.repo_root()))
            if directory:
                game_path_var.set(directory)
        ttk.Button(game_row, text="Выбрать", command=select_dodo_game).pack(side="right", padx=(6, 0))
        import_status = tk.StringVar()
        def copy_dodo_music():
            directory = game_path_var.get().strip()
            if not directory:
                import_status.set("Сначала выбери папку Jackbox 10 или songs.")
                return
            try:
                dodo.songs_directory(directory)
            except (ValueError, OSError) as error:
                import_status.set(str(error))
                return
            import_button.configure(state="disabled")
            import_status.set("Копируем музыку…")
            def work():
                try:
                    count = dodo.import_dodo(directory, plat.repo_root(), log)
                    def done():
                        dodo_var.set(True)
                        import_status.set(f"Скопировано файлов музыки: {count}. Нажми «Сохранить».")
                    call_ui(0, done)
                except (ValueError, OSError) as error:
                    message = str(error)
                    call_ui(0, lambda: import_status.set(message))
            in_thread(work, import_button)
        import_button = ttk.Button(card3, text="Импортировать музыку", command=copy_dodo_music)
        import_button.pack(anchor="w", pady=(6, 0))
        ttk.Label(card3, textvariable=import_status, style="Card.TLabel", foreground=MUTED,
                  wraplength=WRAP).pack(anchor="w", pady=(4, 0))
        ttk.Label(card3, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text="Музыка и сэмплы копируются в LocalBox по кнопке. Файлы игры сохраняются. "
                       "Нужен ffmpeg в PATH или runtime/. Без музыки звучат только сыгранные ноты."
                  ).pack(anchor="w", pady=(6, 0))

        def open_folder(d, label):
            try:
                d.mkdir(parents=True, exist_ok=True)
                if plat.is_windows():
                    os.startfile(str(d))  # noqa: S606
                elif plat.is_linux():
                    subprocess.Popen(["xdg-open", str(d)])
                else:
                    subprocess.Popen(["open", str(d)])
                log(f"{label}: {d}")
            except Exception as e:  # noqa: BLE001
                log(f"{label}: {d} (открыть не удалось: {e})")

        dodo_btns = ttk.Frame(card3, style="Card.TFrame")
        dodo_btns.pack(anchor="w", pady=(8, 0))
        ttk.Button(dodo_btns, text="Открыть папку песен",
                   command=lambda: open_folder(plat.repo_root() / "server" / "render" / "nopus-opus" / "songs",
                                                "Папка бэкингов")).pack(fill="x")
        ttk.Button(dodo_btns, text="Открыть runtime для ffmpeg",
                   command=lambda: open_folder(plat.repo_root() / "runtime",
                                                "Папка runtime")).pack(fill="x", pady=(6, 0))

        # Громкость рендера (инструмент / бэкинг) — ползунки.
        vol = ttk.Frame(card3, style="Card.TFrame")
        vol.pack(fill="x", pady=(10, 0))
        instr_lbl = ttk.Label(vol, style="Card.TLabel", text=f"Громкость инструмента: {instr_var.get():.1f}")
        instr_lbl.grid(row=0, column=0, sticky="w")
        ttk.Scale(vol, from_=1.0, to=10.0, variable=instr_var, orient="horizontal",
                  command=lambda v: instr_lbl.configure(text=f"Громкость инструмента: {float(v):.1f}")
                  ).grid(row=1, column=0, sticky="ew", pady=(0, 6))
        back_lbl = ttk.Label(vol, style="Card.TLabel", text=f"Громкость бэкинга (музыки): {back_var.get():.2f}")
        back_lbl.grid(row=2, column=0, sticky="w")
        ttk.Scale(vol, from_=0.0, to=1.0, variable=back_var, orient="horizontal",
                  command=lambda v: back_lbl.configure(text=f"Громкость бэкинга (музыки): {float(v):.2f}")
                  ).grid(row=3, column=0, sticky="ew")
        vol.columnconfigure(0, weight=1)
        ttk.Label(card3, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text="Инструмент громче = отчётливее ноты; бэкинг тише = меньше музыки. Применяется к следующему рендеру."
                  ).pack(anchor="w", pady=(4, 0))

        # --- Читы (оверлей в игре) ---
        card4 = ttk.Frame(right, style="Card.TFrame", padding=20)
        card4.pack(fill="x", pady=(14, 0))
        ttk.Label(card4, text="Оверлей и код комнаты", style="Card.TLabel",
                  font=(FONT, 14, "bold")).pack(anchor="w", pady=(0, 10))
        ttk.Label(card4, text="Ники с читами (через запятую):", style="Card.TLabel").pack(anchor="w", pady=(6, 2))
        ttk.Entry(card4, textvariable=admin_var).pack(fill="x")
        ttk.Checkbutton(card4, text="Подсвечивать найденные правильные варианты\nна кнопках в игре",
                        variable=cheat_highlight_var, style="Card.TCheckbutton").pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(card4, text="Показывать правильные ответы в панели",
                        variable=cheat_answer_var, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(card4, text="Показывать цену картины (Дуракцион) —\nценник у картины",
                        variable=cheat_price_var, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Label(card4, text="Папка со всеми Jackbox или отдельной игрой (пусто = Steam):", style="Card.TLabel").pack(anchor="w", pady=(8, 2))
        content_row = ttk.Frame(card4, style="Card.TFrame")
        content_row.pack(fill="x")
        ttk.Entry(content_row, textvariable=cheat_content_var).pack(side="left", fill="x", expand=True)
        def select_cheat_content():
            from tkinter import filedialog
            directory = filedialog.askdirectory(parent=root, title="Папка с играми Jackbox или steamapps/common",
                                                initialdir=cheat_content_var.get() or str(plat.repo_root()))
            if directory:
                cheat_content_var.set(directory)
        ttk.Button(content_row, text="Выбрать", command=select_cheat_content).pack(side="right", padx=(6, 0))
        ttk.Label(card4, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text="Кто вписан — заходит в игру под этим ником и получает оверлей читов (вкладка справа, "
                       "или Ctrl+Shift+K): God view (секретные ответы/голоса/рисунки всех), подсветка правильного "
                       "ответа, подмена значений, кик/бан/мьют. Для Бредовухи и Смертельной вечеринки ответы "
                       "читаются из файлов игры: выбери папку с тем же переводом. В Дуракционе видны оценки "
                       "картин, переданные игрокам. Пустой список ников = читы выключены."
                  ).pack(anchor="w", pady=(6, 0))
        # --- Код комнаты ---
        ttk.Label(card4, text="Код комнаты (пусто = случайный):", style="Card.TLabel").pack(anchor="w", pady=(10, 2))
        ttk.Entry(card4, textvariable=room_code_var).pack(fill="x")
        ttk.Label(card4, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text="Свой фиксированный код вместо случайного (напр. ИГРА или GAME). Русские буквы можно, но "
                       "телефон-клиент игры может не дать их ввести — тогда используй латиницу."
                  ).pack(anchor="w", pady=(4, 0))

        def save_close():
            host = server_url_var.get().strip() or plat.local_ip()
            cfg["server_url"] = host
            cfg["qr_overlay"] = qr_var.get()
            cfg["auto_start_full"] = auto_start_var.get()
            cfg["download_missing"] = dl_var.get()
            cfg["tts_engine"] = tts_var.get()
            cfg["tts_voice"] = voice_var.get()
            cfg["tts_python"] = tts_python_var.get().strip()
            content_path = cheat_content_var.get().strip()
            if content_path and not os.path.isdir(os.path.expanduser(content_path)):
                settings_feedback.set("Папка с играми для читов не найдена.")
                return
            game_path = game_path_var.get().strip()
            if game_path and not os.path.isdir(os.path.expanduser(game_path)):
                settings_feedback.set("Папка Jackbox 10 не найдена.")
                return
            cfg["jackbox10_path"] = os.path.abspath(os.path.expanduser(game_path)) if game_path else ""
            cfg["dodo_render"] = dodo_var.get()
            cfg["render_instr"] = round(float(instr_var.get()), 2)
            cfg["render_backing"] = round(float(back_var.get()), 2)
            cfg["admin_nicks"] = admin_var.get().strip()
            cfg["cheat_content_dir"] = os.path.abspath(os.path.expanduser(content_path)) if content_path else ""
            cfg["cheat_answer"] = cheat_answer_var.get()
            cfg["cheat_highlight"] = cheat_highlight_var.get()
            cfg["cheat_price"] = cheat_price_var.get()
            cfg["room_code"] = room_code_var.get().strip()
            if not settings.save(cfg):
                log("Не удалось сохранить настройки. Проверьте права на папку launcher.")
                settings_feedback.set("Ошибка сохранения.\nПроверьте права на папку launcher.")
                return
            url_var.set(host)
            log(f"Настройки сохранены (озвучка: {tts_var.get()} / {voice_var.get()}). "
                "Применятся при следующем запуске сервера.")
            win.destroy()

        pages = (card, card2, card3, card4)
        def select_tab(index):
            for page in pages:
                page.pack_forget()
            pages[index].pack(fill="x")
            for number, button in enumerate(tab_buttons):
                selected = number == index
                button.set_colors(ACC if selected else FIELD, ACC_HOVER if selected else BORDER,
                                  BG if selected else MUTED)
            canvas.yview_moveto(0)
            canvas.after_idle(_on_cols_configure)
        for index, button in enumerate(tab_buttons):
            button.set_command(lambda i=index: select_tab(i))
        select_tab(0)

        root.bind("<Escape>", lambda _e: win.destroy())
        root.bind("<Control-s>", lambda _e: save_close())

    start_btn.set_command(on_start)
    settings_btn.set_command(open_settings)

    def on_close():
        closing.set()
        on_stop(); root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)

    drain()
    poll_qr()
    log("Готово. Нажмите «Запустить» — сертификат и права проверятся автоматически.")
    log("В игре Steam: параметр запуска  -jbg.config serverUrl=" + url_var.get())
    if not engine.engine_dir().exists():
        log("ВНИМАНИЕ: папка server/ не найдена — движок не установлен.")
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
    o = {"check": False, "gui": False, "server": False, "no_web": False, "ip": None, "local": None, "tts": None, "voice": None}
    for a in argv:
        if a == "--check":
            o["check"] = True
        elif a == "--gui":
            o["gui"] = True
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
        print("Движок не найден (server/). Скачайте исходники целиком."); sys.exit(1)
    if not engine.find_node():
        print("Node.js не найден. Установите node или положите его в ./runtime/. См. README."); sys.exit(1)

    # 1) сертификат (перегенерируем, если нет/не покрывает адрес — иначе «bad certificate»)
    if not certs.cert_ok_for(ip):
        if not certs.ensure_cert(ip, log=print, extra_names=[plat.local_ip(), "localhost"], force=True):
            sys.exit(1)
    # 2) конфиг движка
    if not engine.write_config(ip, log=print):
        sys.exit(1)
    # 3) права на порты 80/443
    if not plat.has_admin():
        print("Порты 80/443 требуют прав. Выдаю node право (нужен sudo/pkexec)…")
        if not engine.allow_privileged_ports(log=print):
            print("Вручную: sudo setcap cap_net_bind_service=+ep \"$(command -v node)\"")
            sys.exit(1)
    # 4) зависимости
    if not engine.deps_installed() and not engine.install_deps(log=print):
        print("Не удалось установить зависимости движка."); sys.exit(1)
    # 5) запуск (блокирующе, до Ctrl+C)
    proc = engine.EngineProcess(ip, on_log=print, no_web=no_web)
    if not proc.start():
        sys.exit(1)
    print("Сервер запущен. Игра: -jbg.config serverUrl=" + ip + "   (Ctrl+C — остановить)")
    print("Игрокам: https://" + ip)
    try:
        while proc.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nОстанавливаю…")
        proc.stop()
        return
    if proc.proc.returncode:
        sys.exit(proc.proc.returncode)


def _no_display():
    return plat.is_linux() and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")


def main():
    runtime.activate()
    o = parse_cli(sys.argv[1:])
    # Если лаунчер запущен из start-server.bat в режиме «Додо Ре Ми» (он ставит LOCALBOX_DODO=1) —
    # Меню запуска задаёт оба состояния, чтобы обычный режим снимал старую галочку.
    if os.environ.get("LOCALBOX_DODO") in ("0", "1"):
        _cfg = settings.load()
        _dodo = os.environ["LOCALBOX_DODO"] == "1"
        if bool(_cfg.get("dodo_render")) != _dodo:
            _cfg["dodo_render"] = _dodo
            if not settings.save(_cfg):
                print("Не удалось сохранить выбор Додо Ре Ми.")
                sys.exit(1)
    if o["check"]:
        check_environment()
        return
    # Серверный/headless режим: явный флаг или нет графической сессии.
    if o["server"] and o["gui"]:
        print("Выберите один режим: --gui или --server.")
        sys.exit(1)
    if o["gui"] and _no_display():
        print("GUI недоступен без графической сессии. Запустите --server.")
        sys.exit(1)
    if o["server"] or (_no_display() and not o["gui"]):
        run_server_cli(o["ip"], o["no_web"], o["local"], o["tts"], o["voice"])
        return
    try:
        run_gui()
    except Exception as e:  # noqa: BLE001
        if o["gui"]:
            print(f"Не удалось открыть GUI: {e}. Проверьте tkinter и графическую сессию.")
            sys.exit(1)
        print(f"Не удалось открыть GUI ({e}). Перехожу в серверный режим.")
        print("Подсказка: GUI требует tkinter (Arch: sudo pacman -S tk) и дисплей.")
        run_server_cli(o["ip"], o["no_web"], o["local"], o["tts"], o["voice"])


if __name__ == "__main__":
    main()
