#!/usr/bin/env python3
"""Generate only FUNC stubs from the preserved manifest; no signature guesses."""
import json, pathlib, re
root=pathlib.Path(__file__).resolve().parent
out=root/'build'
manifest=json.loads((root/'generated/reference-manifest.json').read_text())
mock=sorted(re.findall(r'API \w+[ *]+(mock_\w+)\(', (root/'src/mock.h').read_text()))
assert len(mock)==17, mock
pads=[f'mock_pad_{i:04d}' for i in range(1030)]
for kind,names in [('real',sorted(s['name'] for s in manifest['symbols'] if s['function_forwarding_candidate'])),('mock',sorted(mock+pads))]:
    d=out/kind; d.mkdir(parents=True,exist_ok=True)
    assert len(names)==len(set(names)) and all(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',n) for n in names)
    (d/'names.json').write_text(json.dumps(names,indent=2)+'\n')
    (d/'exports.map').write_text('{ global:\n'+''.join(f'  {n};\n' for n in names)+'local: *; };\n')
    (d/'symbols.h').write_text('#pragma once\n#define PROXY_COUNT '+str(len(names))+'u\nextern void *proxy_targets[PROXY_COUNT] __attribute__((visibility("hidden")));\nstatic const char *const proxy_names[PROXY_COUNT] = {\n'+''.join(f'"{n}",\n' for n in names)+'};\n')
    asm=['.text','.hidden proxy_unready']
    for i,n in enumerate(names):
        asm += ['.p2align 2',f'.global {n}',f'.type {n}, %function',f'{n}:',f'  adrp x16, .Lslot_{i}',f'  ldr x16, [x16, :lo12:.Lslot_{i}]','  br x16',f'.size {n}, .-{n}']
    asm += ['.section .data,"aw",%progbits','.p2align 3','.global proxy_targets','.hidden proxy_targets','.type proxy_targets, %object','proxy_targets:']
    for i in range(len(names)): asm += [f'.Lslot_{i}:','  .quad proxy_unready']
    asm += ['.size proxy_targets, .-proxy_targets','.section .note.GNU-stack,"",%progbits']
    (d/'stubs.S').write_text('\n'.join(asm)+'\n')
    if kind=='mock':
        (d/'pads.c').write_text('#include "mock.h"\n'+''.join(f'API uint64_t {n}(uint64_t a) {{ return a+{i}; }}\n' for i,n in enumerate(pads)))
        (d/'rename.h').write_text(''.join(f'#define {n} original_{n}\n' for n in names))
        bind=['#include "mock.h"','#include "symbols.h"','#include <string.h>','#include <unistd.h>']
        bind += [f'uint64_t {n}(uint64_t);' for n in pads]
        bind += [f'extern __typeof__({n}) original_{n};' for n in names]
        bind += ['void proxy_unready(void) { _exit(127); }','void initialize_static_targets(void) {']
        bind += [f'proxy_targets[{i}] = (void*)&original_{n};' for i,n in enumerate(names)]
        bind += ['}','void *static_lookup(const char *name) {']
        bind += [f'if (!strcmp(name,"{n}")) return (void*)&{n};' for n in names]
        bind += ['return 0;','}']
        (d/'static_bind.c').write_text('\n'.join(bind)+'\n')
print('Generated real and mock function-only stubs')
