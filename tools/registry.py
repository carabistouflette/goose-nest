#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline, deterministic registry authoring. Python 3.11+ standard library only."""
import argparse
import gzip
import hashlib
import html
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tomllib
from urllib.parse import urlsplit

NAME = re.compile(r'[a-z][a-z0-9-]{0,63}(?<!-)\Z')
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z')
CAP = 1024 * 1024

def require(value, message):
    if not value:
        raise ValueError(message)

def quote(value):
    return json.dumps(str(value), ensure_ascii=True)

def safe_path(value):
    path = PurePosixPath(value)
    return bool(value) and len(value) <= 1024 and not path.is_absolute() and all(part not in ('', '.', '..') for part in value.split('/')) and not any(ord(c) < 33 or ord(c) > 126 or c in '\\:' for c in value)

def version_key(value):
    match = VERSION.fullmatch(value)
    require(match and len(value) <= 64, 'version must be strict SemVer without build metadata')
    pre = match[4]
    parts = []
    if pre:
        for part in pre.split('.'):
            require(not (part.isdigit() and len(part) > 1 and part[0] == '0'), 'prerelease numeric identifier has a leading zero')
            parts.append((0, int(part)) if part.isdigit() else (1, part))
    return (*map(int, match.groups()[:3]), pre is None, tuple(parts))

def secure_url(value):
    parsed = urlsplit(value)
    return parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment and all(32 < ord(c) < 127 and c != '\\' for c in value)

def record_text(record):
    text = '\n'.join(f'{key} = {quote(record[key])}' for key in ('version', 'url', 'sha256', 'entry'))
    text += '\nyanked = ' + str(record.get('yanked', False)).lower()
    text += '\ndependencies = [' + ', '.join('{ ' + ', '.join(f'{key} = {quote(dep[key])}' for key in ('alias', 'package', 'version')) + ' }' for dep in record['dependencies']) + ']\n'
    return text

def index_text(name, records):
    return f'schema = 1\npackage = {quote(name)}\n' + ''.join('\n[[releases]]\n' + record_text(r) for r in sorted(records, key=lambda r: version_key(r['version']), reverse=True))

def inspect_archive(path):
    require(path.stat().st_size <= 16 * CAP, 'archive exceeds 16 MiB')
    files = {}
    total = 0
    with tarfile.open(path, 'r:gz') as archive:
        for count, entry in enumerate(archive, 1):
            require(count <= 4096, 'archive exceeds 4096 entries')
            name = entry.name.rstrip('/') if entry.isdir() else entry.name
            require(safe_path(name), 'unsafe archive path')
            require(entry.isfile() or entry.isdir(), 'links and special files are forbidden')
            if entry.isdir():
                continue
            require(entry.size <= CAP and name not in files, 'file exceeds 1 MiB or duplicates another file')
            total += entry.size
            require(total <= 64 * CAP, 'expanded archive exceeds 64 MiB')
            with archive.extractfile(entry) as stream:
                files[name] = stream.read(CAP + 1)
            require(len(files[name]) == entry.size, 'truncated archive')
    manifests = [name for name in files if name.count('/') == 1 and name.endswith('/Honk.toml')]
    require(len(manifests) == 1, 'archive needs exactly one top-level package manifest')
    manifest = tomllib.loads(files[manifests[0]].decode())
    package = manifest['package']
    name, version = package['name'], package['version']
    require(NAME.fullmatch(name), 'invalid package name')
    version_key(version)
    label = f'{name}-{version}'
    require(package.get('kind') == 'lib' and safe_path(package['entry']), 'registry package must be a library with a relative entry')
    require(f'{label}/{package["entry"]}' in files, 'missing library entry')
    require(all(name.startswith(label + '/') for name in files), 'archive has another top-level directory')
    dependencies = []
    for alias, dep in manifest.get('dependencies', {}).items():
        require(re.fullmatch(r'[a-z_][a-z0-9_]{0,63}', alias), 'invalid import alias')
        require(isinstance(dep, dict) and set(dep) <= {'package', 'version', 'registry'}, 'published packages require registry dependencies')
        target = dep.get('package', alias)
        require(NAME.fullmatch(target), 'invalid dependency package')
        require(isinstance(dep.get('version'), str) and 0 < len(dep['version']) <= 256, 'missing dependency requirement')
        dependencies.append({'alias': alias, 'package': target, 'version': dep['version']})
    return manifest, dependencies

def pack(project, output):
    manifest = tomllib.loads((project / 'Honk.toml').read_text())
    package = manifest['package']
    require(NAME.fullmatch(package['name']), 'invalid package name')
    version_key(package['version'])
    label = f'{package["name"]}-{package["version"]}'
    tracked = subprocess.check_output(['git', '-C', str(project), 'ls-files', '-z']).split(b'\0')
    paths = sorted({name.decode() for name in tracked if name})
    require('Honk.toml' in paths and 'LICENSE' in paths, 'track Honk.toml and LICENSE before packaging')
    require(len(paths) <= 4096, 'too many tracked files')
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, filename='', mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name in paths:
                require(safe_path(name) and not any(part in {'.git', '.build', '.toolchain', 'target', '.honk'} for part in PurePosixPath(name).parts), 'unsafe or generated tracked file')
                source = project / name
                require(source.is_file() and not source.is_symlink() and all(not parent.is_symlink() for parent in source.parents), 'tracked file or ancestor is not a regular path')
                require(source.stat().st_size <= CAP, 'tracked file exceeds 1 MiB')
                data = source.read_bytes()
                info = tarfile.TarInfo(label + '/' + name)
                info.size, info.mode, info.mtime = len(data), 0o755 if source.stat().st_mode & 0o111 else 0o644, 0
                archive.addfile(info, io.BytesIO(data))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as dest:
        dest.write(stream.getvalue())
    inspect_archive(output)
    print(hashlib.sha256(output.read_bytes()).hexdigest(), output)

def add(index, archive, url):
    require(secure_url(url), 'archive URL must use HTTPS without credentials')
    manifest, dependencies = inspect_archive(archive)
    package = manifest['package']
    record = {'version': package['version'], 'url': url, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'entry': package['entry'], 'yanked': False, 'dependencies': dependencies}
    target = index / f'{package["name"]}.toml'
    records = tomllib.loads(target.read_text())['releases'] if target.exists() else []
    require(all(r['version'] != record['version'] for r in records), 'published version already exists; choose a new version')
    # The hosting index URL must be the same as every published dependency's registry.
    for dep in manifest.get('dependencies', {}).values():
        require(dep.get('registry', 'https://carabistouflette.github.io/goose-nest/index') == 'https://carabistouflette.github.io/goose-nest/index', 'this registry does not accept cross-registry dependencies')
    index.mkdir(parents=True, exist_ok=True)
    target.write_text(index_text(package['name'], records + [record]))
    catalog(index)
    print(target)

def catalog_content(index):
    text = 'schema = 1\npackages = []\n'
    entries = []
    for path in sorted(index.glob('*.toml')):
        if path.stem == '_catalog':
            continue
        doc = tomllib.loads(path.read_text())
        releases = [r for r in doc['releases'] if not r['yanked'] and '-' not in r['version']]
        if releases:
            latest = max(releases, key=lambda r: version_key(r['version']))
            entries.append(f'[[packages]]\nname = {quote(doc["package"])}\nversion = {quote(latest["version"])}\n')
    if entries:
        text = 'schema = 1\n\n' + '\n'.join(entries)
    return text

def catalog(index):
    (index / '_catalog.toml').write_text(catalog_content(index))

def validate(index, base=None):
    for path in sorted(index.glob('*.toml')):
        if path.stem == '_catalog':
            continue
        doc = tomllib.loads(path.read_text())
        require(path.stat().st_size <= CAP and set(doc) == {'schema', 'package', 'releases'} and doc['schema'] == 1, 'invalid index schema')
        require(NAME.fullmatch(doc['package']) and path.stem == doc['package'], 'invalid index package name')
        require(isinstance(doc['releases'], list) and len(doc['releases']) <= 512, 'invalid release count')
        seen = set()
        for record in doc['releases']:
            require(set(record) == {'version', 'url', 'sha256', 'entry', 'yanked', 'dependencies'}, 'unknown release field')
            version_key(record['version'])
            require(record['version'] not in seen, 'duplicate version')
            seen.add(record['version'])
            require(secure_url(record['url']) and re.fullmatch('[0-9a-f]{64}', record['sha256']) and safe_path(record['entry']), 'invalid release source identity')
            require(type(record['yanked']) is bool and len(record['dependencies']) <= 256, 'invalid release fields')
            aliases = set()
            for dep in record['dependencies']:
                require(set(dep) == {'alias', 'package', 'version'} and re.fullmatch('[a-z_][a-z0-9_]{0,63}', dep['alias']) and NAME.fullmatch(dep['package']) and isinstance(dep['version'], str) and 0 < len(dep['version']) <= 256, 'invalid dependency')
                require(dep['alias'] not in aliases, 'duplicate dependency alias')
                aliases.add(dep['alias'])
        if base and (base / path.name).exists():
            old = tomllib.loads((base / path.name).read_text())
            current = {r['version']: r for r in doc['releases']}
            for previous in old['releases']:
                require(previous['version'] in current, 'published releases cannot be deleted')
                require({k: v for k, v in previous.items() if k != 'yanked'} == {k: v for k, v in current[previous['version']].items() if k != 'yanked'}, 'published releases are immutable except yanked')
    if base:
        require(all((index / path.name).exists() for path in base.glob('*.toml')), 'published packages cannot be deleted')
    if (index / '_catalog.toml').exists():
        require((index / '_catalog.toml').read_text() == catalog_content(index), 'search catalog is stale; run the catalog command')
    print('Registry index validated')

def site(index, output):
    import shutil
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(index, output / 'index', dirs_exist_ok=True)
    items = []
    for path in sorted(index.glob('*.toml')):
        if path.stem == '_catalog':
            continue
        doc = tomllib.loads(path.read_text())
        releases = [r for r in doc['releases'] if not r['yanked']]
        if releases:
            latest = max(releases, key=lambda r: version_key(r['version']))
            name = html.escape(doc['package'])
            items.append(f'<article><h2>{name}</h2><p>{html.escape(latest["version"])}</p><code>honk add {name} --version ^{html.escape(latest["version"])}</code></article>')
    (output / '.nojekyll').touch()
    (output / 'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Goose Nest</title><style>body{max-width:850px;margin:5rem auto;padding:0 1.5rem;background:#faf8f1;color:#263d31;font:18px system-ui}h1{font-size:3rem}article{border-top:1px solid #bbb;padding:1rem 0}code{font-size:15px;overflow-wrap:anywhere}a{color:inherit}</style><h1>Goose Nest</h1><p>The package registry for Goose. Built into Honk.</p><p><a href="https://github.com/carabistouflette/goose-nest">Documentation and source</a></p>' + ''.join(items) + '</html>')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('pack'); p.add_argument('project', type=Path); p.add_argument('output', type=Path)
    p = sub.add_parser('add'); p.add_argument('archive', type=Path); p.add_argument('--url', required=True); p.add_argument('--index', type=Path, default=Path('index'))
    p = sub.add_parser('catalog'); p.add_argument('--index', type=Path, default=Path('index'))
    p = sub.add_parser('validate'); p.add_argument('--index', type=Path, default=Path('index')); p.add_argument('--base', type=Path)
    p = sub.add_parser('site'); p.add_argument('output', type=Path); p.add_argument('--index', type=Path, default=Path('index'))
    args = parser.parse_args()
    try:
        if args.command == 'pack': pack(args.project.resolve(), args.output)
        elif args.command == 'add': add(args.index, args.archive, args.url)
        elif args.command == 'catalog': catalog(args.index)
        elif args.command == 'validate': validate(args.index, args.base)
        elif args.command == 'site': validate(args.index); catalog(args.index); site(args.index, args.output)
    except (ValueError, KeyError, OSError, tarfile.TarError, tomllib.TOMLDecodeError) as error:
        parser.exit(1, f'nest registry: {error}\n')
if __name__ == '__main__':
    main()
