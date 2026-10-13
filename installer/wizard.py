#!/usr/bin/env python3
"""One-window download settings for LocalBox, using the desktop colour scheme."""

import argparse
import os
import queue
import subprocess
import threading
from pathlib import Path

from install import install, songs_directory, PIPER_VOICES, SOURCE, read_json
from theme import detect_dark


def run_wizard(target=None, runtime=None, game=None, dodo=False, russian=False, run_after=False,
               tts="piper", voices=None, cheat_content=None):
    import tkinter as tk
    from tkinter import filedialog, ttk
    from tkinter.font import nametofont

    root = tk.Tk()
    root.title("LocalBox")
    root.geometry("680x680")
    root.minsize(640, 620)
    font = nametofont("TkDefaultFont").actual("family")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=(font, 10))
    style.configure("TButton", padding=(12, 7))
    style.configure("TEntry", padding=6)
    style.configure("TCombobox", padding=6)
    style.configure("TCheckbutton", padding=(0, 4))
    style.configure("Title.TLabel", font=(font, 21, "bold"))
    style.configure("Section.TLabel", font=(font, 10, "bold"))
    style.configure("Download.TButton", padding=(24, 9))

    body = ttk.Frame(root, padding=(24, 18))
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="LocalBox", style="Title.TLabel").pack(anchor="w", pady=(0, 16))
    footer = ttk.Frame(body)
    footer.pack(side="bottom", fill="x", pady=(12, 0))
    status = tk.StringVar(value="Зависимости и выбранные голоса скачаются автоматически.")
    status_label = ttk.Label(footer, textvariable=status, style="Muted.TLabel", wraplength=420)
    status_label.pack(side="left", fill="x", expand=True, padx=(0, 16))
    action = ttk.Button(footer, text="Скачать", style="Download.TButton", width=17)
    action.pack(side="right")
    progressbar = ttk.Progressbar(body, mode="indeterminate")
    details = ttk.Frame(body)
    log_view = tk.Text(details, height=6, relief="flat", borderwidth=1, padx=8, pady=8,
                       wrap="word", font=(font, 9), state="disabled")
    scrollbar = ttk.Scrollbar(details, command=log_view.yview)
    scrollbar.pack(side="right", fill="y")
    log_view.configure(yscrollcommand=scrollbar.set)
    log_view.pack(fill="both", expand=True)
    details_var = tk.BooleanVar(value=False)
    def toggle_details():
        if details_var.get():
            details.pack(side="bottom", fill="x", pady=(6, 0), before=detail_toggle)
        else:
            details.pack_forget()
    detail_toggle = ttk.Checkbutton(body, text="Журнал", variable=details_var, command=toggle_details)
    settings_host = ttk.Frame(body)
    settings_host.pack(fill="both", expand=True)
    canvas = tk.Canvas(settings_host, highlightthickness=0, borderwidth=0)
    settings_scrollbar = ttk.Scrollbar(settings_host, command=canvas.yview)
    canvas.configure(yscrollcommand=settings_scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    settings = ttk.Frame(canvas)
    settings_window = canvas.create_window(0, 0, window=settings, anchor="nw")
    def resize_settings(_=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
        if settings.winfo_reqheight() > canvas.winfo_height():
            settings_scrollbar.pack(side="right", fill="y")
        else:
            settings_scrollbar.pack_forget()
    settings.bind("<Configure>", resize_settings)
    def resize_canvas(event):
        canvas.itemconfigure(settings_window, width=event.width)
        resize_settings()
    canvas.bind("<Configure>", resize_canvas)
    def scroll_settings(event):
        if str(event.widget).startswith(str(settings)) or event.widget is canvas:
            direction = -1 if getattr(event, "num", 0) == 4 else 1 if getattr(event, "num", 0) == 5 else -1 if event.delta > 0 else 1
            canvas.yview_scroll(direction * 3, "units")
    for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        root.bind(event, scroll_settings)
    settings.columnconfigure(0, weight=1)

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
    ru_var = tk.BooleanVar(value=russian)
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
            game_path.set(saved.get("jackbox10_path", ""))
            dodo_var.set(bool(saved.get("dodo_render")))
            cheat_path.set(saved.get("cheat_content_dir", ""))
            cheat_var.set(bool(cheat_path.get()))
    app_path.trace_add("write", app_changed)

    editable = []
    def path_field(label, variable, row):
        ttk.Label(settings, text=label).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 5))
        entry = ttk.Entry(settings, textvariable=variable)
        entry.grid(row=row + 1, column=0, sticky="ew")
        def browse():
            chosen = filedialog.askdirectory(parent=root, title=label,
                                             initialdir=variable.get() or str(Path.home()))
            if chosen:
                variable.set(chosen)
        button = ttk.Button(settings, text="Обзор…", command=browse, width=9)
        button.grid(row=row + 1, column=1, padx=(8, 0))
        editable.extend((entry, button))
        return entry, button

    path_field("Куда скачать LocalBox", app_path, 0)
    path_field("Папка зависимостей и TTS", runtime_path, 2)
    ttk.Label(settings, text="Озвучка", style="Section.TLabel").grid(
        row=4, column=0, columnspan=2, sticky="w", pady=(18, 7))
    engines = {"Piper — нейроголоса": "piper", "Silero — русские нейроголоса": "silero",
               "Piper + Silero": "both", "Без озвучки": "none"}
    if os.name != "nt":
        engines["eSpeak — лёгкий голос"] = "espeak"
    tts_var = tk.StringVar(value=next((label for label, code in engines.items() if code == tts), next(iter(engines))))
    combo = ttk.Combobox(settings, textvariable=tts_var, state="readonly", values=list(engines))
    combo.grid(row=5, column=0, columnspan=2, sticky="ew")
    voice_frame = ttk.Frame(settings)
    voice_frame.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
    voice_vars, voice_checks = {}, []
    requested = set(voices if voices is not None else [PIPER_VOICES[0]])
    for index, (voice, label) in enumerate(zip(PIPER_VOICES, ("Денис", "Дмитрий", "Ирина", "Руслан"))):
        value = tk.BooleanVar(value=voice in requested)
        voice_vars[voice] = value
        check = ttk.Checkbutton(voice_frame, text=label, variable=value)
        check.grid(row=0, column=index, padx=(0, 18))
        voice_checks.append(check)
    tts_hint = tk.StringVar()
    ttk.Label(settings, textvariable=tts_hint, style="Muted.TLabel", wraplength=600).grid(
        row=7, column=0, columnspan=2, sticky="w", pady=(3, 0))
    dodo_check = ttk.Checkbutton(settings, text="Поддержка Додо Ре Ми", variable=dodo_var)
    dodo_check.grid(row=8, column=0, columnspan=2, sticky="w", pady=(16, 0))
    editable.append(dodo_check)
    game_entry, game_browse = path_field("Папка Jackbox Party Pack 10 — необязательно", game_path, 9)
    russian_check = ttk.Checkbutton(settings, text="Скачать русский веб-клиент", variable=ru_var)
    cheat_check = ttk.Checkbutton(settings, text="Указать папку с играми для читов", variable=cheat_var)
    cheat_check.grid(row=11, column=0, columnspan=2, sticky="w", pady=(16, 0))
    editable.append(cheat_check)
    cheat_entry, cheat_browse = path_field("Папка со всеми Jackbox или отдельной игрой — необязательно", cheat_path, 12)
    ttk.Label(settings, text="Файлы игр читаются на месте. Без выбранной папки — поиск в Steam.",
              style="Muted.TLabel", wraplength=600).grid(row=14, column=0, columnspan=2, sticky="w", pady=(5, 0))
    russian_check.grid(row=15, column=0, columnspan=2, sticky="w", pady=(12, 0))
    editable.append(russian_check)

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
        for widget in (cheat_entry, cheat_browse):
            widget.configure(state="normal" if not locked and cheat_var.get() else "disabled")
        tts_hint.set("Скачаются только отмеченные голоса." if code in ("piper", "both") else
                     "Скачаются все встроенные русские голоса." if code == "silero" else "")
    tts_var.trace_add("write", lambda *_: controls())
    dodo_var.trace_add("write", lambda *_: controls())
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
        canvas.configure(bg=colors["bg"])
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
            set_status("Скачивание ещё идёт. Дождитесь окончания.")
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
            set_status("Не удалось открыть LocalBox: " + str(error), "error")
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
                raise ValueError("Укажите папки для LocalBox и зависимостей.")
            selected = [voice for voice, value in voice_vars.items() if value.get()]
            if engines[tts_var.get()] in ("piper", "both") and not selected:
                raise ValueError("Выберите хотя бы один голос Piper.")
            chosen_game = game_path.get().strip() if dodo_var.get() else ""
            if chosen_game:
                songs_directory(chosen_game)
            chosen_content = cheat_path.get().strip() if cheat_var.get() else ""
            if cheat_var.get() and not chosen_content:
                raise ValueError("Укажите папку с играми для читов или снимите галочку.")
            if chosen_content and not Path(chosen_content).expanduser().is_dir():
                raise ValueError("Папка с играми для читов не найдена.")
        except (ValueError, OSError) as error:
            set_status(str(error), "error")
            return
        values = (app_path.get().strip(), runtime_path.get().strip(), engines[tts_var.get()], selected,
                  chosen_game or None, dodo_var.get(), ru_var.get())
        running[0] = True
        controls()
        action.configure(text="Скачиваем…", state="disabled")
        detail_toggle.pack(side="bottom", anchor="w", pady=(10, 0), before=settings_host)
        progressbar.pack(side="bottom", fill="x", pady=(10, 0), before=detail_toggle)
        progressbar.start(12)
        set_status("Скачиваем и настраиваем LocalBox…")
        log_view.configure(state="normal")
        log_view.delete("1.0", "end")
        log_view.configure(state="disabled")
        def work():
            try:
                result = install(*values, system_deps=os.name != "nt", log=log, cheat_content=chosen_content)
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
            else:
                running[0] = False
                progressbar.stop()
                progressbar.pack_forget()
                action.configure(state="normal")
                if kind == "done":
                    installed_target[0] = Path(value)
                    set_status("Готово. Можно открыть LocalBox.", "success")
                    action.configure(text="Открыть LocalBox")
                    controls()
                    if run_after:
                        root.after_idle(launch)
                else:
                    controls()
                    set_status("Не получилось скачать: " + value, "error")
                    action.configure(text="Скачать")
                    details_var.set(True)
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
    parser.add_argument("--runtime")
    parser.add_argument("--game")
    parser.add_argument("--cheat-content")
    parser.add_argument("--dodo", action="store_true")
    parser.add_argument("--ru", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--tts", choices=("piper", "silero", "both", "none", "espeak"), default="piper")
    parser.add_argument("--voices", default=PIPER_VOICES[0])
    args = parser.parse_args()
    run_wizard(args.target, args.runtime, args.game, args.dodo, args.ru, args.run,
               args.tts, [voice for voice in args.voices.split(",") if voice], args.cheat_content)
