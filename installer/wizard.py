#!/usr/bin/env python3
"""One-window download settings for LocalBox, using the desktop colour scheme."""

import argparse
import os
import queue
import subprocess
import threading
from pathlib import Path

from install import install, songs_directory, PIPER_VOICES, SOURCE, read_json
from setup.i18n import tr
from theme import detect_dark
from window import fit_window


def run_wizard(target=None, runtime=None, game=None, dodo=False, russian=False, run_after=False,
               tts="piper", voices=None, cheat_content=None, tmp3_game=None, language=None, trust=True):
    import tkinter as tk
    from tkinter import filedialog, ttk
    from tkinter.font import nametofont

    from setup import i18n
    root = tk.Tk()
    root.withdraw()
    if language:
        i18n.set_language(language)
    elif not i18n.choose_language(root):
        root.destroy()
        return
    root.deiconify()
    root.title("LocalBox")
    _, available_height = fit_window(root)
    compact = available_height < 520
    font = nametofont("TkDefaultFont").actual("family")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=(font, 8 if compact else 10))
    style.configure("TButton", padding=(8, 3 if compact else 5))
    style.configure("TEntry", padding=3 if compact else 5)
    style.configure("TCombobox", padding=3 if compact else 5)
    style.configure("TCheckbutton", padding=(0, 2))
    style.configure("Title.TLabel", font=(font, 17 if compact else 21, "bold"))
    style.configure("Section.TLabel", font=(font, 10, "bold"))
    style.configure("Download.TButton", padding=(18, 5))

    body = ttk.Frame(root, padding=(12, 8) if compact else (20, 14))
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="LocalBox", style="Title.TLabel").pack(anchor="w", pady=(0, 8))
    footer = ttk.Frame(body)
    footer.pack(side="bottom", fill="x", pady=(12, 0))
    status = tk.StringVar(value=tr('Зависимости и выбранные голоса скачаются автоматически.'))
    status_label = tk.Label(footer, textvariable=status, height=2, anchor="w", justify="left",
                            font=(font, 8 if compact else 10), wraplength=420)
    status_label.pack(side="left", fill="x", expand=True, padx=(0, 16))
    action = ttk.Button(footer, text=tr('Скачать'), style="Download.TButton", width=17)
    action.pack(side="right")
    progressbar = ttk.Progressbar(body, mode="indeterminate")
    details = tk.Toplevel(root)
    details.title(tr('LocalBox — журнал установки'))
    details.geometry(f"{min(720, root.winfo_screenwidth()-24)}x{min(360, root.winfo_screenheight()-64)}")
    details.withdraw()
    details.protocol("WM_DELETE_WINDOW", details.withdraw)
    log_view = tk.Text(details, relief="flat", borderwidth=1, padx=8, pady=8,
                       wrap="word", font=(font, 9), state="disabled")
    scrollbar = ttk.Scrollbar(details, command=log_view.yview)
    scrollbar.pack(side="right", fill="y")
    log_view.configure(yscrollcommand=scrollbar.set)
    log_view.pack(fill="both", expand=True)
    def toggle_details():
        details.deiconify()
        details.lift()
    detail_toggle = ttk.Button(footer, text=tr('Журнал'), command=toggle_details)
    detail_toggle.pack(side="right", padx=(0, 8))
    settings_host = ttk.Frame(body)
    settings_host.pack(fill="both", expand=True)
    settings_host.columnconfigure((0, 1), weight=1, uniform="settings")
    left = ttk.Frame(settings_host)
    left.grid(row=0, column=0, sticky="new", padx=(0, 10))
    right = ttk.Frame(settings_host)
    right.grid(row=0, column=1, sticky="new", padx=(10, 0))
    for column in (left, right):
        column.columnconfigure(0, weight=1)
        def wrap_labels(event, parent=column):
            for widget in parent.winfo_children():
                if isinstance(widget, ttk.Label):
                    widget.configure(wraplength=max(100, event.width - 4))
        column.bind("<Configure>", wrap_labels)

    app_path = tk.StringVar(value=str(target or SOURCE))
    runtime_path = tk.StringVar(value=str(runtime or Path(app_path.get()) / "runtime"))
    try:
        previous = read_json(Path(app_path.get()) / "launcher" / "localbox-settings.json")
    except (ValueError, OSError):
        previous = {}
    game_path = tk.StringVar(value=str(game if game is not None else previous.get("jackbox10_path", "")))
    dodo_var = tk.BooleanVar(value=bool(dodo or game or previous.get("dodo_render")))
    cheat_path = tk.StringVar(value=str(cheat_content if cheat_content is not None else previous.get("cheat_content_dir", "")))
    cheat_var = tk.BooleanVar(value=bool(cheat_path.get()))
    tmp3_path = tk.StringVar(value=str(tmp3_game or previous.get("tmp3_path", "")))
    tmp3_var = tk.BooleanVar(value=bool(tmp3_game))
    trust_var = tk.BooleanVar(value=bool(trust))
    ru_var = tk.BooleanVar(value=russian and i18n.language() == "ru")
    default_runtime = [runtime_path.get()]
    def app_changed(*_):
        if runtime_path.get() == default_runtime[0]:
            default_runtime[0] = str(Path(app_path.get()) / "runtime")
            runtime_path.set(default_runtime[0])
        try:
            saved = read_json(Path(app_path.get()) / "launcher" / "localbox-settings.json")
        except (ValueError, OSError):
            return
        if saved:
            tmp3_path.set(saved.get("tmp3_path", ""))
            game_path.set(saved.get("jackbox10_path", ""))
            dodo_var.set(bool(saved.get("dodo_render")))
            cheat_path.set(saved.get("cheat_content_dir", ""))
            cheat_var.set(bool(cheat_path.get()))
    app_path.trace_add("write", app_changed)

    editable = []
    def path_field(parent, label, variable, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 3))
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row + 1, column=0, sticky="ew")
        def browse():
            chosen = filedialog.askdirectory(parent=root, title=label,
                                             initialdir=variable.get() or str(Path.home()))
            if chosen:
                variable.set(chosen)
        button = ttk.Button(parent, text="…", command=browse, width=3)
        button.grid(row=row + 1, column=1, padx=(8, 0))
        editable.extend((entry, button))
        return entry, button

    path_field(left, tr('Куда скачать LocalBox'), app_path, 0)
    path_field(left, tr('Зависимости и TTS'), runtime_path, 2)
    ttk.Label(left, text=tr('Озвучка'), style="Section.TLabel").grid(
        row=4, column=0, columnspan=2, sticky="w", pady=(10, 4))
    engines = {tr('Piper — нейроголоса'): "piper", tr('Silero — русские нейроголоса'): "silero",
               "Piper + Silero": "both", tr('Без озвучки'): "none"}
    if os.name != "nt":
        engines[tr('eSpeak — лёгкий голос')] = "espeak"
    tts_var = tk.StringVar(value=next((label for label, code in engines.items() if code == tts), next(iter(engines))))
    combo = ttk.Combobox(left, textvariable=tts_var, state="readonly", values=list(engines))
    combo.grid(row=5, column=0, columnspan=2, sticky="ew")
    voice_frame = ttk.Frame(left)
    voice_frame.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
    voice_vars, voice_checks = {}, []
    requested = set(voices if voices is not None else [PIPER_VOICES[0]])
    for index, (voice, label) in enumerate(zip(PIPER_VOICES, (tr('Денис'), tr('Дмитрий'), tr('Ирина'), tr('Руслан')))):
        value = tk.BooleanVar(value=voice in requested)
        voice_vars[voice] = value
        check = ttk.Checkbutton(voice_frame, text=label, variable=value)
        check.grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 12))
        voice_checks.append(check)
    def resize_footer(event):
        status_label.configure(wraplength=max(100, event.width - action.winfo_reqwidth() - detail_toggle.winfo_reqwidth() - 32))
    footer.bind("<Configure>", resize_footer)
    tts_hint = tk.StringVar()
    ttk.Label(left, textvariable=tts_hint, style="Muted.TLabel").grid(
        row=7, column=0, columnspan=2, sticky="w", pady=(3, 0))
    russian_check = ttk.Checkbutton(left, text=tr('Скачать русский веб-клиент'), variable=ru_var)
    russian_check.grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
    if i18n.language() != "ru":
        russian_check.grid_remove()
    editable.append(russian_check)

    trust_check = ttk.Checkbutton(left, text=tr('Сделать сертификат доверенным для игр Jackbox (рекомендуется)'), variable=trust_var)
    trust_check.grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))
    editable.append(trust_check)
    trust_hint = ttk.Label(left, text=tr('Windows один раз спросит подтверждение. Только там его ищут Windows-версии Jackbox.'),
                           style="Muted.TLabel", wraplength=300, justify="left")
    trust_hint.grid(row=10, column=0, columnspan=2, sticky="w", pady=(3, 0))
    if os.name != "nt":
        # Linux: nothing is installed; native packs use -cafile in the Steam launch line.
        trust_var.set(False)
        trust_check.grid_remove()
        trust_hint.grid_remove()

    tmp3_check = ttk.Checkbutton(right, text=tr('Патч Смертельной вечеринки 3'), variable=tmp3_var)
    tmp3_check.grid(row=0, column=0, columnspan=2, sticky="w", pady=(4, 0))
    editable.append(tmp3_check)
    tmp3_entry, tmp3_browse = path_field(right, tr('Папка Trivia Murder Party 3'), tmp3_path, 1)
    ttk.Label(right, text=tr('Закрой игру. Оригинал сохранится для отката.'), style="Muted.TLabel").grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(3, 0))
    dodo_check = ttk.Checkbutton(right, text=tr('Поддержка Додо Ре Ми'), variable=dodo_var)
    dodo_check.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
    editable.append(dodo_check)
    game_entry, game_browse = path_field(right, tr('Jackbox Party Pack 10 — необязательно'), game_path, 5)
    cheat_check = ttk.Checkbutton(right, text=tr('Папка с играми для читов'), variable=cheat_var)
    cheat_check.grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))
    editable.append(cheat_check)
    cheat_entry, cheat_browse = path_field(right, tr('Все Jackbox или отдельная игра'), cheat_path, 8)
    ttk.Label(right, text=tr('Без папки — поиск игр в Steam.'), style="Muted.TLabel").grid(
        row=10, column=0, columnspan=2, sticky="w", pady=(3, 0))

    events = queue.Queue()
    stopped = threading.Event()
    poll_job = [None]
    running = [False]
    installed_target = [None]
    palette = [{}]
    status_kind = ["muted"]

    def controls():
        locked = running[0] or installed_target[0] is not None
        for widget in editable:
            widget.configure(state="disabled" if locked else "normal")
        combo.configure(state="disabled" if locked else "readonly")
        code = engines[tts_var.get()]
        for check in voice_checks:
            check.configure(state="normal" if not locked and code in ("piper", "both") else "disabled")
        for widget in (game_entry, game_browse):
            widget.configure(state="normal" if not locked and dodo_var.get() else "disabled")
        for widget in (tmp3_entry, tmp3_browse):
            widget.configure(state="normal" if not locked and tmp3_var.get() else "disabled")
        for widget in (cheat_entry, cheat_browse):
            widget.configure(state="normal" if not locked and cheat_var.get() else "disabled")
        tts_hint.set(tr('Скачаются только отмеченные голоса.') if code in ("piper", "both") else
                     tr('Скачаются все встроенные русские голоса.') if code == "silero" else "")
    tts_var.trace_add("write", lambda *_: controls())
    dodo_var.trace_add("write", lambda *_: controls())
    tmp3_var.trace_add("write", lambda *_: controls())
    cheat_var.trace_add("write", lambda *_: controls())
    controls()

    def set_status(message, kind="muted"):
        status.set(message)
        status_kind[0] = kind
        status_label.configure(foreground=palette[0].get(kind, "#555555"))

    def apply_theme(dark):
        colors = ({"bg": "#202124", "field": "#2b2d31", "fg": "#f1f2f3", "muted": "#aeb4bd",
                   "border": "#42474e", "hover": "#373b42", "accent": "#78a9f5", "on_accent": "#122443",
                   "error": "#ffa59e", "success": "#93d9a7"} if dark else
                  {"bg": "#f5f5f5", "field": "#ffffff", "fg": "#202124", "muted": "#626872",
                   "border": "#c7ccd3", "hover": "#e6e9ef", "accent": "#2867c8", "on_accent": "#ffffff",
                   "error": "#b3261e", "success": "#267139"})
        palette[0] = colors
        root.configure(bg=colors["bg"])
        details.configure(bg=colors["bg"])
        status_label.configure(bg=colors["bg"])
        style.configure(".", background=colors["bg"], foreground=colors["fg"])
        for name in ("TFrame", "TLabel", "TCheckbutton"):
            style.configure(name, background=colors["bg"], foreground=colors["fg"])
        style.configure("Muted.TLabel", foreground=colors["muted"])
        for name in ("TEntry", "TCombobox"):
            style.configure(name, fieldbackground=colors["field"], foreground=colors["fg"],
                            background=colors["field"], insertcolor=colors["fg"], arrowcolor=colors["fg"],
                            bordercolor=colors["border"], lightcolor=colors["border"], darkcolor=colors["border"])
            style.map(name, fieldbackground=[("disabled", colors["bg"]), ("readonly", colors["field"])],
                      foreground=[("disabled", colors["muted"]), ("readonly", colors["fg"])],
                      selectbackground=[("readonly", colors["field"])], selectforeground=[("readonly", colors["fg"])])
        style.configure("TButton", background=colors["field"], foreground=colors["fg"],
                        bordercolor=colors["border"], lightcolor=colors["border"], darkcolor=colors["border"])
        style.map("TButton", background=[("active", colors["hover"])], foreground=[("disabled", colors["muted"])])
        style.configure("Download.TButton", background=colors["accent"], foreground=colors["on_accent"],
                        bordercolor=colors["accent"], lightcolor=colors["accent"], darkcolor=colors["accent"])
        style.map("Download.TButton", background=[("disabled", colors["border"]), ("active", colors["accent"])],
                  foreground=[("disabled", colors["muted"]), ("!disabled", colors["on_accent"])])
        style.configure("TCheckbutton", indicatorbackground=colors["field"], indicatorforeground=colors["on_accent"])
        style.map("TCheckbutton", background=[("active", colors["bg"])],
                  foreground=[("disabled", colors["muted"])],
                  indicatorbackground=[("disabled", colors["border"]), ("selected", colors["accent"])])
        style.configure("Horizontal.TProgressbar", background=colors["accent"], troughcolor=colors["field"],
                        bordercolor=colors["border"])
        style.configure("Vertical.TScrollbar", background=colors["field"], troughcolor=colors["bg"],
                        arrowcolor=colors["fg"], bordercolor=colors["border"])
        log_view.configure(bg=colors["field"], fg=colors["fg"], insertbackground=colors["fg"],
                           selectbackground=colors["accent"], selectforeground=colors["on_accent"])
        root.option_add("*TCombobox*Listbox.background", colors["field"])
        root.option_add("*TCombobox*Listbox.foreground", colors["fg"])
        try:
            popup = root.tk.call("ttk::combobox::PopdownWindow", str(combo))
            root.tk.call(str(popup) + ".f.l", "configure", "-background", colors["field"],
                         "-foreground", colors["fg"], "-selectbackground", colors["accent"],
                         "-selectforeground", colors["on_accent"])
        except tk.TclError:
            pass
        set_status(status.get(), status_kind[0])

    def follow_theme():
        previous = None
        while not stopped.is_set():
            dark = detect_dark()
            if dark != previous:
                events.put(("theme", dark))
                previous = dark
            stopped.wait(2)

    def log(message):
        print(message, flush=True)
        events.put(("log", str(message)))

    def close():
        if running[0]:
            set_status(tr('Скачивание ещё идёт. Дождитесь окончания.'))
            return
        stopped.set()
        if poll_job[0] is not None:
            root.after_cancel(poll_job[0])
        root.destroy()

    def launch():
        try:
            if os.name == "nt":
                os.startfile(str(installed_target[0] / "start-server.bat"))
            else:
                subprocess.Popen(["bash", str(installed_target[0] / "start-server.sh"), "--gui"])
        except OSError as error:
            set_status(tr('Не удалось открыть LocalBox: ') + str(error), "error")
            return
        close()

    def start_download():
        if running[0]:
            return
        if installed_target[0] is not None:
            launch()
            return
        try:
            if not app_path.get().strip() or not runtime_path.get().strip():
                raise ValueError(tr('Укажите папки для LocalBox и зависимостей.'))
            selected = [voice for voice, value in voice_vars.items() if value.get()]
            if engines[tts_var.get()] in ("piper", "both") and not selected:
                raise ValueError(tr('Выберите хотя бы один голос Piper.'))
            chosen_game = game_path.get().strip() if dodo_var.get() else ""
            if chosen_game:
                songs_directory(chosen_game)
            chosen_tmp3 = tmp3_path.get().strip() if tmp3_var.get() else ""
            if tmp3_var.get():
                from setup.tmp3 import game_root, game_running
                if not chosen_tmp3:
                    raise ValueError(tr('Выберите папку TMP3 или снимите галочку патча.'))
                game_root(chosen_tmp3)
                if game_running():
                    raise ValueError(tr('Закройте TMP3 перед установкой патча.'))
            chosen_content = cheat_path.get().strip() if cheat_var.get() else ""
            if cheat_var.get() and not chosen_content:
                raise ValueError(tr('Укажите папку с играми для читов или снимите галочку.'))
            if chosen_content and not Path(chosen_content).expanduser().is_dir():
                raise ValueError(tr('Папка с играми для читов не найдена.'))
        except (ValueError, OSError) as error:
            set_status(str(error), "error")
            return
        values = (app_path.get().strip(), runtime_path.get().strip(), engines[tts_var.get()], selected,
                  chosen_game or None, dodo_var.get(), ru_var.get())
        running[0] = True
        controls()
        action.configure(text=tr('Скачиваем…'), state="disabled")
        progressbar.pack(side="bottom", fill="x", pady=(6, 0), before=settings_host)
        progressbar.start(12)
        set_status(tr('Скачиваем и настраиваем LocalBox…'))
        log_view.configure(state="normal")
        log_view.delete("1.0", "end")
        log_view.configure(state="disabled")
        def work():
            try:
                result = install(*values, system_deps=os.name != "nt", log=log, cheat_content=chosen_content,
                                 tmp3_game=chosen_tmp3 or None, language=i18n.language(), trust=trust_var.get())
                events.put(("done", result))
            except Exception as error:
                log(str(error))
                events.put(("failed", str(error)))
        threading.Thread(target=work, daemon=True).start()

    def drain():
        while not events.empty():
            kind, value = events.get_nowait()
            if kind == "theme":
                apply_theme(value)
            elif kind == "log":
                log_view.configure(state="normal")
                log_view.insert("end", value + "\n")
                log_view.see("end")
                log_view.configure(state="disabled")
                if running[0] and value.startswith((tr('Веб-клиент:'), tr('Распаковываю веб-клиент'), tr('Использую готовый веб-клиент'))):
                    set_status(value)
            else:
                running[0] = False
                progressbar.stop()
                progressbar.pack_forget()
                action.configure(state="normal")
                if kind == "done":
                    installed_target[0] = Path(value)
                    set_status(tr('Готово. Можно открыть LocalBox.'), "success")
                    action.configure(text=tr('Открыть LocalBox'))
                    controls()
                    if run_after:
                        root.after_idle(launch)
                else:
                    controls()
                    set_status(tr('Установка не завершена. Подробности — в журнале.'), "error")
                    action.configure(text=tr('Скачать'))
                    toggle_details()
        poll_job[0] = root.after(100, drain)

    apply_theme(False)
    action.configure(command=start_download)
    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<Escape>", lambda _: close())
    root.update_idletasks()
    root.geometry("+%d+%d" % ((root.winfo_screenwidth() - root.winfo_width()) // 2,
                             (root.winfo_screenheight() - root.winfo_height()) // 2))
    threading.Thread(target=follow_theme, daemon=True).start()
    drain()
    root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target")
    parser.add_argument("--language", choices=("ru", "en"))
    parser.add_argument("--runtime")
    parser.add_argument("--game")
    parser.add_argument("--cheat-content")
    parser.add_argument("--tmp3-game")
    parser.add_argument("--dodo", action="store_true")
    parser.add_argument("--no-trust", action="store_true")
    parser.add_argument("--ru", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--tts", choices=("piper", "silero", "both", "none", "espeak"), default="piper")
    parser.add_argument("--voices", default=PIPER_VOICES[0])
    args = parser.parse_args()
    run_wizard(args.target, args.runtime, args.game, args.dodo, args.ru, args.run,
               args.tts, [voice for voice in args.voices.split(",") if voice], args.cheat_content, args.tmp3_game, args.language,
               trust=not args.no_trust)
