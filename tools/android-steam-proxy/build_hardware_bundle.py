#!/usr/bin/env python3
"""Package standalone Job Simulator Android validation. Never deploy/load a provider."""
import argparse
import gzip
import hashlib
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

from generate import ROOT, emit_mock
from generate_target_proxy import compiler_path, inspect_provider, write_json
from verify_target_proxy import verify

PROVIDER_SHA256 = '345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700'
HARDWARE = ROOT / 'hardware'
DEFAULT_TARGET = ROOT / 'build/jobsimulator-target'
DEFAULT_OUTPUT = ROOT / 'build/jobsimulator-hardware-validation.tar.gz'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args):
    subprocess.run(list(map(str, args)), check=True, timeout=120, capture_output=True)


def emit_weak_fixtures(directory, functions):
    """All weak names have controlled uint64_t mock signatures, never real ABI use."""
    weak = [s for s in functions if s['binding'] == 'Weak']
    representatives = [s['name'] for s in functions if s['binding'] == 'Global'][:17]
    pads = {s['name']: i for i, s in enumerate(s for s in functions if s['name'] not in representatives)}
    directory.mkdir()
    (directory / 'weak_cases.h').write_text(
        '#include <stdint.h>\n#define HARDWARE_WEAK_COUNT ' + str(len(weak)) + 'u\n'
        'static const struct { const char *name; unsigned pad; } weak_cases[] = {\n' +
        ''.join(f'{{"{s["name"]}", {pads[s["name"]]}u}},\n' for s in weak) + '};\n')
    (directory / 'strong.c').write_text('#include <stdint.h>\n' + ''.join(
        f'__attribute__((visibility("default"))) uint64_t {s["name"]}(uint64_t a) '
        f'{{ return a + UINT64_C(0x100000) + {i}u; }}\n' for i, s in enumerate(weak)))
    (directory / 'consumer.c').write_text('#include <stdint.h>\n' + ''.join(
        f'extern uint64_t {s["name"]}(uint64_t);\n' for s in weak) +
        '__attribute__((visibility("default"))) uint64_t hardware_weak_call(unsigned i, uint64_t a) {\n'
        'switch (i) {\n' + ''.join(f'case {i}: return {s["name"]}(a);\n' for i, s in enumerate(weak)) +
        'default: return 0; } }\n'
        '__attribute__((visibility("default"))) void *hardware_weak_address(unsigned i) {\n'
        'switch (i) {\n' + ''.join(f'case {i}: return (void *)&{s["name"]};\n' for i, s in enumerate(weak)) +
        'default: return 0; } }\n')
    return weak


def checksum_manifest(directory):
    files = sorted(p for p in directory.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
    (directory / 'SHA256SUMS').write_text(''.join(
        f'{sha256(p)}  {p.relative_to(directory).as_posix()}\n' for p in files))


def deterministic_archive(directory, output):
    """No timestamps, uid/gid, local paths or gzip filename in the archive."""
    with output.open('wb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for path in sorted(p for p in directory.rglob('*') if p.is_file()):
                raw = path.read_bytes()
                info = tarfile.TarInfo(path.relative_to(directory).as_posix())
                info.size = len(raw)
                info.mode = 0o755 if path.suffix == '.so' or path.name in (
                    'abi_test', 'mock_load_probe', 'weak_probe', 'binding_probe', 'resolve_probe',
                    'run_hardware_validation.sh') else 0o644
                archive.addfile(info, io.BytesIO(raw))


def build_bundle(target, output, ndk=None, reader='llvm-readelf'):
    target, output = pathlib.Path(target).resolve(), pathlib.Path(output).resolve()
    if output == target or target in output.parents or output.suffixes[-2:] != ['.tar', '.gz']:
        raise ValueError('output must be .tar.gz outside the target directory')
    if pathlib.Path('/data/app') in output.parents:
        raise ValueError('output must not be under /data/app')
    cc = compiler_path(ndk)
    manifest = json.loads((target / 'manifest.json').read_text())
    if manifest['provider_sha256'] != PROVIDER_SHA256:
        raise ValueError('not the expected Job Simulator manifest checksum')
    functions = manifest['functions']
    if (len(functions), sum(s['binding'] == 'Global' for s in functions),
            sum(s['binding'] == 'Weak' for s in functions)) != (1156, 1135, 21):
        raise ValueError('expected 1156 functions, 1135 GLOBAL and 21 WEAK')
    if functions != sorted(functions, key=lambda s: s['name']) or any(
            not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', s['name']) or s['other'] != 0 for s in functions):
        raise ValueError('expected sorted default-visible Job Simulator names')
    # Static inspection only. The real provider is neither needed nor copied.
    proxy_manifest = inspect_provider(target / 'libsteam_api.so', reader)
    expected = [(s['name'], s['binding'], s['other']) for s in functions]
    if [(s['name'], s['binding'], s['other']) for s in proxy_manifest['functions']] != expected:
        raise ValueError('generated proxy surface differs from manifest')
    if proxy_manifest['non_function_count'] or proxy_manifest['android_api'] != 21:
        raise ValueError('expected Android function-only proxy')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='hardware-bundle-', dir=output.parent) as temporary:
        work = pathlib.Path(temporary)
        sources, bundle = work / 'sources', work / 'bundle'
        sources.mkdir()
        bundle.mkdir()
        mock, weak_dir = sources / 'mock', sources / 'weak'
        emit_mock(mock, 1156, 21, functions)
        weak = emit_weak_fixtures(weak_dir, functions)
        (sources / 'hardware_symbols.h').write_text(
            '#define HARDWARE_FUNCTION_COUNT 1156u\n#define HARDWARE_GLOBAL_COUNT 1135u\n#define HARDWARE_WEAK_COUNT 21u\n'
            'static const struct { const char *name; unsigned binding, other; } hardware_symbols[] = {\n' +
            ''.join(f'{{"{s["name"]}", {2 if s["binding"] == "Weak" else 1}u, {s["other"]}u}},\n'
                    for s in functions) + '};\n')
        flags = [cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-fvisibility=hidden',
                 '-fno-omit-frame-pointer', '-ffile-prefix-map=' + str(work) + '=/hardware-build',
                 '-ffile-prefix-map=' + str(ROOT) + '=/proxy-source',
                 '-I' + str(ROOT / 'src'), '-I' + str(mock), '-I' + str(sources), '-I' + str(weak_dir)]
        hardening = ['-Wl,-z,now,-z,relro,-z,noexecstack', '-Wl,-z,max-page-size=16384', '-Wl,--hash-style=both']
        shared = ['-shared', '-fPIC', *hardening, '-Wl,--no-undefined']
        (bundle / 'mock').mkdir()
        (bundle / 'weak').mkdir()
        shutil.copyfile(target / 'libsteam_api.so', bundle / 'libsteam_api.so')
        original = bundle / 'mock/libmock_original.so'
        command(flags + shared + ['-include', mock / 'mock_rename.h', ROOT / 'src/mock.c', mock / 'pads.c',
                '-Wl,-soname,libmock_original.so', '-Wl,--version-script=' + str(mock / 'exports.map'), '-o', original])
        parity = verify(original, bundle / 'libsteam_api.so', reader)
        if not parity['passed']:
            raise ValueError('mock/generated proxy static parity failed')
        write_json(bundle / 'mock-parity.json', parity)
        (mock / 'pads_missing_weak.c').write_text(''.join(line for line in (mock / 'pads.c').read_text().splitlines(True)
            if f' {weak[0]["name"]}(uint64_t a)' not in line))
        command(flags + shared + ['-include', mock / 'mock_rename.h', ROOT / 'src/mock.c', mock / 'pads_missing_weak.c',
                '-Wl,-soname,libmissing_weak.so', '-o', bundle / 'mock/libmissing_weak.so'])
        command(flags + shared + [ROOT / 'tests/empty.c', '-Wl,-soname,libempty.so', '-o', bundle / 'mock/libempty.so'])
        command(flags + shared + [ROOT / 'tests/empty.c', '-L' + str(bundle / 'mock'), '-Wl,--no-as-needed',
                '-lmock_original', '-Wl,-soname,libdependency.so', '-o', bundle / 'mock/libdependency.so'])
        command(flags + shared + [ROOT / 'tests/empty.c', '-Wl,-soname,libhardware_absent.so', '-o', sources / 'libhardware_absent.so'])
        command(flags + shared + [ROOT / 'tests/empty.c', '-L' + str(sources), '-Wl,--no-as-needed',
                '-lhardware_absent', '-Wl,-soname,libbroken_dependency.so', '-o', bundle / 'mock/libbroken_dependency.so'])
        pie = flags + hardening + ['-fPIE', '-pie']
        command(pie + ['-DTARGET_SURFACE_TEST', '-DMOCK_PAD_COUNT=1139', ROOT / 'tests/abi_test.c', '-ldl', '-o', bundle / 'abi_test'])
        command(pie + [ROOT / 'src/load_probe.c', '-ldl', '-o', bundle / 'mock_load_probe'])
        for name in ('resolve_probe', 'binding_probe', 'weak_probe'):
            command(pie + [HARDWARE / (name + '.c'), '-ldl', '-o', bundle / name])
        command(flags + shared + [weak_dir / 'strong.c', '-Wl,-z,global', '-Wl,-soname,libstrong.so', '-o', bundle / 'weak/libstrong.so'])
        command(flags + shared + [weak_dir / 'consumer.c', '-L' + str(bundle), '-lsteam_api',
                '-Wl,-soname,libconsumer.so', '-o', bundle / 'weak/libconsumer.so'])
        (bundle / 'run_hardware_validation.sh').write_text((HARDWARE / 'run_hardware_validation.sh').read_text().replace('@MISSING_WEAK@', weak[0]['name']))
        (bundle / 'target-functions.tsv').write_text(''.join(f'{s["binding"]}\t{s["name"]}\n' for s in functions))
        compiler = subprocess.run([str(cc), '--version'], check=True, capture_output=True, text=True).stdout.splitlines()[0]
        write_json(bundle / 'manifest.json', dict(
            schema_version=1, target='Job Simulator', architecture='aarch64', runtime='Android/Bionic',
            android_api=21, minimum_weak_scope_runtime_api=23, toolchain=compiler,
            provider_sha256=PROVIDER_SHA256, proxy_sha256=sha256(bundle / 'libsteam_api.so'),
            function_count=1156, global_function_count=1135, weak_function_count=21, omitted_non_function_count=209,
            abi_checks=11156, signature_cases=17, slot_probes=1139, repeated_calls=10000,
            loader_rejection_cases=8, weak_load_scope_cases=4, weak_checks=420,
            stages=['mock', 'weak', 'resolve'], real_provider_included=False,
            weak_policy='All 21 WEAK targets required in explicit original. Consumer relocations use Bionic scope order; explicit handles remain scoped. Late global load does not rebind existing NOW relocations.',
            resolution_policy='dlsym explicit real-provider handle, non-null and same-file owner; no target calls; dlopen runs constructors.',
            safety_root='/data/local/tmp/creamlinux-target-proxy', hardware_validation='not_run'))
        checksum_manifest(bundle)
        deterministic_archive(bundle, output)
    digest = sha256(output)
    output.with_name(output.name + '.sha256').write_text(f'{digest}  {output.name}\n')
    return dict(archive=str(output), archive_sha256=digest, proxy_sha256=proxy_manifest['provider_sha256'],
                functions=1156, weak=21, hardware_validation='not_run')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-dir', type=pathlib.Path, default=DEFAULT_TARGET)
    parser.add_argument('--output', type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--ndk')
    parser.add_argument('--readelf', default='llvm-readelf')
    args = parser.parse_args()
    try:
        result = build_bundle(args.target_dir, args.output, args.ndk, args.readelf)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        detail = exc.stderr.decode(errors='replace') if isinstance(exc, subprocess.CalledProcessError) and isinstance(exc.stderr, bytes) else str(exc)
        print('hardware bundle failed: ' + detail, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
