"""Provider-driven generator/parity regressions. Fixtures are never loaded."""
import copy
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import generate_target_proxy as target
from generate import emit_surface, emit_mock
from verify_target_proxy import verify

READER = shutil.which('llvm-readelf')
NDK = os.environ.get('ANDROID_NDK_HOME') or os.environ.get('ANDROID_NDK_ROOT')
HAS_NDK = bool(NDK and (pathlib.Path(NDK) / 'toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android21-clang').is_file())


@unittest.skipUnless(READER and shutil.which('clang') and shutil.which('ld.lld'),
                     'requires LLVM fixture tools')
class TargetProxyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='target-proxy-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        (self.root / 'provider').mkdir()
        self.provider = self.build('mixed.so', '''
            int target_only_new(void) { return 1; }
            __attribute__((weak)) int weak_target(void) { return 2; }
            __attribute__((visibility("protected"))) int protected_target(void) { return 3; }
            int g_pSteamClientGameServer;
            __attribute__((weak)) int __llvm_fs_discriminator__;
        ''')

    def build(self, name, source, target_arch='aarch64-linux-android21', flags=()):
        path = self.root / 'provider' / name
        subprocess.run(['clang', '--target=' + target_arch, '-fuse-ld=lld', '-nostdlib',
                        '-shared', '-fPIC', '-x', 'c', '-', '-x', 'none', '-o', str(path), *flags],
                       input=source, text=True, check=True, capture_output=True)
        return path

    def generate(self, name='out', provider=None, sources_only=True):
        out = self.root / name
        manifest = target.generate(provider or self.provider, out, READER, NDK, sources_only)
        return out, manifest

    def corrupt(self, transform):
        elf = copy.deepcopy(target.read_elf(self.provider, READER))
        transform(elf)
        with patch.object(target, 'read_elf', return_value=elf):
            with self.assertRaises(ValueError):
                target.inspect_provider(self.provider, READER)

    def function(self, elf):
        return next(e['Symbol'] for e in elf['DynamicSymbols']
                    if e['Symbol']['Name']['Name'] == 'weak_target')

    def test_provider_drives_export_list(self):
        out, manifest = self.generate()
        self.assertEqual(json.loads((out / 'names.json').read_text()),
                         ['protected_target', 'target_only_new', 'weak_target'])
        self.assertEqual(manifest['generated_function_count'], 3)
        self.assertNotIn('SteamAPI_Init', (out / 'stubs.S').read_text())

    def test_weak_directive_preserved(self):
        out, _ = self.generate()
        asm = (out / 'stubs.S').read_text()
        self.assertIn('.weak weak_target\n', asm)
        self.assertNotIn('.global weak_target', asm)

    def test_global_directive_preserved(self):
        out, _ = self.generate()
        self.assertIn('.global target_only_new\n', (out / 'stubs.S').read_text())

    def test_protected_visibility_preserved(self):
        out, _ = self.generate()
        self.assertIn('.protected protected_target\n', (out / 'stubs.S').read_text())

    def test_nonfunctions_never_get_trampolines(self):
        out, _ = self.generate()
        for name in ('g_pSteamClientGameServer', '__llvm_fs_discriminator__'):
            self.assertNotIn(name, (out / 'stubs.S').read_text())
            self.assertNotIn(name, (out / 'symbols.h').read_text())
            self.assertNotIn(name, (out / 'exports.map').read_text())

    def test_omission_manifest_counts_and_binding(self):
        _, m = self.generate()
        self.assertEqual((m['total_public_exports'], m['function_export_count'],
                          m['global_function_count'], m['weak_function_count'], m['non_function_count']),
                         (5, 3, 2, 1, 2))
        self.assertEqual([(s['name'], s['type'], s['binding']) for s in m['omitted_non_function_exports']],
                         [('__llvm_fs_discriminator__', 'Object', 'Weak'),
                          ('g_pSteamClientGameServer', 'Object', 'Global')])
        self.assertEqual(m['validation_status']['runtime'], 'unvalidated/limited')
        self.assertFalse(m['validation_status']['complete_abi_clone'])
        self.assertIn('not a complete ABI clone', m['warning'])

    def test_deterministic_sources_and_manifest(self):
        first, _ = self.generate('first')
        second, _ = self.generate('second')
        self.assertEqual({p.name: p.read_bytes() for p in first.iterdir()},
                         {p.name: p.read_bytes() for p in second.iterdir()})

    def test_missing_provider(self):
        with self.assertRaises(OSError):
            self.generate(provider=self.root / 'missing.so')
        self.assertFalse((self.root / 'out').exists())

    def test_invalid_provider(self):
        path = self.root / 'provider/not-elf.so'
        path.write_text('not ELF')
        with self.assertRaisesRegex(ValueError, 'not ELF'):
            self.generate(provider=path)

    def test_unsupported_architecture(self):
        host = self.build('host.so', 'void host(void) {}', 'x86_64-linux-gnu')
        with self.assertRaisesRegex(ValueError, 'AArch64'):
            self.generate(provider=host)

    def test_no_functions(self):
        data = self.build('data.so', 'int data;')
        with self.assertRaisesRegex(ValueError, 'no public FUNCTION'):
            self.generate(provider=data)

    def test_malformed_symbol_metadata(self):
        self.corrupt(lambda e: self.function(e)['Other'].update(Value='0'))

    def test_inconsistent_binding_metadata(self):
        self.corrupt(lambda e: self.function(e)['Binding'].update(Value=1))

    def test_boolean_binding_metadata_is_malformed(self):
        self.corrupt(lambda e: self.function(e)['Binding'].update(Value=True))

    def test_missing_symbol_metadata(self):
        self.corrupt(lambda e: self.function(e).pop('Type'))

    def test_duplicate_public_symbol(self):
        self.corrupt(lambda e: e['DynamicSymbols'].append({'Symbol': copy.deepcopy(self.function(e))}))

    def test_versioned_and_suspicious_names(self):
        for name in ('weak_target@@V1', 'a;touch_file', 'a\nb', '.unsafe', 'proxy_targets', 'dlsym'):
            with self.subTest(name=name):
                self.corrupt(lambda e: self.function(e)['Name'].update(Name=name))

    def test_variant_pcs_rejected(self):
        self.corrupt(lambda e: self.function(e)['Other'].update(Value=128))

    def test_function_in_invalid_section_rejected(self):
        self.corrupt(lambda e: self.function(e)['Section'].update(Value=65521))

    def test_misaligned_function_rejected(self):
        self.corrupt(lambda e: self.function(e).update(Value=self.function(e)['Value'] + 1))

    def test_ifunc_rejected(self):
        self.corrupt(lambda e: self.function(e)['Type'].update(Name='GNU_IFunc', Value=10))

    def test_hidden_and_undefined_not_exported(self):
        p = self.build('hidden.so', '''
            __attribute__((visibility("hidden"))) int hidden(void) { return 1; }
            extern int imported(void);
            int visible(void) { return imported(); }
        ''')
        out, _ = self.generate(provider=p)
        self.assertEqual(json.loads((out / 'names.json').read_text()), ['visible'])

    def test_no_provider_directory_writes(self):
        before = self.provider.read_bytes()
        with self.assertRaisesRegex(ValueError, 'outside'):
            target.generate(self.provider, self.provider.parent / 'output', READER, sources_only=True)
        self.assertEqual(self.provider.read_bytes(), before)

    def test_stale_directory_rejected(self):
        self.generate()
        with self.assertRaisesRegex(ValueError, 'empty'):
            self.generate()

    def test_data_app_output_rejected(self):
        with self.assertRaisesRegex(ValueError, '/data/app'):
            target.generate(self.provider, '/data/app/target-proxy-test', READER, sources_only=True)

    def test_missing_reader(self):
        with self.assertRaises(OSError):
            target.inspect_provider(self.provider, self.root / 'no-reader')

    def test_cli_failure_no_traceback(self):
        r = subprocess.run([sys.executable, str(target.ROOT / 'generate_target_proxy.py'),
                            '--provider', str(self.root / 'missing'), '--output', str(self.root / 'out')],
                           text=True, capture_output=True)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn('Traceback', r.stderr)

    def test_missing_android_note_is_explicit(self):
        _, manifest = self.generate()
        self.assertIsNone(manifest['android_api'])
        self.assertIsNone(manifest['provider_ndk'])

    def test_surface_size_1156_fixture(self):
        source = '\n'.join(('__attribute__((weak)) ' if i < 21 else '') +
                           f'int function_{i:04d}(void) {{ return {i}; }}' for i in range(1156))
        source += '\n' + '\n'.join(f'int object_{i:04d};' for i in range(209))
        provider = self.build('jobsim-style.so', source)
        out, m = self.generate(provider=provider)
        self.assertEqual((m['generated_function_count'], m['weak_function_count'], m['non_function_count']),
                         (1156, 21, 209))
        self.assertEqual(len(json.loads((out / 'names.json').read_text())), 1156)

    def test_mock_generation_uses_exact_target_names(self):
        functions = [dict(name=f'function_{i:04d}', binding='Weak' if i < 21 else 'Global', other=0)
                     for i in range(1156)]
        out = self.root / 'mock'
        emit_mock(out, 1156, 21, functions)
        self.assertEqual(json.loads((out / 'names.json').read_text()), [s['name'] for s in functions])
        self.assertEqual((out / 'stubs.S').read_text().count('.weak '), 21)
        self.assertIn('1138', (out / 'pads.c').read_text())

    def test_legacy_mock_surface_retained(self):
        out = self.root / 'legacy-mock'
        functions = emit_mock(out)
        self.assertEqual(len(functions), 1047)
        self.assertTrue(all(s['binding'] == 'Global' for s in functions))
        self.assertIn('mock_pad_1029', json.loads((out / 'names.json').read_text()))

    @unittest.skipUnless(HAS_NDK, 'requires Android NDK')
    def test_built_proxy_reproducible_across_output_directories(self):
        first, manifest = self.generate(sources_only=False)
        second = self.root / 'different-build-path'
        other = target.generate(self.provider, second, READER, NDK)
        self.assertEqual((first / 'libsteam_api.so').read_bytes(),
                         (second / 'libsteam_api.so').read_bytes())
        self.assertEqual(manifest, other)
        self.assertEqual(manifest['build_identity']['proxy_sha256'],
                         hashlib.sha256((first / 'libsteam_api.so').read_bytes()).hexdigest())

    @unittest.skipUnless(HAS_NDK, 'requires Android NDK')
    def test_built_exact_parity_global_weak_and_visibility(self):
        out, m = self.generate(sources_only=False)
        r = json.loads((out / 'function-parity.json').read_text())
        self.assertTrue(r['passed'], r)
        self.assertEqual((r['name_parity'], r['weak_function_count'], r['binding_mismatches']),
                         ('exact', 1, []))
        self.assertEqual(r['visibility_mismatches'], [])
        self.assertTrue(r['checks']['every_tail_stub_and_slot_verified'])
        self.assertEqual(m['validation_status']['runtime'], 'unvalidated/limited')

    @unittest.skipUnless(HAS_NDK, 'requires Android NDK')
    def test_verifier_detects_weak_promotion(self):
        out, m = self.generate()
        promoted = [dict(s, binding='Global') for s in m['functions']]
        emit_surface(out, promoted)
        target.build_proxy(out, target.compiler_path(NDK))
        r = verify(self.provider, out / 'libsteam_api.so', READER)
        self.assertFalse(r['passed'])
        self.assertEqual(r['weak_binding_mismatches'], ['weak_target'])

    @unittest.skipUnless(HAS_NDK, 'requires Android NDK')
    def test_verifier_detects_extra_fake_object_function(self):
        out, m = self.generate()
        emit_surface(out, m['functions'] + [dict(name='g_pSteamClientGameServer', binding='Global', other=0)])
        target.build_proxy(out, target.compiler_path(NDK))
        r = verify(self.provider, out / 'libsteam_api.so', READER)
        self.assertFalse(r['passed'])
        self.assertEqual(r['fake_non_function_trampolines'], ['g_pSteamClientGameServer'])
        self.assertEqual(r['extra_functions'], ['g_pSteamClientGameServer'])

    @unittest.skipUnless(HAS_NDK, 'requires Android NDK')
    def test_verifier_detects_instruction_corruption(self):
        out, _ = self.generate(sources_only=False)
        path = out / 'libsteam_api.so'
        elf = target.read_elf(path, READER)
        s = next(s for s in target.public_symbols(elf) if s['name'] == 'weak_target')
        owner = next(x['Section'] for x in elf['Sections'] if x['Section']['Name']['Name'] == '.text')
        offset = owner['Offset'] + s['value'] - owner['Address'] + 8
        raw = bytearray(path.read_bytes())
        raw[offset:offset + 4] = bytes.fromhex('c0035fd6')  # ret instead of br x16
        path.write_bytes(raw)
        r = verify(self.provider, path, READER)
        self.assertFalse(r['passed'])
        self.assertFalse(r['checks']['every_tail_stub_and_slot_verified'])

    @unittest.skipUnless(HAS_NDK, 'requires Android NDK')
    def test_provider_change_during_build_fails_closed(self):
        build = target.build_proxy
        def mutate(directory, cc):
            build(directory, cc)
            self.provider.write_bytes(self.provider.read_bytes() + b'changed')
        with patch.object(target, 'build_proxy', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'static parity'):
                self.generate(sources_only=False)
        report = json.loads((self.root / 'out/function-parity.json').read_text())
        self.assertFalse(report['passed'])
        self.assertTrue(report['provider_changed_during_build'])

    @unittest.skipUnless(HAS_NDK, 'requires Android NDK')
    def test_real_job_simulator_smoke_if_available(self):
        provider = pathlib.Path.home() / 'creamlinux-jobsimulator-cli/libsteam_api.so'
        if not provider.is_file():
            self.skipTest('local capture unavailable')
        out, m = self.generate(provider=provider, sources_only=False)
        self.assertEqual(m['provider_sha256'], '345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700')
        self.assertEqual((m['total_public_exports'], m['generated_function_count'], m['weak_function_count']),
                         (1365, 1156, 21))
        self.assertTrue(json.loads((out / 'function-parity.json').read_text())['passed'])

    @unittest.skipUnless(HAS_NDK, 'requires Android NDK')
    def test_real_walkabout_regression_if_available(self):
        provider = pathlib.Path.home() / 'creamlinux-walkabout-cli/libsteam_api.so'
        if not provider.is_file():
            self.skipTest('local capture unavailable')
        out, m = self.generate(provider=provider, sources_only=False)
        reference = json.loads((target.ROOT / 'generated/reference-manifest.json').read_text())
        expected = sorted(s['name'] for s in reference['symbols'] if s['function_forwarding_candidate'])
        self.assertEqual(json.loads((out / 'names.json').read_text()), expected)
        self.assertEqual((m['generated_function_count'], m['weak_function_count']), (1045, 0))
        self.assertTrue(json.loads((out / 'function-parity.json').read_text())['passed'])


if __name__ == '__main__':
    unittest.main()
