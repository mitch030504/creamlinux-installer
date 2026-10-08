"""CI and frozen SDK guards; no Docker build in the unit suite."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'scripts'))
import frame_ci as ci
import frame_sdk as sdk
import frame_signing as signing
from frame_release_utils import ROOT,sha256,write_json

class FrozenSdkTests(unittest.TestCase):
    def setUp(self):
        self.packages=(sdk.SDK/'packages.tsv').read_text()
        self.versions={'node':'v22.16.0','npm':'10.9.9','rustc':'rustc 1.96.0 (hash date)','cargo':'cargo 1.96.0 (hash date)'}
    def validate(self,**kwargs):
        return sdk.validate_identity(kwargs.get('label',sdk.source_hash()),kwargs.get('embedded',sdk.source_hash()),
            kwargs.get('packages',self.packages),kwargs.get('versions',self.versions),kwargs.get('strict',True),kwargs.get('changes',()))
    def test_approved_definition_and_inventory(self):self.assertTrue(self.validate()['approved'])
    def test_inventory_drift_fails(self):
        with self.assertRaisesRegex(ValueError,'inventory drift'):self.validate(packages=self.packages+'extra\t1\n')
    def test_sdk_definition_drift_fails(self):
        with self.assertRaisesRegex(ValueError,'definition'):self.validate(label='bad')
    def test_embedded_definition_drift_fails(self):
        with self.assertRaisesRegex(ValueError,'definition'):self.validate(embedded='bad')
    def test_system_file_drift_fails(self):
        with self.assertRaisesRegex(ValueError,'root filesystem drift'):self.validate(changes=['C /usr/lib/libssl.so'])
    def test_user_and_temporary_caches_are_allowed(self):
        self.assertTrue(self.validate(changes=['C /home','A /home/ubuntu/.cargo','A /tmp/runtime-cache'])['approved'])
    def test_node_drift_fails(self):
        v=dict(self.versions,node='v23.0.0')
        with self.assertRaisesRegex(ValueError,'Node/npm'):self.validate(versions=v)
    def test_rust_drift_fails(self):
        v=dict(self.versions,cargo='cargo 1.95.0 (hash date)')
        with self.assertRaisesRegex(ValueError,'Rust/Cargo'):self.validate(versions=v)
    def test_development_override_is_explicit(self):
        result=self.validate(label=None,embedded=None,strict=False)
        self.assertEqual(result['mode'],'development');self.assertFalse(result['approved']);self.assertTrue(result['override_reasons'])
    def test_runtime_overrides_are_rejected_without_exposing_values(self):
        for name in ['LD_PRELOAD','RUSTC_WRAPPER','NODE_OPTIONS','BASH_ENV']:
            with self.assertRaises(ValueError) as error:
                sdk.validate_runtime_environment({name:'private-test-value'})
            self.assertIn(name,str(error.exception));self.assertNotIn('private-test-value',str(error.exception))
    def test_development_runtime_override_names_are_explicit(self):
        self.assertEqual(sdk.validate_runtime_environment({'RUSTFLAGS':'private-test-value'},False),['RUSTFLAGS'])
        self.assertEqual(sdk.validate_runtime_environment({'HOME':'/tmp/private','CARGO_INCREMENTAL':'0'}),[])
    def test_base_and_downloads_are_digest_pinned(self):
        lock=json.loads((sdk.SDK/'sdk-lock.json').read_text())
        self.assertRegex(lock['base_image'],r'@sha256:[a-f0-9]{64}$')
        self.assertRegex(lock['binfmt_image'],r'@sha256:[a-f0-9]{64}$')
        for n in ['node','rust','npm']:self.assertRegex(lock[n]['sha256'],r'^[a-f0-9]{64}$')
    def test_sdk_replaces_vulnerable_bootstrap_npm_without_node_tar(self):
        s=(sdk.SDK/'provision.py').read_text()
        self.assertIn("lock['npm']",s)
        self.assertIn("filter='data'",s)
        self.assertNotIn("'npm','install'",s)
        lock=json.loads((sdk.SDK/'sdk-lock.json').read_text())
        self.assertEqual(lock['node']['npm'],lock['npm']['version'])
        self.assertEqual(lock['npm']['version'],'10.9.9')
    def test_docker_context_is_minimal(self):
        d=(sdk.SDK/'Dockerfile').read_text()
        self.assertNotIn('COPY . ',d);self.assertIn('USER ubuntu',d)
        self.assertIn('frame-sdk/provision.py',d)
    def test_all_embedded_sdk_files_survive_dockerignore(self):
        allowed=set((sdk.SDK/'.dockerignore').read_text().splitlines())
        for name in sdk.SDK_FILES:self.assertIn('!'+name,allowed)
    def test_snapshot_is_fixed_and_signed(self):
        s=(sdk.SDK/'ubuntu.sources').read_text()
        self.assertIn('20260927T020000Z',s);self.assertIn('Signed-By:',s)

class CiArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.artifact=self.root/'Test_aarch64.AppImage';self.artifact.write_bytes(b'unit artifact')
        self.report={'status':'passed','artifact_filename':self.artifact.name,'artifact_sha256':sha256(self.artifact),'artifact_size_bytes':self.artifact.stat().st_size,
            'source':{'head':'commit','dirty':True,'snapshot_sha256':hashlib.sha256(b'{}').hexdigest(),'files':{}},'source_date_epoch':42,
            'builder_identity':sdk.validate_identity(sdk.source_hash(),sdk.source_hash(),(sdk.SDK/'packages.tsv').read_text(),{'node':'v22.16.0','npm':'10.9.9','rustc':'rustc 1.96.0 (hash date)','cargo':'cargo 1.96.0 (hash date)'}),
            'tool_versions':{'node':'v22.16.0','npm':'10.9.9','rustc':'rustc 1.96.0 (hash date)','cargo':'cargo 1.96.0 (hash date)'},
            'tests':{n:{'status':'passed'} for n in ['python','rust','rendering']},
            'hardware_validation':{'status':'not_run','performed_this_build':False,'historical_evidence_inherited':False,'artifact_sha256':None},
            'static_validation':{'forbidden_conflict_files':[],'extraction_inventory_match':True,'default_legacy_startup_rejected':True},
            'captured_game_regressions':{'status':'unavailable','performed':False}}
        self.report['tests']['diff_check']='passed'
        for n in ci.UPLOAD_FILES:write_json(self.root/n,{})
        (self.root/'build-packages.tsv').write_bytes((sdk.SDK/'packages.tsv').read_bytes())
        self.save()
        self.patches=[patch.object(ci,'require_elf'),patch.object(ci,'appimage_offset')]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def save(self):
        write_json(self.root/'release-manifest.json',self.report)
        write_json(self.root/'source-inputs.json',self.report['source'])
        (self.root/'SHA256SUMS').write_text(self.report['artifact_sha256']+'  '+self.artifact.name+'\n')
        write_json(self.root/'provenance.json',ci.provenance(self.report,self.root))
    def test_valid_build_has_no_inherited_hardware_or_capture_pass(self):
        self.assertEqual(ci.verify(self.root)['captured_game_regressions']['status'],'unavailable')
    def test_wrong_ci_commit_rejected(self):
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_SHA':'different'}):
            with self.assertRaisesRegex(ValueError,'workflow commit'):ci.verify(self.root)
    def test_capture_status_cannot_inherit_pass(self):
        self.report['captured_game_regressions']['performed']=True;self.save()
        with self.assertRaisesRegex(ValueError,'fixture status'):ci.verify(self.root)
    def test_failure_export_never_contains_appimage(self):
        self.report['status']='failed';self.save()
        destination=self.root/'failure';ci.export(self.root,destination,failed=True)
        self.assertFalse((destination/self.artifact.name).exists())
        self.assertTrue((destination/'release-manifest.json').exists())
    def test_source_inventory_tampering_rejected(self):
        self.report['source']['files']={'forged':{}};self.save()
        with self.assertRaisesRegex(ValueError,'snapshot inventory'):ci.verify(self.root)
    def test_package_inventory_tampering_rejected(self):
        (self.root/'build-packages.tsv').write_text('bad\t1\n')
        with self.assertRaisesRegex(ValueError,'inventory drift'):ci.verify(self.root)
    def test_claimed_sdk_source_is_checked_against_lock(self):
        self.report['builder_identity']['sdk_source_sha256']='forged';self.save()
        with self.assertRaisesRegex(ValueError,'definition'):ci.verify(self.root)
    def test_artifact_poisoning_rejected(self):
        self.artifact.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'identity'):ci.verify(self.root)
    def test_runtime_overrides_cannot_be_claimed_as_official(self):
        self.report['unsafe_runtime_override_names']=['NODE_OPTIONS'];self.save()
        with self.assertRaisesRegex(ValueError,'runtime overrides'):ci.verify(self.root)
    def test_malformed_metadata_cli_fails_without_traceback(self):
        import subprocess
        for bad in [None,[],{'artifact_filename':42}]:
            write_json(self.root/'release-manifest.json',bad)
            result=subprocess.run([sys.executable,str(ROOT/'scripts/frame_ci.py'),'verify',str(self.root)],capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertNotIn('Traceback',result.stderr)
            self.assertIn('verification failed',result.stderr)
    def test_symlink_artifact_rejected_even_when_hash_matches(self):
        real=self.root/'real-artifact';self.artifact.rename(real);self.artifact.symlink_to(real)
        with self.assertRaisesRegex(ValueError,'symlink CI artifact'):ci.verify(self.root)
    def test_symlink_manifest_rejected(self):
        real=self.root/'real-manifest';(self.root/'release-manifest.json').rename(real)
        (self.root/'release-manifest.json').symlink_to(real)
        with self.assertRaisesRegex(ValueError,'symlink CI payload'):ci.verify(self.root)
    def test_symlink_release_directory_rejected(self):
        link=self.root/'alias';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'Symlink CI release directory'):ci.verify(link)
    def test_symlink_diagnostic_directory_rejected(self):
        real=self.root/'real-logs';real.mkdir();(real/'secret.log').write_text('private fixture')
        (self.root/'logs').symlink_to(real,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'diagnostic directory'):ci.export(self.root,self.root/'export')
    def test_unapproved_builder_rejected(self):
        self.report['builder_identity']['approved']=False;self.save()
        with self.assertRaisesRegex(ValueError,'strict'):ci.verify(self.root)
    def test_false_hardware_claim_rejected(self):
        self.report['hardware_validation']['status']='passed';self.save()
        with self.assertRaisesRegex(ValueError,'Historical'):ci.verify(self.root)
    def test_hardware_hash_mismatch_rejected(self):
        self.report['hardware_validation'].update(status='passed',performed_this_build=True,artifact_sha256='wrong');self.save()
        with self.assertRaisesRegex(ValueError,'Hardware identity'):ci.verify(self.root)
    def test_provenance_tampering_rejected(self):
        write_json(self.root/'provenance.json',{})
        with self.assertRaisesRegex(ValueError,'Provenance'):ci.verify(self.root)
    def test_dirty_source_and_unavailable_fixtures_recorded(self):
        p=ci.provenance(self.report,self.root)['predicate']
        self.assertTrue(p['source']['dirty']);self.assertFalse(p['hardware_smoke']['performed_this_build'])
        self.assertEqual(p['captured_game_regressions']['status'],'unavailable')
    def test_export_excludes_real_captures_and_caches(self):
        (self.root/'base.apk').write_bytes(b'never upload');(self.root/'original-provider.so').write_bytes(b'never upload')
        destination=self.root/'export';ci.export(self.root,destination)
        self.assertFalse((destination/'base.apk').exists());self.assertFalse((destination/'original-provider.so').exists())
    def test_export_rejects_symlink_logs(self):
        (self.root/'logs').mkdir();(self.root/'logs/secret.log').symlink_to(self.artifact)
        with self.assertRaisesRegex(ValueError,'diagnostic'):ci.export(self.root,self.root/'export')
    def test_comparison_checks_inputs_and_inventory(self):
        other=self.root/'other';other.mkdir()
        import shutil
        for f in self.root.iterdir():
            if f.is_file():shutil.copy2(f,other/f.name)
        self.assertTrue(ci.compare(self.root,other)['appimage_byte_identical'])
        (other/'appdir-inventory.json').write_text('{}\nchanged')
        # Provenance detects changes before comparison can claim identity.
        with self.assertRaisesRegex(ValueError,'Provenance'):ci.compare(self.root,other)

class SigningAndWorkflowTests(unittest.TestCase):
    def test_legacy_test_build_has_no_production_signing_credentials(self):
        text=(ROOT/'.github/workflows/test-build.yml').read_text()
        self.assertNotIn('secrets.',text);self.assertNotIn('contents: write',text)
        self.assertIn('persist-credentials: false',text)
        self.assertNotIn('/download/continuous/',text)
        self.assertIn('appimagetool checksum mismatch',text)
    def test_arm_platform_keys_only(self):
        import base64
        s=base64.b64encode(b'untrusted comment: public fixture').decode()
        m=signing.updater_metadata('1.7.1',s,'https://example.invalid/inspector.AppImage')
        self.assertEqual(set(m['platforms']),{'linux-aarch64','linux-aarch64-appimage'})
    def test_unsafe_urls_and_signature_rejected(self):
        for url in ['http://example.com/a','https://user:pass@example.com/a','file:///a']:
            with self.assertRaises(ValueError):signing.updater_metadata('1.7.1','bad',url)
    def test_production_signing_variables_rejected(self):
        with patch.dict(os.environ,{'TAURI_SIGNING_PRIVATE_KEY':'test secret'}):
            with self.assertRaisesRegex(ValueError,'refuses inherited'):signing.rehearsal('/missing','/missing','https://example.invalid/a')
    def test_new_workflows_have_immutable_actions_no_release_or_secrets(self):
        import re
        for p in (ROOT/'.github/workflows').glob('steam-frame-*.yml'):
            text=p.read_text()
            for action in re.findall(r'uses:\s+(\S+)',text):self.assertRegex(action,r'@[a-f0-9]{40}$')
            self.assertNotIn('secrets.',text);self.assertNotIn('pull_request_target',text)
            self.assertNotIn('gh release',text);self.assertNotIn('contents: write',text)
    def test_ci_calls_canonical_pipeline(self):
        text=(ROOT/'.github/workflows/steam-frame-release.yml').read_text()
        self.assertIn('scripts/build-steam-frame-release.sh --prepare-tools',text)
        self.assertNotIn('linuxdeploy --',text);self.assertNotIn('npm run tauri build',text)
    def test_frame_capability_excludes_updater_and_process_permissions(self):
        c=json.loads((ROOT/'src-tauri/capabilities/frame-inspector.json').read_text())
        self.assertEqual(set(c['permissions']),{'core:default','dialog:allow-open','core:window:allow-close'})
        f=json.loads((ROOT/'src-tauri/tauri.frame.conf.json').read_text())
        self.assertEqual(f['app']['security']['capabilities'],['frame-inspector'])
        csp=f['app']['security']['csp']
        self.assertIn("script-src 'self'",csp)
        self.assertIn('connect-src ipc: http://ipc.localhost',csp)
        self.assertNotIn('unsafe-eval',csp);self.assertNotIn('https:',csp)
    def test_legacy_publication_is_restricted_to_main(self):
        text=(ROOT/'.github/workflows/build.yml').read_text()
        self.assertIn("if: github.ref == 'refs/heads/main'",text)
        self.assertIn('publishes',text)
        self.assertNotIn('github-script@v6',text)
    def test_frame_feature_guards_embedded_elf_and_disables_updater(self):
        s=(ROOT/'src-tauri/src/main.rs').read_text()
        self.assertIn('frame_entry_allowed',s);self.assertIn('frame-inspector-only',s)
        self.assertIn('else { builder.plugin(UpdaterBuilder',s)
