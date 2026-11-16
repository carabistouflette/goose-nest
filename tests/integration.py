# SPDX-License-Identifier: Apache-2.0
"""Black-box client tests with a counted loopback HTTP registry."""
import contextlib
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import threading
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
NEST = Path(os.environ.get('NEST', ROOT / '.build/nest')).resolve()
HONK = Path(os.environ.get('HONK', ROOT.parent / 'honk/.build/honk')).resolve()
import shutil
GOOSE = Path(os.environ.get('GOOSE', shutil.which('goose') or '/nonexistent/goose'))

def q(value):
    return json.dumps(str(value))

class Registry:
    def __init__(self, root):
        self.root = Path(root)
        self.requests = []
        fixture = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                fixture.requests.append((self.path, self.headers.get('If-None-Match')))
                path = fixture.root / self.path.lstrip('/')
                if not path.is_file():
                    self.send_error(404)
                    return
                data = path.read_bytes()
                etag = '"' + hashlib.sha256(data).hexdigest() + '"'
                if self.headers.get('If-None-Match') == etag:
                    self.send_response(304)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('ETag', etag)
                self.end_headers()
                self.wfile.write(data)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def package(self, name='demo', version='1.0.0', deps=(), payload=None, extra=None):
        label = f'{name}-{version}'
        manifest = f'[package]\nname={q(name)}\nversion={q(version)}\nkind="lib"\nentry="lib.goose"\n[dependencies]\n'
        for alias, package, requirement in deps:
            manifest += f'{alias} = {{ package={q(package)}, version={q(requirement)}, registry={q(self.url + "/index")} }}\n'
        content = {'Honk.toml': manifest.encode(), 'lib.goose': payload or b'namespace demo;\nfn value() -> i64 { 42 }\n'}
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as archive:
            for filename, data in content.items():
                info = tarfile.TarInfo(f'{label}/{filename}')
                info.size = len(data)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(data))
            if extra:
                archive.addfile(extra, io.BytesIO(b'x' * extra.size))
        data = buf.getvalue()
        path = self.root / f'{label}.tar.gz'
        path.write_bytes(data)
        entry = {'version': version, 'url': self.url + '/' + path.name, 'sha256': hashlib.sha256(data).hexdigest(), 'entry': 'lib.goose', 'yanked': False,
                 'dependencies': [{'alias': a, 'package': p, 'version': r} for a, p, r in deps]}
        self.index(name, [entry])
        return entry

    def index(self, name, entries):
        target = self.root / 'index' / f'{name}.toml'
        target.parent.mkdir(exist_ok=True)
        text = f'schema=1\npackage={q(name)}\n'
        for entry in entries:
            text += '\n[[releases]]\n'
            for key in ('version', 'url', 'sha256', 'entry'):
                text += f'{key}={q(entry[key])}\n'
            text += f'yanked={str(entry.get("yanked", False)).lower()}\n'
            text += 'dependencies=[' + ','.join('{'+','.join(f'{k}={q(v)}' for k, v in dep.items())+'}' for dep in entry['dependencies']) + ']\n'
        target.write_text(text)
        (target.parent / '_catalog.toml').write_text(f'schema=1\n[[packages]]\nname={q(name)}\nversion={q(entries[0]["version"])}\n')

class Client(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = Registry(self.root)
        self.cache = self.root / 'cache'
    def tearDown(self):
        self.registry.close()
        self.temp.cleanup()
    def run_client(self, command='fetch', package='demo', requirement='^1.0.0', ok=True):
        result = subprocess.run([str(NEST), command, self.registry.url + '/index', package, requirement, str(self.cache)], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode == 0, ok, result.stderr + result.stdout)
        return result
    def test_fetch_transitive_etag_and_offline(self):
        self.registry.package('shared')
        self.registry.package(deps=[('shared', 'shared', '^1.0.0')])
        result = self.run_client()
        self.assertIn('shared 1.0.0', result.stdout)
        self.assertEqual(len(self.registry.requests), 4)
        self.run_client()
        self.assertEqual(len(self.registry.requests), 6)
        self.assertTrue(all(etag for _, etag in self.registry.requests[-2:]))
        self.run_client('offline')
        self.assertEqual(len(self.registry.requests), 6)
    def test_corrupt_archive(self):
        entry = self.registry.package()
        (self.root / 'demo-1.0.0.tar.gz').write_bytes(b'corrupt')
        result = self.run_client(ok=False)
        self.assertIn('SHA-256', result.stderr)
        self.assertFalse((self.cache / 'packages' / entry['sha256']).exists())
    def test_changed_same_size_source_is_rejected(self):
        entry = self.registry.package()
        self.run_client()
        path = self.cache / 'packages' / entry['sha256'] / 'lib.goose'
        before = path.stat()
        data = path.read_bytes().replace(b'42', b'99')
        path.write_bytes(data)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertIn('content changed', self.run_client('offline', ok=False).stderr)
    def test_added_file_and_symlink_are_rejected(self):
        entry = self.registry.package()
        self.run_client()
        directory = self.cache / 'packages' / entry['sha256']
        (directory / 'extra').symlink_to('/etc/passwd')
        self.run_client('offline', ok=False)
    def test_traversal_symlinks_and_hardlinks_are_rejected(self):
        for kind in ('traversal', 'symlink', 'hardlink', 'duplicate'):
            with self.subTest(kind=kind):
                info = tarfile.TarInfo('demo-1.0.0/../../escape' if kind == 'traversal' else 'demo-1.0.0/lib.goose')
                info.size = 1
                if kind == 'symlink':
                    info.type = tarfile.SYMTYPE
                    info.linkname = '/etc/passwd'
                    info.size = 0
                if kind == 'hardlink':
                    info.type = tarfile.LNKTYPE
                    info.linkname = 'demo-1.0.0/Honk.toml'
                    info.size = 0
                self.registry.package(extra=info)
                self.run_client(ok=False)
                self.assertFalse((self.root / 'escape').exists())
    def test_offline_miss_does_not_access_network(self):
        self.registry.package()
        self.run_client('offline', ok=False)
        self.assertEqual(self.registry.requests, [])
    def test_backtracking_and_conflicts(self):
        one = self.registry.package('shared', '1.0.0')
        two = self.registry.package('shared', '2.0.0')
        self.registry.index('shared', [two, one])
        left_one = self.registry.package('left', '1.0.0', [('shared', 'shared', '=1.0.0')])
        left_two = self.registry.package('left', '1.1.0', [('shared', 'shared', '=2.0.0')])
        self.registry.index('left', [left_two, left_one])
        self.registry.package('right', deps=[('shared', 'shared', '=1.0.0')])
        self.registry.package(deps=[('left', 'left', '^1.0.0'), ('right', 'right', '^1.0.0')])
        result = self.run_client()
        self.assertIn('left 1.0.0', result.stdout)
        self.assertIn('shared 1.0.0', result.stdout)
        self.registry.package('left', '1.0.0', [('shared', 'shared', '=2.0.0')])
        self.run_client(ok=False)
    def test_cycles_are_rejected(self):
        self.registry.package('demo', deps=[('other', 'other', '^1.0.0')])
        self.registry.package('other', deps=[('demo', 'demo', '^1.0.0')])
        self.run_client(ok=False)
    def test_yank_and_duplicate_release(self):
        entry = self.registry.package()
        entry['yanked'] = True
        self.registry.index('demo', [entry])
        self.run_client(ok=False)
        entry['yanked'] = False
        self.registry.index('demo', [entry, entry])
        self.run_client(ok=False)
    def test_concurrent_fetch_is_atomic(self):
        self.registry.package()
        argv = [str(NEST), 'fetch', self.registry.url + '/index', 'demo', '^1.0.0', str(self.cache)]
        children = [subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(6)]
        results = [(*child.communicate(timeout=20), child.returncode) for child in children]
        for out, err, code in results:
            self.assertEqual(code, 0, err + out)
        self.assertEqual(sum(path.endswith('.tar.gz') for path, _ in self.registry.requests), 1)
    def test_honk_fetch_lock_and_real_compilation(self):
        if not HONK.is_file() or not GOOSE.is_file():
            self.skipTest('set HONK and GOOSE for the compiler integration test')
        entry = self.registry.package('goose-answer', payload=b'namespace answer;\nfn value() -> i64 { 42 }\n')
        project = self.root / 'project'
        project.mkdir()
        (project / 'Honk.toml').write_text('[package]\nname="hello"\nversion="0.1.0"\nentry="main.goose"\nkind="bin"\n')
        (project / 'main.goose').write_text('import answer;\nimport std;\nfn main() { assert(answer::value() == 42); print("42"); }\n')
        env = dict(os.environ, HONK_HOME=str(self.root / 'honk-home'), GOOSE=str(GOOSE))
        def honk(*argv, ok=True):
            result = subprocess.run([str(HONK), *argv], cwd=project, env=env, text=True, capture_output=True, timeout=90)
            self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
            return result
        self.assertIn('goose-answer', honk('search', 'answer', '--registry', self.registry.url + '/index').stdout)
        self.assertIn(entry['sha256'], honk('info', 'goose-answer', '--registry', self.registry.url + '/index').stdout)
        honk('add', 'goose-answer', '--as', 'answer', '--registry', self.registry.url + '/index')
        honk('fetch')
        lock = (project / 'Honk.lock').read_bytes()
        before = len(self.registry.requests)
        self.assertIn('42', honk('run', '--frozen').stdout)
        self.assertEqual((project / 'Honk.lock').read_bytes(), lock)
        self.assertEqual(len(self.registry.requests), before)
        # Lock survives a yanked release, and even a missing index cache.
        entry['yanked'] = True
        self.registry.index('goose-answer', [entry])
        import shutil
        shutil.rmtree(self.root / 'honk-home' / 'nest' / 'index')
        honk('fetch', '--frozen')
        self.assertEqual(len(self.registry.requests), before)
        honk('update', ok=False)
        self.assertEqual((project / 'Honk.lock').read_bytes(), lock)
        # A changed constraint must not silently reuse an incompatible lock.
        manifest = project / 'Honk.toml'
        manifest.write_text(manifest.read_text().replace('^1.0.0', '^2.0.0'))
        honk('fetch', '--locked', ok=False)
        self.assertEqual((project / 'Honk.lock').read_bytes(), lock)

if __name__ == '__main__':
    unittest.main()
