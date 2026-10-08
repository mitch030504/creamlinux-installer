#!/usr/bin/env python3
"""Ephemeral-key signing rehearsal only. Never publishes or accepts production keys."""
import argparse
import base64
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
from frame_ci import verify
from frame_release_utils import ROOT, sha256, write_json


def updater_metadata(version, signature, url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('Updater artifact URL must be HTTPS without credentials')
    if not signature or '\n' in signature: raise ValueError('Expected base64 Tauri signature')
    decoded=base64.b64decode(signature,validate=True)
    if not decoded.startswith(b'untrusted comment:'): raise ValueError('Invalid Tauri signature envelope')
    return {'version':version,'notes':'Read-only Steam Frame inspector; separate distribution channel.',
        'pub_date':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'platforms':{p:{'signature':signature,'url':url} for p in ['linux-aarch64','linux-aarch64-appimage']}}


def rehearsal(release, destination, url, container=None):
    # Ordinary CI never reads signing secrets, including ones inherited locally.
    if any(os.environ.get(n) for n in ['TAURI_SIGNING_PRIVATE_KEY','TAURI_SIGNING_PRIVATE_KEY_PATH','TAURI_SIGNING_PRIVATE_KEY_PASSWORD']):
        raise ValueError('Signing rehearsal refuses inherited production signing variables')
    report=verify(release)
    destination=Path(destination);destination.mkdir()
    artifact=Path(release)/report['artifact_filename']
    base=ROOT/'tools/android-steam-proxy/build';base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ephemeral-signing-',dir=base) as temp:
        temp=Path(temp);temp.chmod(0o700)
        def run(args):
            if container:
                args=['docker','exec','--user','ubuntu','--workdir','/work',container,
                      *[str(x).replace(str(ROOT),'/work') for x in args]]
            else: args=[str(x) for x in args]
            r=subprocess.run(args,capture_output=True,text=True)
            if r.returncode: raise ValueError('Ephemeral signing/verification command failed; secret-bearing output suppressed')
            return r.stdout
        key=temp/'test-key'
        run(['node','node_modules/.bin/tauri','signer','generate','--ci','--password','','--write-keys',key])
        key.chmod(0o600)
        # Sign an isolated copy, never mutate the verified release directory.
        import shutil
        copied=temp/artifact.name;shutil.copy2(artifact,copied)
        run(['node','node_modules/.bin/tauri','signer','sign','--private-key-path',key,'--password','',copied])
        sig=Path(str(copied)+'.sig').read_text().strip()
        pub=Path(str(key)+'.pub').read_text().strip()
        for name,encoded in [('public-key',pub),('signature',sig)]:
            (temp/name).write_bytes(base64.b64decode(encoded,validate=True))
        verifier=ROOT/'scripts/release/signature-verifier/Cargo.toml'
        run(['cargo','run','--locked','--manifest-path',verifier,'--',copied,temp/'public-key',temp/'signature'])
        copied.write_bytes(b'tampered artifact')
        try: run(['cargo','run','--locked','--manifest-path',verifier,'--',copied,temp/'public-key',temp/'signature'])
        except ValueError: pass
        else: raise ValueError('Tampered artifact incorrectly accepted')
        write_json(destination/'inspector-latest.prepared.json',updater_metadata(report['version'],sig,url))
        (destination/'test-public-key.txt').write_text(pub+'\n')
        (destination/(artifact.name+'.sig')).write_text(sig+'\n')
        write_json(destination/'signing-rehearsal.json',{'status':'passed','ephemeral_key':True,'production_credentials_used':False,
            'published':False,'artifact_sha256':report['artifact_sha256'],'signature_verified':True,'tampered_artifact_rejected':True,
            'channel':'separate inspector channel; updater disabled in current Frame binary'})
    return {'status':'passed','production_credentials_used':False,'published':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('release',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--url',required=True);p.add_argument('--container')
    a=p.parse_args();print(json.dumps(rehearsal(a.release,a.output,a.url,a.container)))
if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError) as e:
        print('Signing preparation failed: '+str(e),file=sys.stderr);sys.exit(2)
