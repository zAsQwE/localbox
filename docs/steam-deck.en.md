[Русский](steam-deck.md) · [English](steam-deck.en.md) · [Home](README.en.md)

# LocalBox on Steam Deck

The server runs on the Deck itself, in Game Mode, with no PC and no internet: the games connect to it and
players' phones load the web client from it. A launch-option wrapper picks the server, and a join QR code is
drawn over the game.

Files are in `tools/steamdeck/`:

| File | Purpose |
| --- | --- |
| `install.sh` | setup: Node.js, dependencies, the `localbox` user service |
| `jackbox.sh` | Steam launch options: choose the server with one flag |
| `qr-overlay.py` | join QR code over the game (gamescope) |

## Setup

In Desktop Mode, in Konsole:

1. Unpack LocalBox (a Release or `git clone`) anywhere, e.g. `~/LocalBox`.
2. Put a web client into `client-ru/` or `client/` (see [manual setup](manual.en.md)).
3. Run:

   ```sh
   ~/LocalBox/tools/steamdeck/install.sh
   ```

   It downloads a portable Node.js into `runtime/node` (SHA-256 checked against nodejs.org), installs the
   server dependencies, creates `server/config.json` and the `localbox` user service. Re-running is safe and
   also updates the paths after the folder is moved.
4. Run the one command it prints at the end (asks for your password):

   ```sh
   sudo setcap cap_net_bind_service=+ep ~/LocalBox/runtime/node/bin/node
   ```

   Games join a room only over `wss` on port 443, so this permission is required. The firewall needs no
   changes: phones use a high port (see below).

## Launch options

Steam → game → **Properties → Launch Options**, for every Jackbox pack:

| Mode | Launch option |
| --- | --- |
| Local (LocalBox on the Deck, offline) | `~/LocalBox/tools/steamdeck/jackbox.sh -local %command%` |
| Russian servers (jb-ecast.klucva.ru) | `~/LocalBox/tools/steamdeck/jackbox.sh -online-ru %command%` |
| Official game servers | `~/LocalBox/tools/steamdeck/jackbox.sh -online %command%` |
| Default mode | `~/LocalBox/tools/steamdeck/jackbox.sh %command%` |

Change the default with `jackbox.sh mode local|online-ru|online`. `jackbox.sh status` prints the mode, IP,
server state and the players' address. Launch log: `~/.local/state/localbox/launch.log`; the server log is
next to it.

In `-local` mode, on every launch the wrapper:

- detects the Deck's current IP; after a network change it re-issues the certificate and updates `serverUrl`;
- starts the `localbox` service if needed and waits for port 443;
- passes `-jbg.config serverUrl=IP -cafile certs/localbox.pem` to the game, so the game trusts the local
  certificate without touching the system trust store.

## Players and the QR code

| Mode | Players open | QR over the game |
| --- | --- | --- |
| `-local` | `http://DECK_IP:38202` | with the room code; shown in the lobby, hidden once the match starts |
| `-online-ru` | `https://jackbox.ru` | site only; in menus and for 30 s after the room is created |
| `-online` | `https://jackbox.fun` | site only; in menus and for 30 s after the room is created |

Why 38202 and not 80: SteamOS updates reset the firewall to its default, which blocks ports 80 and 443 from the
network but leaves 1024–65535 open. If 38202 is taken by another program, the server uses the next free port;
the QR code and `jackbox.sh status` always show the actual one.

In online modes the room lives on an external server, so players type the code from the game screen and the
QR only opens the site. `LOCALBOX_QR_SECONDS` sets how long it stays, `LOCALBOX_QR=0` turns it off, e.g.
`LOCALBOX_QR=0 ~/LocalBox/tools/steamdeck/jackbox.sh -local %command%`.

## Limitations

- The QR overlay is shown only in Game Mode (gamescope draws it in the top-left corner).
- Public Wi-Fi often isolates devices from each other, so phones can't reach the Deck. Share a hotspot from a
  phone and connect the Deck and the other phones to it.
- The IP is picked when the game starts. If the Deck rejoins the network mid-session, restart the game.

## Tested

Bots (the real web client in a browser) played full matches on the Deck offline with the Russian client:
Party Pack 4 — all 5 games (including drawing in Civic Doodle), Party Pack 5 — all 5 (drawings in Patently
Stupid, the slingshot in Zeeple Dome, speech in Mad Verse City), Party Starter — Quiplash 3. In Split the Room
the match is started with a button in the game itself, not from the VIP's phone.
