#!/usr/bin/env python3
"""Verify and stage the pinned ARM64 reader resource without installing packages."""
import argparse
import hashlib
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/android-steam-proxy'))
from build_llvm_runtime import PACKAGES


def verify(directory):
    directory = pathlib.Path(directory).resolve(strict=True)
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest['architecture'] != 'aarch64' or manifest['package_sha256'] != {
            name: record['sha256'] for name, record in PACKAGES.items()}:
        raise ValueError('not the pinned ARM64 LLVM runtime')
    expected = {'bin/llvm-readelf'} | {name for package in PACKAGES.values() for name in package['members'].values()}
    if set(manifest['sha256']) != expected:
        raise ValueError('incomplete runtime payload/license manifest')
    checksums = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if name.startswith('/') or any(part in ('', '.', '..') for part in name.split('/')) or name in checksums:
            raise ValueError('unsafe runtime checksum member')
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.resolve() != path:
            raise ValueError('nonregular runtime payload')
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != digest or name in manifest['sha256'] and manifest['sha256'][name] != digest:
            raise ValueError('runtime payload checksum mismatch: ' + name)
        checksums[name] = digest
    if set(checksums) != expected | {'manifest.json'}:
        raise ValueError('runtime checksum coverage incomplete')
    actual_files = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file() or p.is_symlink()}
    if actual_files != set(checksums) | {'SHA256SUMS'}:
        raise ValueError('unexpected runtime files')
    reader = directory / 'libexec/llvm-readobj'
    with reader.open('rb') as stream:
        header = stream.read(20)
    if header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\xb7\x00':
        raise ValueError('reader is not ELF64 AArch64')
    if not (directory / 'bin/llvm-readelf').stat().st_mode & 0o111 or not reader.stat().st_mode & 0o111:
        raise ValueError('reader/launcher must be executable')
    return manifest


def stage(source, destination):
    source, destination = pathlib.Path(source).resolve(), pathlib.Path(destination).resolve()
    manifest = verify(source)
    if source == destination or source in destination.parents or destination == pathlib.Path('/data/app') or pathlib.Path('/data/app') in destination.parents:
        raise ValueError('destination must be separate from source and installed games')
    if destination.exists():
        if verify(destination) != manifest:
            raise ValueError('occupied runtime destination differs; choose an empty directory')
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
    verify(destination)
    return destination


def restore_appdir_payloads(source, destination):
    """linuxdeploy rewrites ELF rpaths; restore private reader bytes after it."""
    source, destination = pathlib.Path(source).resolve(), pathlib.Path(destination).resolve()
    verify(source)
    if (len(destination.parts) < 6 or destination.parts[-5:] != ('usr', 'lib', 'Creamlinux', 'compatibility', 'runtime')
            or not destination.parts[-6].endswith('.AppDir') or pathlib.Path('/data/app') in destination.parents):
        raise ValueError('payload restoration is limited to the Creamlinux AppDir resource')
    files = {p.relative_to(source) for p in source.rglob('*') if p.is_file()}
    existing = {p.relative_to(destination) for p in destination.rglob('*') if p.is_file() or p.is_symlink()}
    if files != existing or (source / 'manifest.json').read_bytes() != (destination / 'manifest.json').read_bytes():
        raise ValueError('AppDir reader inventory/identity differs; refusing restoration')
    for name in files:
        path = destination / name
        if path.is_symlink() or path.resolve() != path:
            raise ValueError('nonregular AppDir reader payload')
    for name in files:
        shutil.copy2(source / name, destination / name)
    verify(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=pathlib.Path, default=ROOT / 'tools/android-steam-proxy/build/frame-llvm-runtime-complete')
    parser.add_argument('--output', type=pathlib.Path, default=ROOT / 'src-tauri/resources/compatibility/runtime')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--restore-appdir-payloads', action='store_true',
                        help='Restore verified private resource bytes after linuxdeploy rewrites ELF rpaths')
    args = parser.parse_args()
    try:
        if args.restore_appdir_payloads:
            output = restore_appdir_payloads(args.source, args.output)
        elif args.verify_only:
            verify(args.source)
            output = args.source
        else:
            output = stage(args.source, args.output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('Frame reader resource failed: ' + str(exc), file=sys.stderr)
        return 2
    print('Verified ARM64 LLVM resource: ' + str(output))
    return 0


if __name__ == '__main__':
    sys.exit(main())
