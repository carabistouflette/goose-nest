#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Count network requests and compare warm locked registry fetches; no compilation."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from integration import Registry


def timed(argv, env, cwd):
    start = time.perf_counter_ns()
    result = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=90)
    elapsed = (time.perf_counter_ns() - start) / 1e6
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    return elapsed


def summary(values):
    ordered = sorted(values)
    return {'median_ms': statistics.median(values), 'p95_ms': ordered[min(len(ordered)-1, int(len(ordered)*.95))], 'samples_ms': values}


def run(args):
    nest, honk = args.nest.resolve(), args.honk.resolve()
    cargo = shutil.which('cargo')
    with tempfile.TemporaryDirectory(prefix='nest-bench-') as temporary:
        root = Path(temporary)
        registry = Registry(root)
        try:
            # Identical graph shape, package count, and payload sizes; language-specific manifests differ.
            deps = []
            for number in range(args.packages):
                name = f'bench-{number}'
                registry.package(name, payload=b'namespace benchmark;\n' + b'// payload\n' * 90)
                deps.append((f'dep_{number}', name, '=1.0.0'))
            registry.package('bench-root', deps=deps)
            project = root / 'goose-project'
            project.mkdir()
            (project / 'Honk.toml').write_text(f'[package]\nname="app"\nversion="0.1.0"\nentry="main.goose"\n[dependencies]\nbenchmark={{package="bench-root",version="=1.0.0",registry={json.dumps(registry.url + "/index")} }}\n')
            (project / 'main.goose').write_text('import std;\nfn main() {}\n')
            environment = dict(os.environ, HONK_HOME=str(root / 'honk-home'))
            cold_requests = len(registry.requests)
            cold_honk = timed([str(honk), 'fetch'], environment, project)
            cold_requests = len(registry.requests) - cold_requests
            expected_requests = len(registry.requests)
            commands = {'honk': ([str(honk), 'fetch', '--frozen'], environment, project)}
            if cargo:
                # Build an actual Cargo sparse registry, not path dependencies.
                index = root / 'cargo-index'
                index.mkdir()
                (index / 'config.json').write_text(json.dumps({'dl': registry.url + '/cargo-download/{crate}/{version}/download'}))
                for name, dependencies in [(f'bench-{n}', []) for n in range(args.packages)] + [('bench-root', deps)]:
                    manifest = '[package]\nname=' + json.dumps(name) + '\nversion="1.0.0"\nedition="2021"\n[dependencies]\n'
                    for _, dep, version in dependencies:
                        manifest += f'{dep}={{version="{version}",registry="nestbench"}}\n'
                    buf = io.BytesIO()
                    with tarfile.open(fileobj=buf, mode='w:gz') as archive:
                        for path, data in [('Cargo.toml', manifest.encode()), ('src/lib.rs', b'// payload\n' * 90)]:
                            info = tarfile.TarInfo(f'{name}-1.0.0/{path}')
                            info.size = len(data)
                            archive.addfile(info, io.BytesIO(data))
                    data = buf.getvalue()
                    download = root / 'cargo-download' / name / '1.0.0' / 'download'
                    download.parent.mkdir(parents=True)
                    download.write_bytes(data)
                    entry = {'name': name, 'vers': '1.0.0', 'deps': [{'name': dep, 'req': version, 'features': [], 'optional': False, 'default_features': True, 'target': None, 'kind': 'normal', 'registry': None} for _, dep, version in dependencies], 'cksum': hashlib.sha256(data).hexdigest(), 'features': {}, 'yanked': False}
                    shard = index / name[:2] / name[2:4]
                    shard.mkdir(parents=True, exist_ok=True)
                    (shard / name).write_text(json.dumps(entry) + '\n')
                rust = root / 'rust-project'
                (rust / '.cargo').mkdir(parents=True)
                (rust / 'src').mkdir()
                (rust / 'src/lib.rs').write_text('')
                (rust / 'Cargo.toml').write_text('[package]\nname="app"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nbench-root={version="=1.0.0",registry="nestbench"}\n')
                (rust / '.cargo/config.toml').write_text(f'[registries.nestbench]\nindex={json.dumps("sparse+" + registry.url + "/cargo-index/")}\n')
                cargo_env = dict(os.environ, CARGO_HOME=str(root / 'cargo-home'))
                cold_cargo = timed([cargo, 'fetch'], cargo_env, rust)
                commands['cargo'] = ([cargo, 'fetch', '--locked', '--offline'], cargo_env, rust)
            else:
                cold_cargo = None
            expected_requests = len(registry.requests)
            for _ in range(3):
                for argv, env, cwd in commands.values():
                    timed(argv, env, cwd)
            values = {key: [] for key in commands}
            # Alternate order to avoid always favoring the second tool.
            for number in range(args.samples):
                keys = list(commands)
                if number % 2:
                    keys.reverse()
                for key in keys:
                    argv, env, cwd = commands[key]
                    values[key].append(timed(argv, env, cwd))
            result = {'schema': 1, 'scenario': 'warm locked offline registry fetch; process wall time; no compiler',
                      'packages': args.packages + 1, 'platform': platform.platform(), 'python': platform.python_version(),
                      'cargo': subprocess.check_output([cargo, '--version'], text=True).strip() if cargo else None,
                      'nest_version': subprocess.check_output([str(nest), 'version'], text=True).strip(),
                      'honk_sha256': hashlib.sha256(honk.read_bytes()).hexdigest(), 'nest_sha256': hashlib.sha256(nest.read_bytes()).hexdigest(),
                      'cold_honk_ms': cold_honk, 'cold_cargo_ms': cold_cargo, 'cold_honk_http_requests': cold_requests,
                      'warm_http_requests': len(registry.requests) - expected_requests, 'results': {key: summary(samples) for key, samples in values.items()},
                      'limitations': ['Single Linux host, synthetic small source packages, no compilation.', 'Both use real registry archives. Cargo and Honk use different languages and manifest formats.', 'Honk hashes all extracted source files on cache hits; Cargo uses its own cache policy.', 'Cold timings include loopback HTTP and are not Internet latency measurements.', 'No claim about general Cargo build or resolver performance.']}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps({key: summary(samples)['median_ms'] for key, samples in values.items()}))
        finally:
            registry.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nest', type=Path, default=Path('.build/nest'))
    parser.add_argument('--honk', type=Path, default=Path('../honk/.build/honk'))
    parser.add_argument('--samples', type=int, default=31)
    parser.add_argument('--packages', type=int, default=24)
    parser.add_argument('--output', type=Path, default=Path('bench/results.json'))
    run(parser.parse_args())
