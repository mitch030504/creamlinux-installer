#!/usr/bin/env python3
"""Compare collected standalone direct/proxy records, never execute a library."""
import argparse
import json
import pathlib
import re

NAMES = ('SteamAPI_IsSteamRunning', 'SteamAPI_GetHSteamUser', 'SteamAPI_GetHSteamPipe')


def read_record(folder, mode):
    status = (folder / (mode + '.exit')).read_text().strip()
    if status != '0':
        raise ValueError(f'{mode} exited {status}; inspect {mode}.stderr (not parity)')
    lines = (folder / (mode + '.stdout')).read_text().splitlines()
    records = [json.loads(s[len('PARITY_JSON '):]) for s in lines if s.startswith('PARITY_JSON ')]
    if len(records) != 1:
        raise ValueError(f'{mode}: expected exactly one completed result')
    record = records[0]
    if (record['schema_version'] != 1 or record['status'] != 'ok' or record['mode'] != mode
            or record['steam_api_init_called'] is not False):
        raise ValueError(f'{mode}: invalid record metadata')
    values = record['results']
    if set(values) != set(NAMES):
        raise ValueError(f'{mode}: allowlist does not match')
    if type(values[NAMES[0]]) is not bool:
        raise ValueError(f'{mode}: running result is not bool')
    for name in NAMES[1:]:
        if type(values[name]) is not int or not -(2**31) <= values[name] < 2**31:
            raise ValueError(f'{mode}: {name} is not int32')
    for field in ('original', 'loaded_library'):
        identity = record[field]
        if not isinstance(identity['path'], str) or not identity['path'].startswith('/'):
            raise ValueError(f'{mode}: invalid library path')
        for key in ('device', 'inode', 'size', 'mtime'):
            if type(identity[key]) is not int:
                raise ValueError(f'{mode}: invalid library identity')
    return record


def compare(folder):
    hashes = []
    for filename in ('reference.sha256', 'original-before.sha256', 'original-after.sha256'):
        text = (folder / filename).read_text().strip().split()
        if not text or not re.fullmatch('[0-9a-f]{64}', text[0]):
            raise ValueError(f'invalid {filename}')
        hashes.append(text[0])
    if len(set(hashes)) != 1:
        raise ValueError('original hash differs from reference or changed during the run')
    direct, proxy = (read_record(folder, mode) for mode in ('direct', 'proxy'))
    if direct['original'] != proxy['original']:
        raise ValueError('direct and proxy did not use the same original file identity')
    if direct['loaded_library'] != direct['original']:
        raise ValueError('direct run did not load the original')
    if all(proxy['loaded_library'][key] == proxy['original'][key] for key in ('device', 'inode')):
        raise ValueError('proxy run loaded the original as the proxy')
    rows = [{'function': name, 'direct': direct['results'][name],
             'proxy': proxy['results'][name],
             'equal': direct['results'][name] == proxy['results'][name]} for name in NAMES]
    equal = all(row['equal'] for row in rows)
    return {'status': 'parity' if equal else 'mismatch', 'parity': equal,
            'scope': 'three allowlisted pre-init calls only',
            'original_sha256': hashes[0], 'functions': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=pathlib.Path)
    args = parser.parse_args()
    try:
        result = compare(args.results)
        status = 0 if result['parity'] else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {'status': 'inconclusive', 'parity': None, 'error': str(exc)}
        status = 2
    print(json.dumps(result, indent=2))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
