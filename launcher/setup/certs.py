#
#   LocalBox - local private server for Jackbox games
#   Copyright (C) 2026 LocalBox contributors
#   Licensed under the GNU Affero General Public License v3 or later.
#
"""Генерация локально-доверенного TLS-сертификата для сервера.

Поддерживает имена и IP-адреса (например, локальный IP 192.168.1.10, чтобы телефоны в той
же сети подключались по https://192.168.1.10).

Стратегия:
  1) если установлен mkcert — используем его (сразу доверенный в системе, понимает и IP);
  2) иначе пробуем openssl для самоподписанного сертификата (нужно доверие вручную);
  3) при отсутствии обоих — понятная инструкция пользователю.
"""

import ipaddress
import platform as _pyplat
import shutil
import ssl
import stat
import subprocess
import urllib.request
from pathlib import Path

from . import platform as plat

# Портативный mkcert скачиваем сами, если его нет в системе (особенно для старых Windows,
# где нет ни winget, ни openssl). Один статический бинарник, установка не нужна.
MKCERT_VERSION = "v1.4.4"


def _which(name):
    return shutil.which(name)


def _mkcert_local_path() -> Path:
    exe = "mkcert.exe" if plat.is_windows() else "mkcert"
    return plat.repo_root() / "runtime" / exe


def _mkcert_asset() -> str:
    sysname = "windows" if plat.is_windows() else ("darwin" if plat.is_macos() else "linux")
    m = (_pyplat.machine() or "").lower()
    arch = "arm64" if m in ("arm64", "aarch64") else "amd64"
    name = f"mkcert-{MKCERT_VERSION}-{sysname}-{arch}"
    return name + ".exe" if plat.is_windows() else name


def _ensure_mkcert(log):
    """Возвращает путь к mkcert: из PATH, из локального кэша, иначе скачивает с GitHub.

    Скачивание не требует winget/openssl — только интернет один раз. Возвращает None, если
    скачать не удалось (тогда откатимся на openssl или инструкцию).
    """
    found = _which("mkcert")
    if found:
        return found
    local = _mkcert_local_path()
    if local.exists():
        return str(local)
    asset = _mkcert_asset()
    url = f"https://github.com/FiloSottile/mkcert/releases/download/{MKCERT_VERSION}/{asset}"
    tmp = local.with_name(local.name + ".part")
    try:
        log(f"mkcert не найден — скачиваю {asset} (~5 МБ, один раз)…")
        local.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "LocalBox"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:  # noqa: S310
            shutil.copyfileobj(r, f)
        tmp.replace(local)
        if not plat.is_windows():
            local.chmod(local.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        log(f"mkcert готов: {local}")
        return str(local)
    except Exception as e:  # noqa: BLE001
        log(f"Не удалось скачать mkcert ({e}). Откат на openssl/самоподписанный.")
        try:
            tmp.unlink()
        except OSError:
            pass
        return None


def is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def cert_files(certs_dir: Path):
    return certs_dir / "localbox.pem", certs_dir / "localbox-key.pem"


def _cert_sans(cert_path: Path):
    """Список SAN-имён из PEM-сертификата (через stdlib ssl, без внешних зависимостей)."""
    try:
        info = ssl._ssl._test_decode_cert(str(cert_path))  # noqa: SLF001
        return [val for _typ, val in info.get("subjectAltName", ())]
    except Exception:  # noqa: BLE001
        return []


def cert_ok_for(host: str) -> bool:
    """Покрывает ли текущий серт этот адрес (иначе хост/телефон выдаёт «bad certificate»)."""
    cert, key = cert_files(plat.certs_dir())
    if not cert.exists() or not key.exists():
        return False
    return host in _cert_sans(cert)


def _dedup(names):
    seen = set()
    out = []
    for n in names:
        n = (n or "").strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def generate_cert(names, log=print, force: bool = False) -> bool:
    """Создаёт cert/key в certs/ для переданного списка имён/IP.

    force=True перегенерирует, даже если файлы уже есть.
    """
    certs_dir = plat.certs_dir()
    certs_dir.mkdir(parents=True, exist_ok=True)
    cert, key = cert_files(certs_dir)

    names = _dedup(names)
    if not names:
        log("Не задано ни одного имени/IP для сертификата.")
        return False

    if cert.exists() and key.exists() and not force:
        log(f"Сертификат уже есть: {cert} (для перегенерации используйте кнопку «Получить сертификат»)")
        return True

    log(f"Имена/IP в сертификате: {', '.join(names)}")

    mk = _ensure_mkcert(log)
    if mk:
        return _generate_mkcert(mk, names, cert, key, log)
    if _which("openssl"):
        return _generate_openssl(names, cert, key, log)

    log("Не найден mkcert (не удалось скачать) и нет openssl.")
    log("Проверьте интернет и повторите, либо поставьте mkcert/openssl вручную.")
    return False


def ensure_cert(host: str, log=print, extra_names=None, force: bool = False) -> bool:
    """Гарантирует наличие сертификата для host (+ localhost, 127.0.0.1, домены Jackbox).

    extra_names — дополнительные имена/IP (например, локальный IP сети).
    """
    names = [host, *(extra_names or []), "localhost", "127.0.0.1", *plat.JACKBOX_HOSTS]
    return generate_cert(names, log=log, force=force)


def ensure_local_cert(local_ip: str, log=print, force: bool = True) -> bool:
    """Сертификат для локального использования по IP (mkcert 192.168.1.10 и т.п.)."""
    if not is_ip(local_ip):
        log(f"«{local_ip}» не похоже на IP-адрес.")
        return False
    return generate_cert(
        [local_ip, plat.local_ip(), "localhost", "127.0.0.1", *plat.JACKBOX_HOSTS],
        log=log, force=force,
    )


def _mkcert_caroot(mk="mkcert"):
    try:
        r = subprocess.run([mk, "-CAROOT"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        return r.stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def _generate_mkcert(mk, names, cert: Path, key: Path, log) -> bool:
    log("Генерация доверенного сертификата через mkcert…")

    # -install добавляет корневой CA в доверие (на Windows — в системное хранилище, один раз
    # запрос прав администратора). На Arch/CachyOS mkcert ошибочно зовёт update-ca-certificates
    # (Debian) вместо update-ca-trust и прерывается ДО установки в браузерное хранилище (NSS) —
    # поэтому доверие в браузер/систему добавляем сами ниже.
    subprocess.run([mk, "-install"], capture_output=True, text=True, encoding="utf-8", errors="replace")

    try:
        # mkcert принимает и доменные имена, и IP как обычные аргументы.
        subprocess.run(
            [mk, "-cert-file", str(cert), "-key-file", str(key), *names],
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        log(f"Готово: {cert}")
        trust_ca(log=log, mk=mk)
        return True
    except subprocess.CalledProcessError as e:
        log(f"mkcert не смог сгенерировать сертификат: {e.stderr or e}")
        return False


def trust_ca(log=print, mk="mkcert") -> None:
    """Добавляет корневой CA mkcert в доверенные — браузер (NSS) и подсказка для системы.

    На Linux Chrome/Chromium используют NSS-базу ~/.pki/nssdb (отдельно от системного доверия),
    поэтому без этого шага браузер не доверяет проксируемым ресурсам.
    """
    caroot = _mkcert_caroot(mk)
    if not caroot:
        return
    rootca = Path(caroot) / "rootCA.pem"
    if not rootca.exists():
        log("Корневой CA не найден — пропускаю установку доверия.")
        return

    if plat.is_linux():
        _trust_ca_nss_linux(rootca, log)
        log("Системное доверие (для игр/curl): sudo trust anchor --store " + str(rootca))
        log("ВАЖНО: на телефоне/другом устройстве этот же CA нужно установить вручную,")
        log(f"иначе устройство не доверяет серверу. Файл CA: {rootca}")
    elif plat.is_macos():
        log("macOS: доверие добавляется mkcert автоматически; при проблемах см. вывод mkcert -install.")
    # Windows: mkcert -install обычно ставит CA в системное хранилище штатно.


def _trust_ca_nss_linux(rootca: Path, log) -> None:
    if not _which("certutil"):
        log("Для доверия в Chrome нужен certutil. Установите пакет nss: sudo pacman -S nss")
        return
    nssdb = Path.home() / ".pki" / "nssdb"
    nssdb.mkdir(parents=True, exist_ok=True)
    # Удаляем старую запись с тем же ником (идемпотентность), затем добавляем.
    subprocess.run(["certutil", "-D", "-d", f"sql:{nssdb}", "-n", "mkcert-localbox"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    res = subprocess.run(
        ["certutil", "-A", "-d", f"sql:{nssdb}", "-t", "C,,", "-n", "mkcert-localbox", "-i", str(rootca)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if res.returncode == 0:
        log("CA добавлен в доверие браузера (NSS ~/.pki/nssdb). ПЕРЕЗАПУСТИТЕ Chrome/Chromium полностью.")
    else:
        log(f"Не удалось добавить CA в NSS: {res.stderr or res.stdout}")


def _generate_openssl(names, cert: Path, key: Path, log) -> bool:
    log("Генерация самоподписанного сертификата через openssl…")
    san = ",".join(
        [f"IP:{n}" if is_ip(n) else f"DNS:{n}" for n in names]
    )
    cn = names[0]
    try:
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(key), "-out", str(cert),
                "-days", "825", "-subj", f"/CN={cn}",
                "-addext", f"subjectAltName={san}",
            ],
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        log(f"Готово: {cert}")
        log("ВНИМАНИЕ: сертификат самоподписанный. Чтобы игры/телефоны ему доверяли,")
        log("добавьте его в доверенные корневые сертификаты системы/устройства вручную")
        log("(mkcert делает это автоматически — рекомендуется установить его).")
        return True
    except subprocess.CalledProcessError as e:
        log(f"openssl завершился с ошибкой: {e.stderr or e}")
        return False
