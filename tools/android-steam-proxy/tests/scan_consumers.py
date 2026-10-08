#!/usr/bin/env python3
"""Read-only ELF linkage evidence scan of local base/split APKs and native libraries.

Requires llvm-readelf (including Android packed relocation support). Never loads
an ELF. Archives are opened read-only; members are inspected via temporary copies.
By default the four target names are included in evidence lists; callers may
supply other names. Public exports are also exposed for compatibility analysis.
"""
import argparse
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import zipfile

NAMES = ('g_pSteamClientGameServer', '__bss_start', '_edata', '_end')
ARCHIVES = {'.apk', '.zip', '.apks', '.xapk'}
LOADER_APIS = {'dlopen', 'dlsym', 'android_dlopen_ext'}


def steam_named(name):
    return name.startswith(('SteamAPI_', 'SteamInternal_', 'SteamGameServer_')) or name in {
        'SteamClient', 'GetHSteamUser', 'GetHSteamPipe'}


def base_name(name):
    return name.split('@', 1)[0]


def symbol_record(symbol, table, index):
    return {
        'symbol': base_name(symbol['Name']['Name']),
        'name': symbol['Name']['Name'], 'table': table, 'index': index,
        'binding': symbol['Binding']['Name'], 'type': symbol['Type']['Name'],
        'defined': symbol['Section']['Value'] != 0,
        'section': symbol['Section']['Name'], 'value': symbol['Value'],
        'size': symbol['Size'],
    }


def inspect_elf(label, path, data, readelf, names=NAMES, runtime_names=()):
    result = subprocess.run(
        [readelf, '--elf-output-style=JSON', '--file-header', '--sections',
         '--symbols', '--dyn-syms', '--dynamic-table', '--relocations', '--expand-relocs', str(path)],
        capture_output=True, text=True, timeout=60, env={**os.environ, 'LC_ALL': 'C'})
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'llvm-readelf failed')
    obj = json.loads(result.stdout)[0]
    sections = {s['Section']['Index']: s['Section'] for s in obj['Sections']}
    issues = []
    if result.stderr.strip():
        issues.append(result.stderr.strip())
    # Sectionless images can still load; this section-based scan must not declare
    # their absent symbol/relocation evidence to be a complete negative result.
    if not sections:
        issues.append('No section headers: complete symbol/relocation inspection unavailable')
    dynamic_available = any(s['Type']['Value'] == 11 for s in sections.values())
    if 'SharedObject' in obj['ElfHeader']['Type'] and not dynamic_available:
        issues.append('Shared object has no inspectable dynamic symbol table')
    report = {
        'elf_format': obj['FileSummary']['Format'],
        'public_exports': [dict(symbol_record(s['Symbol'], 'DYNSYM', i),
                                other=s['Symbol']['Other']['Value'])
                           for i, s in enumerate(obj['DynamicSymbols'])
                           if s['Symbol']['Section']['Value'] != 0
                           and s['Symbol']['Binding']['Name'] != 'Local'
                           and (s['Symbol']['Other']['Value'] & 3) in (0, 3)],
        'file': label, 'architecture': obj['FileSummary']['Arch'],
        'elf_type': obj['ElfHeader']['Type'],
        'sha256': hashlib.sha256(data).hexdigest(),
        'dynamic_symbol_table_available': dynamic_available,
        'symbol_table_available': any(s['Type']['Value'] == 2 for s in sections.values()),
        'imported_symbols': [], 'defined_symbols': [],
        'symbol_table_references': [], 'relocations': [], 'string_occurrences': [],
        'inspection_complete': not issues, 'issues': issues,
    }
    dynamic = [symbol_record(s['Symbol'], 'DYNSYM', i)
               for i, s in enumerate(obj['DynamicSymbols'])]
    regular = [symbol_record(s['Symbol'], 'SYMTAB', i)
               for i, s in enumerate(obj['Symbols'])]
    report['dynamic_symbols'] = dynamic
    report['dt_needed'] = sorted({entry['Library'] for entry in obj['DynamicSection']
                                  if entry['Type'] == 'NEEDED'})
    report['soname'] = next((entry['Name'] for entry in obj['DynamicSection']
                             if entry['Type'] == 'SONAME'), None)
    dyn_names = {s['name'] for s in dynamic} | {s['symbol'] for s in dynamic}
    sym_names = {s['name'] for s in regular} | {s['symbol'] for s in regular}
    imports = {s['symbol'] for s in dynamic if not s['defined']}
    report['runtime_loader_imports'] = sorted(imports & LOADER_APIS)
    # Scan printable strings once, requiring an entire string rather than a
    # substring. Exclude symbol/string/debug tables from literal candidates;
    # also conservatively exclude names in either of this ELF's symbol tables.
    targets = set(runtime_names)
    exact, literal, modules, markers, steam_strings = set(), set(), set(), set(), set()
    for match in re.finditer(rb'[\x20-\x7e]{4,}', data):
        raw = match.group()
        if b'Steam' not in raw and b'steam' not in raw and raw.decode('ascii') not in targets:
            continue
        text = raw.decode('ascii')
        table_string = any(
            s['Offset'] <= match.start() < s['Offset'] + s['Size'] and
            (s['Type']['Value'] in (2, 3, 11) or s['Name']['Name'].startswith('.debug'))
            for s in sections.values() if s['Type']['Value'] != 8)
        if text in targets:
            exact.add(text)
            if text not in dyn_names and text not in sym_names and not table_string:
                literal.add(text)
        if not table_string:
            if 'steam' in text.lower():
                steam_strings.add(text)
            if 'steam_api' in text.lower():
                modules.add(text)
            if 'steamworks.net' in text.lower():
                markers.add(text)
    report.update(raw_exact_provider_export_strings=sorted(exact),
                  provider_export_strings_explained_by_dynsym=sorted(exact & dyn_names),
                  provider_export_strings_explained_by_symtab=sorted(exact & sym_names),
                  runtime_lookup_literal_candidates=sorted(literal),
                  steam_module_strings=sorted(modules), steamworks_net_markers=sorted(markers),
                  steam_related_strings=sorted(steam_strings))
    for symbol in dynamic + regular:
        if symbol['symbol'] not in names:
            continue
        if symbol['defined']:
            report['defined_symbols'].append(symbol)
        elif symbol['table'] == 'DYNSYM':
            report['imported_symbols'].append(symbol)
        if symbol['table'] == 'SYMTAB':
            report['symbol_table_references'].append(symbol)
    for group in obj['Relocations']:
        section = sections[group['SectionIndex']]
        linked = sections.get(section['Link'], {})
        is_dynamic = bool(section['Flags']['Value'] & 2) and linked.get('Type', {}).get('Value') == 11
        symbols = dynamic if linked.get('Type', {}).get('Value') == 11 else regular
        for item in group['Relocs']:
            relocation = item['Relocation']
            name = base_name(relocation['Symbol']['Name'])
            if name not in names:
                continue
            index = relocation['Symbol']['Value']
            symbol = symbols[index]
            if symbol['symbol'] != name:
                raise ValueError('Relocation symbol index/name mismatch')
            report['relocations'].append({
                'symbol': name, 'name': relocation['Symbol']['Name'],
                'section': section['Name']['Name'], 'dynamic': is_dynamic,
                'offset': relocation['Offset'], 'type': relocation['Type']['Name'],
                'symbol_index': index, 'symbol_defined': symbol['defined'],
                'binding': symbol['binding'], 'addend': relocation.get('Addend'),
            })
    for name in names:
        needle = name.encode('utf-8')
        start = 0
        while True:
            offset = data.find(needle, start)
            if offset < 0:
                break
            owners = [s['Name']['Name'] for s in sections.values()
                      if s['Type']['Value'] != 8 and
                      s['Offset'] <= offset < s['Offset'] + s['Size']]
            report['string_occurrences'].append({
                'symbol': name, 'offset': offset, 'sections': owners,
                'nul_terminated': data[offset + len(needle):offset + len(needle) + 1] == b'\0',
            })
            start = offset + len(needle)
    return report


class Scanner:
    def __init__(self, readelf, names=NAMES, runtime_names=()):
        self.names = names
        self.readelf = readelf
        self.runtime_names = runtime_names
        self.files = []
        self.errors = []
        self.archives = 0
        self.seen = set()

    def error(self, label, error):
        self.errors.append({'file': str(label), 'error': str(error)})

    def elf(self, label, path, data):
        if not data.startswith(b'\x7fELF'):
            self.error(label, 'Expected native ELF; file is not ELF')
            return
        try:
            report = inspect_elf(label, path, data, self.readelf, self.names, self.runtime_names)
            self.files.append(report)
            for issue in report['issues']:
                self.error(label, issue)
        except (OSError, ValueError, KeyError, IndexError, TypeError, subprocess.TimeoutExpired) as exc:
            self.error(label, exc)

    def archive(self, label, source, depth=0):
        if depth > 16:
            self.error(label, 'Archive nesting limit exceeded')
            return
        try:
            with zipfile.ZipFile(source, 'r') as archive:
                self.archives += 1
                for index, info in enumerate(archive.infolist()):
                    if info.is_dir():
                        continue
                    suffix = pathlib.PurePosixPath(info.filename).suffix.lower()
                    if suffix not in ARCHIVES and suffix != '.so':
                        continue
                    # Include central-directory index so duplicate names remain distinct.
                    member = f'{label}!/{info.filename} [entry {index}]'
                    try:
                        data = archive.read(info)
                        if suffix in ARCHIVES:
                            self.archive(member, io.BytesIO(data), depth + 1)
                        else:
                            with tempfile.TemporaryDirectory(prefix='steam-proxy-scan-') as tmp:
                                scratch = pathlib.Path(tmp) / 'input.so'
                                scratch.write_bytes(data)
                                self.elf(member, scratch, data)
                    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
                        self.error(member, exc)
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
            self.error(label, exc)

    def path(self, path, explicit=True):
        try:
            canonical = path.resolve()
            if canonical in self.seen:
                return
            self.seen.add(canonical)
            if path.is_dir():
                for child in sorted(path.iterdir()):
                    self.path(child, explicit=False)
            elif path.suffix.lower() in ARCHIVES:
                self.archive(str(path), path)
            elif path.is_file():
                with path.open('rb') as stream:
                    magic = stream.read(4)
                if magic == b'\x7fELF' or path.suffix.lower() == '.so' or explicit:
                    self.elf(str(path), canonical, path.read_bytes())
            else:
                self.error(path, 'Missing or non-regular input')
        except OSError as exc:
            self.error(path, exc)

    def report(self):
        if not self.files:
            self.error('<scan>', 'No ELF files successfully inspected')
        summary = {}
        for name in self.names:
            evidence = []
            required = False
            static_reference = False
            for file in self.files:
                for category in ('imported_symbols', 'relocations', 'defined_symbols',
                                 'symbol_table_references', 'string_occurrences'):
                    for item in file[category]:
                        if item['symbol'] != name:
                            continue
                        external = category == 'imported_symbols' or (
                            category == 'relocations' and item['dynamic'] and
                            not item['symbol_defined'] and not item['type'].endswith('_NONE'))
                        static_reference |= external
                        mandatory = external and item['binding'] not in ('Weak', 'Local')
                        required |= mandatory
                        evidence.append({'file': file['file'], 'kind': category,
                                         'requires_external_definition': mandatory, **item})
            summary[name] = {
                'statically_required': required,
                'static_reference_detected': static_reference,
                'evidence': evidence,
            }
        return {
            'schema_version': 3,
            'note': 'statically_required means a non-weak external ELF import/reference was '
                    'found, not proof of execution or of which library supplies it. Weak '
                    'imports remain linkage evidence. Definitions and strings alone do not '
                    'require a proxy export. Strings include symbol/debug tables and substring '
                    'matches; they do not prove dynamic linkage or dlsym use. A false result '
                    'means no requirement was found in inspected inputs; it is inconclusive '
                    'if scan_complete is false or consumers/splits are missing. Computed '
                    'runtime names and stripped internal static uses cannot be excluded.',
            'scan_complete': not self.errors, 'archives_scanned': self.archives,
            'elf_files_scanned': len(self.files), 'files': self.files,
            'summary': summary, 'errors': self.errors,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--readelf', default='llvm-readelf',
                        help='LLVM llvm-readelf executable (default: %(default)s)')
    parser.add_argument('paths', nargs='+', type=pathlib.Path,
                        help='base/split APKs, ZIP/APKS/XAPK bundles, ELF files or directories')
    args = parser.parse_args()
    readelf = shutil.which(args.readelf)
    scanner = Scanner(readelf)
    if readelf is None:
        scanner.error(args.readelf, 'llvm-readelf not found; install LLVM or use --readelf')
    else:
        for path in args.paths:
            scanner.path(path)
    report = scanner.report()
    print(json.dumps(report, indent=2))
    return 0 if report['scan_complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
