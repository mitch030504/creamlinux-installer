#!/usr/bin/env python3
"""Exercise the real read-only Frame inspector through native AT-SPI actions.

Run on the SteamOS host with its existing Python GI/AT-SPI bindings. No browser,
injected JavaScript, application test hooks, global input or package installs.
The work directory contains the image and evidence fixtures staged separately.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback


class NativeInspector:
    def __init__(self, atspi, glib, image, appid, work):
        self.api = atspi
        self.glib = glib
        self.work = work
        env = dict(os.environ, DISPLAY=':0', XDG_RUNTIME_DIR='/run/user/1000',
                   DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus',
                   APPIMAGE_EXTRACT_AND_RUN='1', WEBKIT_DISABLE_DMABUF_RENDERER='1',
                   XDG_CACHE_HOME=str(work / 'cache'))
        env.pop('NO_AT_BRIDGE', None)
        self.log = (work / f'gui-{appid}.log').open('wb')
        self.process = subprocess.Popen([str(image), '--lepton-inspector', appid],
                                        cwd=work, env=env, stdin=subprocess.DEVNULL,
                                        stdout=self.log, stderr=self.log,
                                        start_new_session=True)
        self.group = self.process.pid

    def owns(self, node, skip_closed=False):
        try:
            return os.getpgid(node.get_process_id()) == self.group
        except ProcessLookupError:
            return False
        except self.glib.Error as error:
            # AT-SPI can retain a closed application's root until its removal
            # signal is processed. Only this observed disappearance is stale.
            if skip_closed and 'The application no longer exists' in str(error):
                return False
            raise

    def nodes(self):
        return self.stable_read(self._nodes)

    def stable_read(self, operation):
        # React rerenders and dialog dismissal invalidate accessible objects.
        # Retry only this observed read-side disappearance, never an action or
        # a process-ownership failure. A stable, complete snapshot is required.
        for attempt in range(20):
            try:
                return operation()
            except self.glib.Error as error:
                if 'The application no longer exists' not in str(error) or attempt == 19:
                    raise
                time.sleep(.05)

    def _nodes(self):
        context = self.glib.MainContext.default()
        while context.pending():
            context.iteration(False)
        desktop = self.api.get_desktop(0)
        desktop.clear_cache_single()
        found = []

        def walk(node, depth=0):
            if depth > 40 or len(found) >= 2500:
                raise RuntimeError('Unexpected inspector accessibility tree size')
            if not self.owns(node):
                raise RuntimeError('Accessible node escaped the isolated inspector process group')
            node.clear_cache_single()
            found.append(node)
            for index in range(node.get_child_count()):
                walk(node.get_child_at_index(index), depth + 1)

        for index in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(index)
            if self.owns(app, skip_closed=True):
                walk(app)
        return found

    def rows(self):
        return self.stable_read(self._rows)

    def _rows(self):
        rows = []
        for node in self.nodes():
            iface = node.get_text_iface()
            rows.append({'role': node.get_role_name(), 'name': node.get_name(),
                         'text': self.api.Text.get_text(iface, 0, -1) if iface else ''})
        return rows

    def texts(self):
        return [value for row in self.rows() for value in (row['name'], row['text'])]

    def wait(self, check, description, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stable_read(check):
                return
            if self.process.poll() is not None:
                raise RuntimeError(f'Inspector exited while waiting for {description}')
            time.sleep(.25)
        raise RuntimeError(f'Timed out waiting for {description}')

    def expect(self, text, timeout=60):
        self.wait(lambda: text in self.texts(), repr(text), timeout)

    def find(self, name, role=None):
        matches = self.stable_read(lambda: [node for node in self.nodes() if node.get_name() == name
                   and (role is None or node.get_role_name() == role)])
        if len(matches) != 1:
            raise RuntimeError(f'Expected one {name!r}, found {len(matches)}')
        return matches[0]

    def press(self, name, role='push button'):
        print(f'ACTION native UI: {name}', flush=True)
        node = self.find(name, role)
        if not self.owns(node):
            raise RuntimeError('Refusing action outside own inspector')
        action = node.get_action_iface()
        if not action or not self.api.Action.do_action(action, 0):
            raise RuntimeError(f'Native action failed for {name!r}')

    def picker(self, button, title, path=None):
        self.press(button)
        self.wait(lambda: any(n.get_role_name() == 'file chooser' and n.get_name() == title
                             for n in self.nodes()), title)
        self.find(title, 'file chooser')
        if path is None:
            self.press('Cancel')
        else:
            path = path.resolve(strict=True)
            if self.work not in path.parents:
                raise RuntimeError('Picker fixture must stay inside isolated work directory')
            self.press('File Chooser Widget', 'file chooser')  # show_location
            self.wait(lambda: len(self.location_entries()) == 1, 'file chooser location entry')
            entry = self.location_entries()[0]
            if not self.owns(entry) or not self.api.EditableText.set_text_contents(
                    entry.get_editable_text_iface(), str(path)):
                raise RuntimeError('Cannot set fixture path in native chooser')
            self.press('Open')
        self.wait(lambda: not any(n.get_role_name() == 'file chooser' and n.get_name() == title
                                 for n in self.nodes()), 'native chooser dismissed')
        if path is not None:
            self.expect(str(path))

    def location_entries(self):
        return [n for n in self.nodes() if n.get_role_name() == 'text'
                and n.get_state_set().contains(self.api.StateType.SHOWING)
                and n.get_editable_text_iface()]

    def analyze(self, expected):
        self.press('Analyze compatibility')
        self.expect(expected, timeout=180)

    def scroll_to_analysis(self):
        node = self.find('Analyze compatibility', 'push button')
        window = self.find('Lepton compatibility inspector', 'frame')
        iface = node.get_component_iface()
        if not self.api.Component.scroll_to(iface, self.api.ScrollType.ANYWHERE):
            raise RuntimeError('Native scroll-to action failed')
        time.sleep(.25)
        item = self.api.Component.get_extents(iface, self.api.CoordType.SCREEN)
        frame = self.api.Component.get_extents(window.get_component_iface(), self.api.CoordType.SCREEN)
        if not (frame.y <= item.y and item.y + item.height <= frame.y + frame.height):
            raise RuntimeError('Analyze button remains outside the inspector viewport after scrolling')

    def snapshot(self, name):
        (self.work / f'{name}.json').write_text(json.dumps(self.rows(), indent=2) + '\n')

    def close(self):
        self.press('Close')
        self.process.wait(timeout=10)
        if self.process.returncode != 0:
            raise RuntimeError(f'Close button exited {self.process.returncode}')

    def cleanup(self):
        if self.process.poll() is None:
            os.killpg(self.group, signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.group, signal.SIGKILL)
                self.process.wait(timeout=10)
        self.log.close()


def run(args, atspi, glib, image, work, report):
    def passed(name):
        report['passed'].append(name)
        print('PASS native UI: ' + name, flush=True)

    inspector = NativeInspector(atspi, glib, image, args.appid, work)
    try:
        inspector.expect('Container context is running')
        passed('running context and package metadata rendered')
        inspector.scroll_to_analysis()
        passed('scrolling brings Analyze button into viewport')
        inspector.analyze('Incompatible with the current proxy')
        inspector.expect('No generated artifact selected')
        inspector.snapshot('ui-default')
        passed('real Analyze button preserves fixed false and default artifact status')
        inspector.press('Inspect existing validation artifacts (optional)', role=None)
        inspector.picker('Select generated proxy', 'Select generated proxy directory')
        inspector.expect('No generated artifact selected')
        passed('native folder chooser cancellation preserves previous result')
        inspector.picker('Select generated proxy', 'Select generated proxy directory', work / 'evidence/target')
        inspector.expect('Compatibility has not been analyzed.')
        passed('native generated-folder selection clears stale analysis')
        inspector.analyze('Locally validated — static checks')
        inspector.expect('Incompatible with the current proxy')
        inspector.snapshot('ui-local')
        passed('generated-only analysis reports local validation separately')
        inspector.picker('Select hardware bundle', 'Select hardware validation bundle', work / 'evidence/hardware-bundle.tar.gz')
        passed('native file chooser selects existing hardware bundle')
        inspector.analyze('Analysis incomplete')
        inspector.press('Notes and analysis limitations', role=None)
        inspector.expect('Select a generated proxy directory and both the hardware bundle and results directory.')
        inspector.snapshot('ui-incomplete')
        passed('partial evidence produces incomplete result without compatibility claim')
        inspector.picker('Select results folder', 'Select hardware results directory', work / 'evidence/results')
        passed('native results-folder chooser selects existing logs')
        inspector.analyze('Hardware validated — function harness')
        inspector.expect('Incompatible with the current proxy')
        inspector.press('Validation evidence and identity', role=None)
        inspector.expect('d14dbef4969e32e90564cc15af6b76cc951062629fb415cc2b211d8776eac0e7')
        inspector.expect('345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700')
        inspector.snapshot('ui-hardware')
        passed('real UI analysis verifies matching hardware evidence and exposes precise identities')
        inspector.press('Refresh')
        inspector.expect('Compatibility has not been analyzed.')
        inspector.expect('Container context is running')
        if 'Hardware validated — function harness' in inspector.texts():
            raise RuntimeError('Refresh retained stale hardware result')
        passed('Refresh clears verified snapshot and reruns live introspection')
        inspector.press('Clear artifact selection')
        inspector.expect('Compatibility has not been analyzed.')
        if str(work / 'evidence/target') in inspector.texts():
            raise RuntimeError('Clear retained selected artifact path')
        inspector.snapshot('ui-cleared')
        passed('Clear artifact selection removes paths and result')
        inspector.close()
        passed('native Close button exits isolated inspector cleanly')
    except Exception:
        report['inspector_exit_before_cleanup'] = inspector.process.poll()
        raise
    finally:
        inspector.cleanup()

    if args.stopped_appid:
        inspector = NativeInspector(atspi, glib, image, args.stopped_appid, work)
        try:
            inspector.expect('The Lepton game must already be running to analyze it.')
            button = inspector.find('Analyze compatibility', 'push button')
            if button.get_state_set().contains(atspi.StateType.ENABLED):
                raise RuntimeError('Stopped-context Analyze button is enabled')
            inspector.snapshot('ui-stopped')
            passed('stopped-context UI disables Analyze and explains prerequisite')
            inspector.press('Refresh')
            inspector.expect('The Lepton game must already be running to analyze it.')
            inspector.close()
            passed('stopped-context Refresh and Close work without starting a game')
        finally:
            inspector.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--expected-image-sha256', required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--appid', default='448280')
    parser.add_argument('--stopped-appid')
    args = parser.parse_args()
    report = {'measured_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'mechanism': 'native AT-SPI actions, real GTK/WebKit inspector',
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'appid': args.appid, 'stopped_appid': args.stopped_appid,
              'passed': [], 'status': 'incomplete'}
    work = None
    try:
        work = args.work_dir.resolve(strict=True)
        image = args.image.resolve(strict=True)
        if work != Path('/tmp/creamlinux-inspector-validation') or image.parent != work:
            raise ValueError('Stage image/fixtures under /tmp/creamlinux-inspector-validation')
        for appid in [args.appid, args.stopped_appid]:
            if appid is not None and (not appid.isascii() or not appid.isdigit() or len(appid) > 10):
                raise ValueError('AppID must be numeric')
        with image.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != args.expected_image_sha256:
            raise ValueError('Transferred AppImage checksum differs')
        report['appimage_sha256'] = digest
        os.environ.update(DISPLAY=':0', DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus',
                          XDG_RUNTIME_DIR='/run/user/1000')
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi, GLib
        Atspi.init()
        Atspi.set_timeout(2000, 2000)
        run(args, Atspi, GLib, image, work, report)
        report['status'] = 'passed'
        return 0
    except Exception as error:
        report['error'] = str(error)
        if work == Path('/tmp/creamlinux-inspector-validation'):
            (work / 'native-ui-debug.txt').write_text(traceback.format_exc())
        print('Native inspector validation failed: ' + str(error), file=sys.stderr)
        return 2
    finally:
        if work == Path('/tmp/creamlinux-inspector-validation') and work.is_dir():
            (work / 'native-ui-observation.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    sys.exit(main())
