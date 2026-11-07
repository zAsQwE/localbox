#!/usr/bin/env python3
"""Build LocalBox Android APK with the embedded Go engine (no Termux).
Requires Go, JDK 17+, Android SDK/NDK and Gradle 8.13 (or ./gradlew).
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def build(options):
    sdk = Path(options.sdk or os.environ.get('ANDROID_HOME') or Path.home()/'Android/Sdk').resolve()
    available = list((sdk/'ndk').glob('*/toolchains/llvm/prebuilt/linux-x86_64'))
    if not available:
        raise RuntimeError('Android NDK for Linux x86_64 not found. Pass --sdk or ANDROID_HOME.')
    ndk = max(available, key=lambda p: tuple(int(n) for n in p.parents[3].name.split('.')))
    bins = ndk/'bin'
    env = dict(os.environ, ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk),
               GOCACHE=str(ROOT/'.cache/go-build'))
    targets = [('arm64-v8a', 'arm64', 'aarch64'), ('x86_64', 'amd64', 'x86_64')]
    for abi, arch, triple in targets:
        target = ROOT/'vpn/app/src/main/jniLibs'/abi
        target.mkdir(parents=True, exist_ok=True)
        print('Go engine:', abi, flush=True)
        native_env = dict(env, GOOS='android', GOARCH=arch, CGO_ENABLED='1',
                          CC=str(bins/(triple+'-linux-android24-clang')),
                          CGO_LDFLAGS='-Wl,-z,max-page-size=16384')
        subprocess.run([options.go, 'build', '-buildmode=c-shared', '-trimpath', '-ldflags=-s -w',
                        '-o', str(target/'liblocalbox_server.so'), '.'], cwd=ROOT/'server', env=native_env, check=True)
        (target/'liblocalbox_server.h').unlink(missing_ok=True)
    assets = ROOT/'vpn/app/src/main/assets'
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO/'server/games.json', assets/'games.json')
    subprocess.run([options.gradle, '--no-daemon', 'testDebugUnitTest', 'assembleDebug'],
                   cwd=ROOT/'vpn', env=env, check=True)
    output = ROOT/'dist'
    output.mkdir(exist_ok=True)
    destination = output/'LocalBox-android-dev.apk'
    shutil.copy2(ROOT/'vpn/app/build/outputs/apk/debug/app-debug.apk', destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    (output/'SHA256SUMS').write_text(f'{digest}  {destination.name}\n', encoding='utf-8')
    print('APK:', destination, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk')
    parser.add_argument('--go', default='go')
    parser.add_argument('--gradle', default='./gradlew')
    build(parser.parse_args())
