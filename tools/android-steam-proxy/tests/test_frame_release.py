"""Fast release guards; full packaging is a separate integration workflow."""
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import struct
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[3]/'scripts'
sys.path.insert(0,str(SCRIPTS))
import frame_release_utils as release
spec = importlib.util.spec_from_file_location('frame_builder',SCRIPTS/'frame-release.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def elf(machine=183):
    return b'\x7fELF\x02\x01'+bytes(12)+machine.to_bytes(2,'little')+bytes(4)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.appdir = self.root/'Creamlinux.AppDir'
        for name,raw in [('AppRun',b'#!/bin/bash\nexport WEBKIT_DISABLE_DMABUF_RENDERER=1\n'),
                ('AppRun.plugins',b'#!/bin/bash\n'),('AppRun.wrapped',elf()),('usr/bin/creamlinux',elf()),
                ('usr/share/applications/Creamlinux.desktop',b'[Desktop Entry]'),
                ('usr/share/icons/hicolor/128x128/apps/creamlinux.png',b'icon'),
                ('apprun-hooks/linuxdeploy-plugin-gtk.sh',b'gtk'),('apprun-hooks/linuxdeploy-plugin-gstreamer.sh',b'gst'),
                ('usr/lib/Creamlinux/compatibility/release-capabilities.json',b'{"permissions":["core:window:allow-close"]}')]:
            self.put(name,raw)
        for name in release.WEBKIT_HELPERS:
            self.put('usr/lib/aarch64-linux-gnu/webkit2gtk-4.1/'+name,elf())
        runtime = self.appdir/'usr/lib/Creamlinux/compatibility/runtime'
        names = {'bin/llvm-readelf'} | {n for r in release.resources.PACKAGES.values() for n in r['members'].values()}
        manifest = {'architecture':'aarch64','package_sha256':{n:r['sha256'] for n,r in release.resources.PACKAGES.items()},'sha256':{}}
        for name in names:
            path = runtime/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(elf() if name=='libexec/llvm-readobj' else b'fixture')
            path.chmod(0o755)
            manifest['sha256'][name] = release.sha256(path)
        (runtime/'manifest.json').write_text(json.dumps(manifest))
        (runtime/'SHA256SUMS').write_text(''.join(release.sha256(p)+'  '+p.relative_to(runtime).as_posix()+'\n'
            for p in sorted(runtime.rglob('*')) if p.is_file()))

    def put(self,name,raw):
        path = self.appdir/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o755)
        return path

    def test_complete_appdir_has_explicit_architecture_and_exclusion_result(self):
        result = release.validate_appdir(self.appdir)
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['forbidden_conflict_files'],[])
        self.assertEqual(result['aarch64_elf_files'],6)

    def test_each_conflicting_library_is_rejected_even_in_nested_plugins(self):
        for family in release.FORBIDDEN_FAMILIES:
            path=self.put('usr/lib/plugins/'+family+'.so.99',elf())
            with self.subTest(family=family),self.assertRaisesRegex(ValueError,'Forbidden bundled'):
                release.validate_appdir(self.appdir)
            path.unlink()

    def test_architecture_check_rejects_x86_and_non_elf(self):
        for raw in [elf(62),b'not an ELF']:
            path=self.put('usr/bin/creamlinux',raw)
            with self.assertRaisesRegex(ValueError,'ELF64'):
                release.validate_appdir(self.appdir)

    def test_x86_library_hidden_inside_arm_package_is_rejected(self):
        self.put('usr/lib/libunexpected.so',elf(62))
        with self.assertRaisesRegex(ValueError,'ELF64'):
            release.validate_appdir(self.appdir)

    def test_reader_missing_or_corrupt_is_rejected(self):
        path=self.appdir/'usr/lib/Creamlinux/compatibility/runtime/lib/libLLVM.so.20.1'
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):
            release.validate_appdir(self.appdir)

    def test_missing_close_provenance_or_launch_env_is_rejected(self):
        caps=self.appdir/'usr/lib/Creamlinux/compatibility/release-capabilities.json'
        caps.write_text('{"permissions":[]}')
        with self.assertRaisesRegex(ValueError,'close permission'):
            release.validate_appdir(self.appdir)
        caps.write_text('{"permissions":["core:window:allow-close"]}')
        (self.appdir/'AppRun').write_text('exec /bin/true')
        with self.assertRaisesRegex(ValueError,'launch environment'):
            release.validate_appdir(self.appdir)

    def test_game_captures_credentials_and_debug_directories_are_rejected(self):
        for name in ['original-provider.so','usr/lib/libsteam_api.so','apks/base.apk',
                     '.ssh/id_ed25519','node_modules/anything','target/debug/file','data.core','.env']:
            path=self.put(name,b'forbidden')
            with self.subTest(name=name),self.assertRaises(ValueError):
                release.validate_appdir(self.appdir)
            path.unlink()

    def test_external_symlink_is_rejected(self):
        (self.appdir/'escape').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError,'escapes'):
            release.validate_appdir(self.appdir)

    def test_artifact_name_rejects_traversal_and_wrong_architecture(self):
        self.assertEqual(release.artifact_name('1.7.1'),'Creamlinux_1.7.1_steam-frame-inspector_aarch64.AppImage')
        for name in ['../unsafe_aarch64.AppImage','a_x86_64.AppImage','a;bad_aarch64.AppImage']:
            with self.assertRaises(ValueError):release.artifact_name('1.7.1',name)

    def test_environment_overrides_are_parsed_without_mutating_environment(self):
        env={'FRAME_BUILD_CONTAINER':'isolated','FRAME_CONTAINER_USER':'builder',
            'FRAME_RELEASE_OUTPUT':'/tmp/review','SOURCE_DATE_EPOCH':'1234'}
        args=builder.arguments([],env)
        self.assertEqual(args.container,'isolated')
        self.assertEqual(args.container_user,'builder')
        self.assertEqual(args.output_dir,Path('/tmp/review'))
        self.assertEqual(args.source_date_epoch,1234)

    def test_read_only_preflight_disallows_downloading(self):
        with self.assertRaises(SystemExit),patch('sys.stderr'):
            builder.arguments(['--preflight','--prepare-tools'],{})
    def test_strict_builder_uses_pinned_paths_without_login_or_home_wrappers(self):
        obj=builder.Builder(builder.arguments(['--builder-mode','strict'],{}))
        with patch.object(builder,'command',return_value='') as run:
            obj.docker(['cargo','--version'])
        command=run.call_args.args[0]
        self.assertIn('PATH=/opt/node/bin:/opt/rust/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',command)
        self.assertIn('BASH_ENV=',command)
        self.assertNotIn('-lc',command)
        self.assertNotIn('export PATH="$HOME/.cargo/bin:$PATH"; exec "$@"',command)

    def test_missing_tool_fails_before_container_or_output_mutation(self):
        obj=builder.Builder(builder.arguments(['--preflight'],{}))
        with patch.object(builder.shutil,'which',return_value=None),patch.object(builder,'command') as run:
            with self.assertRaisesRegex(ValueError,'Missing required host tool'):
                obj.preflight()
            run.assert_not_called()
        self.assertIsNone(obj.output)

    def test_successful_preflight_reports_passed_without_creating_outputs(self):
        obj=builder.Builder(builder.arguments(['--preflight'],{}))
        with patch.object(obj,'preflight'),patch('builtins.print') as output:
            obj.run()
        data=json.loads(output.call_args.args[0])
        self.assertEqual(data['status'],'passed')
        self.assertTrue(data['preflight_only'])
        self.assertIsNone(obj.output)

    def test_tool_checksum_mismatch_fails_without_network_fallback(self):
        pins={'tools':{'tool':{'sha256':'0'*64,'url':'https://invalid'}},'gtk_patched_sha256':'unused'}
        tool=self.root/'tool';tool.write_text('wrong');tool.chmod(0o755)
        with patch.object(release,'tool_pins',return_value=pins),patch.object(release.urllib.request,'urlopen') as fetch:
            with self.assertRaisesRegex(ValueError,'Missing/corrupt'):
                release.prepare_tools(self.root,download=True)
            fetch.assert_not_called()

    def test_dirty_source_identity_records_content_changes(self):
        source=self.root/'source';source.mkdir();(source/'a.py').write_text('one')
        def git(args):
            call=args[3:]
            if call==['ls-files','-z']:return b'a.py\0'
            if call[:2]==['ls-files','--others']:return b''
            if call[0]=='status':return b' M a.py\n'
            if call[0]=='branch':return b'test\n'
            if call[0]=='rev-parse':return b'abcdef\n'
            raise AssertionError(call)
        with patch.object(release.subprocess,'check_output',side_effect=git):
            first=release.source_identity(source)
            (source/'a.py').write_text('two')
            second=release.source_identity(source)
        self.assertTrue(first['dirty']);self.assertEqual(first['head'],'abcdef')
        self.assertNotEqual(first['snapshot_sha256'],second['snapshot_sha256'])

    def test_normalization_and_inventory_preserve_contents(self):
        before=release.inventory(self.appdir)
        release.normalize(self.appdir,1234)
        self.assertEqual(release.inventory(self.appdir),before)
        self.assertEqual((self.appdir/'AppRun').stat().st_mtime,1234)

    def test_json_manifest_and_checksums_are_stable(self):
        path=self.root/'report.json'
        release.write_json(path,{'artifact':release.artifact_name('1.7.1'),'status':'passed'})
        digest=release.sha256(path)
        release.write_json(path,{'status':'passed','artifact':release.artifact_name('1.7.1')})
        self.assertEqual(release.sha256(path),digest)
        self.assertEqual(json.loads(path.read_text())['status'],'passed')

    def test_remote_smoke_code_writes_parseable_json_newline(self):
        tree=ast.parse((SCRIPTS/'frame_release_smoke.py').read_text())
        codes=[n.value.value for n in ast.walk(tree) if isinstance(n,ast.Assign)
               and any(isinstance(t,ast.Name) and t.id=='probe' for t in n.targets)]
        self.assertEqual(len(codes),1)
        remote=ast.parse(codes[0])
        writes=[n for n in ast.walk(remote) if isinstance(n,ast.Call)
                and isinstance(n.func,ast.Attribute) and n.func.attr=='write_text'
                and n.args and isinstance(n.args[0],ast.BinOp)
                and isinstance(n.args[0].right,ast.Constant)]
        self.assertEqual(len(writes),1)
        self.assertEqual(writes[0].args[0].right.value,'\n')

    def test_development_binary_cannot_pass_packaged_release_validation(self):
        info={'release_permissions_valid':True,'version':'1.7.1','architecture':'aarch64',
              'production_assets_embedded':True,'inspector_distribution_only':True,
              'default_startup_is_legacy':False,'updater_check_allowed':False,'content_security_policy_enabled':True}
        release.require_release_info(info,'1.7.1')
        for key,value in [('production_assets_embedded',False),('architecture','x86_64'),
                          ('release_permissions_valid',False),('version','0.0.0'),
                          ('inspector_distribution_only',False),('default_startup_is_legacy',True),
                          ('updater_check_allowed',True),('content_security_policy_enabled',False)]:
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'Exact packaged binary'):
                release.require_release_info({**info,key:value},'1.7.1')

    def test_non_utf8_tool_banner_is_preserved_without_traceback(self):
        banner=builder.command([sys.executable,'-c',"import sys;sys.stdout.buffer.write(bytes([118,49,183]))"])
        self.assertEqual(banner,'v1'+r'\xb7')

    def test_appimage_extraction_boundary_without_binfmt_appimage_support(self):
        header=bytearray(elf()+bytes(40));header=header[:64]
        header[8:11]=b'AI\x02'
        struct.pack_into('<Q',header,40,64)
        struct.pack_into('<HH',header,58,64,1)
        block=bytearray(96);block[:4]=b'hsqs'
        struct.pack_into('<HH',block,28,4,0)
        struct.pack_into('<Q',block,40,96)
        p=self.root/'fixture.AppImage';p.write_bytes(header+bytes(64)+block)
        self.assertEqual(release.appimage_offset(p),128)
        for raw in [p.read_bytes()[:-1],bytes(header)+bytes(64)+bytes(96),elf()]:
            p.write_bytes(raw)
            with self.assertRaises(ValueError):release.appimage_offset(p)

    def test_truncated_elf_header_cannot_pass_architecture_guard(self):
        p=self.root/'truncated';p.write_bytes(elf()[:19])
        with self.assertRaises(ValueError):release.require_elf(p)

    def test_packaged_desktop_icon_is_required(self):
        (self.appdir/'usr/share/icons/hicolor/128x128/apps/creamlinux.png').unlink()
        with self.assertRaisesRegex(ValueError,'Required release payload absent'):
            release.validate_appdir(self.appdir)

    def test_missing_webkit_processes_fail_static_validation(self):
        for name in release.WEBKIT_HELPERS:
            path=self.appdir/'usr/lib/aarch64-linux-gnu/webkit2gtk-4.1'/name
            data=path.read_bytes();path.unlink()
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'Required release payload absent'):
                release.validate_appdir(self.appdir)
            path.write_bytes(data);path.chmod(0o755)

    def test_webkit_staging_requires_matching_architecture_before_copying(self):
        source=self.root/'webkit';source.mkdir()
        with self.assertRaisesRegex(ValueError,'Missing WebKit helper'):
            release.stage_webkit(source,self.root/'output')
        for name in release.WEBKIT_HELPERS:
            p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(elf());p.chmod(0o755)
        release.stage_webkit(source,self.root/'output')
        self.assertEqual((self.root/'output/usr/lib/aarch64-linux-gnu/webkit2gtk-4.1/WebKitWebProcess').read_bytes(),elf())
        (source/'WebKitWebProcess').write_bytes(elf(62))
        with self.assertRaisesRegex(ValueError,'ELF64'):
            release.stage_webkit(source,self.root/'wrong-output')
        self.assertFalse((self.root/'wrong-output').exists())

    def test_capture_discovery_accepts_nested_and_flat_apk_layouts(self):
        from frame_release_regressions import capture_pair
        capture=self.root/'capture';capture.mkdir()
        self.assertIsNone(capture_pair(capture))
        (capture/'libsteam_api.so').write_bytes(elf())
        with self.assertRaisesRegex(ValueError,'Partial original capture'):
            capture_pair(capture)
        flat=capture/'base.apk';flat.write_bytes(b'fixture')
        self.assertEqual(capture_pair(capture)[1],flat)
        (capture/'apks').mkdir();nested=capture/'apks/base.apk';nested.write_bytes(b'fixture')
        self.assertEqual(capture_pair(capture)[1],nested)

    def test_launch_wrapper_defaults_and_overrides_and_argument_forwarding(self):
        folder=self.root/'folder with spaces';folder.mkdir()
        plugin=folder/'AppRun.plugins'
        plugin.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$WEBKIT_DISABLE_DMABUF_RENDERER" "$@"\n');plugin.chmod(0o755)
        release.write_launch_wrapper(folder)
        env=dict(os.environ);env.pop('WEBKIT_DISABLE_DMABUF_RENDERER',None)
        args=[str(folder/'AppRun'),'--lepton-release-info','argument with spaces']
        result=subprocess.check_output(args,env=env,text=True).splitlines()
        self.assertEqual(result,['1','--lepton-release-info','argument with spaces'])
        env['WEBKIT_DISABLE_DMABUF_RENDERER']='0'
        self.assertEqual(subprocess.check_output(args,env=env,text=True).splitlines()[0],'0')

    def test_release_finish_writes_identity_checksum_and_rejects_artifact_drift(self):
        obj=builder.Builder(builder.arguments([],{}))
        obj.output=self.root/'release';obj.output.mkdir()
        obj.artifact=self.root/'artifact';obj.artifact.write_bytes(b'validated artifact')
        obj.report.update(source={'snapshot_sha256':'source'},artifact_filename=release.artifact_name('1.7.1'),
                          artifact_sha256=release.sha256(obj.artifact))
        with patch.object(builder,'source_identity',return_value={'snapshot_sha256':'source'}),patch('builtins.print'):
            obj.finish()
        manifest=json.loads((obj.output/'release-manifest.json').read_text())
        self.assertEqual(manifest['status'],'passed')
        self.assertFalse(manifest['hardware_validation']['performed_this_build'])
        self.assertEqual(release.sha256(obj.output/manifest['artifact_filename']),manifest['artifact_sha256'])
        self.assertEqual((obj.output/'SHA256SUMS').read_text(),manifest['artifact_sha256']+'  '+manifest['artifact_filename']+'\n')
        obj.artifact.write_bytes(b'changed artifact')
        with patch.object(builder,'source_identity',return_value={'snapshot_sha256':'source'}):
            with self.assertRaisesRegex(ValueError,'Artifact changed'):
                obj.finish()

    def test_failed_frame_probe_collects_logs_before_own_cleanup(self):
        import frame_release_smoke as smoke
        image=self.root/'image';image.write_bytes(b'fixture')
        fixture=self.root/'fixture';fixture.write_bytes(b'evidence')
        events=[]
        def remote(args,code,*rest,**kwargs):
            events.append('cleanup' if 'shutil.rmtree' in code else 'remote')
            if 'job-default' in code:raise ValueError('fixture GUI failure')
            return ''
        def run(argv,**kwargs):
            events.append('collect' if '*.log' in argv[-2] or '*.json' in argv[-2] or '*.stderr' in argv[-2] else 'transfer')
            return subprocess.CompletedProcess(argv,0,'','')
        obj=SimpleNamespace(args=SimpleNamespace(ssh_target='user@frame',ssh_control=None,smoke_fixtures=fixture),
                            output=self.root,artifact=image,report={'artifact_sha256':release.sha256(image)})
        with patch.object(smoke,'remote',side_effect=remote),patch.object(smoke.subprocess,'run',side_effect=run):
            with self.assertRaisesRegex(ValueError,'fixture GUI failure'):smoke.smoke(obj)
        self.assertEqual(obj.report['hardware_validation']['status'],'failed')
        self.assertEqual(events.count('collect'),3)
        self.assertEqual(events[-1],'cleanup')

    def test_expected_remote_failure_has_clean_cli_error_with_trace_in_log(self):
        import frame_release_smoke as smoke
        args=SimpleNamespace(ssh_target='user@frame',ssh_control=None)
        failure=subprocess.CompletedProcess([],1,'','Traceback (most recent call last):\nValueError: missing runtime helper\n')
        log=self.root/'remote.log'
        with patch.object(smoke.subprocess,'run',return_value=failure):
            with self.assertRaisesRegex(ValueError,'missing runtime helper') as caught:
                smoke.remote(args,'pass',log=log)
        self.assertNotIn('Traceback',str(caught.exception))
        self.assertIn('Traceback',log.read_text())

    def test_existing_release_output_is_refused_without_overwriting_its_manifest(self):
        output=self.root/'existing-release';output.mkdir()
        marker=output/'release-manifest.json';original='{"status":"passed","artifact":"keep"}\n';marker.write_text(original)
        (self.root/'tools/android-steam-proxy/build').mkdir(parents=True)
        obj=builder.Builder(builder.arguments(['--output-dir',str(output)],{}))
        with patch.object(builder,'ROOT',self.root),patch.object(obj,'preflight'):
            with self.assertRaisesRegex(ValueError,'Release output already exists'):
                obj.run()
        self.assertEqual(marker.read_text(),original)
        self.assertIsNone(obj.output)
