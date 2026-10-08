"""Standalone CLI regression tests; fixture ELFs are inspected, never loaded."""
import contextlib
import hashlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import compatibility
import test_scan_consumers

SCRIPT = pathlib.Path(compatibility.__file__).resolve()
SCHEMA = set(compatibility.empty('test'))


class CLITests(unittest.TestCase):
    def run_cli(self, *args, stdin=None, env=None):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              input=stdin, capture_output=True, text=True, timeout=20, env=env)

    def assert_json(self, process, code):
        self.assertEqual(process.returncode, code, process.stderr + process.stdout)
        self.assertEqual(process.stderr, '')
        report = json.loads(process.stdout)
        self.assertEqual(set(report), SCHEMA)
        self.assertNotIn('Traceback', process.stdout)
        return report

    def test_help_does_not_read_open_stdin(self):
        for args in [('--help',), ('live', '--help'), ('files', '--help')]:
            with self.subTest(args=args):
                with subprocess.Popen([sys.executable, str(SCRIPT), *args], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                    # Leave the pipe open without supplying data or EOF.
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        self.fail('help blocked on stdin')
                    stdout, stderr = process.communicate()
                self.assertEqual(process.returncode, 0)
                self.assertIn(b'Exit codes:', stdout)
                self.assertEqual(stderr, b'')

    def test_legacy_malformed_json_still_exits_zero(self):
        report = self.assert_json(self.run_cli(stdin='not JSON'), 0)
        self.assertFalse(report['analyzed'])
        self.assertIsNone(report['proxy_compatible'])

    def test_legacy_missing_llvm_still_exits_zero(self):
        request = dict(cli='/missing', info=dict(context='steamlaunch-1', package='com.example'))
        report = self.assert_json(self.run_cli(stdin=json.dumps(request),
                                              env={**os.environ, 'PATH': ''}), 0)
        self.assertIn('llvm-readelf', report['notes'][0])

    def test_missing_llvm_exits_two(self):
        process = self.run_cli('files', '--steam-api', '/missing', '--apk', '/missing.apk',
                               '--abi', 'arm64-v8a', '--json', env={**os.environ, 'PATH': ''})
        report = self.assert_json(process, 2)
        self.assertIn('LLVM llvm-readelf unavailable', report['notes'][0])

    def test_explicitly_missing_readelf_exits_two(self):
        process = self.run_cli('files', '--steam-api', '/missing', '--apk', '/missing.apk',
                              '--abi', 'arm64-v8a', '--readelf', '/no/such/llvm-readelf', '--json')
        report = self.assert_json(process, 2)
        self.assertIn('/no/such/llvm-readelf', report['notes'][0])

    def test_explicit_tool_without_json_support_exits_two(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = pathlib.Path(directory) / 'invalid-readelf'
            tool.write_text('#!' + sys.executable + '\nprint("not LLVM JSON")\n')
            tool.chmod(0o700)
            report = self.assert_json(self.run_cli('files', '--steam-api', '/missing',
                '--apk', '/missing.apk', '--abi', 'arm64-v8a', '--readelf', tool, '--json'), 2)
            self.assertIn('required LLVM JSON', report['notes'][0])

    @unittest.skipUnless(shutil.which('readelf'), 'requires GNU readelf')
    def test_gnu_readelf_is_rejected(self):
        report = self.assert_json(self.run_cli('files', '--steam-api', '/missing',
            '--apk', '/missing.apk', '--abi', 'arm64-v8a', '--readelf', shutil.which('readelf'),
            '--json'), 2)
        self.assertIn('required LLVM JSON', report['notes'][0])

    def test_walkabout_human_format(self):
        report = compatibility.empty('test')
        report.update(analyzed=True, steam_api_found=True, architecture='ARM64 / arm64-v8a',
                      total_public_exports=1049, function_exports=1045,
                      supported_function_exports=1045, unsupported_exports=[
                          '__bss_start', '_end', '_edata', 'g_pSteamClientGameServer'],
                      proxy_compatible=True, compatibility_scope=compatibility.SCOPE,
                      notes=[compatibility.LIMITS, 'Inspected 1 APK(s), 14 consumer ELF(s).'])
        text = compatibility.format_result(report)
        for expected in ['Architecture:             ARM64 / arm64-v8a',
                         'Public exports:           1049', 'Function exports:         1045',
                         'Supported functions:      1045 / 1045',
                         'Unsupported exports:      4', 'Required unsupported:     none',
                         'Compatibility:            Compatible for observed static consumers',
                         'Consumer ELFs inspected:  14', 'Computed dlsym lookups and runtime-only behavior cannot be ruled out.']:
            self.assertIn(expected, text)

    def test_no_arguments_interactive_shows_help(self):
        with mock.patch.object(sys.stdin, 'isatty', return_value=True):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(compatibility.main([]), 2)
        self.assertIn('usage:', output.getvalue())


@unittest.skipUnless(shutil.which('clang') and shutil.which('ld.lld') and
                     shutil.which('llvm-readelf'), 'requires LLVM')
class CLIIntegrationTests(unittest.TestCase):
    run_cli = CLITests.run_cli
    assert_json = CLITests.assert_json

    @classmethod
    def setUpClass(cls):
        cls.fixture_temp = tempfile.TemporaryDirectory(prefix='compatibility-cli-fixtures-')
        cls.addClassCleanup(cls.fixture_temp.cleanup)
        cls.root = pathlib.Path(cls.fixture_temp.name)
        names = [s['name'] for s in json.loads(
            (SCRIPT.parent / 'generated/reference-manifest.json').read_text())['symbols']
                 if s['function_forwarding_candidate']]
        cls.provider = test_scan_consumers.ScannerTests.build(cls, 'libsteam_api.so',
            '\n'.join(f'void {name}(void) {{}}' for name in names) +
            '\nchar __bss_start, _end, _edata; void *g_pSteamClientGameServer;',
            '-Wl,-soname,libsteam_api.so')
        consumer = test_scan_consumers.ScannerTests.build(cls, 'consumer.so',
            'extern void SteamAPI_Init(void); void (*p)(void) = SteamAPI_Init;')
        required = test_scan_consumers.ScannerTests.build(cls, 'required.so',
            'extern void *g_pSteamClientGameServer; void **p = &g_pSteamClientGameServer;',
            '-Wl,--no-as-needed', str(cls.provider))
        for name, libraries in [('base', [cls.provider, consumer]), ('split', [required]),
                                ('empty', [cls.provider])]:
            with zipfile.ZipFile(cls.root / (name + '.apk'), 'w') as archive:
                for library in libraries:
                    archive.writestr('lib/arm64-v8a/' + library.name, library.read_bytes())
        cls.job_missing = {
            'SteamAPI_ISteamUtils_IsSteamRunningOnSteamDeck', 'SteamAPI_SteamApps_v008',
            'SteamAPI_SteamGameServerNetworkingSockets_SteamAPI_v012', 'SteamAPI_SteamGameServerUtils_v010',
            'SteamAPI_SteamInput_v006', 'SteamAPI_SteamMatchmakingServers_v002',
            'SteamAPI_SteamNetworkingSockets_SteamAPI_v012', 'SteamAPI_SteamRemotePlay_v003',
            'SteamAPI_SteamUtils_v010'}
        job_names = [n for n in names if n not in cls.job_missing] + [f'SteamAPI_New{i}' for i in range(120)]
        cls.job_provider = test_scan_consumers.ScannerTests.build(cls, 'job-provider.so',
            '\n'.join(f'void {name}(void) {{}}' for name in job_names) +
            '\n' + '\n'.join(f'int job_data_{i};' for i in range(209)), '-Wl,-soname,libsteam_api.so')
        runtime = test_scan_consumers.ScannerTests.build(cls, 'libil2cpp.so',
            'extern void *dlopen(const char *, int); extern void *dlsym(void *, const char *); '
            'const char *marker = "com.rlabrecque.steamworks.net.dll"; '
            'void *lookup(void) { return dlsym(dlopen("steam_api", 0), "SteamAPI_New0"); }')
        with zipfile.ZipFile(cls.root / 'job.apk', 'w') as archive:
            archive.writestr('lib/arm64-v8a/libsteam_api.so', cls.job_provider.read_bytes())
            archive.writestr('lib/arm64-v8a/libil2cpp.so', runtime.read_bytes())
        cls.fixture_root = cls.root

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='compatibility-cli-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.log = self.root / 'commands.jsonl'
        self.config_path = self.root / 'config.json'
        self.install_root = '/data/app/~~RANDOM==/com.example-TOKEN=='
        self.config = dict(root=str(self.fixture_root), install_root=self.install_root,
                           abi='arm64-v8a', apks=['base.apk'], libraries=['lib/arm64/libsteam_api.so'])
        self.cli = self.root / 'lepton'
        self.cli.write_text('#!' + sys.executable + '\n' + '''import json, pathlib, sys
root = pathlib.Path(__file__).parent
config = json.loads((root / 'config.json').read_text())
with (root / 'commands.jsonl').open('a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1:3] != ['exec', 'steamlaunch-1']:
    sys.exit(91)
args = sys.argv[3:]
install = config['install_root']
if args == ['true']:
    sys.exit(1 if config.get('stopped') else 0)
elif args == ['pm', 'path', 'com.example']:
    paths = config['apks']
    if config.get('changed') and (root / 'copied').exists():
        paths = ['changed.apk']
    for path in paths:
        print('package:' + install + '/' + path)
elif args == ['dumpsys', 'package', 'com.example']:
    if config.get('dumpsys_failed'): sys.exit(1)
    print('  primaryCpuAbi=' + config.get('metadata_abi', config['abi']))
elif args == ['getprop', 'ro.product.cpu.abi']:
    print(config['abi'])
elif args == ['find', install + '/lib', '-name', 'libsteam_api.so']:
    if config.get('find_failed'): sys.exit(1)
    for path in config['libraries']:
        print(install + '/' + path)
elif args[0] == 'cat' and args[1].startswith(install + '/'):
    (root / 'copied').touch()
    path = pathlib.Path(config['root']) / pathlib.Path(args[1]).name
    sys.stdout.buffer.write(path.read_bytes())
else:
    sys.exit(92)
''')
        self.cli.chmod(0o700)

    def files(self, *extra, apk='base.apk', json_output=True):
        return self.run_cli('files', '--steam-api', self.provider,
            '--apk', self.fixture_root / apk, '--abi', 'arm64-v8a',
            *(['--json'] if json_output else []), *extra)

    def live(self, *extra):
        self.config_path.write_text(json.dumps(self.config))
        return self.run_cli('live', '--lepton', self.cli, '--context', 'steamlaunch-1',
                            '--package', 'com.example', '--json', *extra)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_local_files_compatible_exit_zero_json_only_and_readonly(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.fixture_root.iterdir() if p.is_file()}
        report = self.assert_json(self.files(), 0)
        self.assertTrue(report['proxy_compatible'])
        self.assertEqual(report['function_exports'], 1045)
        self.assertEqual(report['total_public_exports'], 1049)
        self.assertEqual(report['supported_function_exports'], 1045)
        self.assertEqual(report['required_unsupported_exports'], [])
        self.assertEqual(report['compatibility_scope'], compatibility.SCOPE)
        self.assertEqual(report['current_proxy']['manifest_function_count'], 1045)
        self.assertEqual(report['current_proxy']['proxy_targets_absent_from_target'], [])
        self.assertEqual(report['target_specific_forwarding']['non_function_export_count'], 4)
        self.assertEqual(set(report['unsupported_exports']),
                         {'__bss_start', '_end', '_edata', 'g_pSteamClientGameServer'})
        self.assertIn('Inspected 1 APK(s), 1 consumer ELF(s).', report['notes'])
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in self.fixture_root.iterdir() if p.is_file()})
        self.assertFalse(self.log.exists())

    def test_job_style_current_proxy_exit_one_with_separate_feasibility(self):
        report = self.assert_json(self.files('--steam-api', self.job_provider, apk='job.apk'), 1)
        self.assertEqual(report['total_public_exports'], 1365)
        self.assertEqual(report['function_exports'], 1156)
        self.assertEqual(report['supported_function_exports'], 1036)
        current = report['current_proxy']
        self.assertEqual(current['manifest_function_count'], 1045)
        self.assertEqual(current['intersection_count'], 1036)
        self.assertEqual(set(current['proxy_targets_absent_from_target']), self.job_missing)
        self.assertEqual(len(current['target_functions_not_forwarded']), 120)
        self.assertFalse(report['proxy_compatible'])
        self.assertEqual(report['required_unsupported_exports'], [])
        self.assertEqual(report['consumer_evidence']['direct_libsteam_api_consumer_count'], 0)
        self.assertEqual(report['consumer_evidence']['undefined_steam_named_symbols'], [])
        self.assertEqual(report['runtime_resolution_evidence']['strong_candidate_count'], 1)
        target = report['target_specific_forwarding']
        self.assertEqual(target['assessment'], 'candidate')
        self.assertFalse(target['validated'])
        self.assertEqual(target['non_function_export_count'], 209)
        self.assertEqual(target['consumer_required_non_function_exports'], [])

    def test_human_output_sections_and_verbose_details(self):
        normal = self.files(json_output=False)
        detailed = self.files('--verbose', json_output=False)
        self.assertEqual(normal.returncode, 0)
        self.assertEqual(detailed.returncode, 0)
        for section in ('Steam API Target', 'Current Proxy', 'Static Consumer Evidence',
                        'Runtime Resolution Evidence', 'Target-Specific Forwarding Assessment', 'Limitations'):
            self.assertIn(section, normal.stdout)
        self.assertNotIn('  g_pSteamClientGameServer', normal.stdout)
        self.assertIn('  g_pSteamClientGameServer', detailed.stdout)
        self.assertIn('Static consumer details:', detailed.stdout)

    def test_json_with_verbose_is_still_pure_json(self):
        self.assert_json(self.files('--verbose'), 0)

    def test_artifact_status_defaults_do_not_inherit_local_builds(self):
        report = self.assert_json(self.files(), 0)
        target = report['target_specific_forwarding']
        self.assertEqual(target['generation_status'], 'not_generated')
        self.assertEqual(target['hardware_validation_status'], 'not_run')
        self.assertEqual(target['non_function_coverage'], 'omitted-unrequired')
        self.assertEqual(report['provider_sha256'], hashlib.sha256(self.provider.read_bytes()).hexdigest())

    def test_explicit_sources_only_artifact_reports_generated_and_keeps_exit_one(self):
        from generate_target_proxy import generate
        target = self.root / 'job-target'
        generate(self.job_provider, target, shutil.which('llvm-readelf'), sources_only=True)
        report = self.assert_json(self.files('--steam-api', self.job_provider,
            '--target-proxy-dir', target, apk='job.apk'), 1)
        self.assertEqual(report['target_specific_forwarding']['generation_status'], 'generated')
        self.assertEqual(report['target_specific_forwarding']['hardware_validation_status'], 'not_run')
        self.assertFalse(report['current_proxy']['compatible'])

    def test_stale_other_provider_artifact_is_operational_error(self):
        from generate_target_proxy import generate
        target = self.root / 'wrong-target'
        generate(self.job_provider, target, shutil.which('llvm-readelf'), sources_only=True)
        report = self.assert_json(self.files('--target-proxy-dir', target), 2)
        self.assertFalse(report['analyzed'])
        self.assertIn('does not match this provider', report['notes'][0])

    def test_incomplete_hardware_option_combinations_return_pure_json_exit_two(self):
        for args in [('--hardware-results', self.root), ('--hardware-bundle', self.root / 'bundle.tar.gz'),
                     ('--hardware-results', self.root, '--hardware-bundle', self.root / 'bundle.tar.gz')]:
            with self.subTest(args=args):
                report = self.assert_json(self.files(*args), 2)
                self.assertFalse(report['analyzed'])
                self.assertIn('requires --target-proxy-dir', report['notes'][0])

    def test_missing_artifact_is_operational_error_without_traceback(self):
        report = self.assert_json(self.files('--target-proxy-dir', self.root / 'missing'), 2)
        self.assertFalse(report['analyzed'])

    def test_required_nonfunction_reports_blocked_coverage(self):
        report = self.assert_json(self.files('--apk', self.fixture_root / 'split.apk'), 1)
        self.assertEqual(report['target_specific_forwarding']['non_function_coverage'], 'blocked')

    def test_files_does_not_invoke_lepton(self):
        args = ['files', '--steam-api', str(self.provider), '--apk',
                str(self.fixture_root / 'base.apk'), '--abi', 'arm64-v8a', '--json']
        with mock.patch.object(compatibility.Lepton, 'command', side_effect=AssertionError('Lepton')):
            with mock.patch.object(compatibility.Lepton, 'copy', side_effect=AssertionError('Lepton')):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(compatibility.main(args), 0)
        self.assertTrue(json.loads(output.getvalue())['proxy_compatible'])

    def test_default_cli_output_is_human_readable(self):
        process = self.files(json_output=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(process.stdout.startswith('Steam API Compatibility\n'))
        self.assertIn(compatibility.SCOPE, process.stdout)

    def test_multiple_apks_required_data_incompatible_exit_one(self):
        report = self.assert_json(self.files('--apk', self.fixture_root / 'split.apk'), 1)
        self.assertFalse(report['proxy_compatible'])
        self.assertEqual(report['required_unsupported_exports'], ['g_pSteamClientGameServer'])
        self.assertIn('Inspected 2 APK(s), 2 consumer ELF(s).', report['notes'])

    def test_explicit_valid_readelf(self):
        self.assert_json(self.files('--readelf', shutil.which('llvm-readelf')), 0)

    def test_unsupported_abi_incompatible_exit_one(self):
        report = self.assert_json(self.files('--abi', 'x86_64'), 1)
        self.assertFalse(report['proxy_compatible'])
        self.assertEqual(report['architecture'], 'ARM64 / x86_64')

    def test_no_consumers_incomplete_exit_two(self):
        report = self.assert_json(self.files(apk='empty.apk'), 2)
        self.assertIsNone(report['proxy_compatible'])
        self.assertIn('Inspected 1 APK(s), 0 consumer ELF(s).', report['notes'])

    def test_incomplete_takes_precedence_over_incompatible(self):
        report = self.assert_json(self.files('--abi', 'x86_64', apk='empty.apk'), 2)
        self.assertFalse(report['proxy_compatible'])

    def test_missing_local_apk_operational_error_exit_two(self):
        report = self.assert_json(self.files(apk='missing.apk'), 2)
        self.assertFalse(report['analyzed'])

    def test_bad_local_provider_operational_error_exit_two(self):
        bad = self.root / 'bad.so'
        bad.write_bytes(b'not ELF')
        report = self.assert_json(self.files('--steam-api', bad), 2)
        self.assertFalse(report['analyzed'])

    def test_live_discovery_matches_files_and_uses_only_readonly_argv(self):
        report = self.assert_json(self.live(), 0)
        self.assertEqual(report, self.assert_json(self.files(), 0))
        prefix = ['exec', 'steamlaunch-1']
        root = self.install_root
        self.assertEqual(self.commands(), [prefix + args for args in [
            ['true'], ['pm', 'path', 'com.example'], ['dumpsys', 'package', 'com.example'],
            ['find', root + '/lib', '-name', 'libsteam_api.so'],
            ['cat', root + '/lib/arm64/libsteam_api.so'], ['cat', root + '/base.apk'],
            ['pm', 'path', 'com.example']]])

    def test_live_multiple_apks(self):
        self.config['apks'].append('split.apk')
        report = self.assert_json(self.live(), 1)
        self.assertIn('g_pSteamClientGameServer', report['required_unsupported_exports'])
        self.assertIn('Inspected 2 APK(s), 2 consumer ELF(s).', report['notes'])

    def test_live_abi_getprop_fallback(self):
        for config in [dict(metadata_abi='null'), dict(dumpsys_failed=True)]:
            with self.subTest(config=config):
                self.config.update(config)
                self.assert_json(self.live(), 0)
                self.assertIn(['exec', 'steamlaunch-1', 'getprop', 'ro.product.cpu.abi'], self.commands())

    def test_live_not_running(self):
        self.config['stopped'] = True
        report = self.assert_json(self.live(), 2)
        self.assertIn('not running', report['notes'][0])
        self.assertEqual(self.commands(), [['exec', 'steamlaunch-1', 'true']])

    def test_live_no_apk(self):
        self.config['apks'] = []
        report = self.assert_json(self.live(), 2)
        self.assertIn('no APK', report['notes'][0])

    def test_live_missing_steam_api(self):
        self.config['libraries'] = []
        report = self.assert_json(self.live(), 2)
        self.assertIn('no installed libsteam_api.so', report['notes'][0])
        self.assertFalse(any('cat' in command for command in self.commands()))

    def test_live_find_failure(self):
        self.config['find_failed'] = True
        report = self.assert_json(self.live(), 2)
        self.assertIn('Cannot discover libsteam_api.so', report['notes'][0])
        self.assertFalse(any('sh' in command for command in self.commands()))

    def test_live_unsupported_abi(self):
        self.config['abi'] = 'x86_64'
        self.assertFalse(self.assert_json(self.live(), 1)['proxy_compatible'])

    def test_live_missing_abi(self):
        self.config['abi'] = 'null'
        report = self.assert_json(self.live(), 2)
        self.assertIn('primary ABI is unavailable', report['notes'][0])

    def test_live_changed_paths_incomplete(self):
        self.config['changed'] = True
        report = self.assert_json(self.live(), 2)
        self.assertTrue(any('changed during analysis' in note for note in report['notes']))

    def test_live_ambiguous_library_paths(self):
        self.config['libraries'] = ['lib/one/libsteam_api.so', 'lib/two/libsteam_api.so']
        report = self.assert_json(self.live(), 2)
        self.assertIn('Ambiguous', report['notes'][0])

    def test_live_prefers_primary_abi_library(self):
        self.config['libraries'].append('lib/arm/libsteam_api.so')
        self.assert_json(self.live(), 0)
        self.assertIn(['exec', 'steamlaunch-1', 'cat',
                       self.install_root + '/lib/arm64/libsteam_api.so'], self.commands())

    def test_live_unsafe_tokens_rejected_before_exec(self):
        for option, value in [('--context', 'steamlaunch-1;id'), ('--package', '$(id)')]:
            with self.subTest(option=option):
                report = self.assert_json(self.live(option, value), 2)
                self.assertIn('refusing ambiguous Lepton arguments', report['notes'][0])
                self.assertFalse(self.log.exists())

    def test_live_unsafe_discovery_path_rejected_before_copy(self):
        self.config['libraries'] = ['lib/../libsteam_api.so']
        report = self.assert_json(self.live(), 2)
        self.assertIn('refusing ambiguous Lepton arguments', report['notes'][0])
        self.assertFalse(any('cat' in command for command in self.commands()))

    def test_legacy_valid_request_result_and_exit_unchanged(self):
        self.config_path.write_text(json.dumps(self.config))
        request = dict(cli=str(self.cli), info=dict(context='steamlaunch-1', package='com.example',
            apk_path=self.install_root + '/base.apk',
            steam_api_path=self.install_root + '/lib/arm64/libsteam_api.so', primary_abi='arm64-v8a'))
        report = self.assert_json(self.run_cli(stdin=json.dumps(request)), 0)
        self.assertEqual(report, self.assert_json(self.files(), 0))
        self.assertFalse(any('dumpsys' in command or 'find' in command for command in self.commands()))
        self.config['apks'].append('split.apk')
        self.config_path.write_text(json.dumps(self.config))
        self.assertFalse(self.assert_json(self.run_cli(stdin=json.dumps(request)), 0)['proxy_compatible'])
        self.config['stopped'] = True
        self.config_path.write_text(json.dumps(self.config))
        self.assertIsNone(self.assert_json(self.run_cli(stdin=json.dumps(request)), 0)['proxy_compatible'])


if __name__ == '__main__':
    unittest.main()
