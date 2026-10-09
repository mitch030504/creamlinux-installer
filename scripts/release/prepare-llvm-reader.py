#!/usr/bin/env python3
"""Prepare the pinned Ubuntu x86_64 CI reader; never install LLVM packages.

Print only its bin directory for GITHUB_PATH. Reuse the ARM64 runtime's selected
Debian-payload extraction and private-library launcher, without changing it.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/android-steam-proxy'))
from build_llvm_runtime import LAUNCHER, payload
sys.path.insert(0, str(ROOT/'tools/android-steam-proxy/tests'))
from scan_consumers import inspect_elf


def preflight(reader, version='20.1.8'):
    selected = shutil.which(str(reader))
    if not selected:
        raise ValueError('Required llvm-readelf is missing; prepare the pinned CI reader')
    result = subprocess.run([selected, '--version'], capture_output=True, text=True, timeout=30)
    if result.returncode or not re.search(r'\bLLVM version '+re.escape(version)+r'(?![\d.])', result.stdout):
        raise ValueError(f'Required llvm-readelf version {version} is unavailable: {selected}; '
                         'use scripts/release/prepare-llvm-reader.py, not the Ubuntu llvm metapackage')
    if not shutil.which('clang') or not shutil.which('ld.lld'):
        raise ValueError('Reader preflight needs clang and ld.lld to compile representative ELF fixtures')
    with tempfile.TemporaryDirectory(prefix='llvm-reader-probe-') as directory:
        root = Path(directory)
        provider = root/'libreadelf-probe.so'
        consumer = root/'consumer.so'
        provider_source = root/'provider.c'
        consumer_source = root/'consumer.c'
        provider_source.write_text('int probe_function(int n){return n+1;}\n'
                                  '__attribute__((weak)) int weak_probe(void){return 2;}\n'
                                  'int probe_object=3;\n')
        consumer_source.write_text('extern int probe_function(int);\n'
                                  'int (*const pointer_probe)(int)=probe_function;\n'
                                  'int entry(void){return probe_function(1);}\n')
        flags = ['clang', '--target=aarch64-linux-android21', '-fuse-ld=lld', '-fPIC', '-shared', '-nostdlib']
        for cmd in [flags+[str(provider_source), '-Wl,-soname=libreadelf-probe.so', '-o', str(provider)],
                    flags+[str(consumer_source), str(provider), '-Wl,--pack-dyn-relocs=android', '-o', str(consumer)]]:
            compiled = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if compiled.returncode:
                raise ValueError('LLVM reader ELF fixture compilation failed: '+compiled.stderr.strip())
        try:
            p = inspect_elf('provider probe', provider, provider.read_bytes(), selected,
                            names=('probe_function', 'probe_object', 'weak_probe'))
            c = inspect_elf('consumer probe', consumer, consumer.read_bytes(), selected,
                            names=('probe_function',))
            exports = {s['symbol']: s for s in p['public_exports']}
            if (p['architecture'] != 'aarch64' or not p['inspection_complete'] or
                    not c['inspection_complete'] or p['soname'] != provider.name or
                    exports['probe_function']['type'] != 'Function' or
                    exports['weak_probe']['binding'] != 'Weak' or
                    exports['probe_object']['type'] != 'Object' or
                    c['dt_needed'] != [provider.name] or
                    not any(s['symbol'] == 'probe_function' for s in c['imported_symbols']) or
                    not any(s['symbol'] == 'probe_function' for s in c['relocations'])):
                raise ValueError('Representative ELF evidence did not match')
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ValueError('Required LLVM JSON inspection failed: '+str(error)) from error
    return {'status': 'passed', 'version': version, 'reader': str(Path(selected).absolute()),
            'fixtures': ['AArch64 provider with GLOBAL/WEAK/functions/object/SONAME',
                         'AArch64 consumer with DT_NEEDED/imports/Android packed relocations'],
            'steam_api_calls': 0}


def prepare(destination, cache, pin):
    destination, cache = Path(destination).absolute(), Path(cache).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('LLVM output already exists; choose a fresh private directory')
    if destination == cache or destination in cache.parents or cache in destination.parents:
        raise ValueError('LLVM output and package cache must be separate')
    destination.parent.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='llvm-preparation-', dir=destination.parent) as directory:
        result = Path(directory)/'result'
        result.mkdir()
        for name, record in pin['packages'].items():
            if not record['url'].startswith('https://apt.llvm.org/noble/pool/main/l/llvm-toolchain-20/'):
                raise ValueError('Unexpected LLVM package source URL')
            archive = cache/(name+'.deb')
            if archive.is_symlink():
                raise ValueError('Symlink LLVM package cache entry')
            if not archive.exists():
                with urllib.request.urlopen(record['url'], timeout=60) as stream:
                    raw = stream.read(record['size_bytes']+1)
                if len(raw) != record['size_bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
                    raise ValueError('Pinned LLVM package checksum/size mismatch: '+name)
                archive.write_bytes(raw)
            with archive.open('rb') as stream:
                checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            if archive.stat().st_size != record['size_bytes'] or checksum != record['sha256']:
                raise ValueError('Pinned LLVM package checksum/size mismatch: '+name)
            for member, raw in payload(archive, record['members']).items():
                path = Path(record['members'][member])
                if path.is_absolute() or '..' in path.parts or path.parts[0] not in {'lib', 'libexec', 'licenses'}:
                    raise ValueError('Unsafe selected LLVM payload path')
                if path.parts[0] in {'lib', 'libexec'} and (raw[:6] != b'\x7fELF\x02\x01' or raw[18:20] != b'\x3e\x00'):
                    raise ValueError('Expected x86_64 ELF LLVM payload')
                target = result/path
                if target.exists():
                    raise ValueError('Duplicate selected LLVM payload path')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                if path.parts[0] == 'libexec':
                    target.chmod(0o755)
        (result/'bin').mkdir()
        (result/'bin/llvm-readelf').write_text(LAUNCHER)
        (result/'bin/llvm-readelf').chmod(0o755)
        validated = preflight(result/'bin/llvm-readelf', pin['version'])
        validated['reader'] = str(destination/'bin/llvm-readelf')
        manifest = {'schema_version': 1, 'architecture': pin['architecture'], 'version': pin['version'],
                    'packages': pin['packages'], 'installed_packages': False, 'preflight': validated,
                    'sha256': {str(p.relative_to(result)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(result.rglob('*')) if p.is_file()}}
        (result/'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
        result.rename(destination)
    return destination/'bin'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path, nargs='?')
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    pin = json.loads(Path(__file__).with_name('controller.json').read_text())['llvm_reader']
    if args.preflight_only:
        report = preflight('llvm-readelf', pin['version'])
        if args.report:
            args.report.write_text(json.dumps(report, indent=2)+'\n')
        else:
            print(json.dumps(report))
    else:
        if args.destination is None or args.cache is None:
            parser.error('destination and --cache are required for preparation')
        print(prepare(args.destination, args.cache, pin))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, tarfile.TarError) as error:
        print('CI LLVM reader preparation failed: '+str(error), file=sys.stderr)
        sys.exit(2)
