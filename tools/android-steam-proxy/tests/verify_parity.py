#!/usr/bin/env python3
"""Static ARM64 verification only; does not load or call the real Steam API."""
import hashlib
import json
import pathlib
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
toolchain = pathlib.Path(sys.argv[1])
reader = str(toolchain / 'llvm-readelf')
build = root / 'build'
manifest = json.loads((root / 'generated/reference-manifest.json').read_text())
reference = pathlib.Path(manifest['source']['path'])
raw = reference.read_bytes()
expected_hash = 'f424277c8a431542b93bf71215615fa6730edb7968a03f5230d484437f0d4aa4'
assert hashlib.sha256(raw).hexdigest() == expected_hash == manifest['source']['sha256']


def read_elf(path, *flags):
    return json.loads(subprocess.check_output([reader, '--elf-output-style=JSON', *flags,
                                              str(path)], text=True))[0]


elf = read_elf(reference, '--sections', '--dyn-syms')
sections = [s['Section'] for s in elf['Sections']]
candidates = {
    'SteamAPI_IsSteamRunning': ('bool (*)(void)', 0x25ad4, 'e0031f2ac0035fd6'),
    'SteamAPI_GetHSteamUser': ('int32_t (*)(void)', 0x23cec, '480000f000bd44b9c0035fd6'),
    'SteamAPI_GetHSteamPipe': ('int32_t (*)(void)', 0x23ce0, '480000f000b944b9c0035fd6'),
}
functions = []
disassembly = []
for name, (signature, address, code) in candidates.items():
    symbol = next(s['Symbol'] for s in elf['DynamicSymbols'] if s['Symbol']['Name']['Name'] == name)
    assert symbol['Type']['Name'] == 'Function'
    assert symbol['Value'] == address and symbol['Size'] == len(bytes.fromhex(code))
    section = next(s for s in sections if s['Index'] == symbol['Section']['Value'])
    offset = section['Offset'] + address - section['Address']
    assert raw[offset:offset + symbol['Size']].hex() == code, name
    disassembly.append(subprocess.check_output([
        str(toolchain / 'llvm-objdump'), '-d', '--start-address=' + hex(address),
        '--stop-address=' + hex(address + symbol['Size']), str(reference)], text=True))
    functions.append({'function': name, 'signature': signature, 'address': hex(address),
                      'size': symbol['Size'], 'machine_code': code,
                      'init_required_for_this_exact_preinit_read': False})
# The getter loads are mapped words in the original's .bss, not pointer calls.
for address in (0x2e4b8, 0x2e4bc):
    assert any(s['Type']['Name'] == 'SHT_NOBITS' and s['Address'] <= address and
               address + 4 <= s['Address'] + s['Size'] for s in sections)
probe = read_elf(build / 'parity_probe', '--file-header', '--program-headers', '--dyn-syms')
assert probe['ElfHeader']['Machine']['Name'] == 'EM_AARCH64'
assert 'SharedObject' in probe['ElfHeader']['Type']  # PIE executable
segments = [p['ProgramHeader'] for p in probe['ProgramHeaders']]
assert any(p['Type']['Name'] == 'PT_INTERP' for p in segments)
assert all(p['Alignment'] == 16384 for p in segments if p['Type']['Name'] == 'PT_LOAD')
assert not any(s['Symbol']['Name']['Name'].startswith('Steam') for s in probe['DynamicSymbols'])
(build / 'parity/reference-disassembly.txt').write_text('\n'.join(disassembly))
(build / 'parity/reference.sha256').write_text(expected_hash + '  real/libsteam_api_original.so\n')
result = {'reference_sha256': expected_hash, 'reference_unchanged': True,
          'architecture': 'aarch64', 'android_api': 21, 'load_alignment': 16384,
          'real_steam_api_calls_executed_on_build_host': 0,
          'functions': functions}
(build / 'parity/static-verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
