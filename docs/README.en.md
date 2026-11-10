[Русский](../README.md) · [English](README.en.md)

# LocalBox

A local server for Jackbox games (packs 1–12, Naughty Pack, Trivia Murder Party 3).
Games, players' phones, speech and Dodo Re Mi work on your network without internet.

[Download](https://github.com/zAsQwE/localbox/releases) · [Telegram](https://t.me/lacalbox) · [Video tutorial](https://youtu.be/FlBtIWncPLc?si=xLj6I7CLvtbp_o0J)

## Install

Download from **Assets** on the Releases page:

- Windows 10/11 — `setup.exe`;
- Linux — `setup-linux.run`, run it with `chmod +x setup-linux.run && ./setup-linux.run`.

Choose the folder and voices, then click **Download**. Internet is needed only during installation.

## How to play

1. Open LocalBox and click **Start server**.
2. Click **Copy serverUrl** and paste the line into Steam: **game → Properties → Launch Options**.
3. Start the game. Players scan the QR code on screen or open `http://COMPUTER_IP`.

The launcher builds the Steam line for you; there is no need to type it. What it looks like:

| Where the game runs | Launch options |
| --- | --- |
| Windows | `-jbg.config serverUrl=IP` |
| Linux | `SSL_CERT_FILE=Z:/…/localbox-ca-bundle.pem %command% -jbg.config serverUrl=IP protocol=http -cafile /…/localbox-ca-bundle.pem` |
| Trivia Murder Party 3 | the **Patch Trivia Murder Party 3** button in the launcher |

On Windows the installer asks once whether to trust the LocalBox certificate: answer Yes.

## Friends over the internet

Share **TCP port 80** through [Porthole](https://store.steampowered.com/app/4963920/).
Your friend opens `http://127.0.0.1`. If port 80 is taken on their computer, enter another port in the
launcher, e.g. `9999`. Details are in the [manual](manual.en.md#friends-through-porthole).

## Steam Deck

The server can run on the Deck itself, in Game Mode, with no PC and no internet. Run
`tools/steamdeck/install.sh` once, then use the wrapper in every pack's launch options:

| Mode | Launch options |
| --- | --- |
| Local | `~/LocalBox/tools/steamdeck/jackbox.sh -local %command%` |
| Russian servers | `~/LocalBox/tools/steamdeck/jackbox.sh -online-ru %command%` |
| Official servers | `~/LocalBox/tools/steamdeck/jackbox.sh -online %command%` |

A join QR code appears over the game. Details: [Steam Deck](steam-deck.en.md).

## Network and security

When `serverUrl` is a local-network address, the server accepts connections only from that network; with a
public address or domain (VPS) it accepts everyone. Admin cheats require an access key, not just a nickname
(see [cheats](cheats.en.md)). Server environment variables:

| Variable | Meaning |
| --- | --- |
| `LOCALBOX_ALLOW_PUBLIC` | `1` — accept everyone, `0` — local network only (default: based on `serverUrl`) |
| `LOCALBOX_ALLOWED_ORIGINS` | extra websites (comma-separated) allowed to make requests to the server |
| `LOCALBOX_ADMIN_KEY` | cheats key; if unset, one is generated at startup and written to the log |
| `LOCALBOX_PLAYER_PORT` | web port for phones and the QR instead of 80 (the next free one if taken); set by the Steam Deck setup |

## Updates

**Check for updates → Update to …**. Settings and downloaded files are kept.

## Documentation

- [Manual installation and troubleshooting](manual.en.md)
- [Installer and building a Release](install.en.md)
- [Speech](tts.en.md) · [Dodo Re Mi](dodo-re-mi.en.md) · [Admin cheats](cheats.en.md)
- [Android](../android/README.md) · [Steam Deck](steam-deck.en.md)

Created with Claude and Codex. Security is not guaranteed: use it on your local network or with friends.
LocalBox is not affiliated with Jackbox Games; original games and assets belong to their owners.
