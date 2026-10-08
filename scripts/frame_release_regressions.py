"""Optional local game captures; no game changes and no invented live state."""
import json
from pathlib import Path
import shutil
import sys

from frame_release_utils import ROOT, resources, sha256, write_json


def captured_regressions(builder):
    home = Path.home()
    examples = [('1408230',home/'creamlinux-walkabout-cli',1049,1045,True,14),
                ('448280',home/'creamlinux-jobsimulator-cli',1365,1156,False,19)]
    for appid, count in [('438100',39),('801550',37),('3606610',15),('3189340',21)]:
        examples.append((appid,ROOT/'tools/android-steam-proxy/build/frame-game-discovery-2026-10-07'/appid,1355,1146,False,count))
    if builder.args.capture_root:
        root=Path(builder.args.capture_root)
        if not root.is_dir(): raise ValueError('Configured private capture root does not exist: '+str(root))
        examples=[(appid,root/appid,public,functions,compatible,consumers) for appid,_,public,functions,compatible,consumers in examples]
    rows = []
    for appid, capture, public, functions, compatible, consumers in examples:
        pair=capture_pair(capture)
        if pair is None:
            rows.append({'appid':appid,'status':'not_run','reason':'optional original local capture absent'})
            continue
        provider,apk=pair
        out = builder.output/'captured-regressions'
        out.mkdir(exist_ok=True)
        log = out/(appid+'.log')
        # Run files mode with the reader extracted from this exact AppImage.
        # Original captures are copied only into the isolated build workspace,
        # outside AppDir; nothing is copied into installed game directories.
        inputs = builder.stage/'capture-inputs'/appid
        inputs.mkdir(parents=True)
        shutil.copy2(provider,inputs/'provider.so')
        shutil.copy2(apk,inputs/'base.apk')
        result = builder.docker(['python3','-E','-s','-B',builder.inside(ROOT/'tools/android-steam-proxy/compatibility.py'),
            'files','--steam-api',builder.inside(inputs/'provider.so'),'--apk',builder.inside(inputs/'base.apk'),
            '--abi','arm64-v8a','--readelf',builder.inside(builder.extracted/'usr/lib/Creamlinux/compatibility/runtime/bin/llvm-readelf'),
            '--json']) if compatible else None
        if not compatible:
            # A completed incompatible CLI result has exit 1, not an operational
            # failure. Use a wrapper that checks the exact expected exit while
            # retaining the analyzer's pure JSON unaltered.
            wrapper = builder.stage/'capture-files-check.py'
            wrapper.write_text('import subprocess,sys\nr=subprocess.run(sys.argv[2:],capture_output=True)\n'
                'sys.stdout.buffer.write(r.stdout);sys.stderr.buffer.write(r.stderr)\n'
                'sys.exit(0 if r.returncode==int(sys.argv[1]) else 2)\n')
            result = builder.docker(['python3',builder.inside(wrapper),'1','python3','-E','-s','-B',
                builder.inside(ROOT/'tools/android-steam-proxy/compatibility.py'),'files',
                '--steam-api',builder.inside(inputs/'provider.so'),'--apk',builder.inside(inputs/'base.apk'),
                '--abi','arm64-v8a','--readelf',builder.inside(builder.extracted/'usr/lib/Creamlinux/compatibility/runtime/bin/llvm-readelf'),'--json'])
        log.write_text(result+'\n')
        data = json.loads(result)
        if (not data['analyzed'] or data['proxy_compatible'] is not compatible
                or data['total_public_exports'] != public or data['function_exports'] != functions
                or data['required_unsupported_exports'] or data['provider_sha256'] != sha256(provider)
                or data['consumer_evidence']['consumer_elf_count'] != consumers):
            raise ValueError('Captured game regression changed: '+appid)
        if data['runtime_resolution_evidence']['strong_candidate_count'] < 1:
            raise ValueError('Runtime lookup evidence was lost: '+appid)
        if appid=='801550' and data['consumer_evidence']['direct_libsteam_api_consumer_count'] != 1:
            raise ValueError('VAIL direct dependency evidence was lost')
        rows.append({'appid':appid,'status':'passed','provider_sha256':data['provider_sha256'],
            'fixed_proxy_compatible':compatible,'expected_exit':0 if compatible else 1,
            'reader':'this exact AppImage private LLVM on ARM64 build container'})
        shutil.rmtree(inputs)
    write_json(builder.output/'captured-game-regressions.json',rows)
    return rows


def capture_pair(capture):
    capture=Path(capture)
    provider=capture/'libsteam_api.so'
    apks=[capture/'apks/base.apk',capture/'base.apk']
    apk=next((p for p in apks if p.is_file()),None)
    if not provider.exists() and apk is None:
        return None
    if not provider.is_file() or apk is None:
        raise ValueError('Partial original capture; provider and APK required: '+str(capture))
    return provider,apk
