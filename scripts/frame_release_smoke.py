"""Exact-artifact Frame smoke using only established read-only entrypoints."""
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import uuid

from frame_release_utils import ROOT, KNOWN_PROVIDERS, sha256, write_json

REMOTE = '/tmp/creamlinux-inspector-validation'


def ssh(args):
    if not args.ssh_target or args.ssh_target.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_.@:-]+',args.ssh_target):
        raise ValueError('Invalid Frame SSH target')
    options = ['-o','BatchMode=yes','-o','ConnectTimeout=8']
    if args.ssh_control:options += ['-o','ControlPath='+args.ssh_control]
    return options


def remote(args, code, values=(), log=None):
    command = ['ssh',*ssh(args),args.ssh_target,shlex.join(['python3','-',*map(str,values)])]
    result = subprocess.run(command,input=code,text=True,capture_output=True,timeout=900)
    if log:Path(log).write_text(result.stdout+result.stderr)
    if result.returncode:
        raise ValueError(f'Frame read-only smoke failed ({result.returncode}): '+(result.stderr or result.stdout).strip().splitlines()[-1])
    return result.stdout


def smoke_preflight(args):
    import shutil, hashlib
    for tool in ['ssh','scp']:
        if not shutil.which(tool):raise ValueError('Missing hardware smoke tool '+tool)
    if not args.smoke_fixtures.is_file():
        raise ValueError('Native GUI smoke requires existing generated/bundle/log fixtures; set FRAME_SMOKE_FIXTURES. No real providers belong in that archive.')
    with tarfile.open(args.smoke_fixtures) as archive:
        for member in archive:
            if member.name.startswith('/') or '..' in Path(member.name).parts or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe smoke fixture member')
            if member.isfile():
                data=archive.extractfile(member).read()
                if member.name.endswith('.apk') or member.name.endswith('original-provider.so') or hashlib.sha256(data).hexdigest() in KNOWN_PROVIDERS:
                    raise ValueError('Real game capture in smoke fixtures')
    code = """import pathlib,subprocess,importlib.util,gi
gi.require_version('Atspi','2.0')
from gi.repository import Atspi
cli=pathlib.Path.home()/'.local/share/Steam/steamapps/common/Lepton/lepton'
assert cli.is_file(),'Lepton CLI unavailable'
assert subprocess.run([str(cli),'exec','steamlaunch-448280','true'],capture_output=True).returncode==0,'Job Simulator is not currently running; no production context will be started'
assert not pathlib.Path('/tmp/creamlinux-inspector-validation').exists(),'Isolated smoke directory occupied; preserve it and resolve ownership before retrying'
print('PASS read-only Frame prerequisites and authoritative Job running probe')
"""
    remote(args,code)


def smoke(builder):
    args = builder.args
    logdir = builder.output/'frame-smoke'
    logdir.mkdir()
    token = uuid.uuid4().hex
    initialized = False
    builder.report['hardware_validation'] = {'status':'incomplete','performed_this_build':False,
        'artifact_sha256':builder.report['artifact_sha256'],'historical_evidence_inherited':False}
    try:
        remote(args,"import pathlib,sys\np=pathlib.Path(sys.argv[1]);p.mkdir(mode=0o700);(p/'release-owner-token').write_text(sys.argv[2])\n",[REMOTE,token])
        initialized = True
        for path in [builder.artifact,args.smoke_fixtures,ROOT/'scripts/test-frame-inspector-native.py']:
            result = subprocess.run(['scp',*ssh(args),str(path),args.ssh_target+':'+REMOTE+'/'],capture_output=True,text=True,timeout=180)
            if result.returncode:raise ValueError('Frame transfer failed: '+result.stderr[-1600:])
        setup = """import pathlib,sys,hashlib,tarfile
r=pathlib.Path(sys.argv[1]);image=r/sys.argv[2];fixture=r/sys.argv[4]
assert hashlib.sha256(image.read_bytes()).hexdigest()==sys.argv[3],'AppImage transfer hash differs'
assert hashlib.sha256(fixture.read_bytes()).hexdigest()==sys.argv[5],'Fixture transfer hash differs'
with tarfile.open(fixture) as archive:archive.extractall(r/'evidence',filter='data')
print('PASS exact artifact and fixture transfer SHA256')
"""
        remote(args,setup,[REMOTE,builder.artifact.name,builder.report['artifact_sha256'],args.smoke_fixtures.name,sha256(args.smoke_fixtures)],logdir/'transfer.log')
        probe = """import pathlib,sys,os,subprocess,json
r=pathlib.Path(sys.argv[1]);image=r/sys.argv[2];expected=sys.argv[3]
env=dict(os.environ,APPIMAGE_EXTRACT_AND_RUN='1',WEBKIT_DISABLE_DMABUF_RENDERER='1',XDG_CACHE_HOME=str(r/'cache'))
cases=[('release-info',['--lepton-release-info'],0),('job-default',['--lepton-compatibility','448280'],1),
('job-evidence',['--lepton-compatibility','448280','--target-proxy-dir',str(r/'evidence/target'),'--hardware-bundle',str(r/'evidence/hardware-bundle.tar.gz'),'--hardware-results',str(r/'evidence/results')],1),
('partial-evidence',['--lepton-compatibility','448280','--hardware-results',str(r/'evidence/results')],2)]
cli=pathlib.Path.home()/'.local/share/Steam/steamapps/common/Lepton/lepton'
stopped=subprocess.run([str(cli),'exec','steamlaunch-1408230','true'],capture_output=True).returncode!=0
if stopped:cases.append(('walkabout-stopped',['--lepton-compatibility','1408230'],2))
rows=[]
for name,options,exit_code in cases:
 p=subprocess.run([str(image),*options],env=env,capture_output=True,timeout=650)
 (r/(name+'.json')).write_bytes(p.stdout);(r/(name+'.stderr')).write_bytes(p.stderr)
 data=json.loads(p.stdout);assert p.returncode==exit_code,(name,p.returncode,p.stderr)
 if name=='release-info':assert data['release_permissions_valid'] and data['architecture']=='aarch64' and data['production_assets_embedded'] and data['content_security_policy_enabled'] and data['inspector_distribution_only'] and not data['updater_check_allowed']
 if name.startswith('job'):
  assert data['analyzed'] and data['proxy_compatible'] is False
  assert data['provider_sha256']=='345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700'
  assert data['target_specific_forwarding']['generation_status']==('hardware_validated' if name=='job-evidence' else 'not_generated')
 rows.append({'case':name,'exit_code':p.returncode,'status':'passed'})
 print('PASS exact artifact backend: '+name,flush=True)
command=['python3',str(r/'test-frame-inspector-native.py'),'--image',str(image),'--work-dir',str(r),'--expected-image-sha256',expected]
if stopped:command+=['--stopped-appid','1408230']
result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=900)
(r/'native-ui-console.log').write_text(result.stdout+result.stderr)
print(result.stdout,flush=True);assert result.returncode==0,result.stderr
observation=json.loads((r/'native-ui-observation.json').read_text())
assert observation['status']=='passed' and observation['appimage_sha256']==expected
assert len(observation['passed'])==(15 if stopped else 13)
assert subprocess.run([str(cli),'exec','steamlaunch-448280','true'],capture_output=True).returncode==0
(r/'backend-cases.json').write_text(json.dumps(rows,indent=2)+'\\n')
print('PASS exact artifact native GUI and authoritative final Job probe',flush=True)
"""
        builder.report['hardware_validation']['performed_this_build'] = True
        remote(args,probe,[REMOTE,builder.artifact.name,builder.report['artifact_sha256']],logdir/'console.log')
        for pattern in ['*.json','*.stderr','*.log']:
            result = subprocess.run(['scp',*ssh(args),args.ssh_target+':'+REMOTE+'/'+pattern,str(logdir)+'/'],capture_output=True,text=True,timeout=60)
            if result.returncode:raise ValueError('Cannot collect complete Frame smoke logs: '+result.stderr)
        observation = json.loads((logdir/'native-ui-observation.json').read_text())
        evidence_files = {p.name:sha256(p) for p in sorted(logdir.iterdir()) if p.is_file()}
        builder.report['hardware_validation'].update(status='passed',
            native_gui_checks=len(observation['passed']), backend_cases=json.loads((logdir/'backend-cases.json').read_text()),
            measured_at=observation['measured_at'], evidence_sha256=evidence_files,
            evidence_source='frame-smoke/', scope='This exact AppImage read-only inspector/backend; historical function harness evidence verified separately')
    except Exception:
        builder.report['hardware_validation']['status']='failed'
        if initialized:
            for pattern in ['*.json','*.stderr','*.log']:
                result=subprocess.run(['scp',*ssh(args),args.ssh_target+':'+REMOTE+'/'+pattern,str(logdir)+'/'],capture_output=True,text=True,timeout=60)
                if result.returncode:
                    (logdir/'log-collection-errors.log').open('a').write(result.stderr+'\n')
        raise
    finally:
        if initialized:
            cleanup = """import pathlib,sys,shutil
r=pathlib.Path(sys.argv[1]);assert (r/'release-owner-token').read_text()==sys.argv[2],'Smoke directory ownership changed; refusing cleanup'
shutil.rmtree(r)
print('Own isolated release smoke directory removed')
"""
            remote(args,cleanup,[REMOTE,token],logdir/'cleanup.log')
