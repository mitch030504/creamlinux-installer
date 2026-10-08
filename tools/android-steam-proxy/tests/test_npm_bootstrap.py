"""Pinned npm bootstrap boundaries; no network or Node required."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('npm_bootstrap', ROOT/'scripts/release/prepare-npm.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class NpmBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root/'npm.tgz'
        with tarfile.open(self.archive, 'w:gz') as tar:
            for name, content in [('package/package.json', b'{"version":"10.9.9"}'),
                                  ('package/bin/npm-cli.js', b'#!/usr/bin/env node\n'),
                                  ('package/bin/npx-cli.js', b'#!/usr/bin/env node\n'),
                                  ('package/LICENSE', b'public test license')]:
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                entry.mode = 0o755 if name.endswith('.js') else 0o644
                tar.addfile(entry, io.BytesIO(content))
        self.pin = {'version': '10.9.9', 'sha256': hashlib.sha256(self.archive.read_bytes()).hexdigest()}
        self.output = self.root/'prepared'

    def test_valid_archive_and_license_and_executable_links(self):
        binaries = bootstrap.prepare(self.output, self.pin, self.archive)
        self.assertEqual(binaries, self.output/'bin')
        self.assertTrue((binaries/'npm').is_file())
        self.assertTrue((binaries/'npx').stat().st_mode & 0o111)
        self.assertTrue((self.output/'lib/node_modules/npm/LICENSE').is_file())

    def test_wrong_checksum_has_no_partial_output(self):
        self.pin['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'checksum'):
            bootstrap.prepare(self.output, self.pin, self.archive)
        self.assertFalse(self.output.exists())

    def test_wrong_version_has_no_partial_output(self):
        self.pin['version'] = '11.0.0'
        with self.assertRaisesRegex(ValueError, 'version'):
            bootstrap.prepare(self.output, self.pin, self.archive)
        self.assertFalse(self.output.exists())

    def test_existing_directory_refused(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            bootstrap.prepare(self.output, self.pin, self.archive)

    def test_archive_path_escape_rejected(self):
        with tarfile.open(self.archive, 'w:gz') as tar:
            entry = tarfile.TarInfo('../../escaped')
            entry.size = 1
            tar.addfile(entry, io.BytesIO(b'x'))
        self.pin['sha256'] = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        with self.assertRaises(tarfile.FilterError):
            bootstrap.prepare(self.output, self.pin, self.archive)
        self.assertFalse(self.output.exists())

    def test_unexpected_source_rejected_before_fetch(self):
        self.pin['url'] = 'http://example.invalid/npm.tgz'
        with patch('urllib.request.urlopen') as fetch:
            with self.assertRaisesRegex(ValueError, 'source URL'):
                bootstrap.prepare(self.output, self.pin)
        fetch.assert_not_called()

    def test_ci_provisions_patched_npm_without_swallowing_failure(self):
        for name in ['steam-frame-tests.yml', 'steam-frame-signing-preparation.yml', 'test-build.yml', 'build.yml']:
            text = (ROOT/'.github/workflows'/name).read_text()
            self.assertIn('npm_bin="$(python3 scripts/release/prepare-npm.py', text)
            self.assertNotIn('echo "$(python3 scripts/release/prepare-npm.py', text)
