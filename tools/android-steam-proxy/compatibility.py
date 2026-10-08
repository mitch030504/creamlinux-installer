#!/usr/bin/env python3
"""Read-only host analysis. Never loads native libraries or executes Steam APIs."""
import argparse
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent / 'tests'))
from scan_consumers import Scanner, inspect_elf, steam_named

SCOPE = 'Compatible for observed static consumers'
LIMITS = ('Computed dlsym lookups and runtime-only behavior cannot be ruled out. '
          'Scope is native ELF consumers observed in the current base/split APKs, '
          'not downloaded code, system libraries, or universal game compatibility.')


def empty(note):
    return dict(analyzed=False, steam_api_found=False, architecture=None,
                total_public_exports=None, function_exports=None,
                supported_function_exports=None, unsupported_exports=[],
                required_unsupported_exports=[], proxy_compatible=None,
                compatibility_scope=None, notes=[note, LIMITS], current_proxy=None,
                consumer_evidence=None, runtime_resolution_evidence=None,
                target_specific_forwarding=None, provider_sha256=None)


def analysis_complete(provider, consumers):
    return (provider['inspection_complete'] and consumers['scan_complete']
            and consumers['elf_files_scanned'] > 0 and bool(provider['public_exports'])
            and ('files' not in consumers or any(
                f['elf_format'] == provider['elf_format'] for f in consumers['files'])))


def function_candidate(symbol, allow_weak=False):
    """Fixed proxy uses GLOBAL; provider-driven generation also preserves WEAK."""
    bindings = ('Global', 'Weak') if allow_weak else ('Global',)
    return (symbol['type'] == 'Function' and symbol['binding'] in bindings
            and symbol['other'] == 0
            and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', symbol['name']) is not None)


def consumer_model(provider, consumers):
    """Bounded linkage inference, never a claim about Android's actual binding."""
    exports = {s['symbol']: s for s in provider['public_exports']}
    files = consumers.get('files', [])
    relevant = [f for f in files if f['elf_format'] == provider['elf_format']]
    alternate_index = {}
    for file in files:
        for exported in file['public_exports']:
            alternate_index.setdefault(exported['symbol'], []).append(file)
    static, runtime, required = [], [], set()
    for file in files:
        relevant_abi = file['elf_format'] == provider['elf_format']
        imports = [s for s in file['dynamic_symbols'] if not s['defined'] and s['symbol']]
        direct = 'libsteam_api.so' in file['dt_needed']
        intersections = []
        for imported in imports:
            name = imported['symbol']
            if name not in exports:
                continue
            alternates = [dict(file=other['file'], soname=other['soname'],
                               directly_needed=other['soname'] in file['dt_needed'])
                          for other in alternate_index.get(name, []) if other is not file
                          and other['elf_format'] == file['elf_format']]
            # A direct dependency plus a non-weak exact-name import, with no
            # observed alternate, is a conservative unsupported-export blocker.
            # This still does not establish the runtime provider: unobserved
            # system definitions, load scopes and interposition remain unknown.
            hard = (relevant_abi and direct and imported['binding'] not in ('Weak', 'Local')
                    and imported['name'] == exports[name]['name'] and not alternates)
            if hard:
                required.add(exports[name]['name'])
            intersections.append(dict(symbol=name, binding=imported['binding'],
                candidate_alternate_packaged_providers=alternates,
                attribution=('ambiguous / alternate provider available' if alternates else
                             'direct dependency / no alternate observed' if direct else
                             'unattributed provider-export overlap'),
                conservative_steam_requirement=hard, exact_provider_established=False))
        static.append(dict(file=file['file'], relevant_target_abi=relevant_abi, dt_needed=file['dt_needed'],
            directly_needs_libsteam_api=direct,
            undefined_steam_named_symbols=sorted({s['name'] for s in imports if steam_named(s['symbol'])}),
            provider_export_intersections=sorted(intersections, key=lambda s: s['symbol'])))
        literals = file['runtime_lookup_literal_candidates']
        loaders = file['runtime_loader_imports']
        hints = bool(any(steam_named(n) for n in literals) or file['steam_module_strings']
                     or file['steamworks_net_markers'])
        confidence = ('strong_candidate' if hints and 'dlsym' in loaders else
                      'candidate' if hints and loaders else
                      'literal_evidence_only' if hints or literals else 'no_runtime_lookup_evidence')
        runtime.append(dict(file=file['file'], relevant_target_abi=relevant_abi, confidence=confidence,
            runtime_loader_imports=loaders,
            steam_related_string_count=len(file['steam_related_strings']),
            steam_related_strings=file['steam_related_strings'],
            steam_module_strings=file['steam_module_strings'],
            steamworks_net_markers=file['steamworks_net_markers'],
            raw_exact_provider_export_strings=file['raw_exact_provider_export_strings'],
            provider_export_strings_explained_by_dynsym=file['provider_export_strings_explained_by_dynsym'],
            provider_export_strings_explained_by_symtab=file['provider_export_strings_explained_by_symtab'],
            runtime_lookup_literal_candidates=literals,
            steam_named_runtime_lookup_literal_candidates=[n for n in literals if steam_named(n)],
            non_function_runtime_lookup_literal_candidates=[n for n in literals
                if n in exports and exports[n]['type'] != 'Function']))
    return dict(
        consumer_elf_count=len(files), relevant_abi_consumer_count=len(relevant),
        ignored_other_abi_files=[f['file'] for f in files if f not in relevant],
        direct_libsteam_api_consumer_count=sum(f['directly_needs_libsteam_api']
                                             for f in static if f['relevant_target_abi']),
        undefined_steam_named_symbols=sorted({n for f in static if f['relevant_target_abi']
                                             for n in f['undefined_steam_named_symbols']}),
        conservative_steam_requirements=sorted(required), files=static,
        attribution_policy='Non-weak exact-name import plus direct DT_NEEDED libsteam_api.so '
            'and no alternate packaged export is a bounded conservative requirement. '
            'Undefined overlaps alone are unattributed. Alternate providers make attribution '
            'ambiguous, regardless of DT_NEEDED. Actual Android binding is not established; '
            'system providers, transitive dependencies and load scopes remain unknown.'), dict(
        strong_candidate_count=sum(f['confidence'] == 'strong_candidate'
                                   for f in runtime if f['relevant_target_abi']),
        files=runtime,
        interpretation='Strings are evidence, never hard requirements or proof of individual '
            'dlsym calls. Candidates exclude names in the consumer dynamic/regular symbol '
            'tables and strings located in symbol/string/debug tables. Loader imports '
            'strengthen confidence only when Steam literals or markers are also observed.'), required


def evaluate(provider, consumers, supported, abi):
    result = empty(LIMITS)
    result['notes'] = [LIMITS, 'Coverage is against the existing generated proxy manifest.']
    exports = provider['public_exports']
    functions = [s for s in exports if s['type'] == 'Function']
    function_names = {s['name'] for s in functions}
    structurally_supported = [s for s in functions if function_candidate(s)]
    covered = [s for s in structurally_supported if s['name'] in supported]
    covered_names = {s['name'] for s in covered}
    unsupported = sorted(s['name'] for s in exports if s not in covered)
    static, runtime, requirements = consumer_model(provider, consumers)
    for file in runtime['files']:
        file['raw_exact_provider_function_strings'] = sorted(
            set(file['raw_exact_provider_export_strings']) & function_names)
        file['raw_exact_target_only_function_strings'] = sorted(
            set(file['raw_exact_provider_function_strings']) - supported)
        file['target_only_steam_named_runtime_lookup_literal_candidates'] = sorted(
            set(file['steam_named_runtime_lookup_literal_candidates']) & (function_names - supported))
    required = sorted(set(unsupported) & requirements)
    architecture_ok = (provider['elf_format'] == 'elf64-littleaarch64'
                       and 'SharedObject' in provider['elf_type'] and abi == 'arm64-v8a')
    complete = analysis_complete(provider, consumers)
    result.update(analyzed=True, steam_api_found=True,
                  architecture=f"{'ARM64' if provider['architecture'] == 'aarch64' else provider['architecture']} / {abi}",
                  total_public_exports=len(exports), function_exports=len(functions),
                  supported_function_exports=len(covered), unsupported_exports=unsupported,
                  required_unsupported_exports=required, consumer_evidence=static,
                  runtime_resolution_evidence=runtime)
    absent = supported - function_names
    missing_targets = supported - covered_names
    if missing_targets:
        result['notes'].append(f'Existing proxy requires {len(missing_targets)} missing or unsupported function target(s).')
    if not architecture_ok or required or len(covered) != len(functions) or missing_targets:
        result['proxy_compatible'] = False
        result['notes'].append('Unsupported architecture/ABI, function coverage, or conservatively required export.')
    elif complete:
        result['proxy_compatible'] = True
        result['compatibility_scope'] = SCOPE
    result['current_proxy'] = dict(
        manifest_function_count=len(supported), target_function_count=len(functions),
        intersection_count=len(supported & function_names),
        supported_function_count=len(covered),
        target_functions_not_forwarded=sorted(function_names - covered_names),
        target_functions_absent_from_manifest=sorted(function_names - supported),
        proxy_targets_absent_from_target=sorted(absent),
        proxy_targets_present_but_structurally_unsupported=sorted(missing_targets - absent),
        architecture_abi_supported=architecture_ok, compatible=result['proxy_compatible'])
    nonfunctions = sorted(s['name'] for s in exports if s['type'] != 'Function')
    required_nonfunctions = sorted(set(nonfunctions) & requirements)
    structural_blockers = sorted(s['name'] for s in functions if not function_candidate(s, allow_weak=True))
    binding_review = sorted(s['name'] for s in functions if s['binding'] == 'Weak')
    meaningful = (static['direct_libsteam_api_consumer_count'] or
                  static['undefined_steam_named_symbols'] or
                  any(f['relevant_target_abi'] and f['confidence'] in ('strong_candidate', 'candidate')
                      for f in runtime['files']))
    runtime_nonfunctions = sorted({n for f in runtime['files']
                                   if f['relevant_target_abi']
                                   for n in f['non_function_runtime_lookup_literal_candidates']})
    state = ('blocked' if not architecture_ok or structural_blockers or required_nonfunctions else
             'inconclusive' if not complete or not meaningful or runtime_nonfunctions or binding_review else 'candidate')
    reasons = []
    if not architecture_ok:
        reasons.append('Target architecture/ABI is outside the AArch64 shared-library mechanism.')
    if structural_blockers:
        reasons.append(f'{len(structural_blockers)} function export(s) fail structural constraints.')
    if required_nonfunctions:
        reasons.append(f'{len(required_nonfunctions)} non-function export(s) have conservative static requirements.')
    if not complete:
        reasons.append('Provider or target-ABI consumer analysis is incomplete.')
    if not meaningful:
        reasons.append('Insufficient Steam linkage/runtime evidence to assess observed consumer use.')
    if runtime_nonfunctions:
        reasons.append(f'{len(runtime_nonfunctions)} non-function literal candidate(s) need runtime investigation.')
    if binding_review:
        reasons.append(f'{len(binding_review)} weak function export(s) need a binding/interposition policy.')
    if state == 'candidate':
        reasons.append('Function shapes are forwardable; no non-function requirement was observed. '
                       'Target-specific behavior remains unvalidated.')
    result['target_specific_forwarding'] = dict(
        assessment=state, assessment_reasons=reasons, validated=False, target_function_export_count=len(functions),
        generation_status='not_generated', local_validation_status='not_run',
        hardware_validation_status='not_run', binding_validation_status='not_run', validation_evidence=None,
        non_function_coverage=('blocked' if required_nonfunctions else
            'unknown' if not complete or runtime_nonfunctions else
            'omitted-unrequired' if nonfunctions else 'complete'),
        non_function_export_count=len(nonfunctions), non_function_exports=nonfunctions,
        all_target_functions_structurally_forwardable=architecture_ok and not structural_blockers,
        structurally_unsupported_function_exports=structural_blockers,
        weak_function_exports_requiring_binding_review=binding_review,
        consumer_required_non_function_exports=required_nonfunctions,
        runtime_non_function_literal_candidates=runtime_nonfunctions,
        non_function_requirement_evidence=('conservative static requirement observed' if required_nonfunctions else
            'runtime literal evidence only; requirement unknown' if runtime_nonfunctions else
            'no requirement observed in inspected consumers'),
        limitations=['The existing AArch64 trampoline mechanism forwards functions only; '
                    'non-function storage, TLS, aliases and identity need separate consideration.',
                    'The target-specific generator preserves GLOBAL and WEAK bindings. Weak '
                    'interposition still needs provider/proxy-specific validation on Bionic.',
                    'Structural feasibility is not validated target compatibility. Generated artifacts '
                    'and hardware evidence must be supplied explicitly. Computed runtime lookups remain unknown.'])
    if not complete:
        result['notes'].append('Analysis incomplete; a positive compatibility conclusion is unavailable.')
        if not static['relevant_abi_consumer_count']:
            result['notes'].append('No consumer ELF matching the target architecture was inspected.')
    result['notes'].extend(str(e) for e in consumers['errors'])
    result['notes'].extend(provider['issues'])
    return result


def safe_token(value, path=False):
    pattern = r'/data/app/[A-Za-z0-9_./+=~@%-]+' if path else r'[A-Za-z0-9_.-]+'
    if not value or not re.fullmatch(pattern, value) or '..' in value.split('/'):
        raise ValueError('Unrecognized package/context/path; refusing ambiguous Lepton arguments')
    return value


class Lepton:
    """Read-only transport; every command uses an argv array, never a shell."""
    def __init__(self, cli, context, package):
        self.cli = cli
        self.context = safe_token(context)
        self.package = safe_token(package)

    def command(self, *args):
        return subprocess.run([self.cli, 'exec', self.context, *args], check=True,
                              capture_output=True, text=True, timeout=30).stdout

    def paths(self):
        lines = self.command('pm', 'path', self.package).splitlines()
        if not lines:
            raise ValueError('Package has no APK paths')
        if any(not line.startswith('package:') for line in lines):
            raise ValueError('Incomplete pm path response')
        paths = sorted(set(safe_token(line[8:].strip(), path=True) for line in lines))
        if not all(p.endswith('.apk') for p in paths):
            raise ValueError('Package APK list incomplete')
        return paths

    def copy(self, source, target):
        safe_token(source, path=True)
        with target.open('wb') as stream:
            subprocess.run([self.cli, 'exec', self.context, 'cat', source], stdout=stream,
                           stderr=subprocess.PIPE, check=True, timeout=120)

    def discover(self, apks):
        bases = [p for p in apks if pathlib.PurePosixPath(p).name == 'base.apk']
        if len(bases) != 1:
            raise ValueError('Package must have exactly one base.apk')
        root = safe_token(str(pathlib.PurePosixPath(bases[0]).parent), path=True)
        if any(str(pathlib.PurePosixPath(p).parent) != root for p in apks):
            raise ValueError('Package APKs have inconsistent install roots')
        try:
            abi = parse_abi(self.command('dumpsys', 'package', self.package))
        except subprocess.CalledProcessError:
            abi = None
        if abi is None:
            abi = parse_abi(self.command('getprop', 'ro.product.cpu.abi'))
        if abi is None:
            raise ValueError('Package primary ABI is unavailable')
        try:
            output = self.command('find', root + '/lib', '-name', 'libsteam_api.so')
        except subprocess.CalledProcessError as error:
            raise ValueError('Cannot discover libsteam_api.so in package install root') from error
        libraries = sorted(set(safe_token(p.strip(), path=True)
                               for p in output.splitlines() if p.strip()))
        if any(not p.startswith(root + '/') or
               pathlib.PurePosixPath(p).name != 'libsteam_api.so' for p in libraries):
            raise ValueError('Unexpected Steam API discovery path')
        abi_dir = {'arm64-v8a': 'arm64', 'armeabi-v7a': 'arm', 'armeabi': 'arm',
                   'x86_64': 'x86_64', 'x86': 'x86', 'riscv64': 'riscv64'}.get(abi)
        preferred = [p for p in libraries if p == f'{root}/lib/{abi_dir}/libsteam_api.so']
        candidates = preferred or libraries
        if not candidates:
            raise ValueError('Package has no installed libsteam_api.so')
        if len(candidates) != 1:
            raise ValueError('Ambiguous libsteam_api.so paths for package primary ABI')
        return dict(apk_path=bases[0], steam_api_path=candidates[0], primary_abi=abi)


def parse_abi(output):
    for match in re.finditer(r'primary\s*(?:cpu\s*)?abi\s*[:=]\s*([A-Za-z0-9_-]+)',
                             output, re.IGNORECASE):
        if match[1].lower() not in ('null', 'none'):
            return match[1]
    for line in output.splitlines():
        if line.strip() in ('arm64-v8a', 'armeabi-v7a', 'armeabi', 'x86_64', 'x86', 'riscv64'):
            return line.strip()
    return None


def analyze_files(library, apks, abi, readelf, details=None, after_scan=None, prepare_apk=None):
    """Single provider/scanner/policy path for local, live and legacy requests."""
    provider = inspect_elf('installed libsteam_api.so', library, library.read_bytes(), readelf)
    manifest = json.loads((pathlib.Path(__file__).parent / 'generated/reference-manifest.json').read_text())
    supported = {s['name'] for s in manifest['symbols'] if s['function_forwarding_candidate']}
    # Full dynamic symbols support linkage inference; exact runtime strings are
    # scanned once for all exports. Legacy substring lists are unnecessary here.
    scanner = Scanner(readelf, names=(), runtime_names=tuple(s['name'] for s in provider['public_exports']))
    for index, apk in enumerate(apks):
        if prepare_apk:
            apk = prepare_apk(index, apk)
        start = len(scanner.files)
        scanner.path(apk)
        # Stable logical APK indices keep live temporary paths out of results
        # and make the same base/split snapshot comparable across entry points.
        for file in scanner.files[start:]:
            file['file'] = f'apk[{index}]' + file['file'][file['file'].index('!/') :]
    if after_scan:
        after_scan(scanner)
    # Provider definitions/self references do not represent external consumers.
    scanner.files = [f for f in scanner.files if f['sha256'] != provider['sha256']]
    consumers = scanner.report()
    if details is not None:
        details['complete'] = analysis_complete(provider, consumers)
    result = evaluate(provider, consumers, supported, abi)
    result['provider_sha256'] = provider['sha256']
    if details is not None:
        details['provider_path'] = library
    result['notes'].append(f"Inspected {len(apks)} APK(s), {len(scanner.files)} consumer ELF(s).")
    return result


def analyze(request, scratch, readelf=None, details=None, discover=False):
    info = request['info']
    lepton = Lepton(request['cli'], info['context'], info['package'])
    readelf = readelf or discover_readelf()
    if not readelf:
        return empty('Host llvm-readelf is unavailable; provide a bundled reader via CREAMLINUX_LLVM_READELF.')
    # Successful exec is authoritative; lepton ps is deliberately not consulted.
    try:
        lepton.command('true')
    except subprocess.SubprocessError as error:
        raise ValueError('Lepton context is not running or its exec probe failed') from error
    apks = lepton.paths()
    if discover:
        info = lepton.discover(apks)
    if info['apk_path'] not in apks:
        raise ValueError('Package paths changed or APK list incomplete; refresh and retry')
    library = scratch / 'provider.so'
    lepton.copy(info['steam_api_path'], library)

    def prepare_apk(index, source):
        target = scratch / f'package-{index}.apk'
        lepton.copy(source, target)
        return target

    def recheck(scanner):
        if lepton.paths() != apks:
            scanner.error('package', 'Package paths changed during analysis')

    return analyze_files(library, apks, info['primary_abi'], readelf, details, recheck, prepare_apk)


def discover_readelf(selected=None):
    """Explicit choice fails closed; bundled reader precedes host discovery."""
    choice = selected or os.environ.get('CREAMLINUX_LLVM_READELF')
    if choice:
        return shutil.which(choice)
    bundled = pathlib.Path(__file__).parent / 'runtime/bin/llvm-readelf'
    if bundled.is_file():
        return shutil.which(str(bundled))
    return shutil.which('llvm-readelf')


def select_readelf(selected, scratch):
    readelf = discover_readelf(selected)
    if not readelf:
        raise ValueError(f"LLVM llvm-readelf unavailable: {selected or 'llvm-readelf'}; "
                         'provide a bundled LLVM reader via --readelf or CREAMLINUX_LLVM_READELF')
    # A minimal sectionless ELF validates the exact scanner options and JSON
    # structure without running or loading a native library. Its incomplete
    # inspection is expected; only tool/protocol support is being checked here.
    probe = scratch / 'readelf-probe.so'
    probe.write_bytes(b'\x7fELF\x02\x01\x01' + bytes(9) +
                      struct.pack('<HHIQQQIHHHHHH', 3, 183, 1, 0, 0, 0,
                                  0, 64, 56, 0, 64, 0, 0))
    try:
        inspect_elf('LLVM JSON probe', probe, probe.read_bytes(), readelf)
    except (OSError, ValueError, KeyError, IndexError, TypeError,
            subprocess.SubprocessError) as error:
        raise ValueError(f'Selected readelf does not support the required LLVM JSON '
                         f'inspection: {readelf}: {error}') from error
    return readelf


def format_result(result, verbose=False):
    def value(key):
        return 'unavailable' if result[key] is None else str(result[key])

    compatibility = result['compatibility_scope'] or (
        'Incompatible' if result['proxy_compatible'] is False else 'Analysis incomplete')
    lines = ['Steam API Compatibility', '-----------------------']

    def section(title, rows):
        lines.extend(['', title])
        lines.extend(f'{label + ":":26}{" " if len(label) >= 25 else ""}{text}' for label, text in rows)

    section('Steam API Target', [('Architecture', value('architecture')),
            ('Provider SHA256', result.get('provider_sha256', 'unavailable')),
            ('Public exports', value('total_public_exports')),
            ('Function exports', value('function_exports'))])
    current = result.get('current_proxy') or {}
    section('Current Proxy', [
        ('Manifest functions', current.get('manifest_function_count', 'unavailable')),
        ('Function intersection', current.get('intersection_count', 'unavailable')),
        ('Supported functions', f"{value('supported_function_exports')} / {value('function_exports')}"),
        ('Target functions uncovered', len(current.get('target_functions_not_forwarded', []))),
        ('Proxy targets absent', len(current.get('proxy_targets_absent_from_target', []))),
        ('Unsupported exports', len(result['unsupported_exports'])),
        ('Required unsupported', len(result['required_unsupported_exports']) or 'none'),
        ('Compatibility', compatibility)])
    absent = current.get('proxy_targets_absent_from_target', [])
    if absent:
        lines.append('  Constructor blockers: ' + ', '.join(absent[:12]) +
                     (f' (+{len(absent) - 12} more)' if len(absent) > 12 else ''))
    static = result.get('consumer_evidence') or {}
    count = static.get('consumer_elf_count', next((m[1] for note in result['notes']
        if (m := re.fullmatch(r'Inspected \d+ APK\(s\), (\d+) consumer ELF\(s\)\.', note))), 'unavailable'))
    section('Static Consumer Evidence', [
        ('Consumer ELFs inspected', count),
        ('Relevant ABI consumers', static.get('relevant_abi_consumer_count', 'unavailable')),
        ('Direct Steam dependencies', static.get('direct_libsteam_api_consumer_count', 'unavailable')),
        ('Steam undefined names', len(static.get('undefined_steam_named_symbols', []))),
        ('Alternate-provider overlaps', sum(bool(s['candidate_alternate_packaged_providers'])
            for f in static.get('files', []) for s in f['provider_export_intersections']))])
    runtime = result.get('runtime_resolution_evidence') or {}
    section('Runtime Resolution Evidence', [
        ('Strong candidates', runtime.get('strong_candidate_count', 'unavailable'))])
    for file in runtime.get('files', []):
        if file['confidence'] == 'no_runtime_lookup_evidence':
            continue
        lines.append(f"  {file['file']}: {file['confidence']}; "
                     f"loader imports={','.join(file['runtime_loader_imports']) or 'none'}; "
                     f"literal candidates={len(file['runtime_lookup_literal_candidates'])}; "
                     f"Steam-named={len(file['steam_named_runtime_lookup_literal_candidates'])}; "
                     f"module strings={len(file['steam_module_strings'])}; "
                     f"Steamworks.NET markers={len(file['steamworks_net_markers'])}")
    target = result.get('target_specific_forwarding') or {}
    section('Target-Specific Forwarding Assessment', [
        ('Assessment', target.get('assessment', 'unavailable')),
        ('Function proxy status', target.get('generation_status', 'not_generated')),
        ('Local validation', target.get('local_validation_status', 'not_run')),
        ('Hardware validation', target.get('hardware_validation_status', 'not_run')),
        ('Non-function coverage', target.get('non_function_coverage', 'unknown')),
        ('Validated', target.get('validated', False)),
        ('Structurally forwardable', target.get('all_target_functions_structurally_forwardable', 'unavailable')),
        ('Structural blockers', len(target.get('structurally_unsupported_function_exports', []))),
        ('Weak bindings to review', len(target.get('weak_function_exports_requiring_binding_review', []))),
        ('Non-function exports', target.get('non_function_export_count', 'unavailable')),
        ('Non-function requirements', target.get('non_function_requirement_evidence', 'unavailable'))])
    evidence = target.get('validation_evidence') or {}
    if evidence:
        lines.append('  Evidence source: ' + evidence['source'])
        lines.append('  Proxy SHA256: ' + evidence['proxy_sha256'])
    lines.extend('  ' + reason for reason in target.get('assessment_reasons', []))
    if verbose:
        for label, names in [('Unsupported exports', result['unsupported_exports']),
                             ('Conservative required unsupported exports', result['required_unsupported_exports'])]:
            lines.extend(['', label + ':', *('  ' + name for name in names)])
        # JSON retains every per-consumer symbol list; verbose makes those same
        # linkage and runtime details accessible to human CLI users.
        for label, evidence in [('Static consumer details', static), ('Runtime evidence details', runtime)]:
            lines.extend(['', label + ':', json.dumps(evidence, indent=2)])
    lines.extend(['', 'Limitations / notes:'])
    lines.extend('  ' + note for note in result['notes'])
    lines.extend('  ' + note for note in target.get('limitations', []))
    if static:
        lines.append('  ' + static['attribution_policy'])
    if runtime:
        lines.append('  ' + runtime['interpretation'])
    return '\n'.join(lines)


def cli_parser():
    codes = ('Exit codes: 0 = completed and compatible; 1 = completed and incompatible; '
             '2 = incomplete analysis or operational/usage error. '
             'Legacy stdin mode always emits JSON and exits 0 for handled analysis errors.')
    parser = argparse.ArgumentParser(description=__doc__, epilog=codes)
    parser.description += (' With no arguments, read the legacy JSON request from redirected '
                           'stdin. Use live or files for human-readable output, or add --json.')
    modes = parser.add_subparsers(dest='mode')
    live = modes.add_parser('live', help='Analyze a running Lepton package read-only', epilog=codes)
    live.add_argument('--lepton', required=True, help='Lepton executable or development SSH wrapper')
    live.add_argument('--context', required=True, help='Running context (e.g. steamlaunch-1408230)')
    live.add_argument('--package', required=True, help='Android package name')
    files = modes.add_parser('files', help='Analyze local provider and base/split APKs', epilog=codes)
    files.add_argument('--steam-api', required=True, type=pathlib.Path, help='Local libsteam_api.so')
    files.add_argument('--apk', required=True, action='append', type=pathlib.Path,
                       help='Local APK; repeat for each split (supply all base/split APKs)')
    files.add_argument('--abi', required=True, help='Package primary ABI (e.g. arm64-v8a)')
    for mode in (live, files):
        mode.add_argument('--readelf', help='LLVM llvm-readelf path (default: discovery on PATH)')
        mode.add_argument('--json', action='store_true', help='Emit only compatibility JSON to stdout')
        mode.add_argument('--verbose', action='store_true', help='Include complete consumer evidence and symbol lists')
        mode.add_argument('--target-proxy-dir', type=pathlib.Path,
                          help='Explicit provider-specific generated directory; independently reverify static parity')
        mode.add_argument('--hardware-bundle', type=pathlib.Path,
                          help='Exact hardware validation archive (requires --target-proxy-dir and --hardware-results)')
        mode.add_argument('--hardware-results', type=pathlib.Path,
                          help='Recorded stage logs/observation directory; validate exact bundle/provider/proxy identity')
    return parser


ERRORS = (OSError, ValueError, KeyError, IndexError, TypeError, UnicodeError,
          struct.error, subprocess.SubprocessError)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = cli_parser()
    if not argv:
        if sys.stdin.isatty():
            parser.print_help()
            return 2
        # Keep the Rust subprocess contract: original keys and request schema,
        # no tool capability probe added, and exit 0 even on handled failures.
        try:
            request = json.loads(sys.stdin.read())
            with tempfile.TemporaryDirectory(prefix='compatibility-') as directory:
                result = analyze(request, pathlib.Path(directory))
        except ERRORS as error:
            result = empty(f'Analysis incomplete: {error}')
        print(json.dumps(result))
        return 0
    args = parser.parse_args(argv)
    details = {'complete': False}
    try:
        with tempfile.TemporaryDirectory(prefix='compatibility-') as directory:
            scratch = pathlib.Path(directory)
            if (bool(args.hardware_bundle) != bool(args.hardware_results) or
                    args.hardware_bundle and not args.target_proxy_dir):
                raise ValueError('Hardware evidence requires --target-proxy-dir, --hardware-bundle and --hardware-results together')
            readelf = select_readelf(args.readelf, scratch)
            if args.mode == 'live':
                request = dict(cli=args.lepton, info=dict(context=args.context, package=args.package))
                result = analyze(request, scratch, readelf, details, discover=True)
            else:
                apks = list(dict.fromkeys(p.expanduser().resolve() for p in args.apk))
                for path in apks:
                    if not path.is_file() or path.suffix.lower() != '.apk':
                        raise ValueError(f'Expected a local APK file: {path}')
                result = analyze_files(args.steam_api.expanduser(), apks, args.abi, readelf, details)
            if args.target_proxy_dir:
                if not details['complete']:
                    raise ValueError('Cannot attach artifact validation to incomplete consumer analysis')
                from validation_evidence import attach_evidence
                attach_evidence(result, details['provider_path'], args.target_proxy_dir.expanduser(), readelf,
                                args.hardware_bundle, args.hardware_results)
    except ERRORS as error:
        details['complete'] = False
        result = empty(f'Analysis incomplete: {error}')
    print(json.dumps(result) if args.json else format_result(result, args.verbose))
    if not details['complete'] or result['proxy_compatible'] is None:
        return 2
    return 0 if result['proxy_compatible'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
