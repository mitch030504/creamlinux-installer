#!/usr/bin/env python3
"""Independent ELF checks; never executes a Steam API."""
import hashlib, json, pathlib, re, subprocess, sys
root = pathlib.Path(__file__).resolve().parents[1]
build = root / 'build'
manifest = json.loads((root/'generated/reference-manifest.json').read_text())
assert hashlib.sha256(pathlib.Path(manifest['source']['path']).read_bytes()).hexdigest() == manifest['source']['sha256']
def run(*args): return subprocess.check_output(args, text=True)
def exports(path):
    out = {}
    for line in run('readelf', '--dyn-syms', '--wide', str(path)).splitlines():
        p = line.split()
        if len(p) >= 8 and p[4] in ('GLOBAL', 'WEAK', 'UNIQUE') and p[5] in ('DEFAULT', 'PROTECTED') and p[6] != 'UND':
            assert p[4:6] == ['GLOBAL', 'DEFAULT'], (path, p)
            out[p[7]] = p[3]
    return out
result = {}
for kind in ('mock', 'real'):
    names = json.loads((build/kind/'names.json').read_text())
    proxy = build/kind/'libsteam_api.so'
    actual = exports(proxy)
    assert actual == dict.fromkeys(names, 'FUNC'), (kind, set(names)-actual.keys(), actual.keys()-set(names))
    dynamic = run('readelf', '-dW', str(proxy))
    assert 'TEXTREL' not in dynamic
    assert 'Library soname: [libsteam_api.so]' in dynamic
    assert 'BIND_NOW' in dynamic
    header = run('readelf', '-hW', str(proxy))
    assert 'AArch64' in header
    assert '0x0000000000000004 (HASH)' in dynamic, 'API 21 needs SysV hash'
    notes = run('readelf', '-nW', str(proxy))
    assert '15 00 00 00 72 33 30' in notes, 'Expected API 21 / NDK r30 note'
    segments = run('readelf', '-lW', str(proxy))
    assert 'TLS ' not in segments
    assert re.search(r'GNU_STACK.* RW ', segments), 'Stack must be non-executable'
    assert '0x4000' in segments, 'Expected NDK 16 KiB load alignment'
    # All internal target slots must use relative relocations, not symbol lookup.
    relocs = run('readelf', '-rW', str(proxy))
    assert 'proxy_targets' not in relocs and 'proxy_unready' not in relocs
    assert not any(n in relocs for n in names)

    # Inspect every linked stub, including target slots on subsequent pages.
    dump = run(str(build/'llvm-objdump'), '-d', '--no-show-raw-insn', str(proxy))
    symbols = run('readelf', '-sW', str(proxy))
    table = int(next(line.split()[1] for line in symbols.splitlines() if line.split()[-1:] == ['proxy_targets']),16)
    for index, name in enumerate(names):
        block = re.search(r'<'+re.escape(name)+r'>:\n(.*?)(?=\n\n|\Z)', dump, re.S)
        assert block, name
        instructions = [line.split(':',1)[1].strip() for line in block[1].splitlines() if ':' in line]
        assert len(instructions) == 3, (name, instructions)
        assert re.match(r'adrp\s+x16,', instructions[0]), instructions
        assert re.match(r'ldr\s+x16, \[x16', instructions[1]), instructions
        assert instructions[2] == 'br\tx16' or instructions[2] == 'br x16', instructions
        page = int(re.search(r'0x[0-9a-f]+', instructions[0])[0],16)
        offset = re.search(r'#(0x[0-9a-f]+|[0-9]+)', instructions[1])
        address = page + (int(offset[1],0) if offset else 0)
        assert address == table + index*8, (name, hex(address), hex(table+index*8))
    result[kind] = {'function_exports':len(names),'missing_functions':[], 'extra_exports':[], 'all_stubs_verified':True}
real = {s['name'] for s in manifest['symbols'] if s['function_forwarding_candidate']}
assert set(json.loads((build/'real/names.json').read_text())) == real
assert exports(build/'mock/libmock_original.so') == dict.fromkeys(json.loads((build/'mock/names.json').read_text()), 'FUNC')
for executable in ('abi_test','abi_static','load_probe'):
    p = build/executable
    assert p.is_file()
    assert 'AArch64' in run('readelf','-hW',str(p))
result['reference_sha256_unchanged'] = True
result['omitted_real_exports'] = sorted(s['name'] for s in manifest['symbols'] if s['public_export'] and not s['function_forwarding_candidate'])
(build/'static-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
