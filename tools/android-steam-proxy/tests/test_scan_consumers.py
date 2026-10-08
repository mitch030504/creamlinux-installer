#!/usr/bin/env python3
"""Host-only scanner regression tests; generated fixture ELFs are never loaded."""
import hashlib
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCANNER = pathlib.Path(__file__).with_name('scan_consumers.py')
TARGET = 'g_pSteamClientGameServer'


@unittest.skipUnless(shutil.which('clang') and shutil.which('ld.lld') and
                     shutil.which('llvm-readelf'), 'requires clang, lld, llvm-readelf')
class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='consumer-scan-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)

    def build(self, name, source, *flags, target='aarch64-linux-android21'):
        path = self.root / name
        subprocess.run(['clang', '--target=' + target, '-fuse-ld=lld', '-nostdlib',
                        '-shared', '-fPIC', '-x', 'c', '-', '-x', 'none', '-o', str(path), *flags],
                       input=source, text=True, check=True, capture_output=True)
        return path

    def scan(self, *paths, code=0):
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob('*') if p.is_file()}
        result = subprocess.run([sys.executable, str(SCANNER), *map(str, paths)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, code, result.stderr + result.stdout)
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after, 'scanner changed inputs or wrote into input directory')
        report = json.loads(result.stdout)
        self.assertIn('summary', report, 'missing evidence-based linkage summary')
        return report

    def test_strong_import_and_android_packed_relocation(self):
        for packed in (False, True):
            with self.subTest(packed=packed):
                flags = ['-Wl,--pack-dyn-relocs=android'] if packed else []
                path = self.build('import.so', 'extern void *g_pSteamClientGameServer; '
                                  'void **use = &g_pSteamClientGameServer;', *flags)
                r = self.scan(path)
                self.assertTrue(r['summary'][TARGET]['statically_required'])
                f = r['files'][0]
                self.assertEqual(f['architecture'], 'aarch64')
                self.assertEqual(f['imported_symbols'][0]['symbol'], TARGET)
                self.assertTrue(any(x['symbol'] == TARGET and x['dynamic']
                                    for x in f['relocations']))
                self.assertTrue(r['scan_complete'])

    def test_strings_and_near_matches_do_not_prove_linkage(self):
        path = self.build('string.so', 'const char names[] = '
                          '"g_pSteamClientGameServer __bss_start _edata _end"; '
                          'extern int g_pSteamClientGameServer_extra; '
                          'int *p = &g_pSteamClientGameServer_extra;')
        r = self.scan(path)
        self.assertFalse(r['summary'][TARGET]['statically_required'])
        f = r['files'][0]
        self.assertEqual(f['imported_symbols'], [])
        self.assertEqual(f['relocations'], [])
        self.assertEqual({x['symbol'] for x in f['string_occurrences']},
                         {TARGET, '__bss_start', '_edata', '_end'})

    def test_definition_and_self_relocation_are_not_external_requirements(self):
        path = self.build('definition.so', 'void *g_pSteamClientGameServer; '
                          'void **p = &g_pSteamClientGameServer;')
        r = self.scan(path)
        self.assertFalse(r['summary'][TARGET]['statically_required'])
        self.assertTrue(r['files'][0]['defined_symbols'])
        self.assertTrue(r['files'][0]['relocations'])
        self.assertTrue(r['files'][0]['symbol_table_references'])

    def test_weak_import_is_linkage_but_not_mandatory(self):
        path = self.build('weak.so', 'extern void *g_pSteamClientGameServer '
                          '__attribute__((weak)); void **p = &g_pSteamClientGameServer;')
        r = self.scan(path)
        self.assertFalse(r['summary'][TARGET]['statically_required'])
        self.assertTrue(r['summary'][TARGET]['static_reference_detected'])
        self.assertEqual(r['files'][0]['imported_symbols'][0]['binding'], 'Weak')

    def test_boundary_definitions_and_32_bit_rel(self):
        path = self.build('boundary.so', 'extern char __bss_start, _edata, _end; '
                          'char *p[] = {&__bss_start, &_edata, &_end};',
                          target='armv7a-linux-androideabi21')
        r = self.scan(path)
        self.assertEqual(r['files'][0]['architecture'], 'arm')
        self.assertEqual({x['symbol'] for x in r['files'][0]['defined_symbols']},
                         {'__bss_start', '_edata', '_end'})
        self.assertEqual(len(r['files'][0]['relocations']), 3)

    def test_versioned_import_and_relocation(self):
        script = self.root / 'versions.map'
        script.write_text('STEAM_1 { global: g_pSteamClientGameServer; };')
        provider = self.build('provider.so', 'void *g_pSteamClientGameServer;',
                              '-Wl,--version-script=' + str(script))
        consumer = self.build('versioned.so', 'extern void *g_pSteamClientGameServer; '
                              'void **p = &g_pSteamClientGameServer;', str(provider))
        r = self.scan(consumer)
        self.assertTrue(r['summary'][TARGET]['statically_required'])
        self.assertEqual(r['files'][0]['imported_symbols'][0]['name'],
                         TARGET + '@STEAM_1')
        self.assertEqual(r['files'][0]['relocations'][0]['symbol'], TARGET)

    def test_stripped_consumer_retains_dynamic_evidence(self):
        path = self.build('stripped.so', 'extern void *g_pSteamClientGameServer; '
                          'void **p = &g_pSteamClientGameServer;', '-Wl,-s')
        r = self.scan(path)
        self.assertTrue(r['summary'][TARGET]['statically_required'])
        self.assertFalse(r['files'][0]['symbol_table_available'])
        self.assertEqual(r['files'][0]['symbol_table_references'], [])

    def test_local_static_definition_is_symbol_table_evidence_only(self):
        path = self.build('local.so', 'static void *g_pSteamClientGameServer; '
                          'void **get(void) { return &g_pSteamClientGameServer; }')
        r = self.scan(path)
        self.assertFalse(r['summary'][TARGET]['statically_required'])
        self.assertEqual(r['files'][0]['imported_symbols'], [])
        self.assertEqual(r['files'][0]['symbol_table_references'][0]['binding'], 'Local')

    def test_sectionless_elf_is_inconclusive(self):
        # Construct a minimal ELF header, without patching an existing binary.
        import struct
        path = self.root / 'sectionless.so'
        path.write_bytes(b'\x7fELF\x02\x01\x01' + bytes(9) +
                         struct.pack('<HHIQQQIHHHHHH', 3, 183, 1, 0, 0, 0,
                                     0, 64, 56, 0, 64, 0, 0))
        r = self.scan(path, code=2)
        self.assertFalse(r['scan_complete'])
        self.assertTrue(r['errors'])

    def test_relative_relr_does_not_create_symbol_reference(self):
        path = self.build('relative.so', 'static int value; int *p = &value; '
                          'const char name[] = "g_pSteamClientGameServer";',
                          '-Wl,--pack-dyn-relocs=relr')
        r = self.scan(path)
        self.assertFalse(r['summary'][TARGET]['statically_required'])
        self.assertEqual(r['files'][0]['relocations'], [])

    def test_recursive_base_split_and_nested_archives(self):
        lib = self.build('sample.so', 'extern void *g_pSteamClientGameServer; '
                         'void **p = &g_pSteamClientGameServer;').read_bytes()
        inputs = self.root / 'inputs'
        (inputs / 'splits').mkdir(parents=True)
        for path in (inputs / 'base.apk', inputs / 'splits' / 'split.apk'):
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('assets/deep/libsample.so', lib)
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, 'w') as z:
            z.writestr('lib/arm64-v8a/libsample.so', lib)
        with zipfile.ZipFile(inputs / 'bundle.apks', 'w') as z:
            z.writestr('splits/config.apk', nested.getvalue())
        r = self.scan(inputs)
        self.assertEqual(r['elf_files_scanned'], 3)
        self.assertEqual(r['archives_scanned'], 4)
        self.assertTrue(all('!/' in f['file'] for f in r['files']))

    def test_bad_elf_and_missing_input_make_scan_incomplete(self):
        bad = self.root / 'bad.so'
        bad.write_bytes(b'\x7fELFbroken')
        r = self.scan(bad, self.root / 'missing.apk', code=2)
        self.assertFalse(r['scan_complete'])
        self.assertGreaterEqual(len(r['errors']), 2)

    def test_empty_apk_is_not_a_clean_negative(self):
        apk = self.root / 'empty.apk'
        with zipfile.ZipFile(apk, 'w') as z:
            z.writestr('AndroidManifest.xml', b'fixture')
        r = self.scan(apk, code=2)
        self.assertFalse(r['scan_complete'])


if __name__ == '__main__':
    unittest.main()
