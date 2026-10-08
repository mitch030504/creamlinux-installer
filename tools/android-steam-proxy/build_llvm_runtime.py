#!/usr/bin/env python3
"""Build a pinned ARM64 host LLVM reader bundle; never install packages.

Only explicitly selected package payloads are copied. The LLVM shared library
is private to the reader launcher; system display/C++ libraries are not bundled.
"""
import argparse
import hashlib
import io
import json
import pathlib
import subprocess
import sys
import tarfile
import urllib.request

BASE = 'https://apt.llvm.org/noble/'
VERSION = '20.1.8~++20250804090239+87f0227cb601-1~exp1~20250804210352.139'
PACKAGES = {
    'llvm-20': dict(sha256='7d5ad3228c2fb16ab8d78b9e60d4449bd3c69b89273401adcf7e8fff100f3db7',
        members={'./usr/lib/llvm-20/bin/llvm-readobj': 'libexec/llvm-readobj',
                 './usr/share/doc/llvm-20/copyright': 'licenses/llvm-20-copyright'}),
    'libllvm20': dict(sha256='3306e0834d75958d03a3bc46e5ffb5cf4d15638fa29ce79c7738cd6e35006f57',
        members={'./usr/lib/aarch64-linux-gnu/libLLVM.so.20.1': 'lib/libLLVM.so.20.1',
                 './usr/share/doc/libllvm20/copyright': 'licenses/libllvm20-copyright'}),
    'libedit2': dict(sha256='cf642fec16d86517e0e715520c3a7cdaee650e7ae8a4993f82d0e1e7a5883efb',
        url='https://ports.ubuntu.com/ubuntu-ports/pool/main/libe/libedit/libedit2_3.1-20230828-1build1_arm64.deb',
        members={'./usr/lib/aarch64-linux-gnu/libedit.so.2.0.72': 'lib/libedit.so.2',
                 './usr/share/doc/libedit2/copyright': 'licenses/libedit2-copyright'}),
    'libtinfo6': dict(sha256='e8d06277be81d0f6e7d49ce796a477a9fc88e755bf3048e0afe44fc14a310b72',
        url='https://ports.ubuntu.com/ubuntu-ports/pool/main/n/ncurses/libtinfo6_6.4+20240113-1ubuntu2_arm64.deb',
        members={'./usr/lib/aarch64-linux-gnu/libtinfo.so.6.4': 'lib/libtinfo.so.6',
                 './usr/share/doc/libtinfo6/copyright': 'licenses/libtinfo6-copyright'}),
}
LAUNCHER = '''#!/bin/sh
set -eu
runtime_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
unset LD_PRELOAD
export LD_LIBRARY_PATH="$runtime_dir/lib"
exec "$runtime_dir/libexec/llvm-readobj" "$@"
'''


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def payload(path, selection):
    listing = subprocess.run(['ar', 't', str(path)], check=True, capture_output=True,
                             text=True, timeout=30).stdout.splitlines()
    archives = [name for name in listing if name.startswith('data.tar')]
    if len(archives) != 1:
        raise ValueError('expected exactly one Debian data archive')
    raw = subprocess.run(['ar', 'p', str(path), archives[0]], check=True,
                         capture_output=True, timeout=60).stdout
    result = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            if member.name not in selection:
                continue
            if not member.isfile() or member.name in result or not 0 <= member.size <= 160 * 1024 * 1024:
                raise ValueError('invalid/duplicate selected package member')
            result[member.name] = archive.extractfile(member).read()
    if set(result) != set(selection):
        raise ValueError('package lacks an expected pinned payload')
    return result


def build(cache, output, download=False):
    cache, output = pathlib.Path(cache).resolve(), pathlib.Path(output).resolve()
    if (output == cache or cache in output.parents or output == pathlib.Path('/data/app') or
            pathlib.Path('/data/app') in output.parents):
        raise ValueError('output must be separate from cache and installed games')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('output must be new or empty')
    cache.mkdir(parents=True, exist_ok=True)
    selected = {}
    for package, record in PACKAGES.items():
        path = cache / (package + '.deb')
        url = record.get('url') or BASE + 'pool/main/l/llvm-toolchain-20/' + package + '_' + VERSION + '_arm64.deb'
        if not path.is_file() and download:
            with urllib.request.urlopen(url, timeout=60) as stream:
                raw = stream.read(64 * 1024 * 1024 + 1)
            if len(raw) > 64 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != record['sha256']:
                raise ValueError('download checksum/size mismatch: ' + package)
            path.write_bytes(raw)
        if not path.is_file() or checksum(path) != record['sha256']:
            raise ValueError('missing or checksum-mismatched pinned package: ' + package)
        for source, raw in payload(path, record['members']).items():
            destination = record['members'][source]
            if destination.startswith(('lib/', 'libexec/')) and (
                    raw[:6] != b'\x7fELF\x02\x01' or raw[18:20] != b'\xb7\x00'):
                raise ValueError('expected ARM64 ELF payload: ' + source)
            selected[destination] = raw
    output.mkdir(parents=True, exist_ok=True)
    for name, raw in selected.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        if name.startswith('libexec/'):
            path.chmod(0o755)
    (output / 'bin').mkdir()
    (output / 'bin/llvm-readelf').write_text(LAUNCHER)
    (output / 'bin/llvm-readelf').chmod(0o755)
    manifest = dict(schema_version=1, architecture='aarch64', version='20.1.8',
        package_version=VERSION, package_source=BASE, package_sha256={p: r['sha256'] for p, r in PACKAGES.items()},
        sha256={name: hashlib.sha256(raw).hexdigest() for name, raw in selected.items()},
        installed_packages=False, private_library_path=True,
        host_requirements=['glibc >= 2.38', 'libstdc++ >= 13.1', 'libgcc_s.so.1',
                           'libbsd.so.0', 'libmd.so.0', 'libffi.so.8', 'libxml2.so.2', 'libzstd.so.1', 'libz.so.1'])
    manifest['sha256']['bin/llvm-readelf'] = hashlib.sha256(LAUNCHER.encode()).hexdigest()
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    (output / 'SHA256SUMS').write_text(''.join(
        checksum(p) + '  ' + p.relative_to(output).as_posix() + '\n'
        for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--download', action='store_true', help='Fetch missing pinned packages via HTTPS; never install')
    args = parser.parse_args()
    try:
        manifest = build(args.cache, args.output, args.download)
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print('LLVM runtime bundle failed: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
