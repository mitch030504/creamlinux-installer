"""Safe, transactional NDK ZIP extraction with Unix symlink preservation."""
import hashlib
from pathlib import Path
import stat
import tempfile
import zipfile


def digest(stream):
    return hashlib.file_digest(stream,'sha256').hexdigest()


def inspect_members(archive, root_name):
    entries={}
    for member in archive.infolist():
        p=Path(member.filename)
        if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!=root_name:
            raise ValueError('Unsafe NDK member: '+member.filename)
        if p.as_posix() in entries: raise ValueError('Duplicate NDK member')
        kind=stat.S_IFMT(member.external_attr>>16)
        if kind not in (0,stat.S_IFREG,stat.S_IFDIR,stat.S_IFLNK):raise ValueError('Special NDK member')
        entries[p.as_posix()]=member
    return entries


def verify_tree(archive, entries, cache, root_name):
    root=(cache/root_name).resolve()
    for name,member in entries.items():
        p=cache/name
        if p.resolve()!=root and root not in p.resolve().parents:
            raise ValueError('NDK path/link escapes extraction root')
        if stat.S_ISLNK(member.external_attr>>16):
            target=archive.read(member).decode()
            if not p.is_symlink() or p.readlink().as_posix()!=target:raise ValueError('Cached NDK symlink mismatch; use a fresh cache')
        elif member.is_dir():
            if p.is_symlink() or not p.is_dir():raise ValueError('Cached NDK directory mismatch')
        else:
            if p.is_symlink() or not p.is_file():raise ValueError('Cached NDK file missing')
            with p.open('rb') as current,archive.open(member) as expected:
                if digest(current)!=digest(expected):raise ValueError('Cached NDK file checksum mismatch')
            if (p.stat().st_mode&0o777)!=((member.external_attr>>16)&0o777 or 0o644):raise ValueError('Cached NDK mode mismatch')
    expected={n for n in entries if n!=root_name}
    actual={p.relative_to(cache).as_posix() for p in root.rglob('*')}
    if actual!=expected:raise ValueError('Unexpected/missing NDK cache files')


def extract(archive_path, cache, root_name='android-ndk-r30'):
    cache=Path(cache).resolve();root=cache/root_name
    with zipfile.ZipFile(archive_path) as archive:
        entries=inspect_members(archive,root_name)
        if root.exists():
            verify_tree(archive,entries,cache,root_name)
            return root
        with tempfile.TemporaryDirectory(prefix='ndk-stage-',dir=cache) as temp:
            temp=Path(temp)
            links=[]
            for name,member in entries.items():
                path=temp/name
                if stat.S_ISLNK(member.external_attr>>16):
                    target=archive.read(member).decode()
                    if not target or '\0' in target or Path(target).is_absolute():raise ValueError('Unsafe NDK symlink')
                    resolved=(path.parent/target).resolve()
                    if resolved!=temp/root_name and temp/root_name not in resolved.parents:raise ValueError('NDK symlink escapes root')
                    links.append((path,target));continue
                archive.extract(member,temp)
                if not member.is_dir():path.chmod((member.external_attr>>16)&0o777 or 0o644)
            for path,target in links:
                path.parent.mkdir(parents=True,exist_ok=True);path.symlink_to(target)
            verify_tree(archive,entries,temp,root_name)
            (temp/root_name).rename(root)
    return root
