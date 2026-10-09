"""Pinned controller reader and fail-closed protocol checks; no Docker/downloads."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('controller_reader', ROOT/'scripts/release/prepare-llvm-reader.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class ControllerReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root/'cache'
        self.cache.mkdir()
        self.archive = self.cache/'llvm-20.deb'
        self.archive.write_bytes(b'unit package, extraction mocked')
        self.elf = b'\x7fELF\x02\x01'+bytes(12)+b'\x3e\x00'
        self.pin = {'version':'20.1.8', 'architecture':'x86_64', 'packages':{'llvm-20':{
            'url':'https://apt.llvm.org/noble/pool/main/l/llvm-toolchain-20/unit.deb',
            'sha256':hashlib.sha256(self.archive.read_bytes()).hexdigest(),
            'size_bytes':self.archive.stat().st_size,
            'members':{'reader':'libexec/llvm-readobj', 'library':'lib/libLLVM.so.20.1',
                       'license':'licenses/copyright'}}}}
        self.data = {'reader':self.elf, 'library':self.elf, 'license':b'public test license'}
        self.output = self.root/'prepared'

    def prepare(self):
        with patch.object(reader, 'payload', return_value=self.data), \
                patch.object(reader, 'preflight', return_value={'status':'passed'}):
            return reader.prepare(self.output, self.cache, self.pin)

    def fake_reader(self, version='20.1.8', output='[]'):
        binary = self.root/'llvm-readelf'
        binary.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then\n'
                          f"echo 'Ubuntu LLVM version {version}'\nelse\n"
                          f"echo '{output}'\nfi\n")
        binary.chmod(0o755)
        return binary

    def test_pinned_payload_license_permissions_and_manifest(self):
        self.assertEqual(self.prepare(), self.output/'bin')
        manifest = json.loads((self.output/'manifest.json').read_text())
        self.assertEqual(manifest['version'], '20.1.8')
        self.assertFalse(manifest['installed_packages'])
        self.assertEqual((self.output/'licenses/copyright').read_bytes(), b'public test license')
        for p in ['bin/llvm-readelf', 'libexec/llvm-readobj']:
            self.assertTrue((self.output/p).stat().st_mode & 0o111)
        for path, checksum in manifest['sha256'].items():
            self.assertEqual(hashlib.sha256((self.output/path).read_bytes()).hexdigest(), checksum)
        self.assertEqual((self.output/'bin/llvm-readelf').read_text(), reader.LAUNCHER)

    def test_checksum_mismatch_fails_before_extraction(self):
        self.pin['packages']['llvm-20']['sha256'] = '0'*64
        with patch.object(reader, 'payload') as extract, self.assertRaisesRegex(ValueError, 'checksum'):
            reader.prepare(self.output, self.cache, self.pin)
        extract.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_size_mismatch_fails(self):
        self.pin['packages']['llvm-20']['size_bytes'] += 1
        with self.assertRaisesRegex(ValueError, 'size'):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_untrusted_source_rejected_before_download(self):
        self.pin['packages']['llvm-20']['url'] = 'https://example.invalid/package.deb'
        with patch.object(reader.urllib.request, 'urlopen') as fetch, self.assertRaisesRegex(ValueError, 'source URL'):
            self.prepare()
        fetch.assert_not_called()

    def test_symlink_cache_rejected(self):
        real = self.root/'real'; self.archive.rename(real); self.archive.symlink_to(real)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.prepare()

    def test_existing_output_is_preserved(self):
        self.output.mkdir(); (self.output/'user-file').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.prepare()
        self.assertEqual((self.output/'user-file').read_text(), 'keep')

    def test_nested_cache_refused(self):
        with self.assertRaisesRegex(ValueError, 'separate'):
            reader.prepare(self.output, self.output/'cache', self.pin)

    def test_wrong_architecture_has_no_partial_output(self):
        self.data['reader'] = self.elf[:18]+b'\xb7\x00'
        with self.assertRaisesRegex(ValueError, 'x86_64'):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_unsafe_selected_path_has_no_partial_output(self):
        self.pin['packages']['llvm-20']['members']['reader'] = '../escape'
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.prepare()
        self.assertFalse((self.root/'escape').exists())

    def test_failed_protocol_probe_has_no_partial_output(self):
        with patch.object(reader, 'payload', return_value=self.data), \
                patch.object(reader, 'preflight', side_effect=ValueError('JSON protocol unsupported')):
            with self.assertRaisesRegex(ValueError, 'JSON'):
                reader.prepare(self.output, self.cache, self.pin)
        self.assertFalse(self.output.exists())

    def test_missing_reader_fails_closed(self):
        with patch.object(reader.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'missing'):
                reader.preflight('llvm-readelf')

    def test_llvm_18_and_other_versions_fail_before_json_probe(self):
        for version in ['18.1.3', '20.1.80', '20.1.7', '23.1.1']:
            with self.subTest(version=version), patch.object(reader, 'inspect_elf') as inspect:
                with self.assertRaisesRegex(ValueError, 'version 20.1.8'):
                    reader.preflight(self.fake_reader(version))
                inspect.assert_not_called()

    def test_path_priority_also_reaches_cli_subprocesses(self):
        binary = self.fake_reader('18.1.3')
        env = dict(os.environ, PATH=str(self.root)+os.pathsep+os.environ['PATH'])
        selected = subprocess.check_output([sys.executable, '-c', 'import shutil;print(shutil.which("llvm-readelf"))'], env=env, text=True).strip()
        self.assertEqual(selected, str(binary))
        p = subprocess.run([sys.executable, str(ROOT/'scripts/release/prepare-llvm-reader.py'), '--preflight-only'],
                           env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, '')
        self.assertIn('version 20.1.8', p.stderr)
        self.assertNotIn('Traceback', p.stderr)

    @unittest.skipUnless(shutil.which('clang') and shutil.which('ld.lld'), 'requires fixture compiler')
    def test_claimed_version_with_invalid_json_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'LLVM JSON'):
            reader.preflight(self.fake_reader(output='not JSON'))

    @unittest.skipUnless(shutil.which('clang') and shutil.which('ld.lld'), 'requires fixture compiler')
    def test_claimed_version_with_missing_json_fields_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'LLVM JSON'):
            reader.preflight(self.fake_reader(output='[{}]'))

    def test_pins_match_reviewed_official_package_identities(self):
        pin = json.loads((ROOT/'scripts/release/controller.json').read_text())['llvm_reader']
        self.assertEqual(pin['version'], '20.1.8')
        self.assertEqual(pin['architecture'], 'x86_64')
        self.assertEqual(set(pin['packages']), {'llvm-20', 'libllvm20'})
        for record in pin['packages'].values():
            self.assertRegex(record['sha256'], r'^[0-9a-f]{64}$')
            self.assertTrue(record['url'].endswith('_amd64.deb'))
            self.assertIn(pin['package_version'], record['url'])
            self.assertGreater(record['size_bytes'], 0)

    def test_ci_prepends_reader_and_preflights_before_python_tests(self):
        for name in ['steam-frame-tests.yml', 'steam-frame-release.yml']:
            text = (ROOT/'.github/workflows'/name).read_text()
            self.assertIn('llvm_bin="$(python3 scripts/release/prepare-llvm-reader.py', text)
            self.assertIn('echo "$llvm_bin" >> "$GITHUB_PATH"', text)
            self.assertNotIn('echo "$(python3 scripts/release/prepare-llvm-reader.py', text)
            self.assertIn('scripts/release/prepare-llvm-reader.py --preflight-only', text)
            self.assertNotIn(' lld llvm ', text)
            self.assertIn('permissions:\n  contents: read', text)
            gate = 'python3 -m unittest' if name == 'steam-frame-tests.yml' else 'scripts/build-steam-frame-release.sh'
            self.assertLess(text.index('--preflight-only'), text.index(gate))


if __name__ == '__main__':
    unittest.main()
