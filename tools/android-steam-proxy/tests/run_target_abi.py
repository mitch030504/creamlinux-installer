#!/usr/bin/env python3
"""Build/run the existing ABI harness against an exact target-name MOCK surface.

Android static execution uses the NDK and QEMU. Optional Linux AArch64 dynamic
execution tests the same loader/stubs with glibc; it is NOT Android validation.
No real provider is loaded, and no Steam API implementation is called.
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from generate import ROOT, emit_mock
from generate_target_proxy import build_proxy, compiler_path, public_symbols, read_elf, write_json
from verify_target_proxy import verify


def command(args):
    subprocess.run(list(map(str, args)), check=True, timeout=120)


def run(args, expected=0, pattern=None):
    env = dict(os.environ)
    env.pop('CREAMLINUX_ORIGINAL_STEAM_API', None)
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True,
                            timeout=60, env=env)
    record = dict(exit=result.returncode, expected_exit=expected,
                  stdout=result.stdout, stderr=result.stderr)
    print(result.stdout + result.stderr, end='')
    if result.returncode != expected or pattern and pattern not in result.stdout + result.stderr:
        raise ValueError('mock check failed: ' + json.dumps(record))
    return record


def build_suite(directory, cc, functions, android, sysroot=None, gcc_install_dir=None):
    mock = directory / 'mock'
    if android:
        emit_mock(mock, count=len(functions), weak_count=sum(s['binding'] == 'Weak' for s in functions),
                  target_functions=functions)
    else:
        # Reuse byte-identical generated source files for the supplemental libc.
        shutil.copytree(directory.parent / 'mock', mock)
    flags = [str(cc), '-O2', '-g', '-Wall', '-Wextra', '-Werror', '-fvisibility=hidden',
             '-fno-omit-frame-pointer', '-I' + str(ROOT / 'src'), '-I' + str(mock)]
    if sysroot:
        flags += ['--sysroot=' + str(sysroot), '-B' + str(pathlib.Path(cc).parent) + '/']
        if pathlib.Path(cc).name.startswith('clang'):
            flags += ['--target=aarch64-linux-gnu', '-fuse-ld=lld']
        if gcc_install_dir:
            flags += ['--gcc-install-dir=' + str(gcc_install_dir)]
    hardening = ['-Wl,-z,now,-z,relro,-z,noexecstack', '-Wl,-z,max-page-size=16384']
    shared = ['-shared', '-fPIC', *hardening, '-Wl,--no-undefined']
    original = mock / 'libmock_original.so'
    command(flags + shared + ['-include', mock / 'mock_rename.h', ROOT / 'src/mock.c',
            mock / 'pads.c', '-Wl,-soname,libmock_original.so',
            '-Wl,--version-script=' + str(mock / 'exports.map'), '-o', original])
    if android:
        build_proxy(mock, cc)
    else:
        command(flags + shared + [ROOT / 'src/proxy.c', mock / 'stubs.S', '-ldl',
                '-Wl,-soname,libsteam_api.so', '-Wl,--version-script=' + str(mock / 'exports.map'),
                '-o', mock / 'libsteam_api.so'])
    abi_flags = ['-DTARGET_SURFACE_TEST', '-DMOCK_PAD_COUNT=' + str(len(functions) - 17)]
    command(flags + hardening + ['-fPIE', '-pie', *abi_flags, ROOT / 'tests/abi_test.c', '-ldl',
                                '-o', directory / 'abi_test'])
    command(flags + hardening + ['-fPIE', '-pie', ROOT / 'src/load_probe.c', '-ldl',
                                '-o', directory / 'mock_load_probe'])
    if android:
        command(flags + ['-include', mock / 'rename.h', '-c', ROOT / 'src/mock.c',
                         '-o', mock / 'static_mock.o'])
        command(flags + ['-include', mock / 'rename.h', '-c', mock / 'pads.c',
                         '-o', mock / 'static_pads.o'])
        command(flags + ['-static', '-DSTATIC_ABI', '-include', mock / 'static_stub_names.h',
                         *abi_flags, ROOT / 'tests/abi_test.c',
                         mock / 'static_bind.c', mock / 'stubs.S', mock / 'static_mock.o',
                         mock / 'static_pads.o', '-o', directory / 'abi_static'])
        shutil.copyfile(ROOT / 'tests/run_android.sh', directory / 'run_android.sh')
    command(flags + shared + [ROOT / 'tests/empty.c', '-o', mock / 'libempty.so'])
    command(flags + shared + [ROOT / 'tests/empty.c', '-L' + str(mock), '-Wl,--no-as-needed',
            '-lmock_original', '-Wl,-rpath,$ORIGIN', '-o', mock / 'libdependency.so'])
    weak = next((s['name'] for s in functions if s['binding'] == 'Weak'), None)
    if weak:
        # Remove exactly one weak definition, proving weak slots also fail closed.
        source = (mock / 'pads.c').read_text()
        lines = source.splitlines(keepends=True)
        filtered = [line for line in lines if f' {weak}(uint64_t a)' not in line]
        if len(filtered) != len(lines) - 1:
            raise ValueError('weak mock removal did not remove exactly one definition')
        (mock / 'pads_missing_weak.c').write_text(''.join(filtered))
        command(flags + shared + ['-include', mock / 'mock_rename.h', ROOT / 'src/mock.c',
                mock / 'pads_missing_weak.c', '-o', mock / 'libmissing_weak.so'])
    return weak


def loader_cases(directory, prefix, weak):
    proxy = directory / 'mock/libsteam_api.so'
    probe = prefix + [directory / 'mock_load_probe', proxy]
    cases = [
        ('missing_env', [], 'absolute original path required'),
        ('relative_path', ['relative.so'], 'absolute original path required'),
        ('nonexistent', [directory / 'does-not-exist.so'], 'cannot stat original'),
        ('self_load', [proxy], 'original is proxy itself'),
        ('missing_symbols', [directory / 'mock/libempty.so'], 'missing function'),
        ('dependency_target', [directory / 'mock/libdependency.so'], 'target is not in explicit original'),
    ]
    if weak:
        cases.append(('missing_weak', [directory / 'mock/libmissing_weak.so'], 'missing function: ' + weak))
    result = {label: run(probe + arguments, 127, pattern) for label, arguments, pattern in cases}
    result['all_symbols_resolve'] = run(probe + [directory / 'mock/libmock_original.so'],
                                        pattern='zero Steam API calls')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--ndk')
    parser.add_argument('--qemu', required=True)
    parser.add_argument('--readelf', default='llvm-readelf')
    parser.add_argument('--linux-cc', help='optional supplemental Linux AArch64 compiler')
    parser.add_argument('--linux-sysroot', help='matching glibc sysroot for QEMU -L')
    parser.add_argument('--linux-gcc-install-dir', help='optional GCC runtime directory for Linux clang')
    parser.add_argument('--android-sysroot', help='optional Android runtime root for QEMU -L')
    args = parser.parse_args()
    if bool(args.linux_cc) != bool(args.linux_sysroot):
        parser.error('--linux-cc and --linux-sysroot must be supplied together')
    directory = args.output.resolve()
    if directory.exists() and any(directory.iterdir()):
        parser.error('output must be new or empty')
    directory.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text())
    functions = manifest['functions']
    report = dict(target_provider_sha256=manifest['provider_sha256'], target_functions=len(functions),
                  steam_api_calls=0, real_provider_loaded=False,
                  steam_frame_validation='unvalidated', android_dynamic='not_run')
    report['static_scope'] = ('Same NDK-built stubs with namespaced static-test labels to avoid '
                             'interposing bionic C++ runtime before main; exact public names '
                             'and bindings are checked in the Android shared mock.')
    try:
        weak = build_suite(directory, compiler_path(args.ndk), functions, True)
        parity = verify(directory / 'mock/libmock_original.so', directory / 'mock/libsteam_api.so', args.readelf)
        write_json(directory / 'mock-function-parity.json', parity)
        if not parity['passed']:
            raise ValueError('Android mock static parity failed')
        report['android_static_parity'] = 'passed'
        report['android_static_abi'] = run([args.qemu, directory / 'abi_static'], pattern='PASS')
        report['android_uninitialized'] = run([args.qemu, directory / 'abi_static', '--uninitialized'], 127)
        if args.android_sysroot:
            prefix = [args.qemu, '-L', args.android_sysroot]
            report['android_dynamic_abi'] = run(prefix + [directory / 'abi_test',
                directory / 'mock/libsteam_api.so', directory / 'mock/libmock_original.so'], pattern='PASS')
            report['android_dynamic_loader'] = loader_cases(directory, prefix, weak)
            report['android_dynamic'] = 'passed'
        else:
            report['android_dynamic_availability'] = run([args.qemu, directory / 'abi_test'], 255,
                                                         "Could not open '/system/bin/linker64'")
        if args.linux_cc:
            linux = directory / 'linux'
            linux.mkdir()
            build_suite(linux, args.linux_cc, functions, False, args.linux_sysroot, args.linux_gcc_install_dir)
            expected = {(s['name'], s['binding'], s['other']) for s in functions}
            for library in ('libsteam_api.so', 'libmock_original.so'):
                actual = public_symbols(read_elf(linux / 'mock' / library, args.readelf))
                if {(s['name'], s['binding'], s['other']) for s in actual} != expected:
                    raise ValueError('Linux mock surface mismatch: ' + library)
            prefix = [args.qemu, '-L', args.linux_sysroot]
            report['linux_supplemental_dynamic_abi'] = run(prefix + [linux / 'abi_test',
                linux / 'mock/libsteam_api.so', linux / 'mock/libmock_original.so'], pattern='PASS')
            report['linux_supplemental_loader'] = loader_cases(linux, prefix, weak)
            report['linux_scope'] = 'Same AArch64 stubs/loader with glibc; not Android/Steam Frame validation.'
        report['passed'] = True
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report['passed'] = False
        report['error'] = str(exc)
    write_json(directory / 'abi-verification.json', report)
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
