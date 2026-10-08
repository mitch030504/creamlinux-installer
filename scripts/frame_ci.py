#!/usr/bin/env python3
"""Non-publishing artifact verification, provenance and reproducibility checks."""
import argparse
import json
from pathlib import Path
import shutil
import os
import sys
from frame_release_utils import sha256, write_json, require_elf, appimage_offset

UPLOAD_FILES = ('SHA256SUMS','release-manifest.json','source-inputs.json','build-packages.tsv',
                'appdir-inventory.json','python-tests.json','captured-game-regressions.json','provenance.json')

def provenance(report, output):
    output=Path(output)
    return {'_type':'https://in-toto.io/Statement/v1',
        'subject':[{'name':report['artifact_filename'],'digest':{'sha256':report['artifact_sha256']}}],
        'predicateType':'https://creamlinux.invalid/provenance/steam-frame/v1',
        'predicate':{'claim':'unsigned build record; no SLSA compliance level claimed',
            'source':{k:report.get('source',{}).get(k) for k in ['head','branch','dirty','snapshot_sha256']},
            'ci':report.get('ci',{}),'builder':report.get('builder_identity',{}),
            **({'unsafe_runtime_override_names':report['unsafe_runtime_override_names']} if 'unsafe_runtime_override_names' in report else {}),
            'tools':report.get('tool_versions',{}),'cargo_environment':report.get('cargo_environment',{}),
            'controller_pins':report.get('pinned_controller_inputs',{}),'dependency_pins':report.get('pinned_build_tools',{}),
            'llvm_runtime':report.get('llvm_runtime',{}),'source_date_epoch':report.get('source_date_epoch'),
            'appdir_inventory_sha256':sha256(output/'appdir-inventory.json') if (output/'appdir-inventory.json').is_file() else None,
            'tests':report['tests'],'captured_game_regressions':report.get('captured_game_regressions'),
            'hardware_smoke':report['hardware_validation']}}

def verify(output, strict=True):
    output=Path(output)
    if output.is_symlink(): raise ValueError('Symlink CI release directory')
    for filename in ('release-manifest.json','source-inputs.json','build-packages.tsv',
                     'appdir-inventory.json','provenance.json','SHA256SUMS'):
        payload=output/filename
        if payload.is_symlink() or not payload.is_file():
            raise ValueError('Missing or symlink CI payload: '+filename)
    r=json.loads((output/'release-manifest.json').read_text())
    name=r['artifact_filename']
    if Path(name).name!=name: raise ValueError('Unsafe artifact filename')
    artifact=output/name
    if artifact.is_symlink() or not artifact.is_file(): raise ValueError('Missing or symlink CI artifact')
    if r['status']!='passed' or sha256(artifact)!=r['artifact_sha256'] or artifact.stat().st_size!=r['artifact_size_bytes']:
        raise ValueError('Artifact identity/status mismatch')
    require_elf(artifact); appimage_offset(artifact)
    if (output/'SHA256SUMS').read_text()!=r['artifact_sha256']+'  '+name+'\n': raise ValueError('Checksum file mismatch')
    source=json.loads((output/'source-inputs.json').read_text())
    if source!=r['source']: raise ValueError('Source snapshot report mismatch')
    if os.environ.get('GITHUB_ACTIONS')=='true' and source['head']!=os.environ.get('GITHUB_SHA'):
        raise ValueError('Artifact producer source commit does not match this workflow commit')
    import hashlib
    files=source.get('files',{})
    if hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()!=source['snapshot_sha256']:
        raise ValueError('Source snapshot inventory hash mismatch')
    if os.environ.get('GITHUB_ACTIONS')=='true':
        from frame_release_utils import ROOT,source_identity
        if source_identity(ROOT)['snapshot_sha256']!=source['snapshot_sha256']:
            raise ValueError('Artifact source snapshot does not match this exact checkout')
    if strict:
        from frame_sdk import validate_identity
        identity=r['builder_identity']
        actual=validate_identity(identity['sdk_source_sha256'],identity['sdk_source_sha256'],
            (output/'build-packages.tsv').read_text(),r['tool_versions'],True)
        if actual['package_inventory_sha256']!=identity['package_inventory_sha256'] or identity.get('unexpected_rootfs_changes'):
            raise ValueError('Builder inventory/rootfs identity mismatch')
    if strict and (not r['builder_identity']['approved'] or r['builder_identity']['mode']!='strict'):
        raise ValueError('Official validation requires frozen builder strict mode')
    if strict and r.get('unsafe_runtime_override_names'):
        raise ValueError('Official validation forbids SDK runtime overrides')
    for name in ['python','rust','rendering']:
        if r['tests'][name]['status']!='passed': raise ValueError('Test gate failed: '+name)
    if r['tests']['diff_check']!='passed': raise ValueError('Whitespace gate failed')
    static=r['static_validation']
    if static['forbidden_conflict_files'] or not static['extraction_inventory_match'] or not static['default_legacy_startup_rejected']:
        raise ValueError('Static/read-only packaging guard failed')
    hw=r['hardware_validation']
    if hw['performed_this_build']:
        if hw['status']!='passed' or hw['artifact_sha256']!=r['artifact_sha256']: raise ValueError('Hardware identity mismatch')
    elif hw['status']!='not_run' or hw['historical_evidence_inherited']:
        raise ValueError('Historical hardware evidence cannot validate this artifact')
    captures=r['captured_game_regressions']
    if captures['status'] not in {'performed','unavailable'} or (captures['status']=='unavailable' and captures['performed']):
        raise ValueError('Captured fixture status is inconsistent')
    if json.loads((output/'provenance.json').read_text())!=provenance(r,output): raise ValueError('Provenance mismatch')
    return r

def compare(first, second):
    a,b=verify(first),verify(second)
    for key in ['artifact_sha256','source_date_epoch']:
        if a[key]!=b[key]: raise ValueError('Reproducibility mismatch: '+key)
    if a['source']['snapshot_sha256']!=b['source']['snapshot_sha256'] or a['builder_identity']!=b['builder_identity']:
        raise ValueError('Reproducibility inputs differ')
    for key in ['tool_versions','cargo_environment','pinned_build_tools','pinned_controller_inputs']:
        if a.get(key)!=b.get(key):raise ValueError('Reproducibility tool inputs differ: '+key)
    if (Path(first)/'appdir-inventory.json').read_bytes()!=(Path(second)/'appdir-inventory.json').read_bytes():
        raise ValueError('AppDir inventories differ')
    return {'status':'passed','appimage_byte_identical':True,'appdir_inventory_identical':True,
            'artifact_sha256':a['artifact_sha256'],'source_snapshot_sha256':a['source']['snapshot_sha256']}

def export(output, destination, failed=False):
    if failed:
        r=json.loads((Path(output)/'release-manifest.json').read_text())
        if r['status']!='failed': raise ValueError('Failure diagnostics require failed manifest')
    else: r=verify(output)
    destination=Path(destination)
    destination.mkdir() # Refuse existing directories.
    names=UPLOAD_FILES if failed else (*UPLOAD_FILES,r['artifact_filename'])
    for name in names:
        source=Path(output)/name
        if failed and not source.is_file(): continue
        if source.is_symlink(): raise ValueError('Symlink CI payload: '+name)
        shutil.copy2(source,destination/name)
    # Only logs and generated JSON evidence, never arbitrary build directories.
    for directory in ['logs','captured-regressions']:
        source=Path(output)/directory
        if source.exists():
            if source.is_symlink() or not source.is_dir():
                raise ValueError('Unexpected CI diagnostic directory: '+str(source))
            (destination/directory).mkdir()
            for p in source.iterdir():
                if p.is_symlink() or p.suffix not in {'.log','.json'} or not p.is_file():
                    raise ValueError('Unexpected CI diagnostic payload: '+str(p))
                shutil.copy2(p,destination/directory/p.name)
    return {'status':'passed','destination':str(destination)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=['verify','compare','export','export-failure'])
    p.add_argument('output',type=Path);p.add_argument('other',nargs='?',type=Path)
    a=p.parse_args()
    if a.operation=='verify': result={'status':verify(a.output)['status']}
    elif a.other is None: raise ValueError('Second path required')
    elif a.operation=='compare':
        result=compare(a.output,a.other);write_json(a.other/'reproducibility.json',result)
    else: result=export(a.output,a.other,failed=a.operation=='export-failure')
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    try: main()
    except (OSError,ValueError,KeyError,TypeError) as e:
        print('Frame CI verification failed: '+str(e),file=sys.stderr);sys.exit(2)
