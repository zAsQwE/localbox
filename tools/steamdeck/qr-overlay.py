#!/usr/bin/env python3
"""QR-код для входа поверх игры в игровом режиме Steam Deck.

Два режима:
  * локальный (по умолчанию): код и адрес берутся у сервера LocalBox; QR ведёт на страницу
    входа с кодом, показывается в лобби и исчезает, когда матч начался;
  * QR на сайт (LOCALBOX_QR_SITE=https://jackbox.ru): комнату создаёт внешний сервер, поэтому
    QR ведёт на сайт без кода. Виден в меню и LOCALBOX_QR_SECONDS (30) секунд после создания
    комнаты; комнату видно по долгому внешнему соединению игры, его закрытие — возврат в меню.

Завершается сам, когда игра Jackbox закрыта.
Окно помечается GAMESCOPE_EXTERNAL_OVERLAY, чтобы gamescope рисовал его поверх игры;
запускать на X-дисплее самого Steam (GAMESCOPE_XWAYLAND_SERVER_ID = 0), не игры.
"""
import io
import json
import os
import ssl
import subprocess
import sys
import time
import tkinter as tk
import urllib.parse
import urllib.request

# segno (генератор QR для режима сайта) ставит install.sh; путь передаёт jackbox.sh.
if os.environ.get("LOCALBOX_PYLIB"):
    sys.path.insert(0, os.environ["LOCALBOX_PYLIB"])

# Сервер слушает 4 порта, но любой из них может оказаться занят другой программой на Deck,
# и сервер его пропустит. Перебираем все по очереди; последний рабочий пробуем первым.
SERVERS = ["http://127.0.0.1:80", "http://127.0.0.1:38202",
           "https://127.0.0.1:443", "https://127.0.0.1:38203"]
SITE = os.environ.get("LOCALBOX_QR_SITE", "").strip().rstrip("/")
SITE_SECONDS = float(os.environ.get("LOCALBOX_QR_SECONDS", "30"))
POLL_MS = 1500 if not SITE else 2000
GAME_GONE_EXIT_S = 20
GAME_NAMES = r"TJ(PP[0-9]+|PS)_(Vulkan|OpenGL)"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# Самоподписанный сертификат LocalBox: проверку отключаем, запросы идут только на 127.0.0.1.
tls_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                         urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))


def get(path, timeout=1.5):
    error = None
    for base in list(SERVERS):
        try:
            op = tls_opener if base.startswith("https") else opener
            with op.open(base + path, timeout=timeout) as response:
                data = response.read()
            if SERVERS[0] != base:
                SERVERS.remove(base); SERVERS.insert(0, base)
            return data
        except OSError as e:
            error = e
    raise error


def game_pid():
    # Точное имя процесса, а не командная строка: иначе срабатывает на любую команду с этим текстом.
    out = subprocess.run(["pgrep", "-x", GAME_NAMES], capture_output=True, text=True).stdout.split()
    return out[0] if out else None


def has_server_connection(pid):
    """Есть ли у игры установленное соединение не с localhost — значит, комната создана."""
    out = subprocess.run(["ss", "-tnpH", "state", "established"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if f"pid={pid}," not in line:
            continue
        peer = line.split()[3] if len(line.split()) > 3 else ""
        if not (peer.startswith("127.") or peer.startswith("[::1]") or peer.startswith("[::ffff:127.")):
            return True
    return False


def site_png(url):
    import segno
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=6, border=2)
    return buf.getvalue()


class Overlay:
    """Корневое окно Tk всегда скрыто; QR рисуется в отдельном окне self.win.

    gamescope продолжает показывать последний кадр внешнего оверлея и после того, как окно
    скрыто (unmap), поэтому окно с QR не прячем, а уничтожаем и создаём заново.
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.win = None
        self.key = None
        self.image = None
        self.last_game = time.time()
        self.room_since = None          # режим сайта: когда появилась комната
        self.root.after(200, self.tick)

    @staticmethod
    def toplevel_id(widget):
        # Для окна без рамки wm_frame() отдаёт внутреннее окно; верхнее — его родитель.
        inner = hex(widget.winfo_id())
        out = subprocess.run(["xwininfo", "-tree", "-id", inner], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "Parent window id:" in line:
                return line.split(":", 1)[1].split()[0]
        return inner

    def create(self, title, png, big, small):
        win = tk.Toplevel(self.root, bg="white")
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        # gamescope рисует внешний оверлей от левого верхнего угла; на рабочем столе ставим туда же.
        win.geometry("+16+16")
        self.image = tk.PhotoImage(master=win, data=png, format="png")
        labels = [
            tk.Label(win, text=title, bg="white", fg="#222", font=("Sans", 13, "bold")),
            tk.Label(win, image=self.image, bg="white"),
            tk.Label(win, text=big, bg="white", fg="#d0283c", font=("Sans", 18, "bold")),
            tk.Label(win, text=small, bg="white", fg="#444", font=("Sans", 10)),
        ]
        for label in labels:
            label.pack(padx=10, pady=(4, 0))
        labels[-1].pack_configure(pady=(0, 8))
        # Свойство gamescope читает при показе окна — ставим его, пока окно ещё скрыто.
        win.withdraw()
        win.update()
        subprocess.run(["xprop", "-id", self.toplevel_id(win), "-f", "GAMESCOPE_EXTERNAL_OVERLAY", "32c",
                        "-set", "GAMESCOPE_EXTERNAL_OVERLAY", "1"], check=False)
        win.deiconify()
        return win

    def show(self, key, make):
        if self.win is not None and key == self.key:
            return
        title, png, big, small = make()
        self.hide()
        self.win = self.create(title, png, big, small)
        self.key = key

    def hide(self):
        if self.win is not None:
            self.win.destroy()
            self.root.update()
            self.win = None
            self.key = None

    def tick_local(self):
        try:
            room = json.loads(get("/localbox/status")).get("room")
        except Exception:
            room = None
        if room and not room.get("locked"):
            def make():
                png = get("/localbox/qr.png?code=" + urllib.parse.quote(room["code"], safe=""), timeout=3)
                return "Вход для игроков", png, room["code"], room["joinUrl"].split("/?")[0]
            try:
                self.show((room["code"], room["joinUrl"]), make)
            except Exception:
                self.hide()
        else:
            self.hide()

    def tick_site(self, pid):
        if pid and has_server_connection(pid):
            if self.room_since is None:
                self.room_since = time.time()
        else:
            self.room_since = None
        if pid and (self.room_since is None or time.time() - self.room_since < SITE_SECONDS):
            host = urllib.parse.urlparse(SITE).netloc or SITE
            self.show(SITE, lambda: ("Сайт для игроков", site_png(SITE), host, "код комнаты — на экране игры"))
        else:
            self.hide()

    def tick(self):
        pid = game_pid()
        try:
            if SITE:
                self.tick_site(pid)
            else:
                self.tick_local()
        except Exception as error:
            print("qr-overlay:", error, file=sys.stderr)
            self.hide()
        if pid:
            self.last_game = time.time()
        elif time.time() - self.last_game > GAME_GONE_EXIT_S:
            self.root.destroy()
            return
        self.root.after(POLL_MS, self.tick)


if __name__ == "__main__":
    Overlay().root.mainloop()
