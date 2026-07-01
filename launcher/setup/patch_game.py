#
#   LocalBox - local private server for Jackbox games
#   Copyright (C) 2026 LocalBox contributors
#   Licensed under the GNU Affero General Public License v3 or later.
#
"""Подмена serverUrl в jbg.config.jet установленных Steam-игр Jackbox.

Игра читает адрес сервера из jbg.config.jet. Чтобы она обращалась к LocalBox, подменяем
там serverUrl на наш хост. Перед правкой делаем резервную копию <файл>.localbox-backup,
чтобы можно было откатиться.
"""

import re
from pathlib import Path

from . import platform as plat

CONFIG_NAME = "jbg.config.jet"
BACKUP_SUFFIX = ".localbox-backup"

# serverUrl может встречаться как "serverUrl":"https://ecast.jackboxgames.com" и т.п.
_SERVER_URL_RE = re.compile(r'("serverUrl"\s*:\s*")([^"]*)(")')


def find_configs(log=print):
    """Ищет все jbg.config.jet в библиотеках Steam. Возвращает список путей."""
    found = []
    for common in plat.steam_library_candidates():
        for path in common.rglob(CONFIG_NAME):
            found.append(path)
    if found:
        log(f"Найдено конфигов игр: {len(found)}")
    else:
        log("Конфиги игр (jbg.config.jet) не найдены в библиотеках Steam.")
        log("Проверьте, что игры Jackbox установлены, либо укажите путь вручную.")
    return found


def patch_file(path: Path, host: str, *, scheme: str = "https", log=print, dry_run=False) -> bool:
    """Подменяет serverUrl в одном файле. Возвращает True, если файл изменён/совпадает."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        log(f"Не удалось прочитать {path}: {e}")
        return False

    new_url = f"{scheme}://{host}"
    new_text, count = _SERVER_URL_RE.subn(rf'\g<1>{new_url}\g<3>', text)

    if count == 0:
        log(f"В {path.name} не найден serverUrl — пропуск ({path.parent.name})")
        return False

    if dry_run:
        log(f"[dry-run] {path}: serverUrl -> {new_url} ({count} вхожд.)")
        return True

    backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")
    path.write_text(new_text, encoding="utf-8")
    log(f"Пропатчено: {path.parent.name} -> {new_url}")
    return True


def patch_all(host: str, *, log=print, dry_run=False) -> int:
    """Патчит все найденные игры. Возвращает число изменённых файлов."""
    configs = find_configs(log=log)
    n = 0
    for path in configs:
        if patch_file(path, host, log=log, dry_run=dry_run):
            n += 1
    return n


def restore_all(log=print) -> int:
    """Восстанавливает оригинальные конфиги из .localbox-backup."""
    n = 0
    for common in plat.steam_library_candidates():
        for backup in common.rglob(CONFIG_NAME + BACKUP_SUFFIX):
            original = backup.with_suffix("")  # убираем .localbox-backup
            try:
                original.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
                backup.unlink()
                log(f"Восстановлено: {original.parent.name}")
                n += 1
            except Exception as e:  # noqa: BLE001
                log(f"Не удалось восстановить {original}: {e}")
    return n
