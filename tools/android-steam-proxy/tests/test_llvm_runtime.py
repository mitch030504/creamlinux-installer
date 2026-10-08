"""Pinned payload selection and private-reader runtime regressions; no network."""
import io
import json
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import build_llvm_runtime as runtime
import compatibility


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.output = self.root / 'out'
        self.binary = b'\x7fELF\x02\x01' + bytes(12) + b'\xb7\x00' + bytes(44)

    def prepare(self):
        for name in runtime.PACKAGES:
            (self.cache / (name + '.deb')).write_bytes(b'package')

    def payload(self, path, selection):
        return {name: self.binary if dest.startswith(('lib/', 'libexec/')) else b'license'
                for name, dest in selection.items()}

    def build(self, **kwargs):
        self.prepare()
        with mock.patch.object(runtime, 'checksum', side_effect=lambda p: runtime.PACKAGES[p.stem]['sha256']
                if p.suffix == '.deb' else 'f' * 64), mock.patch.object(runtime, 'payload', side_effect=self.payload):
            return runtime.build(self.cache, self.output, **kwargs)

    def test_only_selected_payloads_and_licenses_are_bundled(self):
        manifest = self.build()
        self.assertFalse(manifest['installed_packages'])
        expected = {'bin/llvm-readelf', 'libexec/llvm-readobj', 'lib/libLLVM.so.20.1',
                    'lib/libedit.so.2', 'lib/libtinfo.so.6', 'manifest.json', 'SHA256SUMS'}
        expected.update('licenses/' + name + '-copyright' for name in runtime.PACKAGES)
        self.assertEqual({p.relative_to(self.output).as_posix() for p in self.output.rglob('*') if p.is_file()}, expected)
        self.assertEqual(json.loads((self.output / 'manifest.json').read_text()), manifest)

    def test_libedit_and_tinfo_sonames_are_private_dependencies(self):
        selected = {dest for r in runtime.PACKAGES.values() for dest in r['members'].values()}
        self.assertIn('lib/libedit.so.2', selected)
        self.assertIn('lib/libtinfo.so.6', selected)
        self.assertFalse(any('wayland' in name or 'xcb' in name for name in selected))

    def test_launcher_clears_preload_and_replaces_library_search_path(self):
        self.build()
        binary = self.output / 'libexec/llvm-readobj'
        binary.write_text('#!/bin/sh\nprintf "%s|%s|%s" "${LD_PRELOAD-unset}" "$LD_LIBRARY_PATH" "$1"\n')
        binary.chmod(0o755)
        import os
        env = dict(os.environ, LD_PRELOAD='', LD_LIBRARY_PATH='/unrelated/game/libraries')
        result = subprocess.run([str(self.output / 'bin/llvm-readelf'), 'argument'],
                                env=env, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, 'unset|' + str(self.output / 'lib') + '|argument')

    def test_corrupt_pinned_package_fails_before_creating_output(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'checksum-mismatched'):
            runtime.build(self.cache, self.output)
        self.assertFalse(self.output.exists())

    def test_occupied_output_and_cache_descendant_are_rejected(self):
        self.output.mkdir()
        (self.output / 'unrelated').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'new or empty'):
            self.build()
        with self.assertRaisesRegex(ValueError, 'separate from cache'):
            runtime.build(self.cache, self.cache / 'output')
        self.assertEqual((self.output / 'unrelated').read_text(), 'keep')

    def test_missing_payload_and_symlink_selected_member_are_rejected(self):
        for symlink in (False, True):
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode='w') as archive:
                if symlink:
                    member = tarfile.TarInfo('./selected')
                    member.type = tarfile.SYMTYPE
                    member.linkname = '/outside'
                    archive.addfile(member)
            with mock.patch.object(runtime.subprocess, 'run', side_effect=[
                mock.Mock(stdout='data.tar\n'), mock.Mock(stdout=data.getvalue())]):
                with self.assertRaises(ValueError):
                    runtime.payload(self.root / 'fixture.deb', {'./selected': 'safe'})

    def test_wrong_architecture_is_rejected_before_output(self):
        self.binary = self.binary[:18] + b'\x3e\x00' + self.binary[20:]
        with self.assertRaisesRegex(ValueError, 'ARM64'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_installed_game_root_and_descendants_are_rejected(self):
        for output in ('/data/app', '/data/app/reader'):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'installed games'):
                runtime.build(self.cache, output)

    def test_expected_builder_failure_has_no_traceback(self):
        result = subprocess.run([sys.executable, runtime.__file__, '--cache', str(self.cache),
                                 '--output', str(self.output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)


class ReaderDiscoveryTests(unittest.TestCase):
    def test_explicit_choice_wins_over_environment(self):
        with mock.patch.dict(compatibility.os.environ, {'CREAMLINUX_LLVM_READELF': '/bundle/reader'}), \
             mock.patch.object(compatibility.shutil, 'which', side_effect=lambda p: p):
            self.assertEqual(compatibility.discover_readelf('/chosen/reader'), '/chosen/reader')
            self.assertEqual(compatibility.discover_readelf(), '/bundle/reader')

    def test_broken_environment_selection_never_falls_back_to_system(self):
        with mock.patch.dict(compatibility.os.environ, {'CREAMLINUX_LLVM_READELF': '/missing/reader'}), \
             mock.patch.object(compatibility.shutil, 'which', return_value=None) as lookup:
            self.assertIsNone(compatibility.discover_readelf())
            lookup.assert_called_once_with('/missing/reader')


if __name__ == '__main__':
    unittest.main()
