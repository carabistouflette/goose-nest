# SPDX-License-Identifier: Apache-2.0
import importlib.util
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import tomllib
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
    def test_feature_metadata_roundtrips_and_preserves_legacy_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'feature.tar.gz'
            manifest = b'''[package]
name = "example"
version = "1.0.0"
kind = "lib"
entry = "lib.goose"

[target.linux-x86_64.dependencies]
codec = { package = "codec", version = "^1.0.0", optional = true, default-features = false, features = ["z", "a"] }

[target.linux-aarch64.dependencies]
codec = { package = "win-codec", version = "^1.0.0", optional = true }

[features]
default = ["export"]
export = ["dep:codec", "codec/pretty", "codec?/other"]
'''
            with tarfile.open(archive, 'w:gz') as tar:
                for path, data in [('Honk.toml', manifest), ('lib.goose', b'namespace example;')]:
                    member = tarfile.TarInfo('example-1.0.0/' + path)
                    member.size = len(data)
                    tar.addfile(member, io.BytesIO(data))
            url = 'https://example.com/feature.tar.gz'
            legacy = root / 'legacy'
            with self.assertRaisesRegex(ValueError, 'schema-2'):
                tools.add(legacy, archive, url)
            self.assertFalse(legacy.exists())

            index = root / 'index-v2'
            tools.add(index, archive, url, schema=2)
            tools.validate(index, schema=2)
            entry = index / 'example.toml'
            original = entry.read_bytes()
            data = tomllib.loads(original.decode())
            record = data['releases'][0]
            self.assertEqual(data['schema'], 2)
            self.assertEqual(record['features'], {'default': ['export'], 'export': ['codec/pretty', 'codec?/other', 'dep:codec']})
            self.assertEqual([(d['target-os'], d['target-arch'], d['package']) for d in record['dependencies']],
                             [('linux', 'aarch64', 'win-codec'), ('linux', 'x86_64', 'codec')])
            self.assertEqual(record['dependencies'][1]['features'], ['a', 'z'])
            self.assertIs(record['dependencies'][1]['optional'], True)
            self.assertIs(record['dependencies'][1]['default-features'], False)
            with self.assertRaisesRegex(ValueError, 'invalid index schema'):
                tools.validate(index)

            base = root / 'base'
            base.mkdir()
            (base / entry.name).write_bytes(original)
            entry.write_bytes(original.replace(b'["export"]', b'[]'))
            with self.assertRaisesRegex(ValueError, 'immutable'):
                tools.validate(index, base, schema=2)
            entry.write_bytes(original.replace(b', target-arch = "aarch64"', b''))
            with self.assertRaisesRegex(ValueError, 'overlapping dependency alias'):
                tools.validate(index, schema=2)
            entry.write_bytes(original.replace(b'dep:codec', b'dep:missing'))
            with self.assertRaisesRegex(ValueError, 'unknown optional dependency'):
                tools.validate(index, schema=2)

    def test_feature_metadata_rejects_invalid_references_and_types(self):
        dep = dict(alias='codec', package='codec', version='^1.0.0', optional=True)
        for features, dependencies in [
            ({'default': ['missing']}, [dep]),
            ({'default': ['dep:codec']}, [dict(dep, optional=False)]),
            ({'default': ['dep:codec']}, [dict(dep, optional=1)]),
            ({'default': [42]}, [dep]),
            ({}, [dict(dep, features=['invalid/feature'])]),
            ({}, [dict(dep, **{'default-features': 0})]),
            ({'default': ['codec?/pretty']}, [dict(dep, optional=False)]),
            ({'default': ['typo/pretty']}, [dep]),
            ({'default': ['codec/invalid/name']}, [dep]),
        ]:
            with self.subTest(features=features, dependencies=dependencies), self.assertRaises(ValueError):
                tools.validate_feature_metadata(features, dependencies)

    def test_source_paths_and_transport_policy(self):
        for path in ('../x', '/x', 'x//y', 'x/./y', 'x\\y'):
            self.assertFalse(tools.safe_path(path))
        for url in ('http://example.com/a', 'https://user@example.com/a', 'https://example.com/a#fragment'):
            self.assertFalse(tools.secure_url(url))
