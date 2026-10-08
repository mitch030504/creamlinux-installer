"""Release validation helpers. These inspect packaging, not Android ELF ABI."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import struct
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FAMILIES = ('libwayland-client', 'libwayland-cursor', 'libwayland-egl',
    'libwayland-server', 'libxkbcommon', 'libxcb-randr', 'libxcb-render', 'libxcb-shm',
    'libXau', 'libXdmcp')
KNOWN_PROVIDERS = {'f424277c8a431542b93bf71215615fa6730edb7968a03f5230d484437f0d4aa4',
    '345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700',
    'de0ffad291557797b30e1abd153481cca46225720410f8c8f8709811f9029bb1',
    'ee573a79ad0bf0fa4e6530fa35a4e2911e9f473141a7580b83a3d79fd1679646'}
spec = importlib.util.spec_from_file_location('frame_resources', ROOT/'scripts/prepare-steam-frame-runtime.py')
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def artifact_name(version, override=None):
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?', version):
        raise ValueError('Release version must be a safe semantic version')
    name = override or f'Creamlinux_{version}_steam-frame-inspector_aarch64.AppImage'
    if not re.fullmatch(r'[A-Za-z0-9_.+-]+_aarch64\.AppImage', name):
        raise ValueError('Artifact name must be a basename ending _aarch64.AppImage')
    return name


def require_elf(path, machine=183):
    with Path(path).open('rb') as stream:
        header = stream.read(20)
    if len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != machine:
        raise ValueError(f'Expected ELF64 machine {machine}: {path}')


def source_identity(repo):
    repo = Path(repo)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args])
    paths = set(git('ls-files', '-z').decode().split('\0')) | set(
        git('ls-files', '--others', '--exclude-standard', '-z').decode().split('\0'))
    entries = {}
    for name in sorted(paths - {''}):
        path = repo / name
        # Tracked historical cores are not source inputs and are never staged.
        if path.suffix == '.core':
            continue
        if path.is_symlink():
            entries[name] = {'symlink': os.readlink(path)}
        elif path.is_file():
            entries[name] = {'sha256': sha256(path), 'mode': path.stat().st_mode & 0o777}
    status = git('status', '--porcelain=v1', '--untracked-files=all').decode()
    return {'branch': git('branch', '--show-current').decode().strip(),
        'head': git('rev-parse', 'HEAD').decode().strip(), 'dirty': bool(status),
        'worktree_status': status.splitlines(),
        'snapshot_sha256': hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest(),
        'files': entries}


def tool_pins():
    return json.loads((ROOT/'scripts/release/tools.json').read_text())


def prepare_tools(cache, download=False):
    cache = Path(cache)
    pins = tool_pins()
    for name, record in pins['tools'].items():
        path = cache/name
        if not path.exists() and download:
            cache.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(record['url'], timeout=60) as stream:
                raw = stream.read(40*1024*1024+1)
            if len(raw) > 40*1024*1024 or hashlib.sha256(raw).hexdigest() != record['sha256']:
                raise ValueError('Pinned download checksum mismatch: ' + name)
            path.write_bytes(raw)
            path.chmod(0o755)
        if not path.is_file() or path.is_symlink() or sha256(path) != record['sha256']:
            raise ValueError(f'Missing/corrupt pinned tool {path}; use --prepare-tools or restore exact pinned bytes')
        if not os.access(path, os.X_OK):
            raise ValueError('Tool is not executable: ' + str(path))
    return pins


def inventory(root):
    root = Path(root).resolve()
    entries = {}
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            if path.resolve() != root and root not in path.resolve().parents:
                raise ValueError('AppDir symlink escapes package: ' + name)
            entries[name] = {'symlink': os.readlink(path)}
        elif path.is_file():
            entries[name] = {'sha256': sha256(path), 'size': path.stat().st_size,
                'mode': path.stat().st_mode & 0o777}
    return entries


def normalize(root, epoch):
    root = Path(root)
    if epoch < 0:
        raise ValueError('SOURCE_DATE_EPOCH must be nonnegative')
    for path in sorted(root.rglob('*'), reverse=True) + [root]:
        os.utime(path, (epoch, epoch), follow_symlinks=False)


def validate_appdir(root):
    root = Path(root).resolve()
    for relative in ['AppRun', 'AppRun.plugins', 'AppRun.wrapped', 'usr/bin/creamlinux',
                     'apprun-hooks/linuxdeploy-plugin-gtk.sh', 'apprun-hooks/linuxdeploy-plugin-gstreamer.sh',
                     'usr/share/applications/Creamlinux.desktop',
                     *['usr/lib/aarch64-linux-gnu/webkit2gtk-4.1/'+n for n in WEBKIT_HELPERS],
                     'usr/share/icons/hicolor/128x128/apps/creamlinux.png',
                     'usr/lib/Creamlinux/compatibility/release-capabilities.json']:
        if not (root/relative).is_file():
            raise ValueError('Required release payload absent: ' + relative)
    for relative in ['AppRun', 'AppRun.plugins', 'AppRun.wrapped', 'usr/bin/creamlinux',
                     *['usr/lib/aarch64-linux-gnu/webkit2gtk-4.1/'+n for n in WEBKIT_HELPERS[:2]]]:
        if not os.access(root/relative, os.X_OK):
            raise ValueError('Release executable is not executable: ' + relative)
    if 'WEBKIT_DISABLE_DMABUF_RENDERER' not in (root/'AppRun').read_text():
        raise ValueError('Frame launch environment absent from AppRun')
    capabilities = json.loads((root/'usr/lib/Creamlinux/compatibility/release-capabilities.json').read_text())
    if 'core:window:allow-close' not in capabilities.get('permissions', []):
        raise ValueError('Inspector close permission missing from packaged provenance')
    entries = inventory(root)
    elfs = 0
    for name, record in entries.items():
        path = root/name
        if any(path.name.startswith(family+'.so') for family in FORBIDDEN_FAMILIES):
            raise ValueError('Forbidden bundled display library: ' + name)
        parts = set(Path(name).parts)
        if path.suffix in {'.apk', '.apks', '.core', '.pem', '.p12', '.pfx', '.key'} or path.name in {'.env', 'id_rsa', 'id_ed25519', 'original-provider.so', 'libsteam_api.so'}:
            raise ValueError('Forbidden game capture/credential/debug payload: ' + name)
        if parts & {'.git', '.ssh', 'node_modules', 'target', 'apks', 'unpacked'}:
            raise ValueError('Development directory in package: ' + name)
        if 'sha256' not in record:
            continue
        if record['sha256'] in KNOWN_PROVIDERS:
            raise ValueError('Real game provider in release: ' + name)
        if record['size'] > 180*1024*1024 or sum(x.get('size',0) for x in entries.values()) > 1024*1024*1024:
            raise ValueError('Unexpected huge release payload')
        with path.open('rb') as stream:
            if stream.read(4) == b'\x7fELF':
                require_elf(path)
                elfs += 1
    require_elf(root/'usr/bin/creamlinux')
    llvm = resources.verify(root/'usr/lib/Creamlinux/compatibility/runtime')
    return {'status': 'passed', 'aarch64_elf_files': elfs, 'excluded_conflict_families': list(FORBIDDEN_FAMILIES),
        'forbidden_conflict_files': [], 'capture_credential_debug_guard': 'passed',
        'llvm': llvm, 'inventory': entries}


def require_release_info(info, version):
    if (not info.get('release_permissions_valid') or info.get('version') != version
            or info.get('architecture') != 'aarch64' or not info.get('production_assets_embedded')
            or info.get('inspector_distribution_only') is not True
            or info.get('default_startup_is_legacy') is not False
            or info.get('updater_check_allowed') is not False
            or info.get('content_security_policy_enabled') is not True):
        raise ValueError('Exact packaged binary production assets/resolved ACL/version/architecture/read-only/CSP check failed')


def appimage_offset(path):
    """Locate the type-2 SquashFS boundary, without executing its ARM runtime.

    This handles the ordinary ELF64 section table in pinned AppImage runtimes;
    it is not an Android ABI/relocation parser. Reject unsupported layouts.
    """
    path=Path(path)
    require_elf(path)
    with path.open('rb') as stream:
        header=stream.read(64)
        if len(header)!=64 or header[8:11]!=b'AI\x02':
            raise ValueError('Expected type-2 AppImage header')
        table=struct.unpack_from('<Q',header,40)[0]
        entry_size,entries=struct.unpack_from('<HH',header,58)
        offset=table+entry_size*entries
        if table<64 or entry_size!=64 or not entries or offset+96>path.stat().st_size:
            raise ValueError('Unsupported/truncated AppImage ELF section table')
        stream.seek(offset)
        block=stream.read(96)
        if block[:4]!=b'hsqs' or struct.unpack_from('<HH',block,28)!=(4,0):
            raise ValueError('Expected SquashFS 4 boundary after AppImage ELF')
        used=struct.unpack_from('<Q',block,40)[0]
        if used<96 or offset+used>path.stat().st_size:
            raise ValueError('Truncated AppImage SquashFS payload')
    return offset


WEBKIT_HELPERS=('WebKitNetworkProcess','WebKitWebProcess',
                'injected-bundle/libwebkit2gtkinjectedbundle.so')


def stage_webkit(source, appdir):
    source=Path(source)
    for name in WEBKIT_HELPERS:
        if not (source/name).is_file():
            raise ValueError('Missing WebKit helper '+str(source/name)+'; provision matching ARM64 libwebkit2gtk-4.1 before building')
        require_elf(source/name)
    destination=Path(appdir)/'usr/lib/aarch64-linux-gnu/webkit2gtk-4.1'
    for name in WEBKIT_HELPERS:
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/name,path)


def write_launch_wrapper(appdir):
    path=Path(appdir)/'AppRun'
    path.write_text('#!/usr/bin/env bash\nset -euo pipefail\n'
        'export WEBKIT_DISABLE_DMABUF_RENDERER="${WEBKIT_DISABLE_DMABUF_RENDERER:-1}"\n'
        'case "${1:-}" in --lepton-inspector|--lepton-compatibility|--lepton-release-info) ;;\n'
        '  *) echo "Steam Frame read-only inspector: use --lepton-inspector APPID or --lepton-compatibility APPID" >&2; exit 2 ;; esac\n'
        'release_dir="$(cd "$(dirname "$0")" && pwd -P)"\n'
        'exec "$release_dir/AppRun.plugins" "$@"\n')
    path.chmod(0o755)
