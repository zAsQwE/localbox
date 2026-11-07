"""Reversible TMP3 endpoint patch and game-scoped certificate bundle.

Only the original UTF-16 Ecast hostname is replaced. Code, Steam/EOS login and
license checks are left intact. Backups and state remain in the purchased game.
"""
from __future__ import annotations

from .i18n import tr

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import tempfile

from . import platform as plat, settings, certs

APP_ID = "3ca83887-bbe4-4b23-a254-faad85a79cfa"
APP_TAG = "tmp3"
STEAM_ID = "3048060"
DEFAULT_HOST = "ecast.jackboxgames.com"
NEEDLE = (DEFAULT_HOST + "\0").encode("utf-16-le")
EXE = Path("TMP3/Binaries/Win64/TMP3-Win64-Shipping.exe")
BUNDLE = Path("TMP3/Content/Certificates/cacert.pem")
STATE = Path("TMP3/LocalBox/connection.json")
SHA = re.compile(r"[a-f0-9]{64}")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def address(value):
    value = str(value).strip()
    if not value or len(value) > len(DEFAULT_HOST) or re.search(r"[\s/\\@?#<>\"'`=,]", value):
        raise ValueError(tr('Для TMP3 нужен IP или короткий хост без https:// (до {0} символов вместе с портом).', len(DEFAULT_HOST)))
    host, separator, port = value.partition(":")
    if separator and (not port.isdecimal() or not 1 <= int(port) <= 65535):
        raise ValueError(tr('Неверный порт TMP3.'))
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
            raise ValueError(tr('Неверный адрес TMP3.'))
    return value.lower()


def game_root(folder):
    root = Path(folder).expanduser().resolve()
    if not (root / EXE).is_file() or not (root / "TMP3.exe").is_file():
        raise ValueError(tr('Выбери папку Trivia Murder Party 3, в которой находится TMP3.exe.'))
    for relative in (EXE, BUNDLE, STATE):
        file = root / relative
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise ValueError(tr('Файлы TMP3 не должны вести за пределы папки игры.'))
    return root


def game_running():
    if os.name == "nt":
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq TMP3-Win64-Shipping.exe", "/FO", "CSV", "/NH"],
                                capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        return b"tmp3-win64-shipping.exe" in result.stdout.lower()
    proc = Path("/proc")
    if proc.is_dir():
        for process in proc.iterdir():
            if not process.name.isdecimal():
                continue
            try:
                if (process / "comm").read_text(errors="replace").strip().lower().startswith("tmp3"):
                    return True
            except OSError:
                pass
    return False


def discover():
    configured = settings.load().get("tmp3_path", "")
    if configured:
        try:
            return game_root(configured)
        except (ValueError, OSError):
            pass
    for base in plat.steam_library_candidates():
        try:
            return game_root(base / "Trivia Murder Party 3")
        except (ValueError, OSError):
            continue
    return None


def _atomic(file, data, mode=0o644):
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".localbox-", dir=file.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(mode)
        temporary.replace(file)
    finally:
        temporary.unlink(missing_ok=True)


def _backup(file, data):
    name = file.name + "." + digest(data)[:16] + ".localbox-backup"
    target = file.with_name(name)
    if target.is_symlink():
        raise ValueError(tr('Резервная копия не должна быть ссылкой.'))
    if target.exists():
        if digest(target.read_bytes()) != digest(data):
            raise ValueError(tr('Контрольная сумма резервной копии не совпала.'))
    else:
        _atomic(target, data, file.stat().st_mode & 0o777)
    return name


def _state(root):
    file = root / STATE
    if not file.exists():
        return None
    state = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("format") != 1:
        raise ValueError(tr('Неизвестный формат патча TMP3.'))
    for name in ("original_sha256", "patched_sha256", "bundle_sha256"):
        if not isinstance(state.get(name), str) or not SHA.fullmatch(state[name]):
            raise ValueError(tr('Повреждено описание патча TMP3.'))
    for key, file in (("backup", EXE), ("bundle_backup", BUNDLE)):
        name = state.get(key)
        if name is None and key == "bundle_backup":
            continue
        if not isinstance(name, str) or not re.fullmatch(re.escape(file.name) + r"\.[a-f0-9]{16}\.localbox-backup", name):
            raise ValueError(tr('Недопустимый путь резервной копии TMP3.'))
    address(state.get("host", ""))
    if state.get("bundle_backup") and (not isinstance(state.get("original_bundle_sha256"), str) or not SHA.fullmatch(state["original_bundle_sha256"])):
        raise ValueError(tr('Повреждена контрольная сумма исходного файла сертификатов TMP3.'))
    for key in ("accepted_patched_hashes", "accepted_bundle_hashes"):
        values = state.get(key, [])
        if not isinstance(values, list) or len(values) > 2 or any(not isinstance(value, str) or not SHA.fullmatch(value) for value in values):
            raise ValueError(tr('Повреждены контрольные суммы патча TMP3.'))
    return state


def _read_backup(file, name, expected=None):
    source = file.with_name(name)
    if source.is_symlink():
        raise ValueError(tr('Резервная копия TMP3 не должна быть ссылкой.'))
    data = source.read_bytes()
    if expected and digest(data) != expected:
        raise ValueError(tr('Резервная копия TMP3 повреждена; оригинал не изменён.'))
    return data


def _certificate_bundle(ca_file, original=None):
    return certs.public_ca_bundle(ca_file, original)


def inspect(folder):
    root = game_root(folder)
    state = _state(root)
    data = (root / EXE).read_bytes()
    active = bool(state and digest(data) == state["patched_sha256"])
    return {"game": str(root), "active": active, "host": state["host"] if active else None,
            "supported": data.count(NEEDLE) == 1 or active}


def restore(folder, log=print):
    if game_running():
        raise RuntimeError(tr('Закрой Trivia Murder Party 3 перед восстановлением оригинала.'))
    root = game_root(folder)
    state = _state(root)
    if not state:
        log(tr('Патч TMP3 не установлен.'))
        return False
    exe = root / EXE
    current = digest(exe.read_bytes())
    if current in {state["patched_sha256"], *state.get("accepted_patched_hashes", [])}:
        original = _read_backup(exe, state["backup"], state["original_sha256"])
        _atomic(exe, original, exe.stat().st_mode & 0o777)
    elif current != state["original_sha256"]:
        # Steam may have installed a newer build. Never roll it back to an old exe.
        log(tr('TMP3 обновлена или изменена: текущий EXE оставлен без изменений.'))
    bundle = root / BUNDLE
    if bundle.exists() and digest(bundle.read_bytes()) in {state["bundle_sha256"], *state.get("accepted_bundle_hashes", [])}:
        if state.get("bundle_backup"):
            original = _read_backup(bundle, state["bundle_backup"], state.get("original_bundle_sha256"))
            _atomic(bundle, original)
        else:
            bundle.unlink()
    elif bundle.exists():
        log(tr('Файл сертификатов изменён отдельно; он сохранён.'))
    (root / STATE).unlink()
    log(tr('Подключение TMP3 к LocalBox отменено. Резервные копии сохранены.'))
    return True


def apply(folder, host, ca_file, log=print):
    if game_running():
        raise RuntimeError(tr('Закрой Trivia Murder Party 3 перед настройкой подключения.'))
    root = game_root(folder)
    host = address(host)
    exe, bundle = root / EXE, root / BUNDLE
    state = _state(root)
    previous_state = (root / STATE).read_bytes() if state else None
    current = exe.read_bytes()
    current_hash = digest(current)
    if state and current_hash == state["patched_sha256"]:
        original = _read_backup(exe, state["backup"], state["original_sha256"])
    else:
        original = current
    if not original.startswith(b"MZ") or original.count(NEEDLE) != 1 or (APP_ID + "\0").encode("utf-16-le") not in original:
        raise ValueError(tr('Эта сборка TMP3 не распознана. EXE не изменён.'))
    index = original.index(NEEDLE)
    replacement = (host + "\0").encode("utf-16-le").ljust(len(NEEDLE), b"\0")
    patched = original[:index] + replacement + original[index + len(NEEDLE):]
    assert len(patched) == len(original)
    # Preserve the bundle that was present before the first patch, including
    # across address/CA changes. Do not accidentally back up our own old bundle.
    previous_bundle = bundle.read_bytes() if bundle.exists() else None
    original_bundle = previous_bundle
    if state and original_bundle is not None and digest(original_bundle) == state["bundle_sha256"]:
        original_bundle = _read_backup(bundle, state["bundle_backup"], state.get("original_bundle_sha256")) if state.get("bundle_backup") else None
    new_bundle = _certificate_bundle(ca_file, original_bundle)
    backup_name = _backup(exe, original)
    bundle_backup = _backup(bundle, original_bundle) if original_bundle is not None else None
    record = {"format": 1, "status": "prepared", "host": host,
              "original_sha256": digest(original), "patched_sha256": digest(patched),
              "backup": backup_name, "bundle_backup": bundle_backup,
              "original_bundle_sha256": digest(original_bundle) if original_bundle is not None else None,
              "bundle_sha256": digest(new_bundle),
              "accepted_patched_hashes": [current_hash] if state and current_hash == state["patched_sha256"] and state["original_sha256"] == digest(original) else [],
              "accepted_bundle_hashes": [digest(previous_bundle)] if state and previous_bundle is not None and digest(previous_bundle) == state["bundle_sha256"] else []}
    _atomic(root / STATE, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode())
    try:
        _atomic(bundle, new_bundle)
        _atomic(exe, patched, exe.stat().st_mode & 0o777)
        record["status"] = "active"
        _atomic(root / STATE, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode())
    except OSError:
        # Restore the exact state from before this attempt, including a previous
        # working patch, rather than silently undoing it after a failed repatch.
        if digest(exe.read_bytes()) == record["patched_sha256"]:
            _atomic(exe, current, exe.stat().st_mode & 0o777)
        if bundle.exists() and digest(bundle.read_bytes()) == record["bundle_sha256"]:
            if previous_bundle is None:
                bundle.unlink()
            else:
                _atomic(bundle, previous_bundle)
        if previous_state is None:
            (root / STATE).unlink(missing_ok=True)
        else:
            _atomic(root / STATE, previous_state)
        raise RuntimeError(tr('Не удалось применить патч TMP3. Закрой игру и проверь доступ к её папке.'))
    log(tr('TMP3 подключена к {0}. Запусти её через Steam и выбери локальную игру.', host))
    log(tr('Публичный сертификат используется только в TMP3; доверие системы не изменено.'))
    return inspect(root)


def connect(folder, host, log=print):
    if not inspect(folder)["supported"]:
        raise ValueError(tr('Эта сборка TMP3 не распознана. Файлы игры не изменены.'))
    host = address(host)
    hostname = host.partition(":")[0]
    if not certs.ensure_cert(hostname, extra_names=[plat.local_ip()], log=log):
        raise RuntimeError(tr('Не удалось подготовить сертификат LocalBox.'))
    ca = certs.localbox_ca_files(plat.certs_dir())[0]
    if not ca.is_file():
        raise RuntimeError(tr('Публичный CA LocalBox не найден. Создай сертификат в настройках лаунчера.'))
    result = apply(folder, host, ca, log)
    config = settings.load()
    config["tmp3_path"] = str(game_root(folder))
    config["game_profile"] = "tmp3"
    if not settings.save(config):
        log(tr('Патч применён, но путь игры не удалось сохранить в настройках.'))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=tr('Подключение Trivia Murder Party 3 к LocalBox'))
    parser.add_argument("--game", type=Path)
    parser.add_argument("--host", default=None, help=tr('IP LocalBox; по умолчанию адрес из настроек'))
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--inspect", action="store_true")
    args = parser.parse_args(argv)
    folder = args.game or discover()
    if not folder:
        parser.error(tr('TMP3 не найдена. Укажи --game ПАПКА_ИГРЫ'))
    try:
        if args.inspect:
            print(json.dumps(inspect(folder), ensure_ascii=False, indent=2))
        elif args.restore:
            restore(folder)
        else:
            connect(folder, args.host or settings.load().get("server_url") or plat.local_ip())
    except (OSError, ValueError, RuntimeError, ssl.SSLError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
