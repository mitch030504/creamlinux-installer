#!/usr/bin/env python3
"""Fetch/verify the test NDK; preserve symlinks and never provision binfmt."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
from ndk_archive import extract


def main():
    cache=Path(sys.argv[1]);cache.mkdir(parents=True,exist_ok=True)
    pin=json.loads(Path(__file__).with_name('controller.json').read_text())['ndk']
    archive=cache/'android-ndk-r30-linux.zip'
    if not archive.exists():
        with urllib.request.urlopen(pin['url'],timeout=120) as src,archive.open('xb') as dst:
            remaining=pin['size_bytes']
            while chunk:=src.read(min(1024*1024,remaining+1)):
                remaining-=len(chunk)
                if remaining<0:raise ValueError('NDK download exceeds pinned size')
                dst.write(chunk)
    with archive.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
    if archive.stat().st_size!=pin['size_bytes'] or checksum!=pin['sha256']:
        raise ValueError('NDK checksum/size mismatch; restore the exact pinned input')
    root=extract(archive,cache)
    print(root.resolve())

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,IndexError) as e:
        print('Controller preparation failed: '+str(e),file=sys.stderr);sys.exit(2)
