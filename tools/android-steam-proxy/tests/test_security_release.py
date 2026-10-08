"""Security floors and release boundaries; no Docker, network or private games."""
import json
from pathlib import Path
import re
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[3]


def version(text):
    return tuple(int(v) for v in text.split('.')[:3])


class SecurityReleaseTests(unittest.TestCase):
    def setUp(self):
        self.npm = json.loads((ROOT/'package-lock.json').read_text())['packages']
        self.rust = tomllib.loads((ROOT/'src-tauri/Cargo.lock').read_text())['package']

    def test_project_tar_has_all_six_advisory_fixes(self):
        self.assertGreaterEqual(version(self.npm['node_modules/npm/node_modules/tar']['version']), (7, 5, 21))

    def test_uuid_stays_on_compatible_patched_major(self):
        actual = version(self.npm['node_modules/uuid']['version'])
        self.assertEqual(actual[0], 11)
        self.assertGreaterEqual(actual, (11, 1, 1))

    def test_vite_stays_on_compatible_patched_major(self):
        actual = version(self.npm['node_modules/vite']['version'])
        self.assertEqual(actual[0], 6)
        self.assertGreaterEqual(actual, (6, 4, 3))

    def test_no_unpatched_h2_branch(self):
        rows = [p for p in self.rust if p['name'] == 'h2']
        self.assertTrue(rows)
        for row in rows:
            self.assertGreaterEqual(version(row['version']), (0, 4, 16))

    def test_rustls_security_patch(self):
        for row in [p for p in self.rust if p['name'] == 'rustls']:
            self.assertGreaterEqual(version(row['version']), (0, 23, 45))

    def test_legacy_http_client_api_security_upgrade_is_minimal(self):
        deps = tomllib.loads((ROOT/'src-tauri/Cargo.toml').read_text())['dependencies']
        self.assertEqual(deps['reqwest']['version'], '0.12')
        self.assertEqual(deps['reqwest']['features'], ['json'])

    def test_inspector_dispatcher_has_only_three_read_only_commands(self):
        text = (ROOT/'src-tauri/src/main.rs').read_text()
        commands = re.search(r'let read_only:.*?generate_handler!\[([^]]+)\]', text, re.S).group(1)
        self.assertEqual({s.strip() for s in commands.split(',')},
                         {'get_game_info', 'get_lepton_info', 'analyze_lepton_compatibility'})
        self.assertIn('if inspector_only { read_only(invoke) } else { standard(invoke) }', text)

    def test_all_workflow_action_references_are_commit_pins(self):
        for path in (ROOT/'.github/workflows').glob('*.yml'):
            for action in re.findall(r'uses:\s+(\S+)', path.read_text()):
                self.assertRegex(action, r'@[a-f0-9]{40}$', str(path))
