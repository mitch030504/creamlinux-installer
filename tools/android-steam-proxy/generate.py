#!/usr/bin/env python3
"""Shared function-only AArch64 emitter and legacy fixed-reference entry point."""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent
NAME = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')


def emit_surface(directory, functions):
    """Emit the proven tail stubs; metadata determines binding and visibility."""
    functions = sorted(functions, key=lambda s: s['name'])
    names = [s['name'] for s in functions]
    if len(names) != len(set(names)) or not all(NAME.fullmatch(n) for n in names):
        raise ValueError('duplicate or unsafe function names')
    if not functions or any(s['binding'] not in ('Global', 'Weak') or
                            s.get('other', 0) not in (0, 3) for s in functions):
        raise ValueError('unsupported function surface')
    directory = pathlib.Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'names.json').write_text(json.dumps(names, indent=2) + '\n')
    (directory / 'exports.map').write_text('{ global:\n' + ''.join(
        f'  {n};\n' for n in names) + 'local: *; };\n')
    (directory / 'symbols.h').write_text(
        '#pragma once\n#define PROXY_COUNT ' + str(len(names)) + 'u\n'
        'extern void *proxy_targets[PROXY_COUNT] __attribute__((visibility("hidden")));\n'
        'static const char *const proxy_names[PROXY_COUNT] = {\n' +
        ''.join(f'"{n}",\n' for n in names) + '};\n')
    asm = ['.text', '.hidden proxy_unready']
    for i, symbol in enumerate(functions):
        name = symbol['name']
        binding = '.weak' if symbol['binding'] == 'Weak' else '.global'
        asm += ['.p2align 2', f'{binding} {name}']
        if symbol.get('other', 0) == 3:
            asm += [f'.protected {name}']
        asm += [f'.type {name}, %function', f'{name}:',
                f'  adrp x16, .Lslot_{i}', f'  ldr x16, [x16, :lo12:.Lslot_{i}]',
                '  br x16', f'.size {name}, .-{name}']
    asm += ['.section .data,"aw",%progbits', '.p2align 3', '.global proxy_targets',
            '.hidden proxy_targets', '.type proxy_targets, %object', 'proxy_targets:']
    for i in range(len(names)):
        asm += [f'.Lslot_{i}:', '  .quad proxy_unready']
    asm += ['.size proxy_targets, .-proxy_targets', '.section .note.GNU-stack,"",%progbits']
    (directory / 'stubs.S').write_text('\n'.join(asm) + '\n')
    return functions


def emit_mock(directory, count=1047, weak_count=0, target_functions=None):
    """Existing ABI signatures plus enough pad slots for any target-sized test."""
    mock = sorted(re.findall(r'API \w+[ *]+(mock_\w+)\(', (ROOT / 'src/mock.h').read_text()))
    if len(mock) != 17 or count < len(mock) or not 0 <= weak_count <= count - len(mock):
        raise ValueError('invalid mock surface size/binding counts')
    pads = [f'mock_pad_{i:04d}' for i in range(count - len(mock))]
    weak = set(pads[:weak_count])
    if target_functions is None:
        surface = [dict(name=n, binding='Weak' if n in weak else 'Global', other=0)
                   for n in mock + pads]
        mapping = dict(zip(mock + pads, mock + pads))
    else:
        surface = sorted(target_functions, key=lambda s: s['name'])
        if len(surface) != count:
            raise ValueError('mock size differs from target surface')
        globals_ = [s['name'] for s in surface if s['binding'] == 'Global']
        if len(globals_) < len(mock):
            raise ValueError('target mock requires 17 global signature slots')
        representatives = globals_[:len(mock)]
        remaining = [s['name'] for s in surface if s['name'] not in representatives]
        mapping = dict(zip(mock + pads, representatives + remaining))
    functions = emit_surface(directory, surface)
    names = [s['name'] for s in functions]
    metadata = {s['name']: s for s in functions}
    directory = pathlib.Path(directory)
    def attributes(name):
        return ('__attribute__((weak)) ' if metadata[name]['binding'] == 'Weak' else '') + (
            '__attribute__((visibility("protected"))) ' if metadata[name].get('other', 0) == 3 else '')
    (directory / 'pads.c').write_text('#include "mock.h"\n' + ''.join(
        attributes(mapping[n]) + f'API uint64_t {mapping[n]}(uint64_t a) {{ return a+{i}; }}\n'
        for i, n in enumerate(pads)))
    (directory / 'mock_rename.h').write_text(''.join(
        f'#define {n} {mapping[n]}\n' for n in mock))
    # Static bionic startup itself uses C++ runtime symbols. Namespace only the
    # static test's trampoline labels so it cannot hit them before main.
    (directory / 'static_stub_names.h').write_text(''.join(
        f'#define {n} trampoline_{n}\n' for n in names))
    (directory / 'rename.h').write_text(''.join(
        f'#define {n} original_{mapping.get(n, n)}\n' for n in dict.fromkeys(mock + names)))
    (directory / 'abi_names.h').write_text(
        '#include <string.h>\nstatic const char *abi_lookup_name(const char *name) {\n' +
        ''.join(f'if (!strcmp(name,"{n}")) return "{mapping[n]}";\n' for n in mock + pads) +
        'return name;\n}\n')
    bind = ['#include "mock.h"', '#include "symbols.h"', '#include <string.h>', '#include <unistd.h>']
    bind += [f'extern __typeof__({n}) {mapping[n]};' for n in mock]
    bind += [f'uint64_t {mapping[n]}(uint64_t);' for n in pads]
    bind += [f'extern __typeof__({n}) original_{mapping[n]};' for n in mock]
    bind += [f'extern uint64_t original_{mapping[n]}(uint64_t);' for n in pads]
    bind += ['void proxy_unready(void) { _exit(127); }', 'void initialize_static_targets(void) {']
    bind += [f'proxy_targets[{i}] = (void*)&original_{n};' for i, n in enumerate(names)]
    bind += ['}', 'void *static_lookup(const char *name) {']
    bind += [f'if (!strcmp(name,"{n}")) return (void*)&{n};' for n in names]
    bind += ['return 0;', '}']
    (directory / 'static_bind.c').write_text('\n'.join(bind) + '\n')
    return functions


def main():
    manifest = json.loads((ROOT / 'generated/reference-manifest.json').read_text())
    emit_surface(ROOT / 'build/real', [dict(name=s['name'], binding='Global', other=0)
                 for s in manifest['symbols'] if s['function_forwarding_candidate']])
    emit_mock(ROOT / 'build/mock')
    print('Generated real and mock function-only stubs')


if __name__ == '__main__':
    main()
