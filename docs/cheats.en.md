[Русский](cheats.md) · [English](cheats.en.md) · [Home](README.en.md)

# Admin cheats

In launcher Settings, enter comma-separated admin nicknames. Enable answer highlighting, the correct-answer
panel or Bidiots painting values as desired. Save, restart the server and join with an authorized nickname.
The overlay attaches to Ecast and older Blobcast games. Open it with the right-hand tab or Ctrl+Shift+K.
On first use, enter an admin nickname and the **access key** shown in the launcher log when the server starts
(or set your own with `LOCALBOX_ADMIN_KEY`). The browser remembers the key and reconnects automatically.

## Fibbage and Trivia Murder Party

LocalBox recognizes explicit correct-answer markers from game data. If the answer remains on the host computer,
it can match the current question against installed game files: `content/*.jet` and
`content/fibbageshortie|fibbagespecial|finalfibbage/*/data.jet`.
Supported formats include Fibbage 2/3 and Trivia Murder Party 1/2, including multiple correct answers in final rounds.
Other versions work only if they use these formats or send explicit correct-answer information.

Steam libraries are discovered on Windows, Linux and macOS, including extra drives from `libraryfolders.vdf`.
For a separate installation choose one game's folder, a Party Pack folder or `steamapps/common` in Settings.
A configured folder replaces Steam discovery. Console users can set `LOCALBOX_CHEAT_CONTENT` to the same path.

Content must match the version and translation of the running game. Matching uses question text and available choices;
an ID alone is insufficient. Player lies, ordinary player answers, winner IDs and arbitrary numbers are not treated as correct answers.
Choices highlight only when their text matches, including HTML/BBCode and single-letter/digit answers.
If no answer is found the panel reports that; personal Fibbage questions without a predefined file answer cannot be guessed.

## Bidiots

The server collects `info: [{title, value}]` estimates sent to players and displays prices with painting names.
Player balance and current bids are not used as painting values. When the visible painting name matches an estimate,
a price appears beside it; otherwise use the panel's price list. Conflicting estimates for one title are hidden.
Before estimates arrive, prices remain unknown.

Only admin-overlay connections with nicknames in `LOCALBOX_ADMINS` and the access key receive these hints; regular game messages
and rules are unchanged. Access needs both a listed nickname and the key, so another device on the same
network cannot read answers or kick players just by using an admin nickname.
