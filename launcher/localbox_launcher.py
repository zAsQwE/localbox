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
import urllib.parse
from pathlib import Path

from setup.i18n import tr, language, LANGUAGES
from setup import platform as plat
from setup import certs, cert_trust, engine, settings, tts_preview, runtime, qr, dodo, updates, tmp3, game_tls, game_trust

# Porthole binds each shared port on the friend's own loopback.
PORTHOLE_URL = "http://127.0.0.1"
# Corners for the room QR overlay (settings "qr_position" → label).
QR_POSITIONS = (("bottom-right", 'Справа внизу'), ("bottom-left", 'Слева внизу'),
                ("top-right", 'Справа вверху'), ("top-left", 'Слева вверху'))


def run_gui():
    import tkinter as tk
    from tkinter import font as tkfont, ttk
    from setup.i18n_tk import LiveTranslations

    translations = LiveTranslations()
    tk, ttk, tr = translations.tk, translations.ttk, translations.text

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
            translations.custom.add(self)
            self._render()

        def refresh_language(self):
            if hasattr(self._text, "current"):
                self._text = self._text.current()
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
            self.create_text(self._width/2, h/2, text=translations.render(self._text),
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
    scheduled_jobs = {"drain": None, "qr": None}
    def call_ui(_delay, callback):
        if not closing.is_set():
            ui_q.put(callback)
    def log(message):
        print(str(message), flush=True)
        call_ui(0, lambda: feedback_var.set(str(message)))

    cfg0 = settings.load()
    url_var = tk.StringVar(value=(cfg0.get("server_url") or plat.local_ip()).strip())
    state = {"engine": None, "qr_window": None, "qr_image": None, "qr_code": None,
             "qr_busy": False, "qr_error": None, "settings_window": None, "starting": False,
             "client_busy": False}
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
    tk.Label(brand_copy, text=tr('Jackbox в вашей сети'), bg=BG, fg=MUTED,
             font=(FONT, 10)).pack(anchor="w")

    settings_btn = RoundedButton(header, tr('Настройки'), width=112, height=42, radius=12)
    settings_btn.pack(side="right", anchor="center")

    update_state = {"release": None, "busy": False}
    update_btn = ttk.Button(header, text=tr('Проверить обновления'))
    update_btn.pack(side="right", anchor="center", padx=(0, 8))

    feedback_var = tk.StringVar(value=tr('Готово к запуску'))
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
    tk.Label(hero_top, text=tr('ИГРОВОЙ СЕРВЕР'), bg=CARD, fg=MUTED,
             font=(FONT, 9, "bold")).pack(side="left")
    status_var = tk.StringVar(value=tr('●  Остановлен'))
    status_lbl = tk.Label(hero_top, textvariable=status_var, bg=FIELD, fg=MUTED,
                          padx=10, pady=5, font=(FONT, 9))
    status_lbl.pack(side="right")
    hero_center = tk.Frame(hero, bg=CARD)
    hero_center.pack(expand=True, fill="x", pady=(10, 0))
    headline_var = tk.StringVar(value=tr('Вечер начинается здесь'))
    headline_lbl = tk.Label(hero_center, textvariable=headline_var, bg=CARD, fg=FG,
                            font=(FONT, 20, "bold"))
    headline_lbl.pack()
    subtitle_var = tk.StringVar(value=tr('Запустите сервер и собирайте друзей в игре.'))
    hero_subtitle = tk.Label(hero_center, textvariable=subtitle_var, bg=CARD, fg=MUTED,
                             font=(FONT, 10), wraplength=470, justify="center")
    hero_subtitle.pack(pady=(6, 14))
    start_btn = RoundedButton(hero_center, tr('Запустить сервер'), width=290, height=54, radius=14,
                              fill=ACC, hover=ACC_HOVER, foreground=BG,
                              font=(FONT, 12, "bold"), shadow=True)
    start_btn.pack(pady=(0, 4))

    connection_border, connection = panel(outer, 14)
    connection_border.pack(fill="x", pady=(0, 12))
    connection.columnconfigure(0, weight=1)
    tk.Label(connection, text=tr('АДРЕС ДЛЯ ИГРОКОВ'), bg=CARD, fg=MUTED,
             font=(FONT, 9, "bold")).grid(row=0, column=0, sticky="w")
    player_url_var = tk.StringVar()
    command_var = tk.StringVar()
    def refresh_address(*_):
        host = url_var.get().strip() or "localhost"
        player_url_var.set("http://" + host)
        try:
            # Linux: one line with the game-only CA file (-cafile + SSL_CERT_FILE); Windows: only serverUrl.
            command_var.set(game_tls.steam_launch_options(host))
        except ValueError:
            command_var.set(tr('Укажи корректный адрес сервера в настройках'))
    url_var.trace_add("write", refresh_address)
    refresh_address()
    address_label = tk.Label(connection, textvariable=player_url_var, bg=CARD, fg=FG,
                            font=(MONO, 13, "bold"), anchor="w", justify="left")
    address_label.grid(row=1, column=0, sticky="ew", pady=(5, 0))
    network_hint = tk.Label(connection, text=tr('Телефон и компьютер должны быть в одной сети.'), bg=CARD, fg=MUTED,
                            font=(FONT, 9), anchor="w", justify="left", wraplength=300)
    network_hint.grid(row=2, column=0, sticky="w", pady=(8, 0))
    download_ru_btn = ttk.Button(connection, text=tr('Скачать русский клиент'))
    download_ru_btn.grid(row=2, column=1, sticky="e", padx=(12, 0), pady=(8, 0))
    if language() != "ru":
        download_ru_btn.grid_remove()

    def copy_text(value, message):
        root.clipboard_clear()
        root.clipboard_append(value)
        feedback_var.set(message)

    copy_address_btn = RoundedButton(connection, tr('Копировать'), width=110, height=38, radius=10,
                                     command=lambda: copy_text(player_url_var.get(), tr('Адрес для игроков скопирован')))
    copy_address_btn.grid(row=0, column=1, rowspan=2, padx=(12, 0))

    # Porthole (Steam port sharing): the friend's browser reaches this server on their own
    # 127.0.0.1:<port>; the server answers with whatever address and port the player used.
    # Port 80 is the normal web port; another one (e.g. 9999) is opened as an extra HTTP port.
    porthole_port_var = tk.StringVar(value=str(settings.load().get("porthole_port") or 80))
    def porthole_port():
        return game_tls.porthole_port(porthole_port_var.get())
    def porthole_base():
        port = porthole_port() or 80
        return PORTHOLE_URL + ("" if port == 80 else ":" + str(port))
    def porthole_link():
        room = state.get("qr_code")
        return porthole_base() + ("/?code=" + urllib.parse.quote(room[0]) if room else "")
    porthole_row = tk.Frame(connection, bg=CARD)
    porthole_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    porthole_row.columnconfigure(0, weight=1)
    porthole_label = tk.Label(porthole_row, bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w", justify="left", wraplength=400)
    porthole_label.grid(row=0, column=0, sticky="w")
    tk.Label(porthole_row, text=tr('Порт:'), bg=CARD, fg=MUTED, font=(FONT, 9)).grid(row=0, column=1, sticky="e", padx=(12, 4))
    porthole_entry = tk.Entry(porthole_row, textvariable=porthole_port_var, width=6, relief="flat",
                              bg=FIELD, fg=FG, insertbackground=FG, font=(MONO, 10), bd=0,
                              highlightthickness=1, highlightbackground=FIELD, highlightcolor=ACC)
    porthole_entry.grid(row=0, column=2, sticky="e", ipady=4, ipadx=4)
    ttk.Button(porthole_row, text=tr('Ссылка для друга'),
               command=lambda: copy_text(porthole_link(), tr('Ссылка для друга через Porthole скопирована'))
               ).grid(row=0, column=3, sticky="e", padx=(12, 0))
    def porthole_changed(*_):
        port = porthole_port()
        if port is None:
            porthole_entry.configure(highlightbackground="#c0504d")
            porthole_label.configure(text=tr('Порт для Porthole: 80 или 1024–65535, кроме 38202 и 38203.'))
            return
        porthole_entry.configure(highlightbackground=FIELD)
        porthole_label.configure(text=tr('Друзья через Porthole: поделитесь портом TCP {0}, у друга — {1}', port, porthole_base()))
        options = settings.load()
        if options.get("porthole_port", 80) != port:
            options["porthole_port"] = port
            settings.save(options)
            if state.get("engine"):
                feedback_var.set(tr('Перезапустите сервер, чтобы открыть порт {0} для Porthole.', port))
    porthole_port_var.trace_add("write", porthole_changed)
    porthole_changed()
    def apply_porthole():
        if settings.load().get("porthole_enabled", True):
            porthole_row.grid()
        else:
            porthole_row.grid_remove()
    state["apply_porthole"] = apply_porthole
    apply_porthole()

    steam_border, steam = panel(outer, 14)
    steam_border.pack(fill="x")
    steam.columnconfigure(0, weight=1)
    tk.Label(steam, text=tr('ПОДКЛЮЧЕНИЕ ИГРЫ В STEAM'), bg=CARD, fg=MUTED,
             font=(FONT, 9, "bold")).grid(row=0, column=0, sticky="w")
    command_entry = tk.Entry(steam, textvariable=command_var, state="readonly", relief="flat",
                             readonlybackground=FIELD, fg=FG, selectbackground=ACC,
                             selectforeground=BG, font=(MONO, 10), bd=0, width=1,
                             highlightthickness=1, highlightbackground=FIELD, highlightcolor=ACC)
    command_entry.grid(row=1, column=0, sticky="ew", ipady=10, ipadx=8)
    copy_command_btn = RoundedButton(steam, tr('Копировать serverUrl'), width=180, height=38, radius=10,
                                     command=lambda: copy_text(command_var.get(), tr('Параметр запуска Steam скопирован')))
    copy_command_btn.grid(row=1, column=1, padx=(12, 0))

    def open_tmp3():
        from tkinter import filedialog
        existing = state.get("tmp3_window")
        if existing and existing.winfo_exists():
            existing.lift()
            return
        window = tk.Toplevel(root)
        state["tmp3_window"] = window
        window.title("Trivia Murder Party 3")
        window.configure(bg=BG)
        window.transient(root)
        window.geometry(f"{min(620, window.winfo_screenwidth()-40)}x320")
        body = ttk.Frame(window, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=tr('Подключить TMP3'), font=(FONT, 16, "bold")).pack(anchor="w")
        ttk.Label(body, text=tr('Закрой игру перед настройкой. Оригинал сохраняется для отката.\nСертификат используется только в TMP3; доверие системы не меняется.'),
                  wraplength=550, justify="left").pack(anchor="w", pady=(8, 14))
        folder = tk.StringVar(value=str(tmp3.discover() or ""))
        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=folder).pack(side="left", fill="x", expand=True)
        def browse():
            selected = filedialog.askdirectory(parent=window, title=tr('Папка Trivia Murder Party 3 с TMP3.exe'),
                                               initialdir=folder.get() or str(plat.repo_root()))
            if selected:
                folder.set(selected)
        ttk.Button(row, text=tr('Выбрать…'), command=browse).pack(side="left", padx=(8, 0))
        status = tk.StringVar(value=tr('Адрес LocalBox: ') + (url_var.get().strip() or "localhost"))
        ttk.Label(body, textvariable=status, wraplength=550, justify="left").pack(anchor="w", pady=12)
        actions = ttk.Frame(body)
        actions.pack(fill="x", side="bottom")
        def run(restore=False):
            path = folder.get().strip()
            host = url_var.get().strip() or "localhost"
            if not path:
                status.set(tr('Выбери папку игры.'))
                return
            apply_btn.configure(state="disabled"); undo_btn.configure(state="disabled")
            status.set(tr('Восстанавливаю оригинал…') if restore else tr('Настраиваю TMP3…'))
            def worker():
                try:
                    if restore:
                        tmp3.restore(path, log=log)
                    else:
                        tmp3.connect(path, host, log=log)
                    message = tr('Оригинал восстановлен.') if restore else tr('Готово. Запусти LocalBox и выбери локальную игру в TMP3.')
                except (OSError, ValueError, RuntimeError) as error:
                    message = str(error)
                    log(message)
                def complete():
                    if window.winfo_exists():
                        status.set(message)
                        apply_btn.configure(state="normal"); undo_btn.configure(state="normal")
                call_ui(0, complete)
            threading.Thread(target=worker, daemon=True).start()
        apply_btn = ttk.Button(actions, text=tr('Настроить'), command=run)
        apply_btn.pack(side="left")
        undo_btn = ttk.Button(actions, text=tr('Вернуть оригинал'), command=lambda: run(True))
        undo_btn.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text=tr('Закрыть'), command=window.destroy).pack(side="right")

    patch_row = tk.Frame(steam, bg=CARD)
    patch_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))  # below the Steam line
    patch_status = tk.StringVar(value=tr('Выбери папку игры — патч установится автоматически.'))
    def patch_tmp3():
        from tkinter import filedialog
        if state.get("tmp3_patching"):
            return
        folder = filedialog.askdirectory(parent=root, title=tr('Папка Trivia Murder Party 3 с TMP3.exe'),
                                         initialdir=str(tmp3.discover() or Path.home()))
        if not folder:
            return
        host = url_var.get().strip() or "localhost"
        state["tmp3_patching"] = True
        patch_btn.set_enabled(False)
        patch_btn.set_text(tr('Устанавливаю патч…'))
        patch_status.set(tr('Не запускай игру до завершения патча.'))
        def worker():
            error = None
            try:
                tmp3.connect(folder, host, log=log)
            except (OSError, ValueError, RuntimeError) as caught:
                error = str(caught)
                log(error)
            def complete():
                state["tmp3_patching"] = False
                patch_btn.set_enabled(True)
                patch_btn.set_text(tr('Патч Trivia Murder Party 3'))
                patch_status.set(error or tr('Патч установлен. Запусти сервер и выбери локальную игру в TMP3.'))
            call_ui(0, complete)
        threading.Thread(target=worker, daemon=True).start()
    patch_btn = RoundedButton(patch_row, tr('Патч Trivia Murder Party 3'), width=250, height=38,
                              radius=10, command=patch_tmp3)
    patch_btn.pack(side="left")
    ttk.Button(patch_row, text=tr('Параметры / откат…'), command=open_tmp3).pack(side="right")
    tk.Label(steam, textvariable=patch_status, bg=CARD, fg=MUTED, font=(FONT, 9),
             wraplength=520, justify="left").grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def resize_main(event=None):
        width = event.width if event is not None else outer.winfo_width()
        hero_subtitle.configure(wraplength=max(240, width - 110))
        available = max(120, width - (download_ru_btn.winfo_reqwidth() if language() == "ru" else 0) - 112)
        address_label.configure(wraplength=available)
        network_hint.configure(wraplength=available)
    outer.bind("<Configure>", resize_main)
    main_view = outer

    def server_appearance(phase):
        running = phase == "running"
        starting = phase == "starting"
        status_var.set(tr('●  Работает') if running else tr('●  Подготовка') if starting else tr('●  Остановлен'))
        status_lbl.configure(fg=GREEN if running else ACC if starting else MUTED)
        headline_var.set(tr('Можно подключаться') if running else
                         tr('Готовим всё для игры') if starting else tr('Вечер начинается здесь'))
        subtitle_var.set(tr('Откройте игру в Steam, а на телефонах — адрес ниже.') if running else
                         tr('Проверяем сертификат, порты и зависимости.') if starting else
                         tr('Запустите сервер и собирайте друзей в игре.'))
        start_btn.set_text(tr('Остановить сервер') if running else tr('Запускаем…') if starting else tr('Запустить сервер'))
        start_btn.set_colors(FIELD if running else ACC, BORDER if running else ACC_HOVER,
                             FG if running else BG)
        start_btn.set_enabled(not starting)

    def drain():
        if closing.is_set():
            return
        while not ui_q.empty():
            try:
                ui_q.get_nowait()()
            except tk.TclError:
                pass  # A settings window may already have been closed.
            if closing.is_set():
                return
        if state["engine"] and not state["engine"].is_running():
            on_stop()
        scheduled_jobs["drain"] = root.after(150, drain)

    def in_thread(fn, button=None):
        def enable_button():
            if isinstance(button, RoundedButton):
                button.set_enabled(True)
            elif button is not None:
                button.configure(state="normal")
            if button is start_btn and state["starting"] and not state["engine"]:
                state["starting"] = False
                server_appearance("stopped")
                feedback_var.set(tr('Не удалось запустить сервер. Подробности — в консоли.'))

        def work():
            try:
                fn()
            except Exception as e:
                log(tr('Ошибка: {0}', e))
            finally:
                if button is not None and (button is not start_btn or not state["engine"]):
                    call_ui(0, enable_button)
        threading.Thread(target=work, daemon=True).start()

    def on_cert(button=None, host=None):
        from tkinter import messagebox
        if state.get("cert_busy"):
            return
        state["cert_busy"] = True
        if button:
            button.set_enabled(False) if isinstance(button, RoundedButton) else button.configure(state="disabled")
        host = (host or url_var.get()).strip() or "localhost"

        def finished():
            state["cert_busy"] = False
            try:
                if button:
                    button.set_enabled(True) if isinstance(button, RoundedButton) else button.configure(state="normal")
            except tk.TclError:
                pass

        def failed(error):
            message = tr('Не удалось завершить обновление сертификата и установку доверия: {0}', error)
            log(message)
            def show():
                finished()
                messagebox.showerror(tr('Сертификат LocalBox'), message, parent=root)
            call_ui(0, show)

        def confirm(plan):
            fingerprint = ":".join(plan.fingerprint[i:i+2] for i in range(0,64,2)) if plan.fingerprint else tr('Будет создан новый локальный CA')
            if plat.is_linux():
                prompt = tr('Сервер: {0}\nCA SHA-256: {1}\n\n'
                            'Сертификат сервера будет обновлён. Доверие нигде не устанавливается: системное хранилище, '
                            'Steam и браузеры не меняются. Игры берут сертификат из строки запуска Steam '
                            '(-cafile и SSL_CERT_FILE), скопируйте её на главном экране.\n\nПродолжить?',
                            plan.host, fingerprint)
            else:
                prompt = tr('Сервер: {0}\nCA SHA-256: {1}\n\n'
                            'CA будет добавлен в доверенные Windows: только там его ищут Windows-версии Jackbox. '
                            'После этого в Steam достаточно -jbg.config serverUrl=IP. Windows один раз спросит подтверждение. '
                            'Храни приватный ключ в секрете.\n\n'
                            'Для работающего сервера используется его настоящий CA. Сверь отпечаток с сервером, особенно при подключении к другу. '
                            'Файлы игры и hosts не меняются. Закрой игры Jackbox перед продолжением.\n\nПродолжить?',
                            plan.host, fingerprint)
            if not messagebox.askyesno(tr('Сертификат LocalBox'), prompt, icon="warning", default="no", parent=root):
                finished()
                return
            def apply():
                try:
                    result = cert_trust.renew_and_trust(host, confirmed=True, log=log, plan=plan)
                except Exception as error:
                    failed(error)
                    return
                options = settings.load()
                options["game_trust"] = True  # keep trust in sync on every server start
                settings.save(options)
                def done():
                    finished()
                    message = (tr('Сертификат готов. SHA-256: {0}\nСкопируйте строку запуска с главного экрана в параметры игры в Steam.', result.fingerprint)
                               if plat.is_linux() else
                               tr('CA сервера установлен в Windows. SHA-256: {0}\nЗапусти игру заново с -jbg.config serverUrl, равным IP сервера.', result.fingerprint))
                    messagebox.showinfo(tr('Сертификат LocalBox'), message, parent=root)
                call_ui(0, done)
            in_thread(apply)

        def inspect():
            try:
                log(tr('Проверяю CA работающего сервера…'))
                plan = cert_trust.prepare(host)
            except Exception as error:
                failed(error)
                return
            call_ui(0, lambda: confirm(plan))
        in_thread(inspect)

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
        options = settings.load()
        if closing.is_set() or state.get("engine") is not source_engine or not options.get("qr_overlay", True):
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
                text=tr('Отсканируйте для входа · {0}/{1}', room['playerCount'], room['maxPlayers'])
            )
            win.update_idletasks()
            width, height = win.winfo_reqwidth(), win.winfo_reqheight()
            fallback = qr.Monitor(root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height())
            anchor = (fallback.x + fallback.width // 2, fallback.y + fallback.height // 2)
            x, y = qr.overlay_position(width, height, monitors, anchor, fallback, options.get("qr_position"))
            win.geometry(f"{width}x{height}+{x}+{y}")
            win.deiconify()
            win.lift()
            try:
                win.attributes("-topmost", True)
            except tk.TclError:
                pass
            state["qr_code"] = (room["code"], room["joinUrl"])
        except tk.TclError as error:
            log(tr('[qr] не удалось показать оверлей: {0}', error))

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
                        log(tr('[qr] Не удалось получить QR-код: ') + message)
                finally:
                    state["qr_busy"] = False
            threading.Thread(target=fetch_status, daemon=True).start()
        scheduled_jobs["qr"] = root.after(1000, poll_qr)

    def on_start():
        if update_state["busy"]:
            feedback_var.set(tr('Дождитесь окончания проверки или загрузки обновления.'))
            return
        if state["engine"]:
            on_stop()
            return
        host = url_var.get().strip() or "localhost"
        state["starting"] = True
        server_appearance("starting")
        feedback_var.set(tr('Подготавливаем сервер…'))
        def w():
            if not engine.allow_privileged_ports(log=log):
                log(tr('Без портов 80/443 игра не подключится к адресу без номера порта.'))
                call_ui(0, lambda: start_btn.set_enabled(True)); return
            # Reuse valid certificates, and always prepare the game-local CA file.
            if not certs.ensure_cert(host, log=log, extra_names=[plat.local_ip()]):
                call_ui(0, lambda: start_btn.set_enabled(True)); return
            if settings.load().get("game_trust"):
                game_trust.heal(log=log)  # keep the CA trusted by all Jackbox builds
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
                    log(tr('Игрокам: http://{0}', host))
                    def started():
                        state["starting"] = False
                        refresh_address()  # the game CA file now exists: show the full Linux line
                        server_appearance("running")
                        feedback_var.set(tr('Сервер запущен. Откройте Jackbox и создайте комнату.'))
                    call_ui(0, started)
        in_thread(w, start_btn)

    def on_stop():
        with lifecycle_lock:
            if state["engine"]:
                state["engine"].stop(); state["engine"] = None
        hide_qr()
        state["starting"] = False
        server_appearance("stopped")
        feedback_var.set(tr('Сервер остановлен'))

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
        language_var = tk.StringVar(value=LANGUAGES[language()])
        server_url_var = tk.StringVar(value=(cfg.get("server_url") or plat.local_ip()).strip())
        qr_var = tk.BooleanVar(value=cfg.get("qr_overlay", True))
        qr_position_var = tk.StringVar(value=tr(dict(QR_POSITIONS).get(cfg.get("qr_position"), QR_POSITIONS[0][1])))
        auto_start_var = tk.BooleanVar(value=cfg.get("auto_start_full", False))
        dl_var = tk.BooleanVar(value=cfg.get("download_missing", True))
        game_images_var = tk.BooleanVar(value=cfg.get("download_game_images", True))
        porthole_var = tk.BooleanVar(value=cfg.get("porthole_enabled", True))
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
        title_lbl = tk.Label(settings_header, text=tr('Настройки'), bg=BG, fg=FG,
                             font=(FONT, 22, "bold"))
        title_lbl.pack(side="left", anchor="w")
        close_btn = RoundedButton(settings_header, tr('← Назад'), command=win.destroy,
                                  width=100, height=40, radius=12)
        close_btn.pack(side="right")
        tk.Label(outer, text=tr('Настройте LocalBox под вашу компанию.'), bg=BG, fg=MUTED,
                 font=(FONT, 10)).pack(anchor="w", pady=(0, 20))

        # Кнопки паркуем СНИЗУ и упаковываем РАНЬШЕ прокручиваемой области — тогда их место
        # всегда зарезервировано (не съедается контентом), и «Сохранить» не может пропасть
        # с экрана, даже если настроек слишком много для маленького/маленького-разрешения экрана.
        bar = tk.Frame(outer, bg=BG)
        bar.pack(fill="x", side="bottom", pady=(16, 0))
        settings_feedback = tk.StringVar(value=tr('Изменения применятся после\nперезапуска сервера.'))
        tk.Label(bar, textvariable=settings_feedback, bg=BG, fg=MUTED, justify="left",
                 font=(FONT, 9), wraplength=230).pack(side="left")
        save_btn = RoundedButton(bar, tr('Сохранить'), command=lambda: save_close(),
                                 width=174, height=46, radius=12, fill=ACC,
                                 hover=ACC_HOVER, foreground=BG)
        save_btn.pack(side="right")

        tab_bar = tk.Frame(outer, bg=BG)
        tab_bar.pack(fill="x", pady=(0, 14))
        tab_buttons = []
        for index, name in enumerate((tr('Сервер'), tr('Озвучка'), tr('Додо Ре Ми'), tr('Оверлей'))):
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
                if not closing.is_set() and main_view.winfo_exists():
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
        ttk.Label(card, text=tr('Сервер и вход игроков'), style="Card.TLabel",
                  font=(FONT, 14, "bold")).pack(anchor="w")
        ttk.Label(card, text=tr("Язык интерфейса"), style="Card.TLabel").pack(anchor="w", pady=(12, 5))
        language_combo = ttk.Combobox(card, textvariable=language_var, state="readonly",
                                     values=list(LANGUAGES.values()))
        language_combo.pack(fill="x")
        def change_language(_event=None):
            previous = language()
            selected = next(code for code, name in LANGUAGES.items() if name == language_var.get())
            if selected == previous:
                return
            saved = settings.load()
            saved["language"] = selected
            if not settings.save(saved):
                language_var.set(LANGUAGES[previous])
                settings_feedback.set(tr('Ошибка сохранения.\nПроверьте права на папку launcher.'))
                return
            translations.set_language(selected)
            if selected == "ru":
                download_ru_btn.grid()
            else:
                download_ru_btn.grid_remove()
            refresh_address()
            root.update_idletasks()
            resize_main()
            feedback_var.set(tr("Язык интерфейса изменён."))
        language_combo.bind("<<ComboboxSelected>>", change_language)
        ttk.Label(card, text=tr("Язык меняется сразу и сохраняется автоматически."),
                  style="Card.TLabel", foreground=MUTED, wraplength=WRAP).pack(anchor="w", pady=(4, 0))
        ttk.Label(card, text=tr('Адрес сервера (IP)'), style="Card.TLabel").pack(anchor="w", pady=(12, 5))
        ttk.Entry(card, textvariable=server_url_var).pack(fill="x")
        ttk.Label(card, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text=tr('Укажите локальный IP этого компьютера. Этот же адрес нужен в параметре запуска игры в Steam. Команду можно скопировать на главном экране.')
                  ).pack(anchor="w", pady=(4, 8))
        ttk.Checkbutton(card, text=tr('Показывать QR-код комнаты поверх игры'),
                        variable=qr_var, style="Card.TCheckbutton").pack(anchor="w")
        qr_position_row = ttk.Frame(card, style="Card.TFrame")
        qr_position_row.pack(anchor="w", pady=(3, 3))
        ttk.Label(qr_position_row, text=tr('Положение QR-кода:'), style="Card.TLabel").pack(side="left")
        ttk.Combobox(qr_position_row, textvariable=qr_position_var, state="readonly", width=16,
                     values=[tr(label) for _, label in QR_POSITIONS]).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(card, text=tr('Автоматически начать игру, когда комната\nзаполнена'),
                        variable=auto_start_var, style="Card.TCheckbutton").pack(anchor="w", pady=(3, 0))
        ttk.Label(card, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text=tr('QR открывает локальный сайт с уже введённым кодом. Автостарт нажимает действие VIP «Все в сборе», когда достигнут лимит игроков.')
                  ).pack(anchor="w", pady=(5, 8))
        ttk.Checkbutton(card, text=tr('Поддержка Porthole (друзья через интернет)'),
                        variable=porthole_var, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Label(card, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text=tr('Показывает на главном экране порт и ссылку для друга. Если выключить, строка Porthole скрывается и дополнительный веб-порт не открывается; обычный порт 80 работает как прежде.')
                  ).pack(anchor="w", pady=(5, 8))
        ttk.Checkbutton(card, text=tr('Скачивать недостающие текстуры с jackbox.ru'),
                        variable=dl_var, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(card, text=tr('Скачивать изображения игр и emoji'),
                        variable=game_images_var, style="Card.TCheckbutton").pack(anchor="w", pady=(6, 0))
        ttk.Label(card, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text=tr('Изображения игр скачиваются с CDN Jackbox и сохраняются в кэш; селфи остаются на сервере. Для игры без интернета отключите обе галочки: доступны будут только уже сохранённые файлы. Телефоны подключаются по локальной сети.')
                  ).pack(anchor="w", pady=(6, 0))
        service_buttons = ttk.Frame(card, style="Card.TFrame")
        service_buttons.pack(anchor="w", pady=(10, 0))
        cert_settings_btn = ttk.Button(service_buttons, text=tr('Обновить сертификат'))
        cert_settings_btn.pack(side="left")
        ports_settings_btn = ttk.Button(service_buttons, text=tr('Права на порты'))
        ports_settings_btn.pack(side="left", padx=(6, 0))
        cert_settings_btn.configure(command=lambda: on_cert(cert_settings_btn, server_url_var.get()))
        ports_settings_btn.configure(command=lambda: on_ports(ports_settings_btn))

        # --- озвучка (TTS) ---
        card2 = ttk.Frame(left, style="Card.TFrame", padding=20)
        card2.pack(fill="x", pady=(14, 0))
        card2.columnconfigure(0, weight=1)
        ttk.Label(card2, text=tr('Голос вашей игры'), style="Card.TLabel",
                  font=(FONT, 14, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 16))
        ttk.Label(card2, text=tr('Движок'), style="Card.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(0, 5))
        ttk.Combobox(card2, textvariable=tts_var, state="readonly", width=18,
                     values=settings.TTS_ENGINES).grid(row=2, column=0, columnspan=4, sticky="ew")
        ttk.Label(card2, text=tr('Голос'), style="Card.TLabel").grid(
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

        listen_btn = ttk.Button(card2, text=tr('▶ Прослушать'))
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
                  text=tr('silero — нейроголос (офлайн; pip install torch numpy). piper — нейроголос, легче/быстрее (pip install piper-tts). espeak — робо-голос. silent — без голоса. auto — silero → piper → espeak.')
                  ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Label(card2, text=tr('Python для TTS'), style="Card.TLabel").grid(
            row=6, column=0, columnspan=4, sticky="w", pady=(12, 5))
        ttk.Entry(card2, textvariable=tts_python_var).grid(
            row=7, column=0, columnspan=4, sticky="ew")
        ttk.Label(card2, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text=tr('Пусто = python лаунчера. Укажи путь к python из venv (напр. 3.11/3.12), если основной python слишком новый и ML-библиотеки (torch/coqui) не ставятся.')
                  ).grid(row=8, column=0, columnspan=4, sticky="w", pady=(5, 0))

        # --- Додо Ре Ми (nopus-opus) ---
        card3 = ttk.Frame(right, style="Card.TFrame", padding=20)
        card3.pack(fill="x", pady=(14, 0))
        ttk.Label(card3, text=tr('Музыка в Додо Ре Ми'), style="Card.TLabel",
                  font=(FONT, 14, "bold")).pack(anchor="w", pady=(0, 12))
        ttk.Checkbutton(card3, text=tr('Собирать выступления на этом компьютере'),
                        variable=dodo_var, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Label(card3, text=tr('Папка Jackbox 10 или games/NopusOpus/songs:'), style="Card.TLabel").pack(anchor="w", pady=(10, 2))
        game_row = ttk.Frame(card3, style="Card.TFrame")
        game_row.pack(fill="x")
        ttk.Entry(game_row, textvariable=game_path_var).pack(side="left", fill="x", expand=True)
        def select_dodo_game():
            from tkinter import filedialog
            directory = filedialog.askdirectory(parent=root, title=tr('Папка Jackbox 10 или songs'),
                                                initialdir=game_path_var.get() or str(plat.repo_root()))
            if directory:
                game_path_var.set(directory)
        ttk.Button(game_row, text=tr('Выбрать'), command=select_dodo_game).pack(side="right", padx=(6, 0))
        import_status = tk.StringVar()
        def copy_dodo_music():
            directory = game_path_var.get().strip()
            if not directory:
                import_status.set(tr('Сначала выбери папку Jackbox 10 или songs.'))
                return
            try:
                dodo.songs_directory(directory)
            except (ValueError, OSError) as error:
                import_status.set(str(error))
                return
            import_button.configure(state="disabled")
            import_status.set(tr('Копируем музыку…'))
            def work():
                try:
                    count = dodo.import_dodo(directory, plat.repo_root(), log)
                    def done():
                        dodo_var.set(True)
                        import_status.set(tr('Скопировано файлов музыки: {0}. Нажми «Сохранить».', count))
                    call_ui(0, done)
                except (ValueError, OSError) as error:
                    message = str(error)
                    call_ui(0, lambda: import_status.set(message))
            in_thread(work, import_button)
        import_button = ttk.Button(card3, text=tr('Импортировать музыку'), command=copy_dodo_music)
        import_button.pack(anchor="w", pady=(6, 0))
        ttk.Label(card3, textvariable=import_status, style="Card.TLabel", foreground=MUTED,
                  wraplength=WRAP).pack(anchor="w", pady=(4, 0))
        ttk.Label(card3, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text=tr('Музыка и сэмплы копируются в LocalBox по кнопке. Файлы игры сохраняются. Нужен ffmpeg в PATH или runtime/. Без музыки звучат только сыгранные ноты.')
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
                log(tr('{0}: {1} (открыть не удалось: {2})', label, d, e))

        dodo_btns = ttk.Frame(card3, style="Card.TFrame")
        dodo_btns.pack(anchor="w", pady=(8, 0))
        ttk.Button(dodo_btns, text=tr('Открыть папку песен'),
                   command=lambda: open_folder(plat.repo_root() / "server" / "render" / "nopus-opus" / "songs",
                                                tr('Папка бэкингов'))).pack(fill="x")
        ttk.Button(dodo_btns, text=tr('Открыть runtime для ffmpeg'),
                   command=lambda: open_folder(plat.repo_root() / "runtime",
                                                tr('Папка runtime'))).pack(fill="x", pady=(6, 0))

        # Громкость рендера (инструмент / бэкинг) — ползунки.
        vol = ttk.Frame(card3, style="Card.TFrame")
        vol.pack(fill="x", pady=(10, 0))
        instr_lbl = ttk.Label(vol, style="Card.TLabel", text=tr('Громкость инструмента: {0:.1f}', instr_var.get()))
        instr_lbl.grid(row=0, column=0, sticky="w")
        ttk.Scale(vol, from_=1.0, to=10.0, variable=instr_var, orient="horizontal",
                  command=lambda v: instr_lbl.configure(text=tr('Громкость инструмента: {0:.1f}', float(v)))
                  ).grid(row=1, column=0, sticky="ew", pady=(0, 6))
        back_lbl = ttk.Label(vol, style="Card.TLabel", text=tr('Громкость бэкинга (музыки): {0:.2f}', back_var.get()))
        back_lbl.grid(row=2, column=0, sticky="w")
        ttk.Scale(vol, from_=0.0, to=1.0, variable=back_var, orient="horizontal",
                  command=lambda v: back_lbl.configure(text=tr('Громкость бэкинга (музыки): {0:.2f}', float(v)))
                  ).grid(row=3, column=0, sticky="ew")
        vol.columnconfigure(0, weight=1)
        ttk.Label(card3, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text=tr('Инструмент громче = отчётливее ноты; бэкинг тише = меньше музыки. Применяется к следующему рендеру.')
                  ).pack(anchor="w", pady=(4, 0))

        # --- Читы (оверлей в игре) ---
        card4 = ttk.Frame(right, style="Card.TFrame", padding=20)
        card4.pack(fill="x", pady=(14, 0))
        ttk.Label(card4, text=tr('Оверлей и код комнаты'), style="Card.TLabel",
                  font=(FONT, 14, "bold")).pack(anchor="w", pady=(0, 10))
        ttk.Label(card4, text=tr('Ники с читами (через запятую):'), style="Card.TLabel").pack(anchor="w", pady=(6, 2))
        ttk.Entry(card4, textvariable=admin_var).pack(fill="x")
        ttk.Checkbutton(card4, text=tr('Подсвечивать найденные правильные варианты\nна кнопках в игре'),
                        variable=cheat_highlight_var, style="Card.TCheckbutton").pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(card4, text=tr('Показывать правильные ответы в панели'),
                        variable=cheat_answer_var, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(card4, text=tr('Показывать цену картины (Дуракцион) —\nценник у картины'),
                        variable=cheat_price_var, style="Card.TCheckbutton").pack(anchor="w")
        ttk.Label(card4, text=tr('Папка со всеми Jackbox или отдельной игрой (пусто = Steam):'), style="Card.TLabel").pack(anchor="w", pady=(8, 2))
        content_row = ttk.Frame(card4, style="Card.TFrame")
        content_row.pack(fill="x")
        ttk.Entry(content_row, textvariable=cheat_content_var).pack(side="left", fill="x", expand=True)
        def select_cheat_content():
            from tkinter import filedialog
            directory = filedialog.askdirectory(parent=root, title=tr('Папка с играми Jackbox или steamapps/common'),
                                                initialdir=cheat_content_var.get() or str(plat.repo_root()))
            if directory:
                cheat_content_var.set(directory)
        ttk.Button(content_row, text=tr('Выбрать'), command=select_cheat_content).pack(side="right", padx=(6, 0))
        ttk.Label(card4, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text=tr('Кто вписан — заходит в игру под этим ником и получает оверлей читов (вкладка справа, или Ctrl+Shift+K): God view (секретные ответы/голоса/рисунки всех), подсветка правильного ответа, подмена значений, кик/бан/мьют. Для Бредовухи и Смертельной вечеринки ответы читаются из файлов игры: выбери папку с тем же переводом. В Дуракционе видны оценки картин, переданные игрокам. Пустой список ников = читы выключены.')
                  ).pack(anchor="w", pady=(6, 0))
        # --- Код комнаты ---
        ttk.Label(card4, text=tr('Код комнаты (пусто = случайный):'), style="Card.TLabel").pack(anchor="w", pady=(10, 2))
        ttk.Entry(card4, textvariable=room_code_var).pack(fill="x")
        ttk.Label(card4, style="Card.TLabel", foreground=MUTED, justify="left", wraplength=WRAP,
                  text=tr('Свой фиксированный код вместо случайного (напр. ИГРА или GAME). Русские буквы можно, но телефон-клиент игры может не дать их ввести — тогда используй латиницу.')
                  ).pack(anchor="w", pady=(4, 0))

        def save_close():
            host = server_url_var.get().strip() or plat.local_ip()
            cfg["server_url"] = host
            cfg["qr_overlay"] = qr_var.get()
            cfg["qr_position"] = next((code for code, label in QR_POSITIONS
                                       if qr_position_var.get() in (label, tr(label))), QR_POSITIONS[0][0])
            cfg["auto_start_full"] = auto_start_var.get()
            cfg["download_missing"] = dl_var.get()
            cfg["download_game_images"] = game_images_var.get()
            cfg["porthole_enabled"] = porthole_var.get()
            cfg["tts_engine"] = tts_var.get()
            cfg["tts_voice"] = voice_var.get()
            cfg["tts_python"] = tts_python_var.get().strip()
            content_path = cheat_content_var.get().strip()
            if content_path and not os.path.isdir(os.path.expanduser(content_path)):
                settings_feedback.set(tr('Папка с играми для читов не найдена.'))
                return
            game_path = game_path_var.get().strip()
            if game_path and not os.path.isdir(os.path.expanduser(game_path)):
                settings_feedback.set(tr('Папка Jackbox 10 не найдена.'))
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
            cfg["language"] = next(code for code, name in LANGUAGES.items() if name == language_var.get())
            if not settings.save(cfg):
                log(tr('Не удалось сохранить настройки. Проверьте права на папку launcher.'))
                settings_feedback.set(tr('Ошибка сохранения.\nПроверьте права на папку launcher.'))
                return
            url_var.set(host)
            state["apply_porthole"]()
            log(tr('Настройки сохранены (озвучка: {0} / {1}). Применятся при следующем запуске сервера.', tts_var.get(), voice_var.get()))
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

    def on_download_russian():
        if language() != "ru":
            return
        if state["client_busy"] or update_state["busy"]:
            return
        state["client_busy"] = True
        download_ru_btn.configure(state="disabled", text=tr('Скачиваю клиент…'))
        update_btn.configure(state="disabled")
        feedback_var.set(tr('Ищу Release с архивом русского клиента…'))
        def work():
            message = ""
            installed = False
            reused = False
            try:
                manager = updates.russian_client()
                info = manager.release_info()
                reused = manager.already_installed(plat.repo_root() / "client-ru", info)
                manager.install_client(plat.repo_root(), info=info, log=log)
                installed = True
                message = tr('Русский клиент Release {0} {1}.', info['tag'], tr('уже установлен') if reused else tr('установлен'))
            except Exception as error:
                message = tr('Не удалось скачать русский клиент: ') + str(error)
                log(message)
            finally:
                def finished():
                    state["client_busy"] = False
                    download_ru_btn.configure(state="normal", text=tr('Скачать русский клиент'))
                    update_btn.configure(state="normal")
                    suffix = tr(' Перезапусти сервер, чтобы использовать его.') if installed and not reused and state["engine"] else ""
                    feedback_var.set(message + suffix)
                call_ui(0, finished)
        threading.Thread(target=work, daemon=True).start()
    download_ru_btn.configure(command=on_download_russian)

    def on_update():
        if update_state["busy"] or state["starting"] or state["client_busy"]:
            return
        update_state["busy"] = True
        update_btn.configure(state="disabled")
        download_ru_btn.configure(state="disabled")
        release = update_state["release"]
        feedback_var.set(tr('Скачиваю обновление…') if release else tr('Проверяю новые Releases…'))
        def work():
            directory = None
            handed_off = False
            try:
                manager = updates.updater()
                if release is None:
                    available = manager.latest_release(plat.repo_root())
                    def checked():
                        update_state["release"] = available
                        if available:
                            update_btn.configure(text=tr('Обновить до {0}', available['tag_name']))
                            feedback_var.set(tr('Доступна новая версия. Кнопка обновления установит её и перезапустит лаунчер.'))
                        else:
                            feedback_var.set(tr('Новых выпусков нет. LocalBox {0}.', manager.current_version(plat.repo_root())))
                    call_ui(0, checked)
                else:
                    directory = updates.temporary_directory()
                    archive = manager.download_release(release, directory / manager.ASSET_NAME, log)
                    if closing.is_set():
                        return
                    def ready():
                        try:
                            on_stop()
                            updates.launch(archive, release["tag_name"], directory)
                            on_close()
                        except Exception as error:
                            import shutil
                            shutil.rmtree(directory, ignore_errors=True)
                            log(tr('Не удалось запустить обновление: {0}', error))
                    call_ui(0, ready)
                    handed_off = True
            except Exception as error:
                log(tr('Не удалось обновить LocalBox: {0}', error))
            finally:
                if directory is not None and not handed_off:
                    import shutil
                    shutil.rmtree(directory, ignore_errors=True)
                def finished():
                    update_state["busy"] = False
                    update_btn.configure(state="normal")
                    download_ru_btn.configure(state="normal")
                call_ui(0, finished)
        threading.Thread(target=work, daemon=True).start()
    update_btn.configure(command=on_update)

    def on_close():
        closing.set()
        for job in scheduled_jobs.values():
            if job is not None:
                root.after_cancel(job)
        on_stop(); root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)

    drain()
    poll_qr()
    log(tr('Готово. Нажмите «Запустить» — сертификат и права проверятся автоматически.'))
    if cfg0.get("game_profile") == "tmp3":
        log(tr('TMP3: после настройки подключения запусти игру через Steam и выбери локальную игру.'))
    else:
        log(tr('В игре Steam: параметры запуска  ') + command_var.get())
    if not engine.engine_dir().exists():
        log(tr('ВНИМАНИЕ: папка server/ не найдена — движок не установлен.'))
    root.mainloop()


def check_environment():
    print(tr('ОС: {0}', plat.os_name()))
    print(f"node: {engine.find_node() or tr('НЕ найден')}")
    print(tr('Движок: {0} ({1})', engine.engine_dir(), tr('есть') if engine.engine_dir().exists() else tr('НЕТ')))
    print(tr('Зависимости движка: {0}', tr('установлены') if engine.deps_installed() else tr('нет (нужен npm i)')))
    print(tr('Клиент: {0} ({1})', engine.client_dir(), tr('есть') if engine.client_dir().exists() else tr('НЕТ')))
    print(tr('Локальный IP: {0}', plat.local_ip()))
    print(tr('Права администратора: {0}', plat.has_admin()))


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
            o["local"] = True  # полностью локально: не докачивать текстуры и игровые фото
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
            cfg["download_game_images"] = not local
        if tts is not None:
            cfg["tts_engine"] = tts
        if voice is not None:
            cfg["tts_voice"] = voice
        settings.save(cfg)
    cfg = settings.load()
    fully_local = not (cfg.get("download_missing", True) or cfg.get("download_game_images", True))
    print(tr('== LocalBox (сервер) == адрес: {0} | веб-клиент: {1} | режим: {2}', ip, tr('выкл') if no_web else tr('вкл'), tr('полностью локально') if fully_local else tr('докачка вкл')))

    if not engine.engine_dir().exists():
        print(tr('Движок не найден (server/). Скачайте исходники целиком.')); sys.exit(1)
    if not engine.find_node():
        print(tr('Node.js не найден. Установите node или положите его в ./runtime/. См. README.')); sys.exit(1)

    # 1) сертификат и отдельный публичный файл доверия для игры
    if not certs.ensure_cert(ip, log=print, extra_names=[plat.local_ip(), "localhost"]):
        sys.exit(1)
    if cfg.get("game_trust"):
        game_trust.heal(log=print)
    # 2) конфиг движка
    if not engine.write_config(ip, log=print):
        sys.exit(1)
    # 3) права на порты 80/443
    if not plat.has_admin():
        print(tr('Порты 80/443 требуют прав. Выдаю node право (нужен sudo/pkexec)…'))
        if not engine.allow_privileged_ports(log=print):
            print(tr('Вручную: sudo setcap cap_net_bind_service=+ep "$(command -v node)"'))
            sys.exit(1)
    # 4) зависимости
    if not engine.deps_installed() and not engine.install_deps(log=print):
        print(tr('Не удалось установить зависимости движка.')); sys.exit(1)
    # 5) запуск (блокирующе, до Ctrl+C)
    proc = engine.EngineProcess(ip, on_log=print, no_web=no_web)
    if not proc.start():
        sys.exit(1)
    if cfg.get("game_profile") == "tmp3":
        print(tr('Сервер запущен. TMP3: запуск через Steam → локальная игра. (Ctrl+C — остановить)'))
    else:
        print(tr('Сервер запущен. Игра: ') + game_tls.steam_launch_options(ip) + tr('   (Ctrl+C — остановить)'))
    print(tr('Игрокам: http://') + ip)
    try:
        while proc.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        print(tr('\nОстанавливаю…'))
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
                print(tr('Не удалось сохранить выбор Додо Ре Ми.'))
                sys.exit(1)
    if o["check"]:
        check_environment()
        return
    # Серверный/headless режим: явный флаг или нет графической сессии.
    if o["server"] and o["gui"]:
        print(tr('Выберите один режим: --gui или --server.'))
        sys.exit(1)
    if o["gui"] and _no_display():
        print(tr('GUI недоступен без графической сессии. Запустите --server.'))
        sys.exit(1)
    if o["server"] or (_no_display() and not o["gui"]):
        run_server_cli(o["ip"], o["no_web"], o["local"], o["tts"], o["voice"])
        return
    try:
        run_gui()
    except Exception as e:  # noqa: BLE001
        if o["gui"]:
            print(tr('Не удалось открыть GUI: {0}. Проверьте tkinter и графическую сессию.', e))
            sys.exit(1)
        print(tr('Не удалось открыть GUI ({0}). Перехожу в серверный режим.', e))
        print(tr('Подсказка: GUI требует tkinter (Arch: sudo pacman -S tk) и дисплей.'))
        run_server_cli(o["ip"], o["no_web"], o["local"], o["tts"], o["voice"])


if __name__ == "__main__":
    main()
