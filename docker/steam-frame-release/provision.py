"""Provision exactly the approved apt inventory and checksum-pinned toolchains."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import urllib.request

root = Path('/opt/frame-sdk')
lock = json.loads((root/'sdk-lock.json').read_text())
packages = (root/'packages.tsv').read_bytes()
assert hashlib.sha256(packages).hexdigest() == lock['packages_sha256'], 'Package lock changed'
sources = Path('/etc/apt/sources.list.d/ubuntu.sources')
# Ubuntu's signed snapshot indexes and exact versions are both enforced.
sources.write_text('Types: deb\nURIs: https://snapshot.ubuntu.com/ubuntu/'+lock['apt_snapshot']+'\n'
    'Suites: noble noble-updates noble-security noble-backports\n'
    'Components: main universe restricted multiverse\n'
    'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\nCheck-Valid-Until: no\n')
subprocess.run(['apt-get','update'],check=True)
pins = [name+'='+version for name,version in
        (line.split('\t') for line in packages.decode().splitlines())]
subprocess.run(['apt-get','install','--yes','--no-install-recommends','--allow-downgrades',*pins],check=True)
actual = subprocess.check_output(['dpkg-query','-W','-f=${binary:Package}\t${Version}\n'])
assert actual == packages, 'SDK package inventory drift; refresh/review the lock rather than bypass it'
for name in ('node','rust'):
    pin = lock[name]
    archive = Path('/tmp/'+name+'.tar.xz')
    with urllib.request.urlopen(pin['url'],timeout=120) as source, archive.open('wb') as dest:
        while chunk := source.read(1024*1024):
            dest.write(chunk)
    assert hashlib.file_digest(archive.open('rb'),'sha256').hexdigest() == pin['sha256'], name+' checksum mismatch'
    staging = Path('/tmp/'+name+'-sdk')
    staging.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(staging,filter='data')
    directory = next(staging.iterdir())
    if name == 'node':
        directory.rename('/opt/node')
    else:
        subprocess.run(['bash',str(directory/'install.sh'),'--prefix=/opt/rust',
            '--components=rustc,cargo,rust-std-aarch64-unknown-linux-gnu','--disable-ldconfig'],check=True)
    import shutil
    shutil.rmtree(staging)
    archive.unlink()
# Node's original npm bundles vulnerable tar 6.2.1. Install the approved npm
# patch archive with Python, so bootstrap never executes that archive extractor.
# npm's package includes its third-party license notices and bundled dependencies.
pin = lock['npm']
archive = Path('/tmp/npm.tgz')
with urllib.request.urlopen(pin['url'], timeout=120) as source:
    archive.write_bytes(source.read(16*1024*1024+1))
assert hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest() == pin['sha256'], 'npm checksum mismatch'
staging = Path('/tmp/npm-sdk')
staging.mkdir()
with tarfile.open(archive) as tar:
    tar.extractall(staging, filter='data')
import shutil
shutil.rmtree('/opt/node/lib/node_modules/npm')
(staging/'package').rename('/opt/node/lib/node_modules/npm')
shutil.rmtree(staging)
archive.unlink()
assert json.loads(Path('/opt/node/lib/node_modules/npm/package.json').read_text())['version'] == pin['version']
subprocess.run(['apt-get','clean'],check=True)
