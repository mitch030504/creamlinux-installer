"""Identity, stage-completeness and fail-closed evidence reporting regressions."""
import copy
import io
import json
import pathlib
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import validation_evidence as evidence


def archive(path, files):
    with tarfile.open(path, 'w:gz') as tar:
        for name, raw in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))


class HardwareEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.bundle = self.root / 'bundle.tar.gz'
        self.results = self.root / 'results'
        self.results.mkdir()
        self.provider_sha = 'a' * 64
        self.proxy_sha = evidence.digest(b'proxy fixture')
        self.names = {f'target_{i:04d}': 'Weak' if i < 21 else 'Global' for i in range(1156)}
        manifest = dict(schema_version=1, provider_sha256=self.provider_sha, proxy_sha256=self.proxy_sha,
            function_count=1156, global_function_count=1135, weak_function_count=21, abi_checks=11156,
            weak_checks=420, loader_rejection_cases=8, weak_load_scope_cases=4, architecture='aarch64',
            runtime='Android/Bionic', real_provider_included=False,
            safety_root='/data/local/tmp/creamlinux-target-proxy', toolchain='fixture compiler')
        self.files = {'libsteam_api.so': b'proxy fixture', 'manifest.json': json.dumps(manifest).encode(),
            'mock-parity.json': json.dumps(dict(passed=True, proxy_sha256=self.proxy_sha)).encode(),
            'target-functions.tsv': ''.join(b + '\t' + n + '\n' for n, b in self.names.items()).encode()}
        self.files['SHA256SUMS'] = ''.join(evidence.digest(raw) + '  ' + name + '\n'
                                         for name, raw in self.files.items()).encode()
        archive(self.bundle, self.files)
        self.logs = {name: self.files[name] for name in
                     ('manifest.json', 'mock-parity.json', 'target-functions.tsv', 'SHA256SUMS')}
        self.logs.update({
            'logs/mock-abi.log': b'steam proxy: resolved 1156 functions\nPASS 11156 ABI checks\n',
            'logs/weak-dynsym.log': b'PASS dynsym: 1135 GLOBAL, 21 WEAK FUNC; exact final-link bindings/visibility\n',
            'logs/resolve.log': (''.join('RESOLVED ' + name + ' 0x1234\n' for name in self.names) +
                'PASS resolve: 1156/1156 targets; failures=0; zero Steam API calls\n').encode()})
        for mode in evidence.MODES:
            self.logs['logs/weak-' + mode + '.log'] = (
                'PASS weak ' + mode + ': 21/21 symbols; 105 checks; explicit handles retain mock targets\n').encode()
        for label, diagnostic in evidence.REJECTIONS.items():
            self.logs['logs/' + label + '.log'] = (diagnostic +
                (': target_0000' if label == 'missing_weak' else '') + '\n').encode()
        self.summaries = dict(mock='PASS mock: 1156 targets; 11156 ABI checks; 8 loader rejections',
            weak='PASS weak: 21 WEAK, 1135 GLOBAL; 4 Bionic load-scope cases; 420 checks',
            resolve='PASS resolve: 1156/1156 targets; failures=0; zero Steam API calls')
        rejection_lines = '\n'.join('PASS ' + label + ' (exit 127)' for label in evidence.REJECTIONS)
        for stage in evidence.STAGES:
            body = 'PASS bundle checksums\n'
            body += '\n'.join(self.summaries.values()) if stage == 'all' else self.summaries[stage]
            if stage in ('mock', 'all'):
                body += '\n' + rejection_lines
            if stage in ('resolve', 'all'):
                body += '\nPASS real-provider checksum: ' + self.provider_sha
            body += '\nPASS hardware stage=' + stage + '\n'
            (self.results / (stage + '-console.log')).write_text(body)
        self.observation = dict(schema_version=1, device='Steam Frame', context='creamlinux-poc',
            abi='arm64-v8a', android_api=30, provider_sha256=self.provider_sha,
            bundle_sha256=evidence.digest(self.bundle.read_bytes()), measured_at='2026-10-07T11:00:00Z',
            stage_exits={s: 0 for s in evidence.STAGES}, steam_api_calls_by_resolution_probe=0,
            production_game_files_modified=0, production_game_processes_injected=0)
        self.save()

    def save(self):
        archive(self.results / 'results.tar.gz', self.logs)
        self.observation['results_sha256'] = evidence.digest((self.results / 'results.tar.gz').read_bytes())
        self.observation['console_sha256'] = {s: evidence.digest((self.results / (s + '-console.log')).read_bytes())
                                               for s in evidence.STAGES}
        (self.results / 'observation.json').write_text(json.dumps(self.observation))

    def validate(self):
        return evidence.validate_hardware(self.bundle, self.results, self.provider_sha, self.proxy_sha)

    def test_complete_record_reports_exact_identity_and_scope(self):
        record = self.validate()
        self.assertEqual(record['provider_sha256'], self.provider_sha)
        self.assertEqual(record['proxy_sha256'], self.proxy_sha)
        self.assertEqual(record['function_targets'], 1156)
        self.assertEqual(record['steam_api_calls_by_resolution_probe'], 0)
        self.assertIn('No real Steam function forwarding calls', record['scope'])

    def test_different_provider_cannot_inherit_hardware_status(self):
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            evidence.validate_hardware(self.bundle, self.results, 'b' * 64, self.proxy_sha)

    def test_different_proxy_cannot_inherit_hardware_status(self):
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            evidence.validate_hardware(self.bundle, self.results, self.provider_sha, 'b' * 64)

    def test_nonzero_stage_is_rejected(self):
        for stage in evidence.STAGES:
            with self.subTest(stage=stage):
                self.observation['stage_exits'][stage] = 1
                self.save()
                with self.assertRaisesRegex(ValueError, 'did not exit zero'):
                    self.validate()
                self.observation['stage_exits'][stage] = 0

    def test_combined_pass_cannot_replace_missing_individual_stage(self):
        (self.results / 'weak-console.log').unlink()
        with self.assertRaises(OSError):
            self.validate()

    def test_transfer_metadata_must_match_bundle(self):
        self.logs['manifest.json'] = b'{}'
        self.save()
        with self.assertRaisesRegex(ValueError, 'metadata mismatch'):
            self.validate()

    def test_resolution_must_have_every_exact_target_name_once(self):
        self.logs['logs/resolve.log'] = self.logs['logs/resolve.log'].replace(b'RESOLVED target_0000', b'RESOLVED target_0001')
        self.save()
        with self.assertRaisesRegex(ValueError, 'resolution names'):
            self.validate()

    def test_null_resolution_is_rejected_even_with_pass_summary(self):
        self.logs['logs/resolve.log'] = self.logs['logs/resolve.log'].replace(b'0x1234', b'0x0', 1)
        self.save()
        with self.assertRaisesRegex(ValueError, 'resolution names'):
            self.validate()

    def test_changed_logs_fail_checksum_guard(self):
        (self.results / 'mock-console.log').write_text('PASS')
        with self.assertRaisesRegex(ValueError, 'console changed'):
            self.validate()

    def test_override_is_never_validation(self):
        with (self.results / 'resolve-console.log').open('a') as stream:
            stream.write('DEVELOPMENT OVERRIDE real-provider checksum\n')
        self.save()
        with self.assertRaisesRegex(ValueError, 'incomplete/unsafe'):
            self.validate()

    def test_loader_wrong_exit_is_rejected(self):
        path = self.results / 'mock-console.log'
        path.write_text(path.read_text().replace('missing_weak (exit 127)', 'missing_weak (exit 0)'))
        self.save()
        with self.assertRaisesRegex(ValueError, 'loader exit'):
            self.validate()

    def test_weak_scope_missing_checks_is_rejected(self):
        self.logs['logs/weak-strong-late.log'] = b'PASS weak strong-late\n'
        self.save()
        with self.assertRaisesRegex(ValueError, 'weak scope'):
            self.validate()

    def test_safety_counters_and_context_are_enforced(self):
        original = copy.deepcopy(self.observation)
        for key, value in [('context', 'steamlaunch-448280'), ('android_api', 21),
                           ('steam_api_calls_by_resolution_probe', 1),
                           ('production_game_files_modified', 1), ('production_game_processes_injected', 1)]:
            with self.subTest(key=key):
                self.observation = dict(original, **{key: value})
                self.save()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_bundle_corruption_rejected(self):
        self.files['libsteam_api.so'] = b'changed binary'
        archive(self.bundle, self.files)
        with self.assertRaises(ValueError):
            self.validate()

    def test_unsafe_archive_members_rejected_without_extraction(self):
        for name in ('../outside', '/absolute', 'a/../../outside'):
            with self.subTest(name=name):
                archive(self.bundle, {name: b'content'})
                with self.assertRaisesRegex(ValueError, 'unsafe archive'):
                    evidence.archive_files(self.bundle)
        self.assertFalse((self.root.parent / 'outside').exists())

    def test_duplicate_and_symlink_members_rejected(self):
        with tarfile.open(self.bundle, 'w') as tar:
            for _ in range(2):
                info = tarfile.TarInfo('same')
                tar.addfile(info, io.BytesIO())
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            evidence.archive_files(self.bundle)
        with tarfile.open(self.bundle, 'w') as tar:
            info = tarfile.TarInfo('link')
            info.type = tarfile.SYMTYPE
            info.linkname = '/outside'
            tar.addfile(info)
        with self.assertRaisesRegex(ValueError, 'nonregular'):
            evidence.archive_files(self.bundle)


class ArtifactStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = pathlib.Path(self.temp.name)
        self.sha = 'a' * 64
        self.manifest = dict(provider_sha256=self.sha,
            functions=[dict(name='fixture', binding='Global', other=0)], omitted_non_function_exports=[])
        from generate import emit_surface
        emit_surface(self.target, self.manifest['functions'])
        (self.target / 'manifest.json').write_text(json.dumps(self.manifest))
        self.result = dict(provider_sha256=self.sha, proxy_compatible=False,
            current_proxy=dict(compatible=False), target_specific_forwarding=dict(
                validated=False, generation_status='not_generated', hardware_validation_status='not_run',
                limitations=['Structural feasibility is not validated target compatibility.']))

    def attach(self, **kwargs):
        with mock.patch('generate_target_proxy.inspect_provider', return_value=self.manifest), \
             mock.patch('verify_target_proxy.verify', return_value=dict(
                 passed=True, provider_sha256=self.sha, proxy_sha256='b' * 64)):
            evidence.attach_evidence(self.result, '/fixture/provider', self.target, 'reader', **kwargs)

    def test_sources_only_remains_generated(self):
        self.attach()
        self.assertEqual(self.result['target_specific_forwarding']['generation_status'], 'generated')
        self.assertEqual(self.result['target_specific_forwarding']['hardware_validation_status'], 'not_run')

    def test_manifest_alone_cannot_claim_generated_surface(self):
        (self.target / 'stubs.S').unlink()
        with self.assertRaises(OSError):
            self.attach()

    def test_static_success_does_not_change_fixed_proxy_exit_semantics(self):
        (self.target / 'libsteam_api.so').write_bytes(b'fixture')
        self.attach()
        self.assertEqual(self.result['target_specific_forwarding']['generation_status'], 'locally_validated')
        self.assertFalse(self.result['proxy_compatible'])
        self.assertFalse(self.result['current_proxy']['compatible'])
        self.assertFalse(self.result['target_specific_forwarding']['validated'])

    def test_hardware_success_keeps_fixed_proxy_incompatible(self):
        (self.target / 'libsteam_api.so').write_bytes(b'fixture')
        with mock.patch.object(evidence, 'validate_hardware', return_value={'source': 'fixture logs'}):
            self.attach(bundle='bundle', results='results')
        self.assertEqual(self.result['target_specific_forwarding']['generation_status'], 'hardware_validated')
        self.assertFalse(self.result['current_proxy']['compatible'])
        self.assertFalse(self.result['target_specific_forwarding']['validated'])

    def test_manifest_for_another_provider_is_rejected(self):
        self.result['provider_sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.attach()

    def test_hardware_evidence_requires_built_proxy(self):
        with self.assertRaisesRegex(ValueError, 'requires a built proxy'):
            self.attach(bundle='bundle', results='results')

    def test_failed_static_parity_cannot_become_hardware_pass(self):
        (self.target / 'libsteam_api.so').write_bytes(b'fixture')
        with mock.patch('generate_target_proxy.inspect_provider', return_value=self.manifest), \
             mock.patch('verify_target_proxy.verify', return_value={'passed': False}):
            with self.assertRaisesRegex(ValueError, 'static proxy verification failed'):
                evidence.attach_evidence(self.result, '/fixture/provider', self.target, 'reader')


if __name__ == '__main__':
    unittest.main()
