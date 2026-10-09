"""Same-source frozen-SDK handoff between native compilation and packaging."""
import json
import os
from pathlib import Path
import shutil
from frame_release_utils import require_elf, sha256, write_json
from frame_sdk import validate_identity


def export(output, report, binary):
    output = Path(output)
    require_elf(binary)
    shutil.copy2(binary,output/'creamlinux')
    report.update(status='passed', scope='native_compilation_only',
                  artifact_filename='creamlinux', artifact_sha256=sha256(output/'creamlinux'))
    report['payload_sha256'] = {name:sha256(output/name) for name in
        ['creamlinux','build-packages.tsv','logs/rust-tests.log','logs/rendering-tests.log','logs/tauri-build.log']}
    write_json(output/'compile-manifest.json',report)
    write_json(output/'release-manifest.json',report)


def verify(directory, packaging):
    directory = Path(directory)
    if directory.is_symlink() or (directory/'compile-manifest.json').is_symlink():
        raise ValueError('Symlink compilation handoff')
    report = json.loads((directory/'compile-manifest.json').read_text())
    if report['status']!='passed' or report['scope']!='native_compilation_only':
        raise ValueError('Compilation handoff is incomplete')
    for name in ['head','snapshot_sha256']:
        if report['source'][name]!=packaging['source'][name]:
            raise ValueError('Compilation source identity differs: '+name)
    for name in ['version','source_date_epoch','cargo_environment','build_jobs']:
        if report[name]!=packaging[name]:
            raise ValueError('Compilation inputs differ: '+name)
    if report['llvm_runtime']!=packaging['llvm_runtime']:
        raise ValueError('Compilation LLVM runtime differs')
    if os.environ.get('GITHUB_ACTIONS')=='true':
        for name in ['GITHUB_REPOSITORY','GITHUB_RUN_ID','GITHUB_SHA']:
            if report['ci'][name]!=os.environ.get(name):
                raise ValueError('Compilation producer workflow identity differs: '+name)
    expected = {'creamlinux','build-packages.tsv','logs/rust-tests.log','logs/rendering-tests.log','logs/tauri-build.log'}
    if set(report['payload_sha256'])!=expected:
        raise ValueError('Compilation payload inventory differs')
    for name in expected:
        payload = directory/name
        if payload.is_symlink() or any(p.is_symlink() for p in payload.parents if p!=directory.parent):
            raise ValueError('Symlink compilation payload')
        if sha256(payload)!=report['payload_sha256'][name]:
            raise ValueError('Compilation payload checksum differs: '+name)
    require_elf(directory/'creamlinux')
    if sha256(directory/'creamlinux')!=report['artifact_sha256']:
        raise ValueError('Compilation binary identity differs')
    identity = report['builder_identity']
    validate_identity(identity['sdk_source_sha256'],identity['sdk_source_sha256'],
                      (directory/'build-packages.tsv').read_text(),report['tool_versions'],True,
                      identity['unexpected_rootfs_changes'])
    if not identity['approved'] or identity['mode']!='strict' or report['unsafe_runtime_override_names']:
        raise ValueError('Compilation needs the unmodified frozen SDK')
    for name in ['rust','rendering']:
        test = report['tests'][name]
        if test['status']!='passed' or not test.get('passed',test.get('pass')) or test.get('failed',test.get('fail',0)) or test.get('ignored',test.get('skipped',0)):
            raise ValueError('Compilation test gate failed: '+name)
    return report
