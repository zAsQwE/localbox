#
#   LocalBox - local private server for Jackbox games
#   Copyright (C) 2026 LocalBox contributors
#   Licensed under the GNU Affero General Public License v3 or later.
#
"""Генерация локального TLS-сертификата для сервера без изменения хранилищ доверия.

Поддерживает имена и IP-адреса (например, локальный IP 192.168.1.10, чтобы телефоны в той
же сети подключались по https://192.168.1.10).

Стратегия:
  1) через openssl создаём собственный корневой CA LocalBox и подписываем им сертификат IP;
  2) сертификат и ключи сохраняются только в certs/ внутри LocalBox;
  3) если openssl недоступен, используем mkcert только для генерации, без установки CA.
"""

import ipaddress
import os
import platform as _pyplat
import shutil
import ssl
import stat
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from . import platform as plat

# Портативный mkcert скачиваем сами, если его нет в системе (особенно для старых Windows,
# где нет ни winget, ни openssl). Один статический бинарник, установка не нужна.
MKCERT_VERSION = "v1.4.4"


def _which(name):
    return shutil.which(name)


def _openssl_path() -> str | None:
    found = _which("openssl")
    if found:
        return found
    exe = "openssl.exe" if plat.is_windows() else "openssl"
    candidates = [
        plat.repo_root() / "runtime" / exe,
        plat.repo_root() / "runtime" / "bin" / exe,
    ]
    if plat.is_windows():
        for base in filter(None, [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")]):
            candidates.extend([
                Path(base) / "Git" / "usr" / "bin" / exe,
                Path(base) / "Git" / "mingw64" / "bin" / exe,
                Path(base) / "Programs" / "Git" / "usr" / "bin" / exe,
            ])
    elif plat.is_macos():
        candidates.extend([
            Path("/opt/homebrew/opt/openssl@3/bin/openssl"),
            Path("/usr/local/opt/openssl@3/bin/openssl"),
            Path("/opt/homebrew/bin/openssl"),
        ])
    return next((str(candidate) for candidate in candidates if candidate.is_file()), None)


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
        log(f"Не удалось скачать mkcert ({e}).")
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


def localbox_ca_files(certs_dir: Path):
    return certs_dir / "localbox-ca.pem", certs_dir / "localbox-ca-key.pem"


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
    try:
        info = ssl._ssl._test_decode_cert(str(cert))
        now = time.time()
        if not ssl.cert_time_to_seconds(info["notBefore"]) <= now < ssl.cert_time_to_seconds(info["notAfter"]):
            return False
        # Also reject a damaged key or a key belonging to a different certificate.
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(str(cert), str(key))
        for typ, name in info.get("subjectAltName", ()):
            if typ == "IP Address" and is_ip(host) and ipaddress.ip_address(host) == ipaddress.ip_address(name):
                return True
            if typ == "DNS" and name.lower() == host.lower():
                return True
    except (OSError, ValueError, KeyError):
        pass
    return False


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

    if not force and all(cert_ok_for(name) for name in names):
        log(f"Сертификат уже есть: {cert} (для перегенерации используйте кнопку «Получить сертификат»)")
        return True

    log(f"Имена/IP в сертификате: {', '.join(names)}")

    if _openssl_path():
        return _generate_localbox_openssl(names, cert, key, log)
    mk = _ensure_mkcert(log)
    if mk and _generate_mkcert(mk, names, cert, key, log):
        return True

    log("Не найден openssl, а mkcert не удалось скачать.")
    log("Проверьте интернет и повторите либо установите openssl вручную.")
    return False


def ensure_cert(host: str, log=print, extra_names=None, force: bool = False) -> bool:
    """Гарантирует наличие сертификата для host (+ localhost, 127.0.0.1, домены Jackbox).

    extra_names — дополнительные имена/IP (например, локальный IP сети).
    """
    names = [host, *(extra_names or []), "localhost", "127.0.0.1", *plat.JACKBOX_HOSTS]
    return generate_cert(names, log=log, force=force)


def ensure_local_cert(local_ip: str, log=print, force: bool = True) -> bool:
    """Сертификат LocalBox для локального IP (например, 192.168.1.10)."""
    if not is_ip(local_ip):
        log(f"«{local_ip}» не похоже на IP-адрес.")
        return False
    return generate_cert(
        [local_ip, plat.local_ip(), "localhost", "127.0.0.1", *plat.JACKBOX_HOSTS],
        log=log, force=force,
    )


def _generate_mkcert(mk, names, cert: Path, key: Path, log) -> bool:
    """Creates files in LocalBox only; never invokes mkcert's CA installation mode."""
    log("Генерация локального сертификата через mkcert…")
    # Override a user's global CAROOT so neither the CA nor its key goes into shared storage.
    caroot = cert.parent / "mkcert-ca"
    work = Path(tempfile.mkdtemp(prefix="localbox-cert-", dir=cert.parent))
    new_cert, new_key = work / "server.pem", work / "server-key.pem"
    env = {**os.environ, "CAROOT": str(caroot.resolve())}
    try:
        subprocess.run(
            [mk, "-cert-file", str(new_cert), "-key-file", str(new_key), *names],
            env=env, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        shutil.copyfile(caroot / "rootCA.pem", localbox_ca_files(cert.parent)[0])
        shutil.copyfile(caroot / "rootCA.pem", cert.parent / "localbox-rootCA.pem")
        new_cert.replace(cert)
        new_key.replace(key)
        try:
            key.chmod(0o600)
            (caroot / "rootCA-key.pem").chmod(0o600)
        except OSError:
            pass
        log(f"Готово: {cert}. Хранилища доверия не изменялись.")
        return True
    except (subprocess.CalledProcessError, OSError) as e:
        log(f"mkcert не смог сгенерировать сертификат: {getattr(e, 'stderr', None) or e}")
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _generate_localbox_openssl(names, cert: Path, key: Path, log) -> bool:
    """Creates one persistent LocalBox CA and a replaceable IP/DNS leaf certificate."""
    openssl = _openssl_path() or "openssl"
    ca, ca_key = localbox_ca_files(cert.parent)
    work = Path(tempfile.mkdtemp(prefix="localbox-cert-", dir=cert.parent))
    new_ca, new_ca_key = work / "ca.pem", work / "ca-key.pem"
    new_cert, new_key, csr, ext = work / "server.pem", work / "server-key.pem", work / "server.csr", work / "server.ext"
    try:
        use_existing_ca = ca.is_file() and ca_key.is_file()
        if use_existing_ca:
            # Reject an expired/damaged CA or a mismatched private key.
            ca_check = subprocess.run(
                [openssl, "x509", "-checkend", "86400", "-noout", "-in", str(ca)],
                capture_output=True,
            )
            pub_cert = subprocess.run([openssl, "x509", "-in", str(ca), "-pubkey", "-noout"], capture_output=True)
            pub_key = subprocess.run([openssl, "pkey", "-in", str(ca_key), "-pubout"], capture_output=True)
            use_existing_ca = ca_check.returncode == 0 and pub_cert.returncode == 0 and pub_cert.stdout == pub_key.stdout

        if use_existing_ca:
            shutil.copyfile(ca, new_ca)
            shutil.copyfile(ca_key, new_ca_key)
        else:
            log("Создаю локальный корневой сертификат LocalBox…")
            subprocess.run([
                openssl, "req", "-x509", "-newkey", "rsa:3072", "-nodes", "-sha256",
                "-keyout", str(new_ca_key), "-out", str(new_ca), "-days", "3650",
                "-subj", "/O=LocalBox/CN=LocalBox Local CA",
                "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                "-addext", "subjectKeyIdentifier=hash",
            ], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")

        san_lines = []
        for index, name in enumerate(names, 1):
            if not is_ip(name) and (not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_" for c in name)):
                raise ValueError(f"недопустимое имя для сертификата: {name!r}")
            san_lines.append(f"{'IP' if is_ip(name) else 'DNS'}.{index} = {name}")
        ext.write_text(
            "basicConstraints = critical,CA:FALSE\n"
            "keyUsage = critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage = serverAuth\n"
            "subjectKeyIdentifier = hash\n"
            "authorityKeyIdentifier = keyid,issuer\n"
            "subjectAltName = @alt_names\n[alt_names]\n" + "\n".join(san_lines) + "\n",
            encoding="ascii",
        )
        log("Подписываю сертификат сервера локальным CA LocalBox…")
        subprocess.run([
            openssl, "req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256",
            "-keyout", str(new_key), "-out", str(csr), "-subj", f"/O=LocalBox/CN={names[0]}",
        ], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        serial = "0x" + os.urandom(16).hex()
        subprocess.run([
            openssl, "x509", "-req", "-in", str(csr), "-CA", str(new_ca), "-CAkey", str(new_ca_key),
            "-set_serial", serial, "-out", str(new_cert), "-days", "825", "-sha256", "-extfile", str(ext),
        ], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        subprocess.run([openssl, "verify", "-CAfile", str(new_ca), str(new_cert)], check=True, capture_output=True)

        for source, destination in [(new_ca, ca), (new_ca_key, ca_key), (new_cert, cert), (new_key, key)]:
            source.replace(destination)
        # Public download served by LocalBox; this remains inside certs/.
        shutil.copyfile(ca, cert.parent / "localbox-rootCA.pem")
        try:
            ca_key.chmod(0o600)
            key.chmod(0o600)
        except OSError:
            pass
        log(f"Готово: {cert} (подписан LocalBox Local CA)")
        log("Сертификат и ключи сохранены локально. Хранилища доверия не изменялись.")
        return True
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        detail = getattr(e, "stderr", None) or str(e)
        log(f"Не удалось создать сертификат LocalBox: {detail}")
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


# Kept as an internal compatibility alias for older imports/tests.
_generate_openssl = _generate_localbox_openssl
