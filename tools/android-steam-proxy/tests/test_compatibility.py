"""Compatibility policy and real ELF scanner integration, without loading ELFs."""
import pathlib
import sys
import json
import subprocess
import zipfile
import shutil
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from compatibility import evaluate, safe_token, SCOPE
import test_scan_consumers
from scan_consumers import Scanner, inspect_elf


def symbol(name, kind='Function'):
    return dict(name=name, symbol=name, type=kind, binding='Global', other=0)


def import_symbol(name, binding='Global'):
    return dict(name=name, symbol=name, binding=binding, defined=False)


def consumer_fixture(name='consumer.so', imports=(), needed=(), exports=(), literals=(),
                     raw=(), dynsym_strings=(), loaders=(), modules=(), markers=()):
    return dict(file=name, elf_format='elf64-littleaarch64', dynamic_symbols=list(imports),
        dt_needed=list(needed), soname=name, public_exports=list(exports),
        runtime_lookup_literal_candidates=list(literals), runtime_loader_imports=list(loaders),
        raw_exact_provider_export_strings=list(raw),
        provider_export_strings_explained_by_dynsym=list(dynsym_strings),
        provider_export_strings_explained_by_symtab=[], steam_module_strings=list(modules),
        steamworks_net_markers=list(markers), steam_related_strings=list(literals))


class PolicyTests(unittest.TestCase):
    def evaluate(self, exports=None, required=False, complete=True, arch='elf64-littleaarch64', supported=None):
        provider = dict(public_exports=exports or [symbol('SteamAPI_Test')],
                        elf_format=arch, elf_type='SharedObject (0x3)',
                        architecture='aarch64', inspection_complete=True, issues=[])
        consumers = dict(scan_complete=complete, elf_files_scanned=1, errors=[],
                         summary={'data': {'statically_required': required}},
                         files=[consumer_fixture(imports=[import_symbol('data')] if required else [],
                                                 needed=['libsteam_api.so'])])
        return evaluate(provider, consumers, supported or {'SteamAPI_Test'}, 'arm64-v8a')

    def test_all_functions_supported(self):
        r = self.evaluate()
        self.assertTrue(r['proxy_compatible'])
        self.assertEqual(r['supported_function_exports'], 1)

    def test_optional_nonfunction_exports(self):
        r = self.evaluate([symbol('SteamAPI_Test'), symbol('data', 'Object')])
        self.assertEqual(r['compatibility_scope'], SCOPE)
        self.assertEqual(r['unsupported_exports'], ['data'])
        self.assertEqual(r['required_unsupported_exports'], [])

    def test_required_nonfunction_export(self):
        r = self.evaluate([symbol('SteamAPI_Test'), symbol('data', 'Object')], required=True)
        self.assertFalse(r['proxy_compatible'])
        self.assertEqual(r['required_unsupported_exports'], ['data'])

    def test_unsupported_architecture(self):
        self.assertFalse(self.evaluate(arch='elf64-x86-64')['proxy_compatible'])

    def test_incomplete(self):
        self.assertIsNone(self.evaluate(complete=False)['proxy_compatible'])

    def test_missing_function_coverage(self):
        self.assertFalse(self.evaluate([symbol('new_function')])['proxy_compatible'])

    def test_missing_constructor_target(self):
        self.assertFalse(self.evaluate(supported={'SteamAPI_Test', 'missing'})['proxy_compatible'])

    def test_versioned_or_variant_function(self):
        for s in [symbol('SteamAPI_Test@V1'), dict(symbol('SteamAPI_Test'), other=128)]:
            self.assertFalse(self.evaluate([s])['proxy_compatible'])

    def test_reject_shell_metacharacters(self):
        for value in ['/data/app/a;touch /tmp/x', '/data/app/../x', '$(id)']:
            with self.assertRaises(ValueError):
                safe_token(value, path=True)


class EvidenceModelTests(unittest.TestCase):
    def report(self, exports, files, supported=None, complete=True):
        provider = dict(public_exports=exports, elf_format='elf64-littleaarch64',
                        elf_type='SharedObject', architecture='aarch64',
                        inspection_complete=True, issues=[])
        consumers = dict(files=files, scan_complete=complete,
                         elf_files_scanned=len(files), errors=[], summary={})
        return evaluate(provider, consumers, supported or {'SteamAPI_Test'}, 'arm64-v8a')

    def test_undefined_overlap_without_direct_dependency_is_unattributed(self):
        r = self.report([symbol('SteamAPI_Test'), symbol('data', 'Object')],
                        [consumer_fixture(imports=[import_symbol('data')])])
        self.assertEqual(r['required_unsupported_exports'], [])
        overlap = r['consumer_evidence']['files'][0]['provider_export_intersections'][0]
        self.assertFalse(overlap['exact_provider_established'])
        self.assertEqual(overlap['attribution'], 'unattributed provider-export overlap')

    def test_old_summary_alone_does_not_establish_provider(self):
        provider = dict(public_exports=[symbol('SteamAPI_Test'), symbol('data', 'Object')],
                        elf_format='elf64-littleaarch64', elf_type='SharedObject',
                        architecture='aarch64', inspection_complete=True, issues=[])
        consumers = dict(scan_complete=True, elf_files_scanned=1, errors=[],
                         summary={'data': {'statically_required': True}})
        self.assertEqual(evaluate(provider, consumers, {'SteamAPI_Test'}, 'arm64-v8a')
                         ['required_unsupported_exports'], [])

    def test_direct_needed_without_alternate_is_conservative_blocker(self):
        r = self.report([symbol('SteamAPI_Test'), symbol('data', 'Object')],
                        [consumer_fixture(imports=[import_symbol('data')], needed=['libsteam_api.so'])])
        self.assertEqual(r['required_unsupported_exports'], ['data'])
        self.assertEqual(r['consumer_evidence']['direct_libsteam_api_consumer_count'], 1)
        self.assertEqual(r['target_specific_forwarding']['assessment'], 'blocked')
        self.assertFalse(r['consumer_evidence']['files'][0]
                         ['provider_export_intersections'][0]['exact_provider_established'])

    def test_alternate_provider_prevents_hard_attribution_even_with_direct_needed(self):
        r = self.report([symbol('SteamAPI_Test'), symbol('data', 'Object')], [
            consumer_fixture(imports=[import_symbol('data')], needed=['libsteam_api.so', 'other.so']),
            consumer_fixture('other.so', exports=[symbol('data', 'Object')])])
        self.assertEqual(r['required_unsupported_exports'], [])
        overlap = r['consumer_evidence']['files'][0]['provider_export_intersections'][0]
        self.assertEqual(overlap['attribution'], 'ambiguous / alternate provider available')
        self.assertTrue(overlap['candidate_alternate_packaged_providers'][0]['directly_needed'])

    def test_job_simulator_all_19_libcxx_overlaps_are_not_hard_requirements(self):
        names = ['__cxa_free_exception', '_ZTVN10__cxxabiv117__class_type_infoE',
            '_ZNSt20bad_array_new_lengthC1Ev', '__cxa_begin_catch', '__cxa_allocate_exception',
            '_ZdlPv', '_ZNSt9exceptionD2Ev', '__emutls_get_address', '_ZTISt9exception',
            '_ZTVN10__cxxabiv120__si_class_type_infoE', '__cxa_end_catch', '_ZSt9terminatev',
            '_ZNSt20bad_array_new_lengthD1Ev', '_Znam', '__cxa_throw', '__gxx_personality_v0',
            '_Znwm', '_ZNKSt9exception4whatEv', '_ZTISt20bad_array_new_length']
        cxx_exports = [symbol(n, 'Object' if n.startswith(('_ZTI', '_ZTV')) else 'Function') for n in names]
        r = self.report([symbol('SteamAPI_Test'), *cxx_exports], [
            consumer_fixture(imports=[import_symbol(n) for n in names], needed=['libc++_shared.so']),
            consumer_fixture('libc++_shared.so', exports=cxx_exports)])
        self.assertEqual(r['required_unsupported_exports'], [])
        overlaps = r['consumer_evidence']['files'][0]['provider_export_intersections']
        self.assertEqual(len(overlaps), 19)
        self.assertTrue(all(s['candidate_alternate_packaged_providers'][0]['soname'] ==
                            'libc++_shared.so' for s in overlaps))

    def test_weak_import_does_not_require_nonfunction(self):
        r = self.report([symbol('SteamAPI_Test'), symbol('data', 'Object')], [
            consumer_fixture(imports=[import_symbol('data', 'Weak')], needed=['libsteam_api.so'])])
        self.assertEqual(r['required_unsupported_exports'], [])

    def test_runtime_evidence_without_dt_needed_is_separate(self):
        r = self.report([symbol('SteamAPI_Test'), symbol('new_function')], [consumer_fixture(
            literals=['SteamAPI_Test'], raw=['SteamAPI_Test'], loaders=['dlopen', 'dlsym'],
            modules=['steam_api'], markers=['com.rlabrecque.steamworks.net.dll'])])
        self.assertFalse(r['proxy_compatible'])
        self.assertEqual(r['required_unsupported_exports'], [])
        self.assertEqual(r['consumer_evidence']['direct_libsteam_api_consumer_count'], 0)
        self.assertEqual(r['runtime_resolution_evidence']['strong_candidate_count'], 1)
        target = r['target_specific_forwarding']
        self.assertEqual(target['assessment'], 'candidate')
        self.assertTrue(target['all_target_functions_structurally_forwardable'])
        self.assertFalse(target['validated'])

    def test_literal_without_loader_is_lower_confidence(self):
        r = self.report([symbol('SteamAPI_Test')],
                        [consumer_fixture(literals=['SteamAPI_Test'])])
        self.assertEqual(r['runtime_resolution_evidence']['files'][0]['confidence'], 'literal_evidence_only')
        self.assertEqual(r['target_specific_forwarding']['assessment'], 'inconclusive')

    def test_cpp_literal_with_dlsym_is_not_strong_steam_evidence(self):
        r = self.report([symbol('SteamAPI_Test'), symbol('_ZTIfoo', 'Object')],
                        [consumer_fixture(literals=['_ZTIfoo'], loaders=['dlsym'])])
        self.assertEqual(r['runtime_resolution_evidence']['strong_candidate_count'], 0)
        self.assertEqual(r['target_specific_forwarding']['assessment'], 'inconclusive')
        self.assertEqual(r['required_unsupported_exports'], [])

    def test_missing_proxy_targets_and_target_only_functions_are_distinct(self):
        r = self.report([symbol('SteamAPI_Test'), symbol('SteamAPI_New')],
                        [consumer_fixture()], {'SteamAPI_Test', 'SteamAPI_Old'})
        current = r['current_proxy']
        self.assertEqual(current['manifest_function_count'], 2)
        self.assertEqual(current['target_function_count'], 2)
        self.assertEqual(current['intersection_count'], 1)
        self.assertEqual(current['proxy_targets_absent_from_target'], ['SteamAPI_Old'])
        self.assertEqual(current['target_functions_not_forwarded'], ['SteamAPI_New'])
        self.assertFalse(current['compatible'])

    def test_nonfunction_exports_are_counted_and_listed(self):
        r = self.report([symbol('SteamAPI_Test'), symbol('data', 'Object'), symbol('tls', 'TLS')],
                        [consumer_fixture(needed=['libsteam_api.so'])])
        target = r['target_specific_forwarding']
        self.assertEqual(target['non_function_export_count'], 2)
        self.assertEqual(target['non_function_exports'], ['data', 'tls'])
        self.assertEqual(target['consumer_required_non_function_exports'], [])
        self.assertIn('functions only', target['limitations'][0])

    def test_weak_target_functions_need_binding_review(self):
        r = self.report([symbol('SteamAPI_Test'), dict(symbol('_Znwm'), binding='Weak')],
                        [consumer_fixture(needed=['libsteam_api.so'])])
        target = r['target_specific_forwarding']
        self.assertTrue(target['all_target_functions_structurally_forwardable'])
        self.assertEqual(target['weak_function_exports_requiring_binding_review'], ['_Znwm'])
        self.assertEqual(target['assessment'], 'inconclusive')

    def test_variant_pcs_structurally_blocks_target_specific_forwarding(self):
        r = self.report([dict(symbol('SteamAPI_Test'), other=128)], [consumer_fixture()])
        self.assertFalse(r['target_specific_forwarding']['all_target_functions_structurally_forwardable'])
        self.assertEqual(r['target_specific_forwarding']['assessment'], 'blocked')

    def test_other_abi_consumers_are_reported_but_cannot_complete_target_analysis(self):
        other = consumer_fixture('arm32.so', imports=[import_symbol('SteamAPI_Test')],
                                 needed=['libsteam_api.so'], literals=['SteamAPI_Test'], loaders=['dlsym'])
        other['elf_format'] = 'elf32-littlearm'
        r = self.report([symbol('SteamAPI_Test')], [other])
        self.assertIsNone(r['proxy_compatible'])
        self.assertEqual(r['consumer_evidence']['direct_libsteam_api_consumer_count'], 0)
        self.assertEqual(r['consumer_evidence']['undefined_steam_named_symbols'], [])
        self.assertEqual(r['runtime_resolution_evidence']['strong_candidate_count'], 0)
        self.assertFalse(r['consumer_evidence']['files'][0]['relevant_target_abi'])
        self.assertFalse(r['runtime_resolution_evidence']['files'][0]['relevant_target_abi'])
        self.assertEqual(r['target_specific_forwarding']['assessment'], 'inconclusive')

    def test_other_abi_alternate_is_ignored(self):
        alternate = consumer_fixture('arm32.so', exports=[symbol('data', 'Object')])
        alternate['elf_format'] = 'elf32-littlearm'
        r = self.report([symbol('SteamAPI_Test'), symbol('data', 'Object')], [
            consumer_fixture(imports=[import_symbol('data')], needed=['libsteam_api.so']), alternate])
        self.assertEqual(r['required_unsupported_exports'], ['data'])
        self.assertEqual(r['consumer_evidence']['ignored_other_abi_files'], ['arm32.so'])


@unittest.skipUnless(shutil.which('clang') and shutil.which('ld.lld') and
                     shutil.which('llvm-readelf'), 'requires LLVM')
class IntegrationTests(unittest.TestCase):
    setUp = test_scan_consumers.ScannerTests.setUp
    build = test_scan_consumers.ScannerTests.build
    def test_lepton_transfer_base_and_split_and_failure(self):
        provider = self.build('provider.so', 'int unusual_data; void SteamAPI_Test(void) {}',
                              '-Wl,-soname,libsteam_api.so')
        consumer = self.build('consumer.so', 'extern int unusual_data; int *p = &unusual_data;',
                              '-Wl,--no-as-needed', str(provider))
        for name, data in [('base', provider.read_bytes()), ('split', consumer.read_bytes())]:
            with zipfile.ZipFile(self.root / (name + '.apk'), 'w') as archive:
                archive.writestr('lib/arm64-v8a/lib' + name + '.so', data)
        cli = self.root / 'lepton'
        cli.write_text('#!' + sys.executable + '\n' +
            'import pathlib, sys\n' +
            'root = pathlib.Path(__file__).parent\n' +
            'args = sys.argv[3:]\n' +
            'if args == ["true"]: pass\n' +
            'elif args[:2] == ["pm", "path"]: print("package:/data/app/base.apk\\npackage:/data/app/split.apk")\n' +
            'elif args[0] == "cat": sys.stdout.buffer.write((root / pathlib.Path(args[1]).name).read_bytes())\n' +
            'else: sys.exit(1)\n')
        cli.chmod(0o700)
        request = dict(cli=str(cli), info=dict(context='steamlaunch-1', package='com.example',
            apk_path='/data/app/base.apk', steam_api_path='/data/app/provider.so', primary_abi='arm64-v8a'))
        script = pathlib.Path(__file__).resolve().parents[1] / 'compatibility.py'
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        result = subprocess.run([sys.executable, str(script)], input=json.dumps(request),
                                capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertTrue(report['analyzed'])
        self.assertFalse(report['proxy_compatible'])
        self.assertIn('unusual_data', report['required_unsupported_exports'])
        self.assertIn('Inspected 2 APK(s), 1 consumer ELF(s).', report['notes'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        (self.root / 'split.apk').unlink()
        result = subprocess.run([sys.executable, str(script)], input=json.dumps(request),
                                capture_output=True, text=True, check=True)
        self.assertIsNone(json.loads(result.stdout)['proxy_compatible'])

    def test_custom_unsupported_name_real_elf(self):
        provider = self.build('provider.so', 'int unusual_data; void SteamAPI_Test(void) {}',
                              '-Wl,-soname,libsteam_api.so')
        consumer = self.build('consumer.so', 'extern int unusual_data; int *p = &unusual_data;',
                              '-Wl,--no-as-needed', str(provider))
        original = inspect_elf('provider', provider, provider.read_bytes(), 'llvm-readelf')
        scanner = Scanner('llvm-readelf', ('unusual_data',))
        scanner.path(consumer)
        r = evaluate(original, scanner.report(), {'SteamAPI_Test'}, 'arm64-v8a')
        self.assertFalse(r['proxy_compatible'])
        self.assertIn('unusual_data', r['required_unsupported_exports'])

    def inspect_runtime(self, source, exports=('SteamAPI_Test',)):
        library = self.build('runtime.so', source)
        scanner = Scanner('llvm-readelf', names=(), runtime_names=exports)
        scanner.path(library)
        report = scanner.report()
        self.assertTrue(report['scan_complete'])
        return report

    def test_dynsym_name_and_loader_alone_are_not_runtime_literal(self):
        consumers = self.inspect_runtime('extern void SteamAPI_Test(void); '
            'extern void *dlsym(void *, const char *); '
            'void *use(void) { SteamAPI_Test(); return dlsym(0, "unrelated"); }')
        f = consumers['files'][0]
        self.assertIn('SteamAPI_Test', f['raw_exact_provider_export_strings'])
        self.assertIn('SteamAPI_Test', f['provider_export_strings_explained_by_dynsym'])
        self.assertEqual(f['runtime_lookup_literal_candidates'], [])
        self.assertEqual(f['runtime_loader_imports'], ['dlsym'])
        r = EvidenceModelTests().report([symbol('SteamAPI_Test')], consumers['files'])
        self.assertEqual(r['runtime_resolution_evidence']['strong_candidate_count'], 0)

    def test_exact_literal_with_dlopen_dlsym_and_android_loader(self):
        consumers = self.inspect_runtime('extern void *dlsym(void *, const char *); '
            'extern void *dlopen(const char *, int); '
            'extern void *android_dlopen_ext(const char *, int, void *); '
            'const char *marker = "com.rlabrecque.steamworks.net.dll"; '
            'void *use(void) { android_dlopen_ext("libsteam_api.so", 0, 0); '
            'return dlsym(dlopen("steam_api", 0), "SteamAPI_Test"); }')
        f = consumers['files'][0]
        self.assertEqual(f['runtime_lookup_literal_candidates'], ['SteamAPI_Test'])
        self.assertEqual(f['runtime_loader_imports'], ['android_dlopen_ext', 'dlopen', 'dlsym'])
        self.assertEqual(f['steam_module_strings'], ['libsteam_api.so', 'steam_api'])
        self.assertEqual(f['steamworks_net_markers'], ['com.rlabrecque.steamworks.net.dll'])
        self.assertEqual(f['dt_needed'], [])
        r = EvidenceModelTests().report([symbol('SteamAPI_Test')], consumers['files'])
        self.assertEqual(r['runtime_resolution_evidence']['strong_candidate_count'], 1)
        self.assertEqual(r['required_unsupported_exports'], [])

    def test_substring_is_not_exact_lookup_literal(self):
        f = self.inspect_runtime('const char *name = "SteamAPI_Test_suffix";')['files'][0]
        self.assertEqual(f['raw_exact_provider_export_strings'], [])
        self.assertEqual(f['runtime_lookup_literal_candidates'], [])

    def test_real_elf_libcxx_alternate_blocks_false_provider_attribution(self):
        provider = self.build('libsteam_api.so', 'void SteamAPI_Test(void) {} '
            'void __cxa_throw(void) {} int _ZTISt9exception;', '-Wl,-soname,libsteam_api.so')
        alternate = self.build('libc++_shared.so', 'void __cxa_throw(void) {} int _ZTISt9exception;',
            '-Wl,-soname,libc++_shared.so')
        consumer = self.build('consumer.so', 'extern void __cxa_throw(void); '
            'extern int _ZTISt9exception; int *p = &_ZTISt9exception; '
            'void use(void) { __cxa_throw(); }', '-Wl,--no-as-needed', str(provider), str(alternate))
        scanner = Scanner('llvm-readelf', names=())
        scanner.path(consumer)
        scanner.path(alternate)
        original = inspect_elf('provider', provider, provider.read_bytes(), 'llvm-readelf')
        r = evaluate(original, scanner.report(), {'SteamAPI_Test'}, 'arm64-v8a')
        self.assertEqual(r['required_unsupported_exports'], [])
        self.assertEqual(r['consumer_evidence']['direct_libsteam_api_consumer_count'], 1)
        overlaps = r['consumer_evidence']['files'][0]['provider_export_intersections']
        self.assertEqual(len(overlaps), 2)
        self.assertTrue(all(s['attribution'] == 'ambiguous / alternate provider available' for s in overlaps))


if __name__ == '__main__':
    unittest.main()
