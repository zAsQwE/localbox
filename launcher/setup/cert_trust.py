"""Confirmed installation of the selected running server's public root CA.

Runs only after the user agreed: in setup ("make the certificate trusted"), via the
launcher's certificate button, or on server start when that agreement is stored
(settings "game_trust"), to keep every Jackbox build trusting the same CA.
"""

import hashlib
import json
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import ssl
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from . import certs, engine, platform as plat
from .i18n import tr


@dataclass(frozen=True)
class Plan:
    host: str
    public_ca: str | None
    fingerprint: str | None
    active_server: bool
    renew_local: bool


@dataclass(frozen=True)
class Result:
    fingerprint: str
    source: str


def _public_data(data):
    blocks = re.findall(r"-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----", data)
    if "PRIVATE KEY" in data or len(blocks) != 1 or data.strip() != blocks[0]:
        raise ValueError(tr('Нужен один публичный корневой сертификат без приватного ключа.'))
    der = ssl.PEM_cert_to_DER_cert(data)
    return hashlib.sha256(der).hexdigest().upper()


def _validated(data):
    fingerprint = _public_data(data)
    with tempfile.TemporaryDirectory(prefix="localbox-ca-check-") as folder:
        source = Path(folder) / "ca.pem"
        source.write_text(data, encoding="ascii")
        _validate(source)
    return fingerprint


def verify_server(host, public_ca):
    """A real handshake using only the selected public CA, including hostname checks."""
    from .game_tls import server_address
    name, _, port = server_address(host).partition(":")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=public_ca)
    with socket.create_connection((name, int(port or "443")), timeout=4) as connection:
        with context.wrap_socket(connection, server_hostname=name) as session:
            return hashlib.sha256(session.getpeercert(binary_form=True)).hexdigest().upper()


def _local_host(host):
    name = host.partition(":")[0]
    if name in ("localhost", "127.0.0.1", plat.local_ip()):
        return True
    # Also recognize Radmin and other interfaces, rather than only the default route.
    node = engine.find_node()
    if node:
        try:
            result = subprocess.run([node, "-e", "process.stdout.write(JSON.stringify(Object.values(require('node:os').networkInterfaces()).flat().map(x=>x.address)))"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and name in json.loads(result.stdout):
                return True
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError(tr('Сервер перенаправил скачивание CA. Доверие не изменено.'))


def prepare(host):
    """Read-only preparation before consent: identify the actual running server's CA."""
    from .game_tls import server_address
    host = server_address(host)
    source, _ = certs.localbox_ca_files(plat.certs_dir())
    local_ca = None
    local_fingerprint = None
    local_error = None
    try:
        local_ca = source.read_text(encoding="ascii") if source.is_file() else None
        local_fingerprint = _validated(local_ca) if local_ca else None
    except (OSError, ValueError, ssl.SSLError) as error:
        local_ca, local_error = None, error
    # Bootstrap downloads ONLY a public root, never trusts it globally. The fingerprint
    # is shown for confirmation; a private TLS handshake proves it signs the server leaf.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    try:
        with opener.open("https://" + host + "/localbox-ca.crt", timeout=4) as response:
            data = response.read(65537)
        if len(data) > 65536:
            raise ValueError(tr('Слишком большой файл CA от сервера.'))
        public_ca = data.decode("ascii")
        fingerprint = _validated(public_ca)
        try:
            verify_server(host, public_ca)
        except ssl.SSLCertVerificationError:
            # A local leaf with stale SANs can be repaired, but a different installation
            # or remote CA must never be silently replaced with our own files.
            if fingerprint != local_fingerprint:
                raise
        return Plan(host, public_ca, fingerprint, True, fingerprint == local_fingerprint)
    except urllib.error.HTTPError as error:
        raise ValueError(tr('Работающий сервер не предоставил публичный CA (HTTP {0}).', error.code)) from error
    except urllib.error.URLError as error:
        if not _local_host(host):
            raise ValueError(tr('Сервер недоступен. Его CA не заменён сертификатом этой копии LocalBox.')) from error
        if local_error is not None:
            raise ValueError(tr('Локальный CA повреждён, а работающий сервер недоступен. Доверие не изменено.')) from local_error
        return Plan(host, local_ca, local_fingerprint, False, True)


def _linux_contains(public_ca):
    expected = ssl.PEM_cert_to_DER_cert(public_ca)
    paths = [ssl.get_default_verify_paths().openssl_cafile,
             "/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem",
             "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ca-certificates/extracted/tls-ca-bundle.pem"]
    for path in dict.fromkeys(paths):
        if not path or not Path(path).is_file():
            continue
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_verify_locations(cafile=path)
            if expected in context.get_ca_certs(binary_form=True):
                return True
        except (OSError, ssl.SSLError):
            pass
    return False


def _run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=180, stdin=subprocess.DEVNULL, **kwargs)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout).strip() or
                         tr('Установка доверия отменена или завершилась с ошибкой.'))
    return result


def _validate(public_file):
    """Validate the snapshot, including CA constraints and its own signature."""
    openssl = certs._openssl_path()
    if openssl:
        info = _run([openssl, "x509", "-in", str(public_file), "-text", "-noout"]).stdout
        if "CA:TRUE" not in info:
            raise ValueError(tr('Выбранный сертификат не является корневым CA.'))
        _run([openssl, "verify", "-check_ss_sig", "-CAfile", str(public_file), str(public_file)])
        decoded = ssl._ssl._test_decode_cert(str(public_file))
        if decoded["subject"] != decoded["issuer"]:
            raise ValueError(tr('Выбранный сертификат не является корневым CA.'))
    else:
        node = engine.find_node()
        if not node:
            raise ValueError(tr('Для проверки корневого сертификата нужен OpenSSL или Node.js.'))
        _run([node, "-e", """
const fs = require('node:fs');
const { X509Certificate } = require('node:crypto');
const ca = new X509Certificate(fs.readFileSync(process.argv[1]));
const now = Date.now();
if (!ca.ca || !ca.checkIssued(ca) || !ca.verify(ca.publicKey) ||
    now < Date.parse(ca.validFrom) || now >= Date.parse(ca.validTo)) {
    throw Error('Invalid, expired or non-self-signed root CA');
}
""", str(public_file)])


def _privileged(command):
    if plat.has_admin():
        return command, {}
    pkexec = shutil.which("pkexec")
    if pkexec:
        return [pkexec, *command], {}
    sudo = shutil.which("sudo")
    askpass = plat.repo_root() / "installer" / "askpass.sh"
    if sudo and askpass.is_file():
        return [sudo, "-A", *command], {
            "env": {**os.environ, "SUDO_ASKPASS": str(askpass.resolve())},
        }
    raise ValueError(tr('Для добавления CA в Linux нужен pkexec или sudo с диалогом пароля.'))


def _install_linux(public_file, fingerprint):
    # One elevation request covers both storing the root and rebuilding bundles.
    shell = "/bin/sh"
    update = shutil.which("update-ca-certificates")
    install = shutil.which("install")
    if update and install:
        destination = "/usr/local/share/ca-certificates/localbox-" + fingerprint.lower() + ".crt"
        command = [shell, "-c",
                   '"$1" -d -m 0755 /usr/local/share/ca-certificates && '
                   '"$1" -m 0644 -- "$2" "$3" && "$4"',
                   "localbox-trust", install, str(public_file), destination, update]
    else:
        trust, update = shutil.which("trust"), shutil.which("update-ca-trust")
        if not trust or not update:
            raise ValueError(tr('Не найдены системные инструменты CA: update-ca-certificates или trust и update-ca-trust.'))
        command = [shell, "-c", '"$1" anchor --store "$2" && "$3" extract',
                   "localbox-trust", trust, str(public_file), update]
    command, kwargs = _privileged(command)
    _run(command, **kwargs)


def install_local_ca(*, confirmed=False, log=print, public_ca=None):
    """Import exactly the confirmed public CA, without any private keys."""
    if not confirmed:
        raise ValueError(tr('Добавление CA в доверенные требует подтверждения пользователя.'))
    source, _ = certs.localbox_ca_files(plat.certs_dir())
    # Read once and operate only on a private snapshot; never pass a CA key to a tool.
    data = public_ca if public_ca is not None else source.read_text(encoding="ascii")
    fingerprint = _public_data(data)
    with tempfile.TemporaryDirectory(prefix="localbox-public-ca-") as folder:
        public_file = Path(folder) / "localbox-ca.crt"
        public_file.write_text(data, encoding="ascii")
        _validate(public_file)
        log(tr('Добавляю LocalBox CA в доверенные. SHA-256: {0}', fingerprint))
        if plat.is_windows():
            from . import windows_roots
            windows_roots.install(data)
        elif plat.is_macos():
            _run(["/usr/bin/security", "add-trusted-cert", "-r", "trustRoot", "-k",
                  str(Path.home() / "Library/Keychains/login.keychain-db"), str(public_file)])
        elif plat.is_linux():
            if not _linux_contains(data):
                _install_linux(public_file, fingerprint)
            if not _linux_contains(data):
                raise ValueError(tr('Системное хранилище Linux не подтвердило CA после импорта.'))
        else:
            raise ValueError(tr('Автоматическое добавление доверия на этой ОС не поддерживается.'))
    log(tr('LocalBox CA добавлен в доверенные на этом компьютере. Перезапусти браузер и игру.'))
    log(tr('Firefox, Steam/Proton и приложения со своим хранилищем могут потребовать отдельной настройки доверия.'))
    return fingerprint


def renew_and_trust(host, *, confirmed=False, log=print, plan=None):
    if not confirmed:
        raise ValueError(tr('Добавление CA в доверенные требует подтверждения пользователя.'))
    from .game_tls import server_address
    plan = plan or prepare(host)
    if plan.host != server_address(host):
        raise ValueError(tr('Адрес сервера изменился после проверки. Повтори настройку сертификата.'))
    data = plan.public_ca
    if plan.renew_local:
        if not certs.ensure_cert(host, log=log, extra_names=[plat.local_ip()], force=True):
            raise ValueError(tr('Сертификат не обновлён. Доверие не изменено.'))
        data = certs.localbox_ca_files(plat.certs_dir())[0].read_text(encoding="ascii")
        if plan.fingerprint and _public_data(data) != plan.fingerprint:
            raise ValueError(tr('CA изменился после подтверждения. Повтори настройку и проверь новый отпечаток.'))
    if plan.active_server:
        deadline = time.monotonic() + 20
        while True:
            try:
                verify_server(host, data)
                break
            except (OSError, ssl.SSLError):
                if not plan.renew_local or time.monotonic() >= deadline:
                    raise ValueError(tr('Работающий сервер не подтвердил выбранный CA. Доверие не установлено.'))
                time.sleep(0.5)
    if plat.is_linux():
        # Nothing is installed anywhere: games trust the server through the Steam line.
        fingerprint = _public_data(data)
        certs.prepare_game_ca_bundle(log)
        log(tr('Доверие не устанавливается: игры берут сертификат из строки запуска Steam (-cafile и SSL_CERT_FILE).'))
    else:
        fingerprint = install_local_ca(confirmed=True, log=log, public_ca=data)
    return Result(fingerprint, host)
