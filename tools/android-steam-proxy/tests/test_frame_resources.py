"""Reader resource staging must retain exact pinned payloads and licenses."""
import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest

script = pathlib.Path(__file__).resolve().parents[3] / 'scripts/prepare-steam-frame-runtime.py'
spec = importlib.util.spec_from_file_location('frame_resources', script)
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / 'source'
        names = {'bin/llvm-readelf'} | {n for r in resources.PACKAGES.values() for n in r['members'].values()}
        manifest = dict(architecture='aarch64', package_sha256={n:r['sha256'] for n,r in resources.PACKAGES.items()}, sha256={})
        for name in names:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = b'fixture'
            if name == 'libexec/llvm-readobj': raw = b'\x7fELF\x02\x01'+bytes(12)+b'\xb7\x00'
            path.write_bytes(raw)
            path.chmod(0o755)
            manifest['sha256'][name] = hashlib.sha256(raw).hexdigest()
        (self.source / 'manifest.json').write_text(json.dumps(manifest))
        self.checksums()

    def checksums(self):
        (self.source / 'SHA256SUMS').write_text(''.join(
            hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(self.source).as_posix()+'\n'
            for p in sorted(self.source.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))

    def test_stage_preserves_complete_runtime_and_can_reverify(self):
        target = resources.stage(self.source, self.root / 'staged')
        self.assertEqual(resources.verify(self.source), resources.verify(target))
        self.assertEqual(resources.stage(self.source, target), target)

    def test_corrupt_payload_blocks_staging(self):
        (self.source / 'lib/libedit.so.2').write_bytes(b'corruption')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            resources.stage(self.source, self.root / 'staged')
        self.assertFalse((self.root / 'staged').exists())

    def test_missing_license_and_unexpected_file_are_rejected(self):
        (self.source / 'licenses/libllvm20-copyright').unlink()
        with self.assertRaises(ValueError): resources.verify(self.source)
        (self.source / 'licenses/libllvm20-copyright').write_bytes(b'fixture')
        (self.source / 'unexpected').write_bytes(b'not a reader payload')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            resources.verify(self.source)

    def test_symlink_payload_is_rejected(self):
        path = self.source / 'bin/llvm-readelf'
        path.unlink(); path.symlink_to('/usr/bin/readelf')
        with self.assertRaisesRegex(ValueError, 'nonregular'):
            resources.verify(self.source)

    def test_changed_package_identity_and_incomplete_checksums_are_rejected(self):
        path = self.source / 'manifest.json'
        manifest = json.loads(path.read_text()); manifest['package_sha256']['llvm-20'] = '0'*64
        path.write_text(json.dumps(manifest)); self.checksums()
        with self.assertRaisesRegex(ValueError, 'pinned'):
            resources.verify(self.source)

    def test_installed_games_and_source_descendants_are_rejected(self):
        for target in ['/data/app', '/data/app/reader', self.source / 'child']:
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'separate'):
                resources.stage(self.source, target)

    def test_linuxdeploy_modified_private_elf_is_restored_and_reverified(self):
        target = self.root / 'Creamlinux.AppDir/usr/lib/Creamlinux/compatibility/runtime'
        resources.stage(self.source, target)
        (target / 'lib/libLLVM.so.20.1').write_bytes(b'linuxdeploy rpath rewrite')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            resources.verify(target)
        resources.restore_appdir_payloads(self.source, target)
        self.assertEqual(resources.verify(self.source), resources.verify(target))

    def test_payload_restoration_refuses_unrelated_files_or_destinations(self):
        target = self.root / 'Creamlinux.AppDir/usr/lib/Creamlinux/compatibility/runtime'
        resources.stage(self.source, target)
        (target / 'unrelated').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            resources.restore_appdir_payloads(self.source, target)
        self.assertEqual((target / 'unrelated').read_text(), 'keep')
        with self.assertRaisesRegex(ValueError, 'limited'):
            resources.restore_appdir_payloads(self.source, self.root / 'not-an-appdir')
