[Русский](README.md) · [English](docs/README.en.md)

# LocalBox

Локальный сервер для игр Jackbox (паки 1–12, Naughty Pack, Trivia Murder Party 3).
Игры, телефоны игроков, озвучка и Додо Ре Ми работают в вашей сети без интернета.

[Скачать](https://github.com/zAsQwE/localbox/releases) · [Telegram](https://t.me/lacalbox)

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

## Обновление

**«Проверить обновления» → «Обновить до …»**. Настройки и скачанные файлы сохраняются.

## Документация

- [Ручная установка и решение проблем](docs/manual.md)
- [Установщик и сборка Release](docs/install.md)
- [Озвучка](docs/tts.md) · [Додо Ре Ми](docs/dodo-re-mi.md) · [Админские читы](docs/cheats.md)
- [Android](android/README.md)

Проект создан с помощью Claude и Codex. Безопасность не гарантирована: используйте его
в локальной сети или для игры с друзьями. LocalBox не связан с Jackbox Games, оригинальные игры
и материалы принадлежат их правообладателям.
