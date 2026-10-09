"""Bounded release commands with owned process groups and resource diagnostics."""
import argparse
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time


def diagnostics(directory):
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        name, value = line.split(':', 1)
        if name in {'MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'}:
            memory[name] = value.strip()
    disk = shutil.disk_usage(directory)
    process = subprocess.run(['ps', '-eo', 'pid,ppid,stat,pcpu,rss,comm'],
                             capture_output=True, text=True, timeout=5)
    rows = [r.strip() for r in process.stdout.splitlines()
            if any(n in r for n in ['rustc', 'cargo', 'qemu', 'cc1', 'ld.lld', 'node'])]
    return {'load_average': os.getloadavg(), 'memory': memory,
            'cgroup': {name:(Path('/sys/fs/cgroup')/name).read_text().strip() for name in
                       ['memory.current','memory.max','memory.events','cpu.stat'] if (Path('/sys/fs/cgroup')/name).is_file()},
            'disk_free_bytes': disk.free, 'disk_used_bytes': disk.used,
            'compiler_processes_pid_ppid_state_cpu_rss_name': rows[:20]}


def start_identity(pid):
    # Field 22 is the kernel start time, preventing accidental PID reuse.
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]


def terminate(pid):
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def stop_owned(path):
    path = Path(path)
    if not path.exists():
        return
    record = json.loads(path.read_text())
    try:
        if start_identity(record['pid']) == record['start']:
            terminate(record['pid'])
    except FileNotFoundError:
        pass


def run(args, cwd, log=None, env=None, timeout=600, heartbeat=60, pid_file=None, cleanup=None, passthrough=False):
    if timeout <= 0 or heartbeat <= 0:
        raise ValueError('Command timeout and heartbeat must be positive')
    started = time.monotonic()
    # A file avoids blocked output pipes and retains partial logs on failure.
    import tempfile
    stream = sys.stdout if passthrough else (Path(log).open('w', encoding='utf-8', errors='backslashreplace') if log else tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='backslashreplace'))
    errors = sys.stderr if passthrough else (stream if log else tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='backslashreplace'))
    proc = None
    try:
        proc = subprocess.Popen([str(x) for x in args], cwd=cwd, env=env,
                                stdout=stream, stderr=errors, start_new_session=True)
        if pid_file:
            with open(pid_file, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as pid:
                json.dump({'pid': proc.pid, 'start': start_identity(proc.pid)}, pid)
        next_heartbeat = started+heartbeat
        while proc.poll() is None:
            elapsed = time.monotonic()-started
            if elapsed >= timeout:
                raise ValueError(f'Release command timed out after {timeout:.1f}s; owned process group {proc.pid}; log={log}')
            if time.monotonic() >= next_heartbeat:
                status = {'event':'release-heartbeat', 'elapsed_seconds':round(elapsed, 1),
                          'limit_seconds':timeout, 'pid':proc.pid, **diagnostics(cwd)}
                print(json.dumps(status), file=sys.stderr, flush=True)
                if log:
                    stream.write('\n'+json.dumps(status)+'\n'); stream.flush()
                next_heartbeat = time.monotonic()+heartbeat
            time.sleep(min(0.1, max(0.01, timeout-elapsed)))
        if proc.returncode:
            stream.flush()
            if log or passthrough:
                raise ValueError(f'Command failed ({proc.returncode}); inspect {log}')
            stream.seek(0)
            errors.seek(0)
            raise ValueError(f'{Path(str(args[0])).name} failed ({proc.returncode}): '+(errors.read() or stream.read())[-1600:])
        if log or passthrough:
            return ''
        stream.seek(0)
        return stream.read().strip()
    except BaseException:
        if proc:
            terminate(proc.pid); proc.wait(timeout=10)
            message = {'event':'release-command-terminated', 'elapsed_seconds':round(time.monotonic()-started, 3),
                       'pid':proc.pid, 'returncode':proc.returncode}
            print(json.dumps(message), file=sys.stderr, flush=True)
            if log:
                stream.write('\n'+json.dumps(message)+'\n'); stream.flush()
        if cleanup:
            cleanup()
        raise
    finally:
        if not passthrough:
            stream.close()
            if not log:
                errors.close()
        if pid_file:
            Path(pid_file).unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--timeout', type=float, default=600)
    p.add_argument('--heartbeat', type=float, default=60)
    p.add_argument('--pid-file', type=Path)
    p.add_argument('--stop', type=Path)
    p.add_argument('command', nargs=argparse.REMAINDER)
    a = p.parse_args()
    if a.stop:
        stop_owned(a.stop)
    else:
        command = a.command[1:] if a.command[:1] == ['--'] else a.command
        if not command:
            p.error('Command is required')
        # Forward termination through the supervisor to its owned descendants.
        def interrupted(*_):
            raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM, interrupted)
        run(command, Path.cwd(), timeout=a.timeout, heartbeat=a.heartbeat, pid_file=a.pid_file, passthrough=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print('Release command failed: '+str(error), file=sys.stderr)
        sys.exit(2)
