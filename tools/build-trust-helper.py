#!/usr/bin/env python3
"""Reproducible, CRT-free Windows ROOT helper for native Windows and Proton."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "launcher/setup/pki"


def build():
    for name in ("clang", "lld-link", "llvm-dlltool"):
        if not shutil.which(name):
            raise RuntimeError("Required build tool: " + name)
    imports = {
        "kernel32": "GetCommandLineW LocalFree CreateFileW GetFileSize ReadFile WriteFile CloseHandle GetStdHandle GetLastError ExitProcess",
        "shell32": "CommandLineToArgvW",
        "crypt32": "CryptHashCertificate2 CertCreateCertificateContext CertFreeCertificateContext CertOpenStore CertOpenSystemStoreW CertCloseStore CertAddCertificateContextToStore CertEnumCertificatesInStore",
    }
    destination = DIRECTORY / "windows-root-x64.exe"
    with tempfile.TemporaryDirectory(prefix="localbox-root-build-") as folder:
        stage = Path(folder)
        libraries = []
        for name, symbols in imports.items():
            definition = stage / (name + ".def")
            definition.write_text("LIBRARY " + name + ".dll\nEXPORTS\n" + "\n".join(symbols.split()) + "\n")
            library = stage / (name + ".lib")
            subprocess.run(["llvm-dlltool", "-m", "i386:x86-64", "-d", str(definition), "-l", str(library)], check=True)
            libraries.append(str(library))
        obj = stage / "root.obj"
        subprocess.run(["clang", "--target=x86_64-pc-windows-msvc", "-O2", "-ffreestanding", "-fno-builtin",
                        "-fno-stack-protector", "-Wall", "-Wextra", "-Werror", "-c", str(DIRECTORY / "windows-root.c"), "-o", str(obj)], check=True)
        subprocess.run(["lld-link", "/entry:mainCRTStartup", "/subsystem:console", "/nodefaultlib", "/Brepro",
                        "/out:" + str(destination), str(obj), *libraries], check=True)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    (DIRECTORY / "windows-root.json").write_text(json.dumps({"sha256": digest,
        "source_sha256": hashlib.sha256((DIRECTORY / "windows-root.c").read_bytes()).hexdigest(),
        "architecture": "x64"}, indent=2) + "\n")
    print(destination.name, digest)


if __name__ == "__main__":
    build()
