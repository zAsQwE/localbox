[Русский](README.md) · [English](docs/README.en.md)

# LocalBox

Локальный сервер для игр Jackbox (паки 1–12, Naughty Pack, Trivia Murder Party 3).
Игры, телефоны игроков, озвучка и Додо Ре Ми работают в вашей сети без интернета.

[Скачать](https://github.com/zAsQwE/localbox/releases) · [Telegram](https://t.me/lacalbox) · [Видео-туториал](https://youtu.be/FlBtIWncPLc?si=xLj6I7CLvtbp_o0J)

## Установка

Скачайте из **Assets** на странице Releases:

- Windows 10/11 — `setup.exe`;
- Linux — `setup-linux.run`, запуск: `chmod +x setup-linux.run && ./setup-linux.run`.

Выберите папку и голоса, нажмите **«Скачать»**. Интернет нужен только на время установки.

## Как играть

1. Откройте LocalBox и нажмите **«Запустить сервер»**.
2. Нажмите **«Копировать serverUrl»** и вставьте строку в Steam: **игра → Свойства → Параметры запуска**.
3. Запустите игру. Игроки сканируют QR-код на экране или открывают `http://IP_компьютера`.

Строку для Steam лаунчер собирает сам, вписывать её вручную не нужно. Как она выглядит:

| Где запущена игра | Параметры запуска |
| --- | --- |
| Windows | `-jbg.config serverUrl=IP` |
| Linux | `SSL_CERT_FILE=Z:/path/your/folder/localbox/certs/localbox-ca-bundle.pem %command% -jbg.config serverUrl=IP protocol=http -cafile /path/your/folder/localbox/certs/localbox-ca-bundle.pem` |
| Trivia Murder Party 3 | кнопка **«Патч Trivia Murder Party 3»** в лаунчере |

На Windows установщик один раз спросит, доверять ли сертификату LocalBox: ответьте «Да».

## Друзья через интернет

Через [Porthole](https://store.steampowered.com/app/4963920/) поделитесь портом **TCP 80**.
Друг открывает `http://127.0.0.1`. Если у друга порт 80 занят, впишите в лаунчере другой порт,
например `9999`. Подробнее — в [инструкции](docs/manual.md#друзья-через-porthole).

## Steam Deck

Сервер может работать прямо на Deck, в игровом режиме, без ПК и без интернета. Один раз запустите
`tools/steamdeck/install.sh`, затем в параметрах запуска каждого пака укажите обёртку:

| Режим | Параметры запуска |
| --- | --- |
| Локально | `~/LocalBox/tools/steamdeck/jackbox.sh -local %command%` |
| Российские серверы | `~/LocalBox/tools/steamdeck/jackbox.sh -online-ru %command%` |
| Официальные серверы | `~/LocalBox/tools/steamdeck/jackbox.sh -online %command%` |

QR-код для входа появляется поверх игры. Подробнее — [Steam Deck](docs/steam-deck.md).

## Сеть и безопасность

Если `serverUrl` — адрес из локальной сети, сервер принимает подключения только из неё; с публичным
адресом или доменом (VPS) — от всех. Админские читы требуют ключ доступа, а не только ник
(см. [читы](docs/cheats.md)). Переменные окружения сервера:

| Переменная | Значение |
| --- | --- |
| `LOCALBOX_ALLOW_PUBLIC` | `1` — пускать всех, `0` — только локальную сеть (по умолчанию — по `serverUrl`) |
| `LOCALBOX_ALLOWED_ORIGINS` | дополнительные сайты (через запятую), которым разрешены запросы к серверу |
| `LOCALBOX_ADMIN_KEY` | ключ к читам; без него генерируется при старте и пишется в журнал |
| `LOCALBOX_PLAYER_PORT` | веб-порт для телефонов и QR вместо 80 (если занят — следующий свободный); ставит установка для Steam Deck |

## Обновление

**«Проверить обновления» → «Обновить до …»**. Настройки и скачанные файлы сохраняются.

## Документация

- [Ручная установка и решение проблем](docs/manual.md)
- [Установщик и сборка Release](docs/install.md)
- [Озвучка](docs/tts.md) · [Додо Ре Ми](docs/dodo-re-mi.md) · [Админские читы](docs/cheats.md)
- [Android](android/README.md) · [Steam Deck](docs/steam-deck.md)

Проект создан с помощью Claude и Codex. Безопасность не гарантирована: используйте его
в локальной сети или для игры с друзьями. LocalBox не связан с Jackbox Games, оригинальные игры
и материалы принадлежат их правообладателям.
