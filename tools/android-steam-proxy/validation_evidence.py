"""Read-only artifact/log verification. Never loads a proxy or calls a provider.

Evidence is a recorded operator observation, not a cryptographic attestation of
hardware execution. Checksums bind its exact inputs and retained logs; they do
not authenticate the operator. No evidence is inferred from a game name.
"""
import hashlib
import json
import pathlib
import re
import tarfile
import tempfile


STAGES = ('mock', 'weak', 'resolve', 'all')
MODES = ('baseline', 'strong-first', 'strong-middle', 'strong-late')
REJECTIONS = {
    'missing_env': 'absolute original path required',
    'relative_path': 'absolute original path required',
    'nonexistent': 'cannot stat original',
    'self_load': 'original is proxy itself',
    'missing_symbols': 'missing function',
    'dependency_target': 'target is not in explicit original',
    'dependency_failure': 'dlopen original',
    'missing_weak': 'missing function',
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError('Validation evidence rejected: ' + message)


def archive_files(path):
    """Read bounded regular members in memory; never extract paths onto disk."""
    records = {}
    total = 0
    try:
        with tarfile.open(path) as archive:
            for index, member in enumerate(archive):
                name = member.name
                require(index < 128 and not name.startswith('/') and
                        all(p not in ('', '.', '..') for p in name.split('/')),
                        'unsafe archive path/member count')
                if member.isdir():
                    continue
                require(member.isfile() and name not in records, 'nonregular/duplicate member')
                total += member.size
                require(0 <= member.size <= 16 * 1024 * 1024 and total <= 64 * 1024 * 1024,
                        'archive exceeds evidence limits')
                records[name] = archive.extractfile(member).read()
    except tarfile.TarError as exc:
        raise ValueError('Validation evidence archive unreadable: ' + str(exc)) from exc
    return records


def validate_hardware(bundle, results, provider_sha, proxy_sha):
    """Validate the existing Job Simulator profile, including independent stages."""
    bundle, results = pathlib.Path(bundle).resolve(), pathlib.Path(results).resolve()
    files = archive_files(bundle)
    manifest = json.loads(files['manifest.json'])
    require(manifest['schema_version'] == 1 and
            manifest['provider_sha256'] == provider_sha and
            manifest['proxy_sha256'] == proxy_sha and digest(files['libsteam_api.so']) == proxy_sha,
            'provider/proxy identity mismatch')
    # The current runner/profile is deliberately specific. Do not extrapolate
    # Job Simulator's weak checks or counters to an arbitrary target bundle.
    require((manifest['function_count'], manifest['global_function_count'],
             manifest['weak_function_count'], manifest['abi_checks'], manifest['weak_checks'],
             manifest['loader_rejection_cases'], manifest['weak_load_scope_cases']) ==
            (1156, 1135, 21, 11156, 420, 8, 4), 'unsupported hardware profile')
    require(manifest['architecture'] == 'aarch64' and manifest['runtime'] == 'Android/Bionic' and
            manifest['real_provider_included'] is False and
            manifest['safety_root'] == '/data/local/tmp/creamlinux-target-proxy',
            'unsupported runtime or isolation policy')
    checksums = {}
    for line in files['SHA256SUMS'].decode().splitlines():
        sha, name = line.split('  ', 1)
        require(name not in checksums and name in files and digest(files[name]) == sha,
                'bundle checksum mismatch/duplicate')
        checksums[name] = sha
    require(set(checksums) == set(files) - {'SHA256SUMS'}, 'bundle checksum coverage')
    parity = json.loads(files['mock-parity.json'])
    require(parity['passed'] is True and parity['proxy_sha256'] == proxy_sha,
            'bundle mock parity failed')
    functions = {}
    for line in files['target-functions.tsv'].decode().splitlines():
        binding, name = line.split('\t')
        require(name not in functions and binding in ('Global', 'Weak'), 'invalid target list')
        functions[name] = binding
    require(len(functions) == 1156 and sum(b == 'Weak' for b in functions.values()) == 21,
            'target list count/bindings')
    observation = json.loads((results / 'observation.json').read_text())
    require(observation['schema_version'] == 1 and observation['device'] == 'Steam Frame' and
            observation['context'] == 'creamlinux-poc' and observation['abi'] == 'arm64-v8a' and
            type(observation['android_api']) is int and observation['android_api'] >= 23,
            'unsupported device/context/runtime observation')
    require(observation['provider_sha256'] == provider_sha and
            observation['bundle_sha256'] == digest(bundle.read_bytes()) and
            observation['results_sha256'] == digest((results / 'results.tar.gz').read_bytes()),
            'observation input hashes changed')
    for key in ('steam_api_calls_by_resolution_probe', 'production_game_files_modified',
                'production_game_processes_injected'):
        require(type(observation[key]) is int and observation[key] == 0, 'nonzero safety counter')
    consoles = {}
    for stage in STAGES:
        require(type(observation['stage_exits'][stage]) is int and observation['stage_exits'][stage] == 0,
                stage + ' did not exit zero')
        raw = (results / (stage + '-console.log')).read_bytes()
        require(digest(raw) == observation['console_sha256'][stage], stage + ' console changed')
        consoles[stage] = raw.decode()
        require('DEVELOPMENT OVERRIDE' not in consoles[stage] and
                not re.search(r'^FAIL\b', consoles[stage], re.M) and
                'PASS bundle checksums' in consoles[stage] and
                'PASS hardware stage=' + stage in consoles[stage], stage + ' incomplete/unsafe run')
    logs = archive_files(results / 'results.tar.gz')
    for name in ('manifest.json', 'SHA256SUMS', 'target-functions.tsv', 'mock-parity.json'):
        require(logs[name] == files[name], 'transferred bundle metadata mismatch')
    summaries = {
        'mock': 'PASS mock: 1156 targets; 11156 ABI checks; 8 loader rejections',
        'weak': 'PASS weak: 21 WEAK, 1135 GLOBAL; 4 Bionic load-scope cases; 420 checks',
        'resolve': 'PASS resolve: 1156/1156 targets; failures=0; zero Steam API calls',
    }
    for stage, summary in summaries.items():
        require(summary in consoles[stage] and summary in consoles['all'], stage + ' summary missing')
    for stage in ('resolve', 'all'):
        require('PASS real-provider checksum: ' + provider_sha in consoles[stage], 'provider transfer hash missing')
    abi = logs['logs/mock-abi.log'].decode()
    require('PASS 11156 ABI checks' in abi and 'resolved 1156 functions' in abi, 'mock counts missing')
    require('PASS dynsym: 1135 GLOBAL, 21 WEAK FUNC; exact final-link bindings/visibility' in
            logs['logs/weak-dynsym.log'].decode(), 'final-link binding check missing')
    for mode in MODES:
        require('PASS weak ' + mode + ': 21/21 symbols; 105 checks; explicit handles retain mock targets' in
                logs['logs/weak-' + mode + '.log'].decode(), 'weak scope check missing: ' + mode)
    for label, diagnostic in REJECTIONS.items():
        for stage in ('mock', 'all'):
            require('PASS ' + label + ' (exit 127)' in consoles[stage], 'loader exit not observed: ' + label)
        require(diagnostic in logs['logs/' + label + '.log'].decode(), 'loader diagnostic missing: ' + label)
    weak_missing = logs['logs/missing_weak.log'].decode()
    require(any('missing function: ' + name in weak_missing for name, binding in functions.items()
                if binding == 'Weak'), 'missing-weak diagnostic names no WEAK function')
    resolve = logs['logs/resolve.log'].decode()
    resolved = re.findall(r'^RESOLVED (\S+) (0x[0-9a-fA-F]+)$', resolve, re.M)
    require(len(resolved) == len(functions) and {name for name, _ in resolved} == set(functions) and
            all(int(address, 16) != 0 for _, address in resolved) and summaries['resolve'] in resolve,
            'real resolution names/count/addresses mismatch')
    return dict(source=str(results), evidence_kind='recorded hardware observation; not an attestation',
        provider_sha256=provider_sha, proxy_sha256=proxy_sha, bundle_sha256=observation['bundle_sha256'],
        results_sha256=observation['results_sha256'], toolchain=manifest['toolchain'],
        device=observation['device'], context=observation['context'], android_api=observation['android_api'],
        measured_at=observation['measured_at'], function_targets=1156, abi_checks=11156,
        weak_functions=21, global_functions=1135, weak_checks=420, loader_rejections=8,
        resolution_failures=0, steam_api_calls_by_resolution_probe=0,
        scope='Function-only proxy mock ABI/loader/binding and zero-call provider resolution. '
              'No real Steam function forwarding calls or game injection were tested.')


def attach_evidence(result, provider, target_dir, reader, bundle=None, results=None):
    from generate import emit_surface
    from generate_target_proxy import inspect_provider
    from verify_target_proxy import verify
    target_dir = pathlib.Path(target_dir).resolve()
    manifest = json.loads((target_dir / 'manifest.json').read_text())
    actual = inspect_provider(provider, reader)
    require(manifest['provider_sha256'] == result['provider_sha256'] == actual['provider_sha256'] and
            manifest['functions'] == actual['functions'] and
            manifest['omitted_non_function_exports'] == actual['omitted_non_function_exports'],
            'generated manifest does not match this provider')
    with tempfile.TemporaryDirectory(prefix='proxy-source-verify-') as temporary:
        expected_dir = pathlib.Path(temporary)
        emit_surface(expected_dir, actual['functions'])
        for name in ('names.json', 'exports.map', 'symbols.h', 'stubs.S'):
            require((target_dir / name).read_bytes() == (expected_dir / name).read_bytes(),
                    'generated source surface is missing/stale: ' + name)
    target = result['target_specific_forwarding']
    target['generation_status'] = 'generated'
    proxy = target_dir / 'libsteam_api.so'
    if not proxy.is_file():
        require(not bundle and not results, 'hardware evidence requires a built proxy')
        target['validation_evidence'] = dict(source=str(target_dir), provider_sha256=actual['provider_sha256'],
                                             proxy_sha256=None, scope='Generated sources only; no binary validated.')
        return
    report = verify(provider, proxy, reader)
    require(report['passed'] is True, 'independent static proxy verification failed')
    identity = manifest.get('build_identity')
    if identity:
        require(identity['proxy_sha256'] == report['proxy_sha256'], 'build identity proxy checksum changed')
    target.update(generation_status='locally_validated', local_validation_status='passed_static_parity',
        validation_evidence=dict(source=str(target_dir), provider_sha256=report['provider_sha256'],
            proxy_sha256=report['proxy_sha256'], build_identity=identity,
            scope='Independent static surface/stub/slot verification only.'))
    if bundle and results:
        evidence = validate_hardware(bundle, results, report['provider_sha256'], report['proxy_sha256'])
        target.update(generation_status='hardware_validated', hardware_validation_status='passed',
                      binding_validation_status='passed_controlled_bionic_fixtures',
                      validation_evidence=evidence)
        target['weak_function_exports_requiring_binding_review'] = []
        target['assessment_reasons'] = [s for s in target.get('assessment_reasons', [])
                                       if 'weak function export(s) need a binding/interposition policy' not in s]
        if target.get('assessment') == 'inconclusive' and not target['assessment_reasons']:
            target['assessment'] = 'candidate'
        target['assessment_reasons'].append('Controlled Bionic binding/ABI fixtures passed for the exact proxy; '
                                            'actual game behavior remains unvalidated.')
    # Keep the legacy compatibility conclusion/validated boolean conservative:
    # harness validation is not observed real-game behavior or non-function ABI.
    target['limitations'] = [s for s in target['limitations']
                            if not s.startswith('Structural feasibility is not validated')]
    target['limitations'].append('Artifact evidence applies only to the exact provider/proxy hashes shown. '
                                'Computed runtime lookups and actual game behavior remain unvalidated.')
