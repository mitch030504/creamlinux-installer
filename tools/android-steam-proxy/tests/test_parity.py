#!/usr/bin/env python3
"""Exercise the real harness/loader on host-only fixture DSOs; never load Steam."""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAMES = ('SteamAPI_IsSteamRunning', 'SteamAPI_GetHSteamUser', 'SteamAPI_GetHSteamPipe')


@unittest.skipUnless(shutil.which('cc'), 'host C compiler required')
class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='steam-parity-test-')
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = pathlib.Path(cls.tmp.name)
        cls.bin = cls.root / 'parity_probe'
        if (ROOT / 'src/parity_probe.c').exists():
            cls.compile(cls.bin, ROOT / 'src/parity_probe.c')
        cls.original = cls.root / 'original.so'
        cls.compile(cls.original, cls.source('original.c', '''
#include <stdbool.h>
#include <stdint.h>
bool SteamAPI_IsSteamRunning(void) { return false; }
int32_t SteamAPI_GetHSteamUser(void) { return -17; }
int32_t SteamAPI_GetHSteamPipe(void) { return 123456; }
'''), shared=True)
        cls.empty = cls.root / 'empty.so'
        cls.compile(cls.empty, cls.source('empty.c', 'int empty(void) { return 0; }'), shared=True)
        (cls.root / 'symbols.h').write_text(
            '#define PROXY_COUNT 3u\nextern void *proxy_targets[3];\n'
            'static const char *const proxy_names[3] = {' +
            ','.join(json.dumps(n) for n in NAMES) + '};\n')
        # Exercise the unchanged production proxy constructor, using typed host
        # forwarding wrappers in place of ARM64 assembly (ABI suite is separate).
        wrappers = cls.source('wrappers.c', '''
#include <stdbool.h>
#include <stdint.h>
void *proxy_targets[3];
bool SteamAPI_IsSteamRunning(void) { return ((bool (*)(void))proxy_targets[0])(); }
int32_t SteamAPI_GetHSteamUser(void) { return ((int32_t (*)(void))proxy_targets[1])(); }
int32_t SteamAPI_GetHSteamPipe(void) { return ((int32_t (*)(void))proxy_targets[2])(); }
''')
        cls.proxy = cls.root / 'proxy.so'
        cls.compile(cls.proxy, ROOT / 'src/proxy.c', wrappers, shared=True)
        cls.dependency = cls.root / 'dependency.so'
        cls.compile(cls.dependency, cls.root / 'empty.c', '-Wl,--no-as-needed',
                    cls.original, shared=True)

    @classmethod
    def source(cls, name, text):
        path = cls.root / name
        path.write_text(text)
        return path

    @classmethod
    def compile(cls, output, *inputs, shared=False):
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(cls.root), *(['-shared', '-fPIC'] if shared else []),
                        *map(str, inputs), '-ldl', '-o', str(output)], check=True,
                       capture_output=True, text=True)

    def run_probe(self, *args, code=0):
        self.assertTrue(self.bin.is_file(), 'parity harness has not been implemented')
        env = {k: v for k, v in os.environ.items() if k != 'LD_PRELOAD'}
        env['CREAMLINUX_ORIGINAL_STEAM_API'] = '/deliberately/stale.so'
        result = subprocess.run([str(self.bin), *map(str, args)], env=env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    @staticmethod
    def record(result):
        return json.loads(next(s[len('PARITY_JSON '):] for s in result.stdout.splitlines()
                               if s.startswith('PARITY_JSON ')))

    def test_direct_and_proxy_preserve_false_and_signed_handles(self):
        direct = self.record(self.run_probe('direct', self.original))
        proxy = self.record(self.run_probe('proxy', self.proxy, self.original))
        expected = dict(zip(NAMES, (False, -17, 123456)))
        self.assertEqual(direct['results'], expected)
        self.assertEqual(proxy['results'], expected)
        self.assertEqual(direct['original'], proxy['original'])
        self.assertFalse(direct['steam_api_init_called'])
        self.assertNotEqual(direct['loaded_library'], proxy['loaded_library'])

    def test_invalid_mode_argument_count_and_relative_paths(self):
        for args in [(), ('other', self.original), ('direct', 'relative.so'),
                     ('proxy', self.proxy), ('proxy', self.proxy, 'relative.so'),
                     ('direct', self.original, 'extra')]:
            with self.subTest(args=args):
                self.run_probe(*args, code=2)

    def test_missing_original_and_invalid_elf(self):
        self.run_probe('direct', self.root / 'not-present.so', code=1)
        self.run_probe('direct', self.root / 'empty.c', code=1)

    def test_self_proxy_is_rejected_including_hardlinks(self):
        alias = self.root / 'same-proxy.so'
        os.link(self.proxy, alias)
        self.run_probe('proxy', self.proxy, alias, code=2)

    def test_missing_symbol_is_rejected_before_any_calls(self):
        result = self.run_probe('direct', self.empty, code=1)
        self.assertIn('resolve', result.stderr)
        self.assertNotIn('calling ', result.stderr)

    def test_symbol_from_dependency_is_rejected(self):
        result = self.run_probe('direct', self.dependency, code=1)
        self.assertIn('owner', result.stderr)
        self.assertNotIn('calling ', result.stderr)

    def test_proxy_constructor_failure_is_not_success(self):
        result = self.run_probe('proxy', self.proxy, self.empty, code=127)
        self.assertNotIn('"status":"ok"', result.stdout)
        self.assertIn('missing function', result.stderr)

    def test_runner_pins_reference_captures_results_and_refuses_reuse(self):
        script = ROOT / 'tests/run_parity.sh'
        self.assertTrue(script.exists(), 'standalone runner has not been implemented')
        folder = pathlib.Path(tempfile.mkdtemp(dir=self.root))
        (folder / 'real').mkdir()
        (folder / 'runtime').mkdir()
        for source, target in [(self.bin, folder / 'parity_probe'),
                               (self.proxy, folder / 'real/libsteam_api.so'),
                               (self.original, folder / 'real/libsteam_api_original.so')]:
            shutil.copy2(source, target)
        shutil.copy2(script, folder / 'run_parity.sh')
        digest = hashlib.sha256(self.original.read_bytes()).hexdigest()
        (folder / 'reference.sha256').write_text(digest + '  real/libsteam_api_original.so\n')
        paths = sorted(p for p in folder.rglob('*') if p.is_file())
        (folder / 'SHA256SUMS').write_text(''.join(
            hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(folder)) + '\n'
            for p in paths))
        def run(name):
            return subprocess.run(['sh', str(folder / 'run_parity.sh'), name],
                                  capture_output=True, text=True, timeout=20)
        result = run('results')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.compare(folder / 'results')['parity'])
        self.assertNotEqual(run('results').returncode, 0)
        # A different safe fixture in the original slot must fail before calls.
        shutil.copy2(self.empty, folder / 'real/libsteam_api_original.so')
        self.assertNotEqual(run('changed').returncode, 0)
        self.assertFalse((folder / 'changed/direct.stdout').exists())

    def make_results(self):
        folder = pathlib.Path(tempfile.mkdtemp(dir=self.root))
        for mode, args in [('direct', (self.original,)),
                           ('proxy', (self.proxy, self.original))]:
            r = self.run_probe(mode, *args)
            (folder / (mode + '.stdout')).write_text(r.stdout)
            (folder / (mode + '.exit')).write_text('0\n')
        digest = hashlib.sha256(self.original.read_bytes()).hexdigest()
        for name in ('reference.sha256', 'original-before.sha256', 'original-after.sha256'):
            (folder / name).write_text(digest + '  real/libsteam_api_original.so\n')
        return folder

    def compare(self, folder, code=0):
        r = subprocess.run([sys.executable, str(ROOT / 'tests/compare_parity.py'), str(folder)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_comparator_accepts_parity_and_rejects_value_mismatch(self):
        folder = self.make_results()
        self.assertTrue(self.compare(folder)['parity'])
        path = folder / 'proxy.stdout'
        record = self.record(subprocess.CompletedProcess([], 0, stdout=path.read_text()))
        record['results'][NAMES[1]] = 0
        path.write_text('PARITY_JSON ' + json.dumps(record) + '\n')
        r = self.compare(folder, code=1)
        self.assertFalse(r['parity'])
        self.assertFalse(r['functions'][1]['equal'])

    def test_comparator_rejects_failed_missing_duplicate_or_malformed_results(self):
        for change in ('exit', 'missing', 'duplicate', 'type', 'identity', 'hash'):
            with self.subTest(change=change):
                folder = self.make_results()
                path = folder / 'proxy.stdout'
                if change == 'exit':
                    (folder / 'proxy.exit').write_text('127\n')
                elif change == 'missing':
                    path.write_text('')
                elif change == 'duplicate':
                    path.write_text(path.read_text() * 2)
                elif change == 'hash':
                    (folder / 'original-after.sha256').write_text('0' * 64 + '\n')
                else:
                    record = self.record(subprocess.CompletedProcess([], 0, stdout=path.read_text()))
                    if change == 'type':
                        record['results'][NAMES[0]] = 0
                    else:
                        record['original']['inode'] += 1
                    path.write_text('PARITY_JSON ' + json.dumps(record) + '\n')
                self.assertIsNone(self.compare(folder, code=2)['parity'])


if __name__ == '__main__':
    unittest.main()
