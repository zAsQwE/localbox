#
#   LocalBox - local private server for Jackbox games
#   Copyright (C) 2026 LocalBox contributors
#   Licensed under the GNU Affero General Public License v3 or later.
#
"""Режим «без домена»: перенаправление доменов Jackbox на локальный сервер через hosts-файл.

Все правки помещаются между маркерами LocalBox, чтобы их можно было аккуратно снять.
"""

from pathlib import Path

from . import platform as plat

BEGIN = "# >>> LocalBox begin >>>"
END = "# <<< LocalBox end <<<"


def _block(target_ip: str) -> str:
    lines = [BEGIN]
    for host in plat.JACKBOX_HOSTS:
        lines.append(f"{target_ip}\t{host}")
    lines.append(END)
    return "\n".join(lines) + "\n"


def _strip_existing(text: str) -> str:
    if BEGIN not in text:
        return text
    before, _, rest = text.partition(BEGIN)
    _, _, after = rest.partition(END)
    return (before.rstrip("\n") + "\n" + after.lstrip("\n")).strip("\n") + "\n"


def preview(target_ip: str = "127.0.0.1") -> str:
    """Возвращает блок, который будет добавлен (для dry-run/показа в GUI)."""
    return _block(target_ip)


def apply(target_ip: str = "127.0.0.1", log=print, dry_run: bool = False) -> bool:
    """Добавляет/обновляет блок LocalBox в hosts. Требует прав администратора."""
    path = plat.hosts_path()
    block = _block(target_ip)

    if dry_run:
        log(f"[dry-run] В {path} был бы записан блок:\n{block}")
        return True

    if not plat.has_admin():
        log(f"Нужны права администратора для правки {path}.")
        log("Запустите лаунчер от имени администратора (Windows) или через sudo (Linux/macOS).")
        return False

    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        new_text = _strip_existing(text).rstrip("\n") + "\n\n" + block
        path.write_text(new_text, encoding="utf-8")
        log(f"hosts обновлён: домены Jackbox -> {target_ip}")
        return True
    except PermissionError:
        log(f"Отказано в доступе к {path}. Нужны права администратора.")
        return False
    except Exception as e:  # noqa: BLE001
        log(f"Ошибка правки hosts: {e}")
        return False


def remove(log=print) -> bool:
    """Удаляет блок LocalBox из hosts (откат режима «без домена»)."""
    path = plat.hosts_path()
    if not path.exists():
        return True
    if not plat.has_admin():
        log("Нужны права администратора для очистки hosts.")
        return False
    try:
        text = path.read_text(encoding="utf-8")
        path.write_text(_strip_existing(text), encoding="utf-8")
        log("Блок LocalBox удалён из hosts.")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"Ошибка очистки hosts: {e}")
        return False
