"""Short owned-process timeout and native-compilation trust-boundary fixtures."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts'))
import frame_process as process
import frame_compile as compile
import frame_sdk as sdk
from frame_release_utils import sha256
spec=importlib.util.spec_from_file_location('release_builder',ROOT/'scripts/frame-release.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_capture_preserves_non_utf8_output(self):
        self.assertEqual(process.run([sys.executable,'-c','import sys;sys.stdout.buffer.write(b"a\\xff")'],self.root),'a\\xff')

    def test_heartbeat_and_child_stderr_never_contaminate_json_stdout(self):
        code='import sys,time;print("diagnostic",file=sys.stderr);time.sleep(.15);print("{\\\"value\\\":1}")'
        with patch('sys.stderr'):
            output=process.run([sys.executable,'-c',code],self.root,heartbeat=.05)
        self.assertEqual(json.loads(output),{'value':1})
        p=subprocess.run([sys.executable,str(ROOT/'scripts/frame_process.py'),'--heartbeat','.05','--',sys.executable,'-c',code],
                         cwd=self.root,capture_output=True,text=True)
        self.assertEqual(p.returncode,0);self.assertEqual(json.loads(p.stdout),{'value':1})
        self.assertIn('release-heartbeat',p.stderr);self.assertIn('diagnostic',p.stderr)

    def test_timeout_retains_progress_and_terminates_grandchild_only(self):
        log=self.root/'command.log';pid=self.root/'grandchild.pid'
        other=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])
        self.addCleanup(other.wait);self.addCleanup(other.kill)
        code=('import subprocess,time,pathlib; p=subprocess.Popen(["'+sys.executable+'","-c",'
              '"import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(20)"]);'
              'pathlib.Path('+repr(str(pid))+').write_text(str(p.pid));print("Compiling fixture",flush=True);time.sleep(20)')
        with self.assertRaisesRegex(ValueError,'timed out'):
            process.run([sys.executable,'-c',code],self.root,log=log,timeout=.4,heartbeat=.1)
        self.assertIn('Compiling fixture',log.read_text());self.assertIn('release-heartbeat',log.read_text())
        self.assertIn('release-command-terminated',log.read_text());self.assertIsNone(other.poll())
        status=Path('/proc')/pid.read_text()/'stat'
        deadline=time.monotonic()+2
        while status.exists() and status.read_text().rsplit(')',1)[1].split()[0]!='Z' and time.monotonic()<deadline:
            time.sleep(.01)
        if status.exists():self.assertEqual(status.read_text().rsplit(')',1)[1].split()[0],'Z')

    def test_stale_identity_never_kills_another_process(self):
        pid=self.root/'pid.json';pid.write_text(json.dumps({'pid':os.getpid(),'start':'stale'}))
        with patch.object(process,'terminate') as terminate:process.stop_owned(pid)
        terminate.assert_not_called()

    def test_bad_budgets_fail_cleanly(self):
        for option,value in [('--build-timeout','0'),('--test-timeout','-1'),('--package-timeout','bad'),('--heartbeat-seconds','21601'),('--build-jobs','0')]:
            with self.subTest(option=option),self.assertRaises(SystemExit),patch('sys.stderr'):
                builder.arguments([option,value],{})
        args=builder.arguments([],{'FRAME_BUILD_TIMEOUT':'4200','FRAME_BUILD_JOBS':'3'})
        self.assertEqual(args.build_timeout,4200);self.assertEqual(args.build_jobs,3)

    def test_failed_stage_records_elapsed_limit_and_failure(self):
        obj=builder.Builder(builder.arguments([],{}));obj.output=self.root
        def fail():raise ValueError('fixture failure')
        with self.assertRaises(ValueError):obj.step('synthetic',fail,12)
        row=json.loads((self.root/'release-manifest.json').read_text())['stages'][0]
        self.assertEqual(row['status'],'failed');self.assertEqual(row['timeout_seconds'],12)
        self.assertGreaterEqual(row['elapsed_seconds'],0)


class CompilationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        versions={'node':'v22.16.0','npm':'10.9.9','rustc':'rustc 1.96.0 (fixture)','cargo':'cargo 1.96.0 (fixture)'}
        packages=(sdk.SDK/'packages.tsv').read_text();(self.root/'build-packages.tsv').write_text(packages)
        (self.root/'logs').mkdir()
        for name in ['rust-tests.log','rendering-tests.log','tauri-build.log']:(self.root/'logs'/name).write_text('fixture log')
        binary=self.root/'input';binary.write_bytes(b'\x7fELF\x02\x01'+bytes(12)+b'\xb7\x00')
        self.report={'source':{'head':'commit','snapshot_sha256':'snapshot'},'version':'1.7.1','source_date_epoch':42,
                     'cargo_environment':{},'build_jobs':2,'llvm_runtime':{'fixture':'pin'},'ci':{},
                     'unsafe_runtime_override_names':[],'tool_versions':versions,
                     'builder_identity':sdk.validate_identity(sdk.source_hash(),sdk.source_hash(),packages,versions),
                     'tests':{'rust':{'status':'passed','passed':53,'failed':0,'ignored':0},
                              'rendering':{'status':'passed','pass':8,'fail':0,'skipped':0}}}
        compile.export(self.root,self.report,binary);self.packaging=copy.deepcopy(self.report)
        environment=patch.dict(os.environ,{'GITHUB_ACTIONS':'false'});environment.start();self.addCleanup(environment.stop)

    def save(self): (self.root/'compile-manifest.json').write_text(json.dumps(self.report))

    def test_same_source_frozen_compilation_is_accepted(self):
        self.assertEqual(compile.verify(self.root,self.packaging)['artifact_sha256'],sha256(self.root/'creamlinux'))

    def test_wrong_source_epoch_runtime_or_build_environment_rejected(self):
        for name in ['version','source_date_epoch','cargo_environment','build_jobs','llvm_runtime']:
            packaging=copy.deepcopy(self.packaging);packaging[name]='changed'
            with self.subTest(name=name),self.assertRaises(ValueError):compile.verify(self.root,packaging)
        packaging=copy.deepcopy(self.packaging);packaging['source']['head']='different'
        with self.assertRaisesRegex(ValueError,'source identity'):compile.verify(self.root,packaging)

    def test_tampered_binary_and_logs_rejected(self):
        for name in ['creamlinux','logs/rust-tests.log']:
            path=self.root/name;original=path.read_bytes();path.write_bytes(b'tampered')
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'checksum'):compile.verify(self.root,self.packaging)
            path.write_bytes(original)

    def test_skipped_failed_or_empty_native_gate_rejected(self):
        for values in [{'skipped':1},{'fail':1},{'pass':0}]:
            original=copy.deepcopy(self.report);self.report['tests']['rendering'].update(values);self.save()
            with self.assertRaisesRegex(ValueError,'test gate'):compile.verify(self.root,self.packaging)
            self.report=original;self.save()

    def test_symlink_payload_rejected(self):
        p=self.root/'creamlinux';p.rename(self.root/'real');p.symlink_to(self.root/'real')
        with self.assertRaisesRegex(ValueError,'Symlink'):compile.verify(self.root,self.packaging)

    def test_wrong_workflow_producer_rejected(self):
        self.report['ci']={'GITHUB_REPOSITORY':'fixture','GITHUB_RUN_ID':'1','GITHUB_SHA':'commit'};self.save()
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'fixture','GITHUB_RUN_ID':'2','GITHUB_SHA':'commit'}):
            with self.assertRaisesRegex(ValueError,'workflow identity'):compile.verify(self.root,self.packaging)


if __name__=='__main__':unittest.main()
