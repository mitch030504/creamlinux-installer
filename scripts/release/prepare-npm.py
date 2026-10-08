#!/usr/bin/env python3
"""Prepare checksum-pinned npm without invoking Node's vulnerable bootstrap tar.

Print only the new bin directory for GITHUB_PATH. Never installs globally.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def prepare(destination, pin, archive=None):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('npm output already exists; choose a fresh private directory')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='npm-preparation-', dir=destination.parent) as directory:
        staging = Path(directory)
        payload = staging/'npm.tgz'
        if archive is None:
            if not pin['url'].startswith('https://registry.npmjs.org/npm/-/npm-'):
                raise ValueError('Unexpected npm source URL')
            with urllib.request.urlopen(pin['url'], timeout=60) as stream:
                raw = stream.read(16*1024*1024+1)
        else:
            raw = Path(archive).read_bytes()
        if len(raw) > 16*1024*1024 or hashlib.sha256(raw).hexdigest() != pin['sha256']:
            raise ValueError('Pinned npm checksum/size mismatch')
        payload.write_bytes(raw)
        unpacked = staging/'unpacked'
        unpacked.mkdir()
        with tarfile.open(payload) as tar:
            tar.extractall(unpacked, filter='data')
        package = unpacked/'package'
        if json.loads((package/'package.json').read_text())['version'] != pin['version']:
            raise ValueError('Pinned npm package version mismatch')
        result = staging/'result'
        library = result/'lib/node_modules'
        library.mkdir(parents=True)
        shutil.move(package, library/'npm')
        binaries = result/'bin'
        binaries.mkdir()
        for name in ['npm', 'npx']:
            (binaries/name).symlink_to('../lib/node_modules/npm/bin/'+name+'-cli.js')
        result.rename(destination)
    return destination/'bin'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    pin = json.loads((ROOT/'docker/steam-frame-release/sdk-lock.json').read_text())['npm']
    print(prepare(args.destination, pin))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        print('Pinned npm preparation failed: '+str(error), file=sys.stderr)
        sys.exit(2)
