#!/usr/bin/env python3
"""Exact provider/proxy parity and machine-code ABI checks; never dlopen either."""
import argparse
import hashlib
import pathlib
import struct
import subprocess
import sys

from generate_target_proxy import android_note, inspect_provider, public_symbols, read_elf, write_json


def verify(provider, proxy, reader='llvm-readelf'):
    manifest = inspect_provider(provider, reader)
    proxy = pathlib.Path(proxy)
    raw = proxy.read_bytes()
    elf = read_elf(proxy, reader)
    actual = public_symbols(elf)
    functions = {s['name']: s for s in actual if s['type'] == 'Function'}
    expected = {s['name']: s for s in manifest['functions']}
    shared = sorted(expected.keys() & functions.keys())
    missing = sorted(expected.keys() - functions.keys())
    extra = sorted(functions.keys() - expected.keys())
    binding = [n for n in shared if expected[n]['binding'] != functions[n]['binding']]
    visibility = [n for n in shared if expected[n]['other'] != functions[n]['other']]
    nonfunctions = [s['name'] for s in actual if s['type'] != 'Function']
    fake = sorted({s['name'] for s in manifest['omitted_non_function_exports']} & functions.keys())
    header = elf['ElfHeader']
    segments = [p['ProgramHeader'] for p in elf['ProgramHeaders']]
    loads = [p for p in segments if p['Type']['Name'] == 'PT_LOAD']
    dynamic = elf['DynamicSection']
    checks = dict(
        aarch64_elf64_little_endian=(header['Machine']['Value'] == 183 and
                                    header['Ident']['Class']['Value'] == 2 and
                                    header['Ident']['DataEncoding']['Value'] == 1),
        shared_object=header['Type'].startswith('SharedObject'),
        android_api_21=android_note(elf)['api'] == 21,
        soname=any(d['Type'] == 'SONAME' and d['Name'] == 'libsteam_api.so' for d in dynamic),
        load_alignment_16384=bool(loads) and all(p['Alignment'] == 16384 and
            (p['VirtualAddress'] - p['Offset']) % 16384 == 0 for p in loads),
        non_executable_stack=any(p['Type']['Name'] == 'PT_GNU_STACK' and
                                 not p['Flags']['Value'] & 1 for p in segments),
        no_writable_executable_loads=all(p['Flags']['Value'] & 3 != 3 for p in loads),
        no_tls=not any(p['Type']['Name'] == 'PT_TLS' for p in segments),
        no_textrel=not any(d['Type'] == 'TEXTREL' for d in dynamic),
        bind_now=any(d['Type'] == 'FLAGS' and 'BIND_NOW' in d['Flags'] for d in dynamic),
        relro=any(p['Type']['Name'] == 'PT_GNU_RELRO' for p in segments),
        sysv_hash=any(d['Type'] == 'HASH' for d in dynamic),
        no_non_function_exports=not nonfunctions,
    )
    regular = {e['Symbol']['Name']['Name']: e['Symbol'] for e in elf['Symbols']}
    slots, unready = regular.get('proxy_targets'), regular.get('proxy_unready')
    stub_errors = []
    sections = [s['Section'] for s in elf['Sections']]
    relocation_index = {r['Relocation']['Offset']: r['Relocation']
                        for group in elf['Relocations'] for r in group['Relocs']}
    if not slots or not unready or slots['Size'] != len(expected) * 8:
        stub_errors.append('missing/incorrect internal target table or fail-closed entry point')
    else:
        for index, name in enumerate(sorted(expected)):
            if name not in functions:
                continue
            s = functions[name]
            address = s['value']
            owner = next((sec for sec in sections if sec['Type']['Value'] != 8 and
                          sec['Address'] <= address and address + 12 <= sec['Address'] + sec['Size']), None)
            if s['size'] != 12 or address % 4 or owner is None or not owner['Flags']['Value'] & 4:
                stub_errors.append(name + ': invalid size/alignment/code section')
                continue
            offset = owner['Offset'] + address - owner['Address']
            a, b, c = struct.unpack_from('<III', raw, offset)
            # Only x16 is touched. No stack, LR, argument GPR/SIMD or dlsym call.
            if a & 0x9f00001f != 0x90000010 or b & 0xffc003ff != 0xf9400210 or c != 0xd61f0200:
                stub_errors.append(name + ': not adrp x16; ldr x16,[x16]; br x16')
                continue
            imm = ((a >> 5 & 0x7ffff) << 2) | (a >> 29 & 3)
            if imm & (1 << 20):
                imm -= 1 << 21
            target_slot = (address & ~4095) + imm * 4096 + (b >> 10 & 4095) * 8
            expected_slot = slots['Value'] + index * 8
            reloc = relocation_index.get(expected_slot, {})
            if target_slot != expected_slot:
                stub_errors.append(name + ': wrong slot address')
            if (reloc.get('Type', {}).get('Name') != 'R_AARCH64_RELATIVE' or
                    reloc.get('Addend') != unready['Value']):
                stub_errors.append(name + ': slot not initialized by relative fail-closed relocation')
    checks['every_tail_stub_and_slot_verified'] = not stub_errors
    passed = not (missing or extra or binding or visibility or fake) and all(checks.values())
    return dict(schema_version=1, provider_sha256=manifest['provider_sha256'],
                proxy_sha256=hashlib.sha256(raw).hexdigest(), provider_functions=len(expected),
                proxy_target_functions=len(functions.keys() & expected.keys()),
                proxy_public_functions=len(functions), name_parity='exact' if not missing and not extra else 'different',
                global_function_count=sum(s['binding'] == 'Global' for s in functions.values()),
                weak_function_count=sum(s['binding'] == 'Weak' for s in functions.values()),
                missing_functions=missing, extra_functions=extra, documented_internal_function_exports=[],
                binding_mismatches=binding, weak_binding_mismatches=[n for n in binding if expected[n]['binding'] == 'Weak'],
                visibility_mismatches=visibility, fake_non_function_trampolines=fake,
                non_function_exports=nonfunctions, omitted_non_function_count=manifest['non_function_count'],
                checks=checks, stub_errors=stub_errors, passed=passed,
                runtime_validation_status='unvalidated/limited', steam_api_calls=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', type=pathlib.Path, required=True)
    parser.add_argument('--proxy', type=pathlib.Path, required=True)
    parser.add_argument('--readelf', default='llvm-readelf')
    parser.add_argument('--report', type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        report = verify(args.provider, args.proxy, args.readelf)
        write_json(args.report, report)
    except (OSError, ValueError, KeyError, TypeError, struct.error, subprocess.SubprocessError) as exc:
        print('parity verification failed: ' + str(exc), file=sys.stderr)
        return 2
    print('Function parity: ' + report['name_parity'] + '; ' +
          str(report['provider_functions']) + ' functions; ' + str(report['weak_function_count']) +
          ' weak; binding mismatches: ' + str(len(report['binding_mismatches'])))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
