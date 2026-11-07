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

from .i18n import tr

import ipaddress
import json
import os
import platform as _pyplat
import re
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
        log(tr('mkcert не найден — скачиваю {0} (~5 МБ, один раз)…', asset))
        local.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "LocalBox"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:  # noqa: S310
            shutil.copyfileobj(r, f)
        tmp.replace(local)
        if not plat.is_windows():
            local.chmod(local.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        log(tr('mkcert готов: {0}', local))
        return str(local)
    except Exception as e:  # noqa: BLE001
        log(tr('Не удалось скачать mkcert ({0}).', e))
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


def public_ca_bundle(ca_file, original=None):
    """Game-local roots plus LocalBox's public CA; never a system trust import."""
    public_ca = Path(ca_file).read_text(encoding="ascii")
    if "PRIVATE KEY" in public_ca:
        raise ValueError(tr('Нужен публичный CA-сертификат, а не приватный ключ.'))
    ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=public_ca)
    if original is None:
        original = "".join(ssl.DER_cert_to_PEM_cert(cert) for cert in
                           ssl.create_default_context().get_ca_certs(binary_form=True)).encode("ascii")
    combined = original + b"\n" + public_ca.encode("ascii")
    if b"PRIVATE KEY" in combined:
        raise ValueError(tr('Файл доверия игры не должен содержать приватные ключи.'))
    blocks = re.findall(rb"-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----", combined)
    return b"\n".join(dict.fromkeys(blocks)) + b"\n"


def game_bundle_path():
    return plat.certs_dir() / "localbox-ca-bundle.pem"


def prepare_game_ca_bundle(log=print):
    """Write a public bundle usable by Jackbox's -cafile launch argument."""
    temporary = None
    try:
        target = game_bundle_path()
        if target.is_symlink():
            raise ValueError(tr('Файл доверия игры не должен быть ссылкой.'))
        data = public_ca_bundle(localbox_ca_files(plat.certs_dir())[0])
        if target.is_file() and target.read_bytes() == data:
            return target
        fd, name = tempfile.mkstemp(prefix=".localbox-bundle-", dir=target.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        temporary.replace(target)
        log(tr('Публичный файл доверия для игр: {0}', target))
        return target
    except (OSError, ValueError) as error:
        log(tr('Не удалось подготовить файл доверия игры: {0}', error))
        return None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _cert_sans(cert_path: Path):
    """Список SAN-имён из PEM-сертификата (через stdlib ssl, без внешних зависимостей)."""
    try:
        info = ssl._ssl._test_decode_cert(str(cert_path))  # noqa: SLF001
        return [val for _typ, val in info.get("subjectAltName", ())]
    except Exception:  # noqa: BLE001
        return []


def _san_entries(names):
    entries = []
    for name in names:
        if is_ip(name):
            address = ipaddress.ip_address(name)
            entries.append(("IP", str(address)))
            if address.version == 4:
                # TMP3's libwebsockets verifies numeric hosts through the DNS API.
                # Keep the IP SAN as well for browsers and libcurl.
                entries.append(("DNS", str(address)))
        else:
            if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_" for c in name):
                raise ValueError(tr('недопустимое имя для сертификата: {0!r}', name))
            entries.append(("DNS", name))
    return list(dict.fromkeys(entries))


def _verify_chain(cert: Path, key: Path, ca: Path) -> bool:
    """Verify the actual signature using a private in-memory TLS handshake, never OS trust."""
    try:
        pem = cert.read_text(encoding="ascii")
        issuer = ca.read_text(encoding="ascii").strip()
        # Send the issuer explicitly; its unique subject avoids collisions with cached legacy CAs.
        if issuer not in pem or pem.count("-----BEGIN CERTIFICATE-----") < 2:
            return False
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(str(cert), str(key))
        client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client_context.check_hostname = False  # SAN is checked separately below.
        client_context.load_verify_locations(cafile=str(ca))
        server_in, server_out = ssl.MemoryBIO(), ssl.MemoryBIO()
        client_in, client_out = ssl.MemoryBIO(), ssl.MemoryBIO()
        server = server_context.wrap_bio(server_in, server_out, server_side=True)
        client = client_context.wrap_bio(client_in, client_out)
        finished = set()
        for _ in range(12):
            for name, session in (("client", client), ("server", server)):
                if name not in finished:
                    try:
                        session.do_handshake()
                        finished.add(name)
                    except ssl.SSLWantReadError:
                        pass
            server_in.write(client_out.read())
            client_in.write(server_out.read())
            if len(finished) == 2:
                return True
    except (OSError, ValueError, ssl.SSLError):
        pass
    return False


def cert_ok_for(host: str) -> bool:
    """Покрывает ли текущий серт этот адрес (иначе хост/телефон выдаёт «bad certificate»)."""
    cert, key = cert_files(plat.certs_dir())
    ca, _ = localbox_ca_files(plat.certs_dir())
    if not cert.exists() or not key.exists() or not ca.exists():
        return False
    try:
        info = ssl._ssl._test_decode_cert(str(cert))
        now = time.time()
        if not ssl.cert_time_to_seconds(info["notBefore"]) <= now < ssl.cert_time_to_seconds(info["notAfter"]):
            return False
        # Also reject a damaged key or a key belonging to a different certificate.
        if not _verify_chain(cert, key, ca):
            return False
        sans = info.get("subjectAltName", ())
        for typ, name in sans:
            if typ == "IP Address" and is_ip(host) and ipaddress.ip_address(host) == ipaddress.ip_address(name):
                if ipaddress.ip_address(host).version == 4 and ("DNS", str(ipaddress.ip_address(host))) not in sans:
                    return False
                return True
            if typ == "DNS" and not is_ip(host) and name.lower() == host.lower():
                return True
    except (OSError, ValueError, KeyError, ssl.SSLError):
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
        log(tr('Не задано ни одного имени/IP для сертификата.'))
        return False

    if not force and all(cert_ok_for(name) for name in names):
        log(tr('Сертификат уже есть: {0} (для перегенерации используйте кнопку «Обновить сертификат»)', cert))
        return prepare_game_ca_bundle(log) is not None

    log(tr('Имена/IP в сертификате: {0}', ', '.join(names)))

    if _openssl_path():
        return _generate_localbox_openssl(names, cert, key, log) and prepare_game_ca_bundle(log) is not None
    mk = _ensure_mkcert(log)
    if mk and _generate_mkcert(mk, names, cert, key, log):
        return prepare_game_ca_bundle(log) is not None

    log(tr('Не найден openssl, а mkcert не удалось скачать.'))
    log(tr('Проверьте интернет и повторите либо установите openssl вручную.'))
    return False


def ensure_cert(host: str, log=print, extra_names=None, force: bool = False) -> bool:
    """Гарантирует наличие сертификата для host (+ localhost, 127.0.0.1, домены Jackbox).

    extra_names — дополнительные имена/IP (например, локальный IP сети).
    """
    names = [host, *(extra_names or []), "localhost", "127.0.0.1", *plat.JACKBOX_TLS_NAMES]
    return generate_cert(names, log=log, force=force)


def ensure_local_cert(local_ip: str, log=print, force: bool = True) -> bool:
    """Сертификат LocalBox для локального IP (например, 192.168.1.10)."""
    if not is_ip(local_ip):
        log(tr('«{0}» не похоже на IP-адрес.', local_ip))
        return False
    return generate_cert(
        [local_ip, plat.local_ip(), "localhost", "127.0.0.1", *plat.JACKBOX_TLS_NAMES],
        log=log, force=force,
    )


def _generate_mkcert(mk, names, cert: Path, key: Path, log) -> bool:
    """Creates files in LocalBox only; never invokes mkcert's CA installation mode."""
    log(tr('Генерация локального сертификата через mkcert…'))
    # Override a user's global CAROOT so neither the CA nor its key goes into shared storage.
    caroot = cert.parent / "mkcert-ca"
    work = Path(tempfile.mkdtemp(prefix="localbox-cert-", dir=cert.parent))
    new_cert, new_key = work / "server.pem", work / "server-key.pem"
    env = {**os.environ, "CAROOT": str(caroot.resolve())}
    try:
        ca, ca_key = localbox_ca_files(cert.parent)
        if ca.exists():
            # Switching generation tools must not silently change the trusted identity.
            if not ca_key.is_file() and (caroot / "rootCA-key.pem").is_file() and (caroot / "rootCA.pem").is_file() and ca.read_bytes().strip() == (caroot / "rootCA.pem").read_bytes().strip():
                shutil.copyfile(caroot / "rootCA-key.pem", ca_key)
            if not ca_key.is_file():
                raise ValueError(tr('Отсутствует ключ существующего CA. Новый CA не создан автоматически.'))
            from .engine import find_node
            node = find_node()
            if not node:
                raise ValueError(tr('Для проверки существующего CA при смене генератора нужен Node.js.'))
            subprocess.run([node, "-e", """
const fs=require('node:fs'),crypto=require('node:crypto');
const cert=new crypto.X509Certificate(fs.readFileSync(process.argv[1]));
const key=crypto.createPrivateKey(fs.readFileSync(process.argv[2]));
const derived=crypto.createPublicKey(key).export({type:'spki',format:'der'});
const actual=cert.publicKey.export({type:'spki',format:'der'});
if(!cert.ca || !cert.verify(cert.publicKey) || !derived.equals(actual) || Date.now()>=Date.parse(cert.validTo))throw Error('CA/key validation failed');
""", str(ca), str(ca_key)], check=True, capture_output=True, text=True)
            caroot.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ca, caroot / "rootCA.pem")
            shutil.copyfile(ca_key, caroot / "rootCA-key.pem")
            (caroot / "rootCA-key.pem").chmod(0o600)
        entries = _san_entries(names)
        if any(typ == "IP" and ipaddress.ip_address(name).version == 4 for typ, name in entries):
            # mkcert's normal CLI classifies each argument as either IP or DNS.
            # A CSR preserves both SAN types without requiring OpenSSL on Windows.
            from .engine import find_node
            node = find_node()
            if not node:
                raise ValueError(tr('Для совместимого с TMP3 сертификата нужен Node.js. Установи зависимости LocalBox.'))
            csr = work / "server.csr"
            request = {"commonName": names[0], "sans": [
                {"ipHex": ipaddress.ip_address(name).packed.hex()} if typ == "IP" else {"dns": name}
                for typ, name in entries
            ]}
            subprocess.run(
                [node, str(Path(__file__).with_name("cert-csr.js")), str(csr), str(new_key)],
                input=json.dumps(request), check=True, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            command = [mk, "-cert-file", str(new_cert), "-csr", str(csr)]
        else:
            command = [mk, "-cert-file", str(new_cert), "-key-file", str(new_key), *names]
        subprocess.run(
            command,
            env=env, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        # Serve leaf + its own issuer, rather than relying on a browser's cached CA.
        new_cert.write_bytes(new_cert.read_bytes().rstrip() + b"\n" + (caroot / "rootCA.pem").read_bytes())
        if not _verify_chain(new_cert, new_key, caroot / "rootCA.pem"):
            raise ValueError(tr('Подпись сертификата mkcert не прошла проверку.'))
        shutil.copyfile(caroot / "rootCA.pem", localbox_ca_files(cert.parent)[0])
        shutil.copyfile(caroot / "rootCA-key.pem", localbox_ca_files(cert.parent)[1])
        shutil.copyfile(caroot / "rootCA.pem", cert.parent / "localbox-rootCA.pem")
        new_cert.replace(cert)
        new_key.replace(key)
        try:
            key.chmod(0o600)
            localbox_ca_files(cert.parent)[1].chmod(0o600)
            (caroot / "rootCA-key.pem").chmod(0o600)
        except OSError:
            pass
        log(tr('Готово: {0}. Хранилища доверия не изменялись.', cert))
        return True
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        log(tr('mkcert не смог сгенерировать сертификат: {0}', getattr(e, 'stderr', None) or e))
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
        # Recover a mkcert-generated key from this installation only, never a global CAROOT.
        recovered_key = cert.parent / "mkcert-ca/rootCA-key.pem"
        recovered_ca = cert.parent / "mkcert-ca/rootCA.pem"
        if ca.is_file() and not ca_key.exists() and recovered_key.is_file() and recovered_ca.is_file() and ca.read_bytes().strip() == recovered_ca.read_bytes().strip():
            shutil.copyfile(recovered_key, ca_key)
            ca_key.chmod(0o600)
        # Like LocalBox 1.1.x: a working CA is always kept, whatever its name, because
        # games, Proton prefixes and browsers may already trust it.
        use_existing_ca = ca.is_file() and ca_key.is_file()
        if use_existing_ca:
            # Reject an expired/damaged CA or a mismatched private key.
            ca_check = subprocess.run(
                [openssl, "x509", "-checkend", "86400", "-noout", "-in", str(ca)],
                capture_output=True,
            )
            pub_cert = subprocess.run([openssl, "x509", "-in", str(ca), "-pubkey", "-noout"], capture_output=True)
            pub_key = subprocess.run([openssl, "pkey", "-in", str(ca_key), "-pubout"], capture_output=True)
            ca_signature = subprocess.run([openssl, "verify", "-check_ss_sig", "-CAfile", str(ca), str(ca)], capture_output=True)
            use_existing_ca = ca_signature.returncode == 0 and ca_check.returncode == 0 and pub_cert.returncode == 0 and pub_cert.stdout == pub_key.stdout

        if (ca.exists() or ca_key.exists()) and not use_existing_ca:
            raise ValueError(tr('Корневой CA или его ключ повреждён, отсутствует либо истекает. Он не заменён автоматически: восстанови certs из резервной копии, чтобы сохранить доверие.'))

        if use_existing_ca:
            shutil.copyfile(ca, new_ca)
            shutil.copyfile(ca_key, new_ca_key)
        else:
            log(tr('Создаю локальный корневой сертификат LocalBox…'))
            subprocess.run([
                openssl, "req", "-x509", "-newkey", "rsa:3072", "-nodes", "-sha256",
                "-keyout", str(new_ca_key), "-out", str(new_ca), "-days", "3650",
                "-subj", "/O=LocalBox/CN=LocalBox Local CA " + os.urandom(8).hex(),
                "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                "-addext", "subjectKeyIdentifier=hash",
            ], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")

        san_lines = []
        for index, (typ, name) in enumerate(_san_entries(names), 1):
            san_lines.append(f"{typ}.{index} = {name}")
        ext.write_text(
            "basicConstraints = critical,CA:FALSE\n"
            "keyUsage = critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage = serverAuth\n"
            "subjectKeyIdentifier = hash\n"
            "authorityKeyIdentifier = keyid,issuer\n"
            "subjectAltName = @alt_names\n[alt_names]\n" + "\n".join(san_lines) + "\n",
            encoding="ascii",
        )
        log(tr('Подписываю сертификат сервера локальным CA LocalBox…'))
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

        new_cert.write_bytes(new_cert.read_bytes().rstrip() + b"\n" + new_ca.read_bytes())
        if not _verify_chain(new_cert, new_key, new_ca):
            raise ValueError(tr('Подпись сертификата или цепочка LocalBox CA не прошла проверку.'))
        for source, destination in [(new_ca, ca), (new_ca_key, ca_key), (new_cert, cert), (new_key, key)]:
            source.replace(destination)
        # Public download served by LocalBox; this remains inside certs/.
        shutil.copyfile(ca, cert.parent / "localbox-rootCA.pem")
        try:
            ca_key.chmod(0o600)
            key.chmod(0o600)
        except OSError:
            pass
        log(tr('Готово: {0} (подписан LocalBox Local CA)', cert))
        log(tr('Сертификат и ключи сохранены локально. Хранилища доверия не изменялись.'))
        return True
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        detail = getattr(e, "stderr", None) or str(e)
        log(tr('Не удалось создать сертификат LocalBox: {0}', detail))
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


# Kept as an internal compatibility alias for older imports/tests.
_generate_openssl = _generate_localbox_openssl
