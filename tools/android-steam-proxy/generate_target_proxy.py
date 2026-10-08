#!/usr/bin/env python3
"""Build a provider-driven, function-only Android proxy. Never load the provider."""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys

from generate import NAME, ROOT, emit_surface

SCHEMA = 1
VERSION = '1.1'
# These collide with the shared loader's code/data or would recursively route
# its own dependencies through unresolved slots. No aliases are invented.
RESERVED = {'proxy_targets', 'proxy_names', 'proxy_unready', 'initialize', 'fail',
            'same_file', 'original_handle', 'dlopen', 'dlsym', 'dladdr', 'dlerror',
            'getenv', 'stat', 'write', 'fprintf', '_exit', 'stderr',
            '__cxa_finalize', '__cxa_atexit', '_init', '_fini', '__dso_handle'}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def read_elf(path, reader):
    result = subprocess.run([str(reader), '--elf-output-style=JSON', '--file-header',
                             '--sections', '--program-headers', '--dyn-syms', '--symbols',
                             '--dynamic-table', '--relocations', '--expand-relocs',
                             '--notes', str(path)], capture_output=True, text=True,
                            timeout=60, env={**os.environ, 'LC_ALL': 'C'})
    if result.returncode or result.stderr.strip():
        raise ValueError('ELF inspection failed: ' + (result.stderr.strip() or 'readelf error'))
    try:
        records = json.loads(result.stdout)
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError('expected one ELF JSON record')
        return records[0]
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError('malformed readelf JSON') from exc


def android_note(elf):
    for section in elf.get('NoteSections', []):
        for note in section['NoteSection']['Notes']:
            if note['Owner'] == 'Android' and note['Type'] == 'NT_ANDROID_TYPE_IDENT':
                raw = bytes(note['Description data']['Bytes'])
                if len(raw) < 4:
                    raise ValueError('malformed Android ABI note')
                return dict(api=int.from_bytes(raw[:4], 'little'),
                            ndk=raw[4:68].split(b'\0', 1)[0].decode('ascii') or None)
    return dict(api=None, ndk=None)


def public_symbols(elf):
    """Validate raw dynsym metadata before selecting public definitions."""
    symbols = []
    bindings = {'Local': 0, 'Global': 1, 'Weak': 2, 'GNUUnique': 10}
    types = {'None': 0, 'Object': 1, 'Function': 2, 'Section': 3, 'File': 4,
             'Common': 5, 'TLS': 6, 'GNU_IFunc': 10}
    for entry in elf['DynamicSymbols']:
        s = entry['Symbol']
        name, binding, kind = s['Name']['Name'], s['Binding']['Name'], s['Type']['Name']
        other, section = s['Other']['Value'], s['Section']['Value']
        if (not isinstance(name, str) or binding not in bindings or kind not in types or
                type(s['Binding']['Value']) is not int or type(s['Type']['Value']) is not int or
                s['Binding']['Value'] != bindings[binding] or s['Type']['Value'] != types[kind] or
                any(type(n) is not int or n < 0 for n in (other, section, s['Value'], s['Size'])) or
                other > 255 or section > 65535):
            raise ValueError('malformed symbol metadata: ' + repr(name))
        if section == 0 or binding == 'Local' or other & 3 not in (0, 3):
            continue
        if not name or '\0' in name:
            raise ValueError('malformed public symbol name')
        symbols.append(dict(name=name, type=kind, binding=binding, other=other,
                            visibility='Protected' if other & 3 == 3 else 'Default',
                            value=s['Value'], size=s['Size']))
    names = [s['name'] for s in symbols]
    if len(names) != len(set(names)):
        raise ValueError('duplicate public symbol names')
    return sorted(symbols, key=lambda s: s['name'])


def inspect_provider(provider, reader):
    provider = pathlib.Path(provider).resolve(strict=True)
    if not provider.is_file():
        raise ValueError('provider must be a regular file')
    raw = provider.read_bytes()
    if not raw.startswith(b'\x7fELF'):
        raise ValueError('provider is not ELF')
    elf = read_elf(provider, reader)
    try:
        header = elf['ElfHeader']
        if (header['Machine']['Value'] != 183 or header['Ident']['Class']['Value'] != 2 or
                header['Ident']['DataEncoding']['Value'] != 1 or
                not header['Type'].startswith('SharedObject') or header['Flags']['Value'] != 0):
            raise ValueError('requires ordinary ELF64 little-endian AArch64 shared object')
        if not any(s['Section']['Type']['Value'] == 11 for s in elf['Sections']):
            raise ValueError('missing inspectable dynamic symbol table')
        exports = public_symbols(elf)
        # IFUNC resolvers cannot be represented as ordinary pre-resolved FUNCs.
        functions = [s for s in exports if s['type'] == 'Function']
        if any(s['type'] == 'GNU_IFunc' for s in exports):
            raise ValueError('IFUNC exports are unsupported')
        if not functions:
            raise ValueError('provider has no public FUNCTION exports')
        sections = {s['Section']['Index']: s['Section'] for s in elf['Sections']}
        dynsyms = {e['Symbol']['Name']['Name']: e['Symbol'] for e in elf['DynamicSymbols']
                   if e['Symbol']['Section']['Value'] != 0}
        for s in functions:
            if (s['binding'] not in ('Global', 'Weak') or s['other'] not in (0, 3) or
                    not NAME.fullmatch(s['name']) or s['name'] in RESERVED):
                raise ValueError('unsupported function metadata/name: ' + s['name'])
            section = sections.get(dynsyms[s['name']]['Section']['Value'])
            if (not section or section['Flags']['Value'] & 6 != 6 or s['value'] % 4 or
                    not section['Address'] <= s['value'] < section['Address'] + section['Size']):
                raise ValueError('function is not aligned mapped executable code: ' + s['name'])
        note = android_note(elf)
    except (KeyError, TypeError, IndexError, UnicodeError) as exc:
        raise ValueError('malformed ELF/symbol metadata') from exc
    if provider.read_bytes() != raw:
        raise ValueError('provider changed during inspection')
    omitted = [s for s in exports if s['type'] != 'Function']
    manifest = dict(schema_version=SCHEMA, generator_version=VERSION,
                    provider_sha256=hashlib.sha256(raw).hexdigest(),
                    architecture='aarch64', abi='arm64-v8a', android_api=note['api'],
                    provider_ndk=note['ndk'], total_public_exports=len(exports),
                    function_export_count=len(functions),
                    global_function_count=sum(s['binding'] == 'Global' for s in functions),
                    weak_function_count=sum(s['binding'] == 'Weak' for s in functions),
                    generated_function_count=len(functions), non_function_count=len(omitted),
                    functions=functions, omitted_non_function_exports=omitted,
                    warning='FUNCTION exports only; non-function exports are omitted. '
                            'This proxy is not a complete ABI clone.',
                    original_provider_loading='Explicit absolute CREAMLINUX_ORIGINAL_STEAM_API; '
                                              'all targets required, including weak functions.',
                    validation_status=dict(static='not_run', runtime='unvalidated/limited',
                                           steam_frame='unvalidated', complete_abi_clone=False))
    return manifest


def compiler_path(ndk):
    ndk = ndk or os.environ.get('ANDROID_NDK_HOME') or os.environ.get('ANDROID_NDK_ROOT')
    if not ndk:
        raise ValueError('provide --ndk or ANDROID_NDK_HOME for an Android build')
    cc = pathlib.Path(ndk) / 'toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android21-clang'
    if not cc.is_file():
        raise ValueError('Android API 21 AArch64 compiler not found: ' + str(cc))
    return cc


def build_proxy(directory, cc):
    directory = pathlib.Path(directory).resolve()
    subprocess.run([str(cc), '-std=c11', '-O2', '-g', '-Wall', '-Wextra', '-Werror',
                    '-ffile-prefix-map=' + str(ROOT) + '=/proxy-source',
                    '-ffile-prefix-map=' + str(directory) + '=/proxy-target',
                    '-fdebug-compilation-dir=/proxy-build',
                    '-fvisibility=hidden', '-fno-omit-frame-pointer', '-shared', '-fPIC',
                    '-I' + str(directory), str(ROOT / 'src/proxy.c'), str(directory / 'stubs.S'),
                    '-ldl', '-Wl,-z,now,-z,relro,-z,noexecstack', '-Wl,--no-undefined',
                    '-Wl,-z,max-page-size=16384', '-Wl,--hash-style=both',
                    '-Wl,-soname,libsteam_api.so',
                    '-Wl,--version-script=' + str(directory / 'exports.map'),
                    '-o', str(directory / 'libsteam_api.so')], check=True, timeout=120)


def generate(provider, output, reader, ndk=None, sources_only=False):
    manifest = inspect_provider(provider, reader)
    output = pathlib.Path(output).resolve()
    provider = pathlib.Path(provider).resolve()
    # Build-only POC: refuse the provider directory and an occupied destination.
    if output == provider.parent or provider.parent in output.parents:
        raise ValueError('output must be outside the provider directory')
    if output == pathlib.Path('/data/app') or pathlib.Path('/data/app') in output.parents:
        raise ValueError('output must not be in /data/app')
    cc = None if sources_only else compiler_path(ndk)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('output directory must be empty (prevents stale build reports)')
    emit_surface(output, manifest['functions'])
    write_json(output / 'manifest.json', manifest)
    if not sources_only:
        build_proxy(output, cc)
        # Re-inspect the provider for parity, rather than trusting generated names.
        from verify_target_proxy import verify
        report = verify(provider, output / 'libsteam_api.so', reader)
        if report['provider_sha256'] != manifest['provider_sha256']:
            report['passed'] = False
            report['provider_changed_during_build'] = True
        write_json(output / 'function-parity.json', report)
        compiler = subprocess.run([str(cc), '--version'], check=True, capture_output=True,
                                  text=True, timeout=30).stdout.splitlines()[0]
        manifest['build_identity'] = dict(toolchain=compiler, android_api=21,
            proxy_sha256=report['proxy_sha256'], reproducible_paths=True)
        inputs = ['generate.py', 'generate_target_proxy.py', 'verify_target_proxy.py', 'src/proxy.c']
        fingerprint = hashlib.sha256()
        for name in inputs:
            fingerprint.update(name.encode() + b'\0' + (ROOT / name).read_bytes() + b'\0')
        identity = dict(provider_sha256=manifest['provider_sha256'], generator_version=VERSION,
                        generator_inputs_sha256=fingerprint.hexdigest(), toolchain=compiler, android_api=21)
        manifest['build_identity'].update(identity)
        manifest['build_identity']['cache_key'] = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        manifest['validation_status']['static'] = 'passed' if report['passed'] else 'failed'
        write_json(output / 'manifest.json', manifest)
        if not report['passed']:
            raise ValueError('static parity verification failed; see function-parity.json')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True,
                        help='new or empty build directory outside the provider directory')
    parser.add_argument('--readelf', default='llvm-readelf')
    parser.add_argument('--ndk', help='Android NDK root (defaults to ANDROID_NDK_HOME/ROOT)')
    parser.add_argument('--sources-only', action='store_true', help='emit sources without compiling')
    args = parser.parse_args(argv)
    try:
        manifest = generate(args.provider, args.output, args.readelf, args.ndk, args.sources_only)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('target proxy generation failed: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps({k: manifest[k] for k in ('provider_sha256', 'total_public_exports',
          'generated_function_count', 'global_function_count', 'weak_function_count',
          'non_function_count', 'warning', 'validation_status')}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
