#!/usr/bin/env python3
import json, pathlib, subprocess
root=pathlib.Path(__file__).resolve().parents[1]
build=root/'build'
results={}
for mode,args,expected in [('static_abi',[],0),('uninitialized_slot',['--uninitialized'],127)]:
    r=subprocess.run(['qemu-aarch64',str(build/'abi_static'),*args],text=True,capture_output=True)
    results[mode]={'exit':r.returncode,'expected_exit':expected,'stdout':r.stdout,'stderr':r.stderr}
    print(mode, r.returncode, r.stdout, r.stderr)
    assert r.returncode==expected, results[mode]
r=subprocess.run(['qemu-aarch64',str(build/'abi_test')],text=True,capture_output=True)
results['dynamic_runtime_probe']={'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'abi_tests_executed':False}
assert "Could not open '/system/bin/linker64'" in r.stderr, 'Runtime availability changed: run dynamic tests instead of assuming unavailable'
(build/'runtime-verification.json').write_text(json.dumps(results,indent=2)+'\n')
print('Dynamic Android ABI/loader tests NOT RUN: /system/bin/linker64 unavailable')
