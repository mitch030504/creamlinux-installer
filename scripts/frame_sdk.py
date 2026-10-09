#!/usr/bin/env python3
"""Build/identify the approved SDK. No registry push or privileged provisioning."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from frame_release_utils import ROOT, sha256, write_json
from frame_process import run

SDK = ROOT/'docker/steam-frame-release'
SDK_FILES = ('.dockerignore','Dockerfile','provision.py','ubuntu.sources','packages.tsv','sdk-lock.json')

def validate_runtime_environment(environ, strict=True):
    # Values may contain credentials or private paths; report names only.
    sensitive = {'RUSTC','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTFLAGS',
        'CARGO_ENCODED_RUSTFLAGS','CARGO_BUILD_RUSTFLAGS','CARGO_BUILD_RUSTC_WRAPPER',
        'CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER','NODE_OPTIONS',
        'NPM_CONFIG_NODE_OPTIONS','LD_PRELOAD','LD_LIBRARY_PATH','LD_AUDIT',
        'BASH_ENV','ENV'}
    overrides=sorted(k for k in sensitive if environ.get(k))
    if strict and overrides:
        raise ValueError('Frozen SDK runtime overrides are forbidden: '+', '.join(overrides)+
                         '; create a fresh container or explicitly select development mode')
    return overrides

def source_hash():
    return hashlib.sha256(json.dumps({n:sha256(SDK/n) for n in SDK_FILES},sort_keys=True).encode()).hexdigest()

def validate_identity(label, embedded, packages, versions, strict=True, changes=()):
    lock=json.loads((SDK/'sdk-lock.json').read_text())
    expected=source_hash()
    reasons=[]
    if label!=expected or embedded!=expected: reasons.append('SDK definition does not match approved source')
    if hashlib.sha256(packages.encode()).hexdigest()!=lock['packages_sha256']: reasons.append('SDK package inventory drift')
    if versions['node']!='v'+lock['node']['version'] or versions['npm']!=lock['node']['npm']: reasons.append('Node/npm drift')
    if not versions['rustc'].startswith('rustc '+lock['rust']['version']+' ') or not versions['cargo'].startswith('cargo '+lock['rust']['version']+' '): reasons.append('Rust/Cargo drift')
    unexpected=[line for line in changes if not any(line.split(' ',1)[-1]==p or line.split(' ',1)[-1].startswith(p+'/') for p in ['/home','/tmp','/run','/var/tmp'])]
    if unexpected: reasons.append('SDK root filesystem drift: '+repr(unexpected[:20]))
    if strict and reasons: raise ValueError('; '.join(reasons)+'; rebuild the frozen SDK, or explicitly select development mode')
    return {'mode':'strict' if strict else 'development','approved':not reasons,'override_reasons':reasons,
            'rootfs_drift_checked':True,'unexpected_rootfs_changes':unexpected,'sdk_source_sha256':expected,'package_inventory_sha256':hashlib.sha256(packages.encode()).hexdigest(),
            'base_image':lock['base_image'],'apt_snapshot':lock['apt_snapshot'],'pins':lock}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',default='creamlinux-frame-sdk:locked')
    p.add_argument('--add-host',action='append',default=[],help='Isolated Docker build DNS override, never a global network change')
    p.add_argument('--timeout',type=int,default=1800,help='SDK build deadline in seconds (1..21600)')
    a=p.parse_args()
    if not 1<=a.timeout<=21600:p.error('--timeout must be between 1 and 21600 seconds')
    cmd=['docker','build','--platform','linux/arm64','--build-arg','SDK_SOURCE_SHA256='+source_hash(),'-t',a.image]
    for host in a.add_host: cmd+=['--add-host',host]
    run(cmd+[str(SDK)],ROOT,timeout=a.timeout,passthrough=True)
    image=json.loads(subprocess.check_output(['docker','image','inspect',a.image]))[0]
    print(json.dumps({'image_id':image['Id'],'repo_digests':image['RepoDigests'],'sdk_source_sha256':source_hash()},indent=2))

if __name__=='__main__':
    try: main()
    except (OSError,ValueError,subprocess.SubprocessError) as e:
        print('SDK build failed: '+str(e),file=sys.stderr);sys.exit(2)
