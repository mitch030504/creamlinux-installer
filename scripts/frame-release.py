#!/usr/bin/env python3
"""Fail-closed ARM64 inspector release orchestration; never publishes releases."""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
import tomllib

from frame_release_utils import (ROOT, appimage_offset, artifact_name, inventory, normalize, prepare_tools,
    require_elf, require_release_info, resources, sha256, source_identity, tool_pins, validate_appdir, write_json, write_launch_wrapper)


def command(args, cwd=ROOT, log=None, env=None, timeout=1800):
    if log:
        with Path(log).open('w') as stream:
            result = subprocess.run([str(x) for x in args], cwd=cwd, env=env,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        if result.returncode:
            raise ValueError(f'Command failed ({result.returncode}); inspect {log}')
        return ''
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=env, capture_output=True,
                            text=True, errors='backslashreplace', timeout=timeout)
    if result.returncode:
        raise ValueError(f'{shlex.join([str(x) for x in args])} failed ({result.returncode}): {(result.stderr or result.stdout).strip()[:1600]}')
    return result.stdout.strip()


def arguments(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', default=environ.get('FRAME_BUILD_CONTAINER', 'creamlinux-arm64-lepton-validation'))
    parser.add_argument('--container-user', default=environ.get('FRAME_CONTAINER_USER', 'ubuntu'))
    parser.add_argument('--container-workdir', default=environ.get('FRAME_CONTAINER_WORKDIR', '/work'))
    parser.add_argument('--tools-dir', type=Path, default=Path(environ.get('FRAME_RELEASE_TOOLS_DIR', ROOT/'tools/android-steam-proxy/build/release-tools')))
    parser.add_argument('--llvm-cache', type=Path, default=Path(environ.get('FRAME_LLVM_CACHE', ROOT/'tools/android-steam-proxy/build/llvm-runtime')))
    parser.add_argument('--output-dir', type=Path, default=environ.get('FRAME_RELEASE_OUTPUT'))
    parser.add_argument('--artifact-name', default=environ.get('FRAME_RELEASE_NAME'))
    parser.add_argument('--prepare-tools', action='store_true', help='Fetch only missing checksum-pinned build inputs before preflight')
    parser.add_argument('--capture-root', type=Path, default=environ.get('FRAME_CAPTURE_ROOT'), help='Optional private capture directory with one APPID subdirectory per game; never bundled')
    parser.add_argument('--builder-mode', choices=['strict','development'], default=environ.get('FRAME_BUILDER_MODE','development'))
    parser.add_argument('--preflight', action='store_true', help='Read-only dependency checks; no output, downloads, container start or build')
    parser.add_argument('--smoke', action='store_true', help='Measure this exact artifact on the supplied Frame using read-only entrypoints')
    parser.add_argument('--ssh-target', default=environ.get('FRAME_SSH_TARGET'))
    parser.add_argument('--ssh-control', default=environ.get('FRAME_SSH_CONTROL'))
    parser.add_argument('--smoke-fixtures', type=Path, default=Path(environ.get('FRAME_SMOKE_FIXTURES', ROOT/'tools/android-steam-proxy/build/frame-inspector-results/validation-artifacts.tar.gz')))
    parser.add_argument('--source-date-epoch', type=int, default=environ.get('SOURCE_DATE_EPOCH'))
    args = parser.parse_args(argv)
    if args.preflight and args.prepare_tools:
        parser.error('--preflight is read-only; run --prepare-tools as part of a build instead')
    if args.smoke and not args.ssh_target:
        parser.error('--smoke requires --ssh-target or FRAME_SSH_TARGET')
    return args


class Builder:
    def __init__(self, args):
        self.args = args
        self.managed_container = False
        self.output = None
        self.stage = None
        self.report = {'schema_version': 1, 'status': 'incomplete', 'architecture': 'aarch64',
            'build_timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'build_host_architecture': platform.machine(), 'stages': [], 'tests': {},
            'hardware_validation': {'status': 'not_run', 'performed_this_build': False,
                'artifact_sha256': None, 'historical_evidence_inherited': False},
            'historical_behavioral_reference': {'artifact_filename': 'Creamlinux_1.7.1_steam-frame-inspector_aarch64.AppImage',
                'sha256': 'cb5f6616e264139aa9bbc1bcecd49004c00a61afb0965e2777328435a575ec85',
                'status': 'reference_only', 'rerun_for_this_build': False}}

    def inside(self, path):
        path = Path(path).resolve()
        if path == ROOT:
            return self.args.container_workdir
        if ROOT not in path.parents:
            raise ValueError('Container build input must be inside mounted repository: '+str(path))
        return str(Path(self.args.container_workdir)/path.relative_to(ROOT))

    def docker(self, args, cwd=ROOT, log=None):
        prefix = ['docker', 'exec', '--user', self.args.container_user, '--workdir', self.inside(cwd),
            '--env', 'TZ=UTC', '--env', 'LANG=C.UTF-8']
        if self.args.source_date_epoch is not None:
            prefix += ['--env', 'SOURCE_DATE_EPOCH='+str(self.args.source_date_epoch)]
        for name in ['CARGO_PROFILE_DEV_DEBUG','CARGO_PROFILE_TEST_DEBUG','CARGO_INCREMENTAL']:
            if name in os.environ: prefix += ['--env',name+'='+os.environ[name]]
        strict = self.args.builder_mode == 'strict'
        if strict:
            prefix += ['--env','PATH=/opt/node/bin:/opt/rust/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                       '--env','BASH_ENV=','--env','ENV=']
        # Fixed shell code; all caller paths/options remain separate argv values.
        prefix += [self.args.container, 'bash', '-c' if strict else '-lc',
                   'exec "$@"' if strict else 'export PATH="$HOME/.cargo/bin:$PATH"; exec "$@"', 'frame-build']
        return command(prefix + [str(x) for x in args], log=log)

    def step(self, name, action):
        print('Frame release: '+name, flush=True)
        started = time.monotonic()
        action()
        self.report['stages'].append({'name': name, 'status': 'passed',
                                     'elapsed_seconds': round(time.monotonic()-started, 3)})

    def preflight(self):
        if platform.machine() != 'x86_64':
            raise ValueError('This workflow requires an x86_64 controller for pinned appimagetool/NDK; use a documented x86_64 build host')
        for name in ['python3', 'docker', 'git', 'ar', 'patch', 'clang', 'ld.lld', 'llvm-readelf', 'readelf']:
            if not shutil.which(name):
                raise ValueError(f'Missing required host tool {name}; install documented controller prerequisites before building')
        if sys.version_info < (3,11):
            raise ValueError('Python >= 3.11 required')
        inspect = json.loads(command(['docker','inspect',self.args.container]))[0]
        from frame_sdk import validate_runtime_environment
        overrides=validate_runtime_environment(dict(v.split('=',1) for v in inspect['Config'].get('Env',[])),
                                               self.args.builder_mode=='strict')
        self.report['unsafe_runtime_override_names']=overrides
        if not any(m.get('Source') == str(ROOT) and m.get('Destination') == self.args.container_workdir
                   and m.get('RW') for m in inspect['Mounts']):
            raise ValueError('Build container must bind this live repository read/write at '+self.args.container_workdir)
        if not inspect['State']['Running']:
            if self.args.preflight:
                raise ValueError(f'Build container is stopped; run docker start {self.args.container} before read-only preflight')
            command(['docker','start',self.args.container])
            self.managed_container = True
        if self.docker(['uname','-m']) != 'aarch64':
            raise ValueError('Container must execute AArch64; enable QEMU/binfmt on the build controller')
        for name in ['node','npm','rustc','cargo','pkg-config','patchelf','unsquashfs','dpkg-query','ldd']:
            try:
                self.docker(['bash','-c','command -v "$1"','container-tool-check',name])
            except ValueError as error:
                raise ValueError('Missing required container tool '+name+'; provision the documented ARM64 build environment') from error
        if not (ROOT/'node_modules/.bin/tauri').is_file():
            raise ValueError('ARM64 frontend dependencies missing; run npm ci inside the documented build container')
        missing = json.loads(self.docker(['node','-e',
            "const names=['vite','esbuild','react','typescript','@tauri-apps/cli','@tauri-apps/cli-linux-arm64-gnu'];"
            "const missing=names.filter(x=>{try{require.resolve(x);return false}catch{return true}});console.log(JSON.stringify(missing))"]))
        if missing:
            raise ValueError('Missing ARM64 frontend dependencies '+', '.join(missing)+'; run npm ci inside the documented build container')
        versions = {'node': self.docker(['node','--version']), 'npm': self.docker(['npm','--version']),
            'rustc': self.docker(['rustc','--version']), 'cargo': self.docker(['cargo','--version']),
            'tauri_cli': self.docker(['node','node_modules/.bin/tauri','--version']),
            'gtk_webkit': self.docker(['pkg-config','--modversion','gtk+-3.0','webkit2gtk-4.1']),
            'patchelf': self.docker(['patchelf','--version']),
            'unsquashfs': self.docker(['python3','-c',
                "import subprocess; r=subprocess.run(['unsquashfs','-version'],capture_output=True,text=True); "
                "s=r.stdout or r.stderr; assert r.returncode in (0,1) and s.startswith('unsquashfs version '),s; print(s.splitlines()[0])"]),
            'host_python': sys.version.split()[0], 'host_llvm': command(['llvm-readelf','--version'])}
        self.docker(['bash','-c','test -d /usr/lib/aarch64-linux-gnu/gstreamer-1.0 && command -v dpkg-query && command -v ldd'])
        self.docker(['python3','-c',
            "from pathlib import Path; p=Path('/usr/lib/aarch64-linux-gnu/webkit2gtk-4.1'); "
            "names=['WebKitNetworkProcess','WebKitWebProcess','injected-bundle/libwebkit2gtkinjectedbundle.so']; "
            "missing=[n for n in names if not (p/n).is_file()]; "
            "assert not missing,'Missing matching WebKit subprocess helpers: '+str(missing)+'; provision ARM64 libwebkit2gtk-4.1'"])
        ndk = os.environ.get('ANDROID_NDK_HOME') or os.environ.get('ANDROID_NDK_ROOT')
        if not ndk or not (Path(ndk)/'toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android21-clang').is_file():
            raise ValueError('Full Python gate requires ANDROID_NDK_HOME with linux-x86_64 ARM64 clang; set the documented external NDK path')
        versions['android_ndk'] = (Path(ndk)/'source.properties').read_text().strip()
        self.report['tool_versions'] = versions
        self.report['cargo_environment']={n:os.environ.get(n) for n in ['CARGO_PROFILE_DEV_DEBUG','CARGO_PROFILE_TEST_DEBUG','CARGO_INCREMENTAL']}
        self.report['pinned_controller_inputs']=json.loads((ROOT/'scripts/release/controller.json').read_text())
        self.report['build_environment'] = {'container':self.args.container, 'container_user':self.args.container_user,'container_workdir':self.args.container_workdir,
            'image_id':inspect['Image'], 'configured_image':inspect['Config']['Image'],
            'system_package_inventory_sha256': None, 'reuses_existing_container':True}
        self.packages = self.docker(['dpkg-query','-W','-f=${binary:Package}\t${Version}\n'])
        import hashlib
        self.report['build_environment']['system_package_inventory_sha256'] = hashlib.sha256((self.packages+'\n').encode()).hexdigest()
        from frame_sdk import validate_identity, SDK_FILES
        label=(inspect['Config'].get('Labels') or {}).get('org.creamlinux.sdk.source')
        embedded=None
        if label:
            embedded=self.docker(['python3','-c',
                "import hashlib,json,pathlib,sys;p=pathlib.Path('/opt/frame-sdk'); "
                "print(hashlib.sha256(json.dumps({n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in sys.argv[1:]},sort_keys=True).encode()).hexdigest())",*SDK_FILES])
        self.report['builder_identity']=validate_identity(label,embedded,self.packages+'\n',versions,
                                                        self.args.builder_mode=='strict',command(['docker','diff',self.args.container]).splitlines())
        self.report['builder_identity']['image_id']=inspect['Image']
        self.report['ci']={name:os.environ.get(name) for name in
            ['GITHUB_ACTIONS','GITHUB_WORKFLOW','GITHUB_WORKFLOW_REF','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT',
             'GITHUB_REPOSITORY','GITHUB_SHA','GITHUB_REF','GITHUB_REF_NAME','RUNNER_OS','RUNNER_ARCH','RUNNER_NAME','ImageOS','ImageVersion']}
        self.report['pinned_build_tools'] = prepare_tools(self.args.tools_dir, self.args.prepare_tools)
        for name,record in resources.PACKAGES.items():
            path = self.args.llvm_cache/(name+'.deb')
            if not path.exists() and self.args.prepare_tools:
                # Existing audited builder performs the bounded pinned downloads.
                break
            if not path.is_file() or sha256(path) != record['sha256']:
                raise ValueError(f'Missing/corrupt pinned LLVM package {path}; use --prepare-tools to fetch missing inputs')
        package = json.loads((ROOT/'package.json').read_text())
        tauri = json.loads((ROOT/'src-tauri/tauri.conf.json').read_text())
        cargo = tomllib.loads((ROOT/'src-tauri/Cargo.toml').read_text())
        version = package['version']
        if tauri['version'] != version or cargo['package']['version'] != version:
            raise ValueError('package.json, tauri.conf.json and Cargo.toml release versions differ; use the existing set-version script first')
        self.report['version'] = version
        self.report['artifact_filename'] = artifact_name(version,self.args.artifact_name)
        if self.args.source_date_epoch is None:
            self.args.source_date_epoch = int(command(['git','show','-s','--format=%ct','HEAD']))
        if self.args.source_date_epoch < 0:
            raise ValueError('SOURCE_DATE_EPOCH must be nonnegative')
        self.report['source_date_epoch'] = self.args.source_date_epoch
        if self.args.smoke:
            from frame_release_smoke import smoke_preflight
            smoke_preflight(self.args)

    def reserve(self):
        base = ROOT/'tools/android-steam-proxy/build'
        (base/'release-work').mkdir(exist_ok=True)
        self.stage = Path(tempfile.mkdtemp(prefix='run-',dir=base/'release-work'))
        destination = (self.args.output_dir or base/'releases'/self.stage.name).resolve()
        if destination.exists():
            raise ValueError('Release output already exists; choose a fresh output directory: '+str(destination))
        destination.mkdir(parents=True)
        # Failure reporting may write only a directory this invocation created.
        self.output = destination
        (self.output/'logs').mkdir()
        self.report['source'] = source_identity(ROOT)
        write_json(self.output/'source-inputs.json',self.report['source'])
        (self.output/'build-packages.tsv').write_text(self.packages+'\n')

    def prepare_runtime(self):
        runtime = self.stage/'llvm-runtime'
        command([sys.executable, ROOT/'tools/android-steam-proxy/build_llvm_runtime.py',
            '--cache',self.args.llvm_cache,'--output',runtime,
            *(['--download'] if self.args.prepare_tools else [])], log=self.output/'logs/llvm-runtime.log')
        resources.verify(runtime)
        resources.stage(runtime,ROOT/'src-tauri/resources/compatibility/runtime')
        self.report['llvm_runtime'] = {'manifest_sha256':sha256(runtime/'manifest.json'),
            'manifest':json.loads((runtime/'manifest.json').read_text()), 'installed_packages_on_frame':False}

    def tests(self):
        command([sys.executable,ROOT/'scripts/release/run_python_tests.py',ROOT/'tools/android-steam-proxy/tests',
                 self.output/'python-tests.json'],log=self.output/'logs/python-tests.log')
        python = json.loads((self.output/'python-tests.json').read_text())
        critical_skips = [s for s in python['skipped'] if s['reason'] != 'local capture unavailable']
        if critical_skips:
            raise ValueError('Required Python test dependencies caused skips: '+repr(critical_skips))
        self.report['tests']['python'] = python
        self.docker(['cargo','test','--locked','--features','frame-inspector-only','--','--test-threads=2'],cwd=ROOT/'src-tauri',log=self.output/'logs/rust-tests.log')
        text = (self.output/'logs/rust-tests.log').read_text()
        match = re.search(r'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;',text)
        if not match or int(match[2]) or int(match[3]):
            raise ValueError('Rust test summary absent, failed or ignored')
        self.report['tests']['rust'] = {'status':'passed','passed':int(match[1]),'failed':int(match[2]),'ignored':int(match[3])}
        self.docker(['npm','run','test:lepton-ui'],log=self.output/'logs/rendering-tests.log')
        text = (self.output/'logs/rendering-tests.log').read_text()
        counts = {name:int(re.search(r'# '+name+r' (\d+)',text)[1]) for name in ['tests','pass','fail','skipped']}
        if counts['fail'] or counts['skipped'] or not counts['tests']:
            raise ValueError('Rendering gate incomplete')
        self.report['tests']['rendering'] = {'status':'passed',**counts}
        command(['git','diff','--check'],log=self.output/'logs/diff-check.log')
        self.report['tests']['diff_check'] = 'passed'

    def build(self):
        self.docker(['npm','run','tauri','build','--','--ci','--config','src-tauri/tauri.frame.conf.json',
            '--no-bundle','--features','custom-protocol,frame-inspector-only','--','--locked'],log=self.output/'logs/tauri-build.log')
        require_elf(ROOT/'src-tauri/target/release/creamlinux')

    def deploy(self):
        self.appdir = self.stage/'Creamlinux.AppDir'
        (self.appdir/'usr/bin').mkdir(parents=True)
        shutil.copy2(ROOT/'src-tauri/target/release/creamlinux',self.appdir/'usr/bin/creamlinux')
        compat = self.appdir/'usr/lib/Creamlinux/compatibility'
        resources.stage(self.stage/'llvm-runtime',compat/'runtime')
        shutil.copy2(ROOT/'src-tauri/capabilities/frame-inspector.json',compat/'release-capabilities.json')
        write_json(compat/'release-source.json',{'head':self.report['source']['head'],
            'source_snapshot_sha256':self.report['source']['snapshot_sha256'],
            'version':self.report['version'],'architecture':'aarch64','source_date_epoch':self.args.source_date_epoch})
        shutil.copy2(ROOT/'src-tauri/icons/128x128.png',self.appdir/'creamlinux.png')
        installed_icon = self.appdir/'usr/share/icons/hicolor/128x128/apps/creamlinux.png'
        installed_icon.parent.mkdir(parents=True)
        shutil.copy2(self.appdir/'creamlinux.png',installed_icon)
        desktop = self.appdir/'usr/share/applications/Creamlinux.desktop'
        desktop.parent.mkdir(parents=True)
        desktop.write_text('[Desktop Entry]\nName=Creamlinux Steam Frame Inspector\nNoDisplay=true\nExec=creamlinux\nIcon=creamlinux\nType=Application\nTerminal=false\nCategories=Utility;\nStartupWMClass=creamlinux\n')
        self.docker(['python3','-c',
            "import sys;sys.path.insert(0,sys.argv[1]);from frame_release_utils import stage_webkit;stage_webkit(sys.argv[2],sys.argv[3])",
            self.inside(ROOT/'scripts'),'/usr/lib/aarch64-linux-gnu/webkit2gtk-4.1',self.inside(self.appdir)])
        private = self.stage/'tools'
        private.mkdir()
        for name in tool_pins()['tools']:
            shutil.copy2(self.args.tools_dir/name,private/name)
        command(['patch','--batch','--forward',private/'linuxdeploy-plugin-gtk.sh',ROOT/'scripts/release/gtk-tauri.patch'],log=self.output/'logs/gtk-patch.log')
        if sha256(private/'linuxdeploy-plugin-gtk.sh') != tool_pins()['gtk_patched_sha256']:
            raise ValueError('GTK workaround did not produce the validated pinned plugin')
        deployment = private/'linuxdeploy-extracted'
        self.docker(['unsquashfs','-no-progress','-processors','1','-o',str(appimage_offset(private/'linuxdeploy-aarch64.AppImage')),
            '-d',self.inside(deployment),self.inside(private/'linuxdeploy-aarch64.AppImage')],log=self.output/'logs/linuxdeploy-extraction.log')
        for name in ['linuxdeploy-plugin-gtk.sh','linuxdeploy-plugin-gstreamer.sh']:
            shutil.copy2(private/name,deployment/'usr/bin'/name)
        deploy_binary = deployment/'usr/bin/linuxdeploy'
        self.report['tool_versions']['linuxdeploy'] = self.docker([self.inside(deploy_binary),'--version'])
        self.report['tool_versions']['appimagetool'] = command(['env','APPIMAGE_EXTRACT_AND_RUN=1',private/'appimagetool-x86_64.AppImage','--version'])
        shutil.copy2(private/'AppRun-aarch64',self.appdir/'AppRun')
        self.docker(['env','APPIMAGE_EXTRACT_AND_RUN=1','DEPLOY_GTK_VERSION=3',self.inside(deploy_binary),
            '--appdir',self.inside(self.appdir),'--executable',self.inside(self.appdir/'usr/bin/creamlinux'),
            '--desktop-file',self.inside(desktop),'--icon-file',self.inside(self.appdir/'creamlinux.png'),
            '--plugin','gtk','--plugin','gstreamer'],log=self.output/'logs/linuxdeploy.log')
        self.docker(['patchelf','--set-rpath','$ORIGIN/../lib',self.inside(self.appdir/'usr/bin/creamlinux')])
        # Preserve linuxdeploy's plugin hooks/native AppRun, with a Frame default.
        (self.appdir/'AppRun').rename(self.appdir/'AppRun.plugins')
        write_launch_wrapper(self.appdir)
        icon = self.appdir/'.DirIcon'
        if icon.is_symlink() or icon.exists(): icon.unlink()
        icon.symlink_to('creamlinux.png')
        self.artifact = self.stage/self.report['artifact_filename']
        env = dict(os.environ, APPIMAGETOOL=str(self.args.tools_dir/'appimagetool-x86_64.AppImage'),
            FRAME_APPIMAGE_RUNTIME=str(self.args.tools_dir/'runtime-aarch64'), SOURCE_DATE_EPOCH=str(self.args.source_date_epoch),
            FRAME_PACKAGE_PREPARE_ONLY='1')
        command(['bash',ROOT/'scripts/package-steam-frame-appimage.sh',self.appdir,self.artifact],
            log=self.output/'logs/package-preparation.log',env=env)
        normalize(self.appdir,self.args.source_date_epoch)
        env.pop('FRAME_PACKAGE_PREPARE_ONLY')
        command(['bash',ROOT/'scripts/package-steam-frame-appimage.sh',self.appdir,self.artifact],
            log=self.output/'logs/appimagetool.log',env=env)

    def validate(self):
        require_elf(self.artifact)
        if not os.access(self.artifact,os.X_OK):raise ValueError('AppImage is not executable')
        check = validate_appdir(self.appdir)
        write_json(self.output/'appdir-inventory.json',check.pop('inventory'))
        self.report['static_validation'] = check
        extracted = self.stage/'extracted'
        extracted.mkdir()
        self.docker(['unsquashfs','-no-progress','-processors','1','-o',str(appimage_offset(self.artifact)),
            '-d',self.inside(extracted/'squashfs-root'),self.inside(self.artifact)],log=self.output/'logs/appimage-extract.log')
        self.extracted = extracted/'squashfs-root'
        extracted_check = validate_appdir(self.extracted)
        original = json.loads((self.output/'appdir-inventory.json').read_text())
        if original != extracted_check['inventory']:
            raise ValueError('Extracted AppImage inventory differs from validated AppDir')
        self.report['static_validation']['extraction_inventory_match'] = True
        rejected=self.docker(['python3','-c',
            "import subprocess,sys;r=subprocess.run([sys.argv[1]],capture_output=True);assert r.returncode==2 and b'Legacy startup is disabled' in r.stderr;print('passed')",
            self.inside(self.extracted/'usr/bin/creamlinux')])
        self.report['static_validation']['default_legacy_startup_rejected']=rejected=='passed'
        info = json.loads(self.docker([self.inside(self.extracted/'AppRun'),'--lepton-release-info']))
        require_release_info(info,self.report['version'])
        if not info.get('inspector_distribution_only') or info.get('default_startup_is_legacy') or info.get('updater_check_allowed'):
            raise ValueError('Frame distribution must enforce read-only entrypoints')
        self.report['static_validation']['resolved_tauri_acl'] = info
        self.report['artifact_sha256'] = sha256(self.artifact)
        self.report['artifact_size_bytes'] = self.artifact.stat().st_size

    def regressions(self):
        from frame_release_regressions import captured_regressions
        self.report['captured_game_regressions']={'status':'failed','performed':False}
        rows=captured_regressions(self)
        self.report['tests']['captured_six_game']=rows
        self.report['captured_game_regressions']={'status':'performed' if any(r['status']=='passed' for r in rows) else 'unavailable',
            'performed':any(r['status']=='passed' for r in rows),'passed':sum(r['status']=='passed' for r in rows),'unavailable':sum(r['status']=='not_run' for r in rows)}

    def finish(self):
        if self.args.builder_mode=='strict':
            from frame_sdk import validate_identity
            validate_identity(self.report['builder_identity']['sdk_source_sha256'],self.report['builder_identity']['sdk_source_sha256'],
                self.docker(['dpkg-query','-W','-f=${binary:Package}\t${Version}\n'])+'\n',
                {n:self.docker([n,'--version']) for n in ['node','npm','rustc','cargo']},True,
                command(['docker','diff',self.args.container]).splitlines())
        current = source_identity(ROOT)
        if current['snapshot_sha256'] != self.report['source']['snapshot_sha256']:
            raise ValueError('Source inputs changed during release; outputs remain incomplete, rerun from stable source')
        if sha256(self.artifact) != self.report['artifact_sha256']:
            raise ValueError('Artifact changed after validation; refusing release publication')
        shutil.copy2(self.artifact,self.output/self.report['artifact_filename'])
        (self.output/'SHA256SUMS').write_text(self.report['artifact_sha256']+'  '+self.report['artifact_filename']+'\n')
        self.report['status'] = 'passed'
        from frame_ci import provenance
        write_json(self.output/'provenance.json',provenance(self.report,self.output))
        write_json(self.output/'release-manifest.json',self.report)
        print('PASS Frame release: '+str(self.output/self.report['artifact_filename']),flush=True)

    def run(self):
        try:
            self.preflight()
            if self.args.preflight:
                print(json.dumps({**self.report,'status':'passed','preflight_only':True},indent=2))
                return
            self.reserve()
            for name, action in [('prepare pinned LLVM runtime',self.prepare_runtime),('complete test gates',self.tests),
                ('Tauri ARM64 no-bundle build',self.build),('fresh AppDir and manual linuxdeploy',self.deploy),
                ('static extraction/runtime validation',self.validate),('available captured game regressions',self.regressions)]:
                self.step(name,action)
            if self.args.smoke:
                from frame_release_smoke import smoke
                self.step('exact artifact Steam Frame smoke',lambda:smoke(self))
            self.finish()
        except Exception as error:
            self.report['status'] = 'failed'
            self.report['error'] = str(error)
            if self.output and self.output.exists():write_json(self.output/'release-manifest.json',self.report)
            raise
        finally:
            if self.managed_container:command(['docker','stop',self.args.container])


def main():
    try:
        Builder(arguments()).run()
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print('Frame release failed: '+str(error),file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
