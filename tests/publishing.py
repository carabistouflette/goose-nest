# SPDX-License-Identifier: Apache-2.0
import importlib.util
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('registry_tools', Path(__file__).resolve().parents[1] / 'tools/registry.py')
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)

class Publishing(unittest.TestCase):
    def test_semver_precedence(self):
        values = ['1.0.0-alpha.10', '1.0.0', '1.0.0-alpha.2', '1.0.0-beta', '2.0.0']
        self.assertEqual(sorted(values, key=tools.version_key), ['1.0.0-alpha.2', '1.0.0-alpha.10', '1.0.0-beta', '1.0.0', '2.0.0'])
        with self.assertRaises(ValueError):
            tools.version_key('1.0.0-alpha.01')
    def test_deterministic_pack_add_and_append_only_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'project'
            project.mkdir()
            subprocess.run(['git', 'init', '-q', str(project)], check=True)
            (project / 'Honk.toml').write_text('[package]\nname="example"\nversion="1.0.0"\nkind="lib"\nentry="lib.goose"\n')
            (project / 'LICENSE').write_text('example')
            (project / 'lib.goose').write_text('namespace example;\n')
            (project / 'secret').write_text('do not export')
            subprocess.run(['git', '-C', str(project), 'add', 'Honk.toml', 'LICENSE', 'lib.goose'], check=True)
            first, second = root / 'a.tar.gz', root / 'b.tar.gz'
            tools.pack(project, first)
            tools.pack(project, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first) as archive:
                self.assertNotIn('example-1.0.0/secret', archive.getnames())
            index, base = root / 'index', root / 'base'
            tools.add(index, first, 'https://example.com/example-1.0.0.tar.gz')
            tools.validate(index)
            with self.assertRaises(ValueError):
                tools.add(index, first, 'https://example.com/changed.tar.gz')
            base.mkdir()
            old = index / 'example.toml'
            (base / old.name).write_text(old.read_text())
            old.write_text(old.read_text().replace('yanked = false', 'yanked = true'))
            tools.catalog(index)
            tools.validate(index, base)
            old.write_text(old.read_text().replace('https://example.com/', 'https://other.example/'))
            with self.assertRaises(ValueError):
                tools.validate(index, base)
    def test_source_paths_and_transport_policy(self):
        for path in ('../x', '/x', 'x//y', 'x/./y', 'x\\y'):
            self.assertFalse(tools.safe_path(path))
        for url in ('http://example.com/a', 'https://user@example.com/a', 'https://example.com/a#fragment'):
            self.assertFalse(tools.secure_url(url))
