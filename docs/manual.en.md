[Русский](manual.md) · [English](manual.en.md) · [Home](README.en.md)

# Manual setup of LocalBox

The installer from [Releases](https://github.com/zAsQwE/localbox/releases) is usually enough: it installs
everything itself. This page is for installing from source and for when something does not work.

From source the easiest way is `./setup.sh` (Linux) or `install.bat` (Windows) in the project folder:
they install the dependencies themselves. Below is the same done fully by hand.

## 1. What you need

| Program | Why |
| --- | --- |
| Node.js 18+ (with npm) | the server |
| Python 3.10+ with Tk | the launcher |
| git | to get the project and the English client |
| ffmpeg | Dodo Re Mi and speech compression (optional) |

**Windows:** install [Node.js LTS](https://nodejs.org) and [Python](https://python.org). In the Python installer
tick **Add python.exe to PATH**. git — from [git-scm.com](https://git-scm.com).

**Linux:**

```sh
sudo apt install nodejs npm python3 python3-tk git ffmpeg     # Debian / Ubuntu
sudo pacman -S nodejs npm python tk git ffmpeg                # Arch / CachyOS
sudo dnf install nodejs npm python3 python3-tkinter git ffmpeg # Fedora
```

If your Debian/Ubuntu ships Node.js older than 18, install a current one from [nodejs.org](https://nodejs.org/en/download).

## 2. Get LocalBox

```sh
git clone https://github.com/zAsQwE/localbox
cd localbox
```

Or download the ZIP from the project page and unpack it. The folder path must have **no spaces**
(on Windows also no non-Latin letters), e.g. `C:\LocalBox` or `~/LocalBox`.

## 3. Web client for phones

The client is not in the repository; get it separately. One of the two is enough:

- **English** — into the `client` folder:
  ```sh
  git clone https://github.com/DdejjCAT/jackbox.tv client
  ```
- **Russian** — the **Download Russian client** button in the launcher (after step 4) or:
  ```sh
  python3 tools/fetch-jackbox-ru.py
  ```

## 4. Start

- Windows: `start-server.bat`.
- Linux: `./start-server.sh`.

The menu asks whether to open the window or the console, whether to enable Dodo Re Mi and which voice to use.
Then in the launcher:

1. Check the computer's IP in **Settings**: it must be from your network, e.g. `192.168.1.108`.
2. Click **Start server**.

On first start the launcher installs the server dependencies, creates a certificate in `certs/`, and on Linux
asks for your password once so the server may use ports 80 and 443. On Windows allow Node.js network
access in the firewall window on first start.

## 5. Connect the game

Click **Copy serverUrl** and paste the line into Steam: **game → Properties → Launch Options**.

- **Windows:** the line is `-jbg.config serverUrl=IP`. After a manual install click **Renew certificate**
  in Settings once and answer Yes in the Windows dialog. Without it games won't connect to the server.
- **Linux:** paste the whole line; it is long, that is expected. Add your own options
  (e.g. `--renderer=OpenGL`) at the end **after a space**.
- **Trivia Murder Party 3:** click **Patch Trivia Murder Party 3** and choose the local server in the game.
- **Game on another computer:** the same line with the IP of the computer running LocalBox. On Windows that
  computer also needs LocalBox and one **Renew certificate** with the server IP.

## 6. Connect players

Players scan the QR code on screen: the site opens with the room code filled in. Or they open
`http://COMPUTER_IP`. Phones must be on the same network; they need no certificate.

In **Settings** you can turn the QR off, pick its screen corner and enable auto-start when the room is full.

## Friends through Porthole

[Porthole](https://store.steampowered.com/app/4963920/) shares a port with a Steam friend without router setup.

1. Start LocalBox and the game as usual.
2. In Porthole create a lobby and share **TCP port 80**.
3. Your friend opens `http://127.0.0.1`. **Link for a friend** copies the address with the room code.

If port 80 is taken on your friend's computer, enter e.g. `9999` in the **Port** field next to Porthole in the
launcher and restart the server. Share that port; your friend opens `http://127.0.0.1:9999`. Port 80 keeps
working for Wi-Fi players. If you don't need Porthole, untick **Porthole support** in Settings.

## If something does not work

| What you see | What to do |
| --- | --- |
| Server log shows `[tls] … не доверяет сертификату` (the game does not trust the certificate) | Windows: **Renew certificate**. Linux: copy the launch line again, whole. The game log (`TJPP2-log.txt` etc. in the game folder) should show `Using specified CA Bundle`. |
| Linux: the game crashes with `vkDeviceWaitIdle: Invalid device` | Add ` --renderer=OpenGL` at the end of the launch options (with a space before it). |
| The game keeps "connecting" and the server log is empty | The IP in Settings is not this computer's IP, or the server is not running. Check the IP and the launch line. |
| A phone cannot open the site | The phone is on another network (guest Wi-Fi, mobile data) or the Windows firewall blocked Node.js. |
| The site has no controller and offers **Update client** | Click it: a fresh English client is downloaded. |
| `EADDRINUSE :80` or `:443` | Another program holds the port (nginx, Apache, IIS, Skype). Find it: `sudo ss -ltnp \| grep -E ':(80\|443)\b'` on Linux, `netstat -ano \| findstr :80` on Windows. |
| `EADDRINUSE :38203` | A previous server is still running: `pkill -f server/server.js` (Linux) or end `node.exe` in Task Manager. |
| Linux: `EACCES` on port 80/443 | `sudo setcap cap_net_bind_service=+ep "$(readlink -f "$(command -v node)")"` |
| `HTTP 422 game_disabled` | Jackbox 12 games are disabled by `LOCALBOX_ENABLE_PACK12=0`; remove it. |

---

## Reference

### Launcher options

| Command (from the `launcher` folder) | What it does |
| --- | --- |
| `python3 localbox_launcher.py` | the launcher window (console server without a display) |
| `python3 localbox_launcher.py -ip=192.168.1.108` | console server on this IP |
| `python3 localbox_launcher.py -ip=192.168.1.108 -no-web` | game server only, no site for phones |
| `python3 localbox_launcher.py --offline` | console server, download nothing from the internet |
| `python3 localbox_launcher.py --check` | check node, the server and the client |

### Ports

The server listens on **80** (site and players), **443** (HTTPS for games), **38202** and **38203** (old Blobcast
games). A custom Porthole port is added to these when set.

### Certificates

LocalBox creates its own certificate (CA) in `certs/` offline and never replaces it by itself.
Phones and browsers don't need it: they use `http://`. Only games need it:

- **Windows** reads the CA from the Windows store — the setup checkbox or **Renew certificate**.
  To remove: `certmgr.msc` → Trusted Root Certification Authorities → LocalBox.
- **Linux:** LocalBox changes nothing in the system or Steam; the certificate reaches the game only through the
  launch line. Linux builds of the packs read it from `-cafile`, Windows builds under Proton from `SSL_CERT_FILE`.
  `protocol=http` sends the room creation request over HTTP. `certs/localbox-ca-bundle.pem` is refreshed on
  every server start.
- **Trivia Murder Party 3** has its own certificate file in the game folder; the patch installs it.

LocalBox does not change `hosts`, DNS or game files (except the TMP3 patch).

### Language and web client

Change the language in **Settings → Server**. With the Russian interface phones get `client-ru` if present,
otherwise `client`; missing images are looked up in both folders and, when enabled, downloaded from jackbox.ru.
For fully offline play untick both download options in Settings or start with `--offline`.

To repair an incomplete Russian client: `python3 tools/fetch-jackbox-ru.py` (downloads only what is missing;
`--force` downloads again, `--dry-run` shows what would be downloaded).

### New games

The server registers a new game by its `appTag` automatically. Player limits can be set in `server/games.json`
(`maxPlayers`, `minPlayers`); the `appTag` appears in the server log on the `POST /api/v2/rooms` line.
Restart the server after editing.

### More

[Speech](tts.en.md) · [Dodo Re Mi](dodo-re-mi.en.md) · [Admin cheats](cheats.en.md) · [Installer](install.en.md)

---

LocalBox is not affiliated with Jackbox Games. Rights to the original games, the Jackbox name and brand
belong to Jackbox Games. Translations are by the community (jackbox.ru / What If?).
