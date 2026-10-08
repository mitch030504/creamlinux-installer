"""Host build/packaging/runner checks. No Android or Steam function execution."""
import hashlib
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import build_hardware_bundle as hardware
from generate import emit_surface
from generate_target_proxy import build_proxy, compiler_path, public_symbols, read_elf

NDK = os.environ.get('ANDROID_NDK_HOME') or os.environ.get('ANDROID_NDK_ROOT')
READER = shutil.which('llvm-readelf')
HAS_NDK = bool(NDK and (pathlib.Path(NDK) / 'toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android21-clang').is_file())
MEMBERS = {
    'SHA256SUMS', 'abi_test', 'binding_probe', 'libsteam_api.so', 'manifest.json',
    'mock/libbroken_dependency.so', 'mock/libdependency.so', 'mock/libempty.so',
    'mock/libmissing_weak.so', 'mock/libmock_original.so', 'mock-parity.json',
    'mock_load_probe', 'resolve_probe', 'run_hardware_validation.sh',
    'target-functions.tsv', 'weak/libconsumer.so', 'weak/libstrong.so', 'weak_probe',
}


class HardwareSourceTests(unittest.TestCase):
    def test_zero_call_resolver_has_no_target_invocation(self):
        source = (hardware.HARDWARE / 'resolve_probe.c').read_text()
        self.assertIn('dlsym(handle, hardware_symbols[i].name)', source)
        self.assertNotRegex(source, r'\b(?:SteamAPI|SteamGameServer|SteamInternal)_\w+\s*\(')
        self.assertNotRegex(source, r'\(\s*\*')  # No function pointer declaration/cast/call.
        self.assertNotRegex(source, r'\b(?:address|resolved|target)\s*\(')
        self.assertNotIn('dlclose(', source)
        self.assertNotIn('libsteam_api.so', source)
        self.assertIn('st.st_ino == original.st_ino', source)

    def test_weak_fixtures_cover_all_names_and_mock_offsets(self):
        functions = [dict(name=f'f_{i:04d}', binding='Weak' if i < 21 else 'Global', other=0)
                     for i in range(1156)]
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary) / 'weak'
            weak = hardware.emit_weak_fixtures(directory, functions)
            strong = (directory / 'strong.c').read_text()
            consumer = (directory / 'consumer.c').read_text()
            self.assertEqual(len(weak), 21)
            self.assertEqual(strong.count('visibility("default")'), 21)
            self.assertNotIn('__attribute__((weak))', strong)
            for i in range(21):
                self.assertIn(f'uint64_t f_{i:04d}(uint64_t a)', strong)
                self.assertIn(f'case {i}: return f_{i:04d}(a);', consumer)
                self.assertIn(f'{{"f_{i:04d}", {i}u}}', (directory / 'weak_cases.h').read_text())

    def test_runner_invalid_stage_and_argument_counts(self):
        script = hardware.HARDWARE / 'run_hardware_validation.sh'
        for args in ([], ['unknown'], ['mock', 'extra'], ['weak', 'extra'], ['resolve'], ['all'], ['resolve', 'a', 'b']):
            with self.subTest(args=args):
                result = subprocess.run(['sh', str(script), *args], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('usage:', result.stderr)

    def test_runner_rejects_execution_outside_isolation_directory(self):
        result = subprocess.run(['sh', str(hardware.HARDWARE / 'run_hardware_validation.sh'), 'mock'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('run only from', result.stderr)

    def test_deterministic_archive_and_checksums(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            directory = root / 'bundle'
            directory.mkdir()
            (directory / 'fixture').write_bytes(b'fixture bytes')
            hardware.checksum_manifest(directory)
            self.assertEqual((directory / 'SHA256SUMS').read_text(),
                             hashlib.sha256(b'fixture bytes').hexdigest() + '  fixture\n')
            hardware.deterministic_archive(directory, root / 'a.tar.gz')
            os.utime(directory / 'fixture', (99999, 99999))
            hardware.deterministic_archive(directory, root / 'b.tar.gz')
            self.assertEqual((root / 'a.tar.gz').read_bytes(), (root / 'b.tar.gz').read_bytes())


@unittest.skipUnless(HAS_NDK and READER, 'requires Android NDK and llvm-readelf')
class HardwareBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='hardware-build-test-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = pathlib.Path(cls.temporary.name)
        cls.target = cls.root / 'target'
        cls.functions = [dict(name=f'fixture_{i:04d}', binding='Weak' if i < 21 else 'Global', other=0)
                         for i in range(1156)]
        emit_surface(cls.target, cls.functions)
        build_proxy(cls.target, compiler_path(NDK))
        # Synthetic metadata exercises the fixed profile without any captured provider.
        (cls.target / 'manifest.json').write_text(json.dumps(dict(
            provider_sha256=hardware.PROVIDER_SHA256, functions=cls.functions)))
        cls.output = cls.root / 'test.tar.gz'
        cls.report = hardware.build_bundle(cls.target, cls.output, NDK, READER)
        cls.archive_bytes = cls.output.read_bytes()

    def setUp(self):
        self.temporary_case = tempfile.TemporaryDirectory(prefix='hardware-runner-test-')
        self.addCleanup(self.temporary_case.cleanup)
        self.directory = pathlib.Path(self.temporary_case.name)
        with tarfile.open(self.output) as archive:
            archive.extractall(self.directory, filter='data')

    def adapt_runner(self):
        # Host-only sandbox adaptation; production has no path override.
        script = self.directory / 'run_hardware_validation.sh'
        script.write_text(script.read_text().replace('/data/local/tmp/creamlinux-target-proxy', str(self.directory)))
        hardware.checksum_manifest(self.directory)
        return script

    def run_stage(self, *args, override=False):
        env = dict(os.environ)
        env.pop('CREAMLINUX_ALLOW_PROVIDER_SHA_MISMATCH', None)
        if override:
            env['CREAMLINUX_ALLOW_PROVIDER_SHA_MISMATCH'] = '1'
        return subprocess.run(['sh', str(self.directory / 'run_hardware_validation.sh'), *map(str, args)],
                              capture_output=True, text=True, env=env)

    def stub(self, name, body):
        path = self.directory / name
        path.write_text('#!/bin/sh\nset -eu\n' + body + '\n')
        path.chmod(0o755)

    def prepare_stage_stubs(self):
        self.stub('abi_test', 'echo "steam proxy: resolved 1156 functions"\necho "PASS 11156 ABI checks"')
        self.stub('binding_probe', 'echo "PASS dynsym: 1135 GLOBAL, 21 WEAK FUNC"')
        self.stub('weak_probe', 'echo "PASS weak $1: 21/21 symbols; 105 checks"')
        self.stub('mock_load_probe', '''
case "${2:-}" in
  '') text='absolute original path required' ;;
  relative.so) text='absolute original path required' ;;
  */does-not-exist.so) text='cannot stat original' ;;
  */libsteam_api.so) text='original is proxy itself' ;;
  */libempty.so) text='missing function' ;;
  */libdependency.so) text='target is not in explicit original' ;;
  */libbroken_dependency.so) text='dlopen original' ;;
  */libmissing_weak.so) text='missing function: fixture_0000' ;;
  *) exit 3 ;;
esac
echo "$text"
exit 127''')
        self.stub('resolve_probe', 'echo called > logs/resolver-invoked\necho "PASS resolve: 1156/1156 targets; failures=0; zero Steam API calls"')
        self.adapt_runner()

    def test_expected_bundle_members_and_no_real_provider(self):
        with tarfile.open(self.output) as archive:
            self.assertEqual(set(archive.getnames()), MEMBERS)
            self.assertTrue(all(m.isfile() and not m.name.startswith('/') and '..' not in m.name for m in archive.getmembers()))
            self.assertTrue(all(m.uid == m.gid == m.mtime == 0 for m in archive.getmembers()))
        self.assertNotIn('original-provider.so', MEMBERS)
        self.assertEqual(hardware.sha256(self.directory / 'libsteam_api.so'), hardware.sha256(self.target / 'libsteam_api.so'))

    def test_generated_checksums_cover_every_member(self):
        records = (self.directory / 'SHA256SUMS').read_text().splitlines()
        self.assertEqual(len(records), len(MEMBERS) - 1)
        for line in records:
            digest, name = line.split('  ')
            self.assertEqual(digest, hardware.sha256(self.directory / name))
        digest, name = self.output.with_name(self.output.name + '.sha256').read_text().split()
        self.assertEqual(name, self.output.name)
        self.assertEqual(digest, hardware.sha256(self.output))

    def test_bundle_manifest_counts_and_safety(self):
        manifest = json.loads((self.directory / 'manifest.json').read_text())
        self.assertEqual((manifest['function_count'], manifest['global_function_count'], manifest['weak_function_count']), (1156, 1135, 21))
        self.assertEqual(manifest['abi_checks'], 11156)
        self.assertEqual(manifest['provider_sha256'], hardware.PROVIDER_SHA256)
        self.assertEqual(manifest['proxy_sha256'], hardware.sha256(self.directory / 'libsteam_api.so'))
        self.assertFalse(manifest['real_provider_included'])
        self.assertEqual(manifest['hardware_validation'], 'not_run')
        self.assertTrue(json.loads((self.directory / 'mock-parity.json').read_text())['passed'])

    def test_repeated_build_byte_identical(self):
        second = self.root / 'second.tar.gz'
        hardware.build_bundle(self.target, second, NDK, READER)
        self.assertEqual(self.archive_bytes, second.read_bytes())

    def test_android_dynamic_harness_and_fixtures(self):
        elf = read_elf(self.directory / 'abi_test', READER)
        self.assertTrue(any(p['ProgramHeader'].get('Interp') == '/system/bin/linker64' or
                            p['ProgramHeader']['Type']['Name'] == 'PT_INTERP' for p in elf['ProgramHeaders']))
        for name in ('resolve_probe', 'weak_probe', 'binding_probe', 'mock_load_probe'):
            header = read_elf(self.directory / name, READER)['ElfHeader']
            self.assertEqual(header['Machine']['Value'], 183)
        strong = read_elf(self.directory / 'weak/libstrong.so', READER)
        exports = public_symbols(strong)
        self.assertEqual({(s['name'], s['binding']) for s in exports},
                         {(s['name'], 'Global') for s in self.functions[:21]})
        self.assertTrue(any(d['Type'] == 'FLAGS_1' and 'GLOBAL' in d['Flags'] for d in strong['DynamicSection']))
        consumer = read_elf(self.directory / 'weak/libconsumer.so', READER)
        self.assertTrue(any(d['Type'] == 'NEEDED' and d['Library'] == 'libsteam_api.so' for d in consumer['DynamicSection']))
        undefined = {s['Symbol']['Name']['Name'] for s in consumer['DynamicSymbols'] if s['Symbol']['Section']['Value'] == 0}
        self.assertTrue({s['name'] for s in self.functions[:21]} <= undefined)
        missing = public_symbols(read_elf(self.directory / 'mock/libmissing_weak.so', READER))
        self.assertEqual(len(missing), 1155)
        self.assertNotIn('fixture_0000', {s['name'] for s in missing})
        broken = read_elf(self.directory / 'mock/libbroken_dependency.so', READER)
        self.assertTrue(any(d['Type'] == 'NEEDED' and d['Library'] == 'libhardware_absent.so' for d in broken['DynamicSection']))
        self.assertFalse((self.directory / 'libhardware_absent.so').exists())

    def test_android_dynsym_parser_logic_accepts_exact_bindings_and_rejects_corruption(self):
        native_cc = shutil.which('cc')
        if not native_cc:
            self.skipTest('requires a native C compiler for ELF reader logic')
        header = self.directory / 'hardware_symbols.h'
        header.write_text(
            '#define HARDWARE_FUNCTION_COUNT 1156u\n#define HARDWARE_GLOBAL_COUNT 1135u\n#define HARDWARE_WEAK_COUNT 21u\n'
            'static const struct { const char *name; unsigned binding, other; } hardware_symbols[] = {\n' +
            ''.join(f'{{"{s["name"]}", {2 if s["binding"] == "Weak" else 1}u, 0u}},\n' for s in self.functions) + '};\n')
        probe = self.directory / 'native-binding-probe'
        subprocess.run([native_cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I' + str(self.directory),
                        str(hardware.HARDWARE / 'binding_probe.c'), '-o', str(probe)], check=True, capture_output=True)
        library = self.directory / 'libsteam_api.so'
        result = subprocess.run([str(probe), str(library)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1135 GLOBAL, 21 WEAK FUNC', result.stdout)
        raw = bytearray(library.read_bytes())
        elf = read_elf(library, READER)
        dynsym = next(s['Section'] for s in elf['Sections'] if s['Section']['Type']['Value'] == 11)
        index = next(i for i, s in enumerate(elf['DynamicSymbols']) if s['Symbol']['Name']['Name'] == 'fixture_0000')
        offset = dynsym['Offset'] + index * 24 + 4
        self.assertEqual(raw[offset], 0x22)  # STB_WEAK | STT_FUNC
        raw[offset] = 0x12  # Accidental promotion to STB_GLOBAL.
        library.write_bytes(raw)
        result = subprocess.run([str(probe), str(library)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('FAIL dynsym', result.stderr)
        struct.pack_into('<Q', raw, 40, len(raw) + 8)  # Out-of-bounds section table.
        library.write_bytes(raw)
        self.assertEqual(subprocess.run([str(probe), str(library)], capture_output=True).returncode, 1)

    def test_failure_missing_file(self):
        self.adapt_runner()
        (self.directory / 'abi_test').unlink()
        result = self.run_stage('weak')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing/nonregular bundle member: abi_test', result.stderr)

    def test_failure_corrupt_transferred_file(self):
        self.adapt_runner()
        with (self.directory / 'libsteam_api.so').open('ab') as stream:
            stream.write(b'corrupt')
        result = self.run_stage('mock')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('bundle checksums', result.stderr)

    def test_failure_missing_checksum_manifest(self):
        self.adapt_runner()
        (self.directory / 'SHA256SUMS').unlink()
        result = self.run_stage('mock')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing checksum manifest', result.stderr)

    def test_failure_missing_provider(self):
        self.adapt_runner()
        result = self.run_stage('resolve', self.directory / 'original-provider.so')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing/nonregular real provider', result.stderr)

    def test_wrong_real_provider_checksum_rejected_before_execution(self):
        self.prepare_stage_stubs()
        provider = self.directory / 'original-provider.so'
        provider.write_bytes(b'wrong provider')
        result = self.run_stage('all', provider)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('real-provider checksum', result.stderr)
        self.assertFalse((self.directory / 'logs/resolver-invoked').exists())
        self.assertFalse((self.directory / 'logs/mock-abi.log').exists())

    def test_development_checksum_override_is_explicit(self):
        self.prepare_stage_stubs()
        provider = self.directory / 'original-provider.so'
        provider.write_bytes(b'development provider')
        result = self.run_stage('resolve', provider, override=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DEVELOPMENT OVERRIDE', result.stdout)
        self.assertTrue((self.directory / 'logs/resolver-invoked').is_file())
        self.assertFalse((self.directory / 'logs/mock-abi.log').exists())

    def test_provider_outside_root_rejected_even_with_override(self):
        self.prepare_stage_stubs()
        result = self.run_stage('resolve', '/data/app/libsteam_api.so', override=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('copy provider separately', result.stderr)
        self.assertFalse((self.directory / 'logs/resolver-invoked').exists())

    def test_symlink_member_rejected(self):
        self.adapt_runner()
        binary = self.directory / 'abi_test'
        binary.unlink()
        binary.symlink_to('/bin/true')
        result = self.run_stage('weak')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('nonregular bundle member', result.stderr)

    def test_stage_mock_routes_all_rejections(self):
        self.prepare_stage_stubs()
        result = self.run_stage('mock')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('8 loader rejections', result.stdout)
        self.assertEqual(len(list((self.directory / 'logs').glob('*.log'))), 10)
        self.assertFalse((self.directory / 'logs/weak-baseline.log').exists())
        self.assertFalse((self.directory / 'logs/resolver-invoked').exists())

    def test_stage_weak_routes_four_separate_processes(self):
        self.prepare_stage_stubs()
        result = self.run_stage('weak')
        self.assertEqual(result.returncode, 0, result.stderr)
        for mode in ('baseline', 'strong-first', 'strong-middle', 'strong-late'):
            self.assertIn(f'PASS weak {mode}', (self.directory / f'logs/weak-{mode}.log').read_text())
        self.assertFalse((self.directory / 'logs/mock-abi.log').exists())

    def test_stage_all_runs_all_three_stages(self):
        self.prepare_stage_stubs()
        provider = self.directory / 'original-provider.so'
        provider.write_bytes(b'development provider')
        result = self.run_stage('all', provider, override=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS hardware stage=all', result.stdout)
        for name in ('mock-abi.log', 'weak-dynsym.log', 'resolve.log'):
            self.assertTrue((self.directory / 'logs' / name).is_file())

    def test_nonzero_child_failure_propagates(self):
        self.prepare_stage_stubs()
        self.stub('weak_probe', 'echo deliberate failure >&2\nexit 17')
        hardware.checksum_manifest(self.directory)
        result = self.run_stage('weak')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('weak-baseline (exit 17)', result.stderr)

    def test_loader_wrong_exit_status_rejected(self):
        self.prepare_stage_stubs()
        self.stub('mock_load_probe', 'echo "absolute original path required"\nexit 1')
        hardware.checksum_manifest(self.directory)
        result = self.run_stage('mock')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('expected exit 127', result.stderr)

    def test_loader_wrong_diagnostic_rejected(self):
        self.prepare_stage_stubs()
        self.stub('mock_load_probe', 'echo wrong diagnostic\nexit 127')
        hardware.checksum_manifest(self.directory)
        result = self.run_stage('mock')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('expected exit 127', result.stderr)


if __name__ == '__main__':
    unittest.main()
