#
#   LocalBox - local private server for Jackbox games
#   Copyright (C) 2026 LocalBox contributors
#   Licensed under the GNU Affero General Public License v3 or later.
#
"""Режим «свой домен»: запись конфига сервера под пользовательский домен.

В этом режиме hosts не трогаем — предполагается, что домен указывает на машину с сервером
(через DNS), а TLS-сертификат выдан на этот домен (реальный CA или mkcert для теста).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import platform as plat


def write_config(host: str, locale: str, *, tls_enabled: bool = True,
                 http_port: int = 80, https_port: int = 443,
                 proxy_enabled: bool = False, log=print) -> Path:
    """Создаёт/обновляет config.json в корне репо. Возвращает путь."""
    path = plat.config_path()
    config = {
        "host": host,
        "httpPort": http_port,
        "httpsPort": https_port,
        "tls": {
            "enabled": tls_enabled,
            "cert": "certs/localbox.pem",
            "key": "certs/localbox-key.pem",
        },
        "defaultLocale": locale,
        "roomCodeLength": 4,
        "proxy": {
            "enabled": proxy_enabled,
            "webHosts": [
                "jackbox.tv", "www.jackbox.tv", "bundles.jackbox.tv", "cdn.jackboxgames.com",
                "jackbox.fun", "www.jackbox.fun",
            ],
            "rewriteHosts": ["ecast.jackboxgames.com", "api.jackbox.tv", "jack.fenst4r.live"],
            "doh": "https://1.1.1.1/dns-query",
            "playUrls": {"ru": "https://jackbox.fun/", "en": "https://jackbox.tv/"},
            "playUrl": "https://jackbox.tv/",
            "cacheDir": "cache/proxy",
        },
    }
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Конфиг записан: {path} (host={host}, locale={locale}, tls={tls_enabled}, proxy={proxy_enabled})")
    return path


def validate_domain(host: str) -> str | None:
    """Простейшая проверка домена. Возвращает текст ошибки или None, если ок."""
    host = (host or "").strip()
    if not host:
        return "Укажите домен"
    if " " in host or "/" in host:
        return "Домен не должен содержать пробелы или '/'"
    if "." not in host and host not in ("localhost",):
        return "Похоже на некорректный домен"
    return None
