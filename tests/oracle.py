# SPDX-License-Identifier: Apache-2.0
"""Independent exhaustive validity oracle for the supported flat stable-version subset."""
import itertools
import random
import subprocess
import tempfile
import unittest
from pathlib import Path

from integration import NEST, Registry

VERSIONS = ('1.0.0', '1.1.0', '2.0.0')
REQUIREMENTS = ('=1.0.0', '=1.1.0', '=2.0.0', '^1.0.0', '>=1.0.0, <3.0.0', '=9.0.0')


def matches(requirement, value):
    """Deliberately small model: no calls to Nest or its SemVer implementation."""
    if requirement.startswith('='):
        return value == requirement[1:]
    if requirement == '^1.0.0':
        return value in ('1.0.0', '1.1.0')
    if requirement == '>=1.0.0, <3.0.0':
        return value in VERSIONS
    raise AssertionError('oracle fixture uses an unmodeled requirement')


def valid_assignment(graph, assignment, root, requirement, require_exact_reachability=False):
    if root not in assignment or not matches(requirement, assignment[root]):
        return False
    active, complete = set(), set()

    def visit(package):
        if package in active:
            return False
        if package in complete:
            return True
        if package not in assignment or assignment[package] not in graph[package]:
            return False
        active.add(package)
        for child, requested in graph[package][assignment[package]]:
            if child not in assignment or not matches(requested, assignment[child]) or not visit(child):
                return False
        active.remove(package)
        complete.add(package)
        return True

    return visit(root) and (not require_exact_reachability or set(assignment) == complete)


def satisfiable(graph, root, requirement):
    packages = sorted(graph)
    # An assignment includes unreachable packages too; only root-reachable edges constrain it.
    for versions in itertools.product(*(tuple(graph[package]) for package in packages)):
        if valid_assignment(graph, dict(zip(packages, versions)), root, requirement):
            return True
    return False


class ExhaustiveOracle(unittest.TestCase):
    def test_seeded_graphs_agree_with_exhaustive_search(self):
        randomizer = random.Random(20261116)
        with tempfile.TemporaryDirectory(prefix='nest-oracle-') as temporary:
            directory = Path(temporary)
            server = Registry(directory)
            successes = failures = 0
            try:
                for case in range(160):
                    packages = [f'pkg-{letter}' for letter in 'abcd'[:randomizer.randint(2, 4)]]
                    graph = {}
                    for package in packages:
                        graph[package] = {}
                        for version in randomizer.sample(VERSIONS, randomizer.randint(1, 3)):
                            dependencies = [(child, randomizer.choice(REQUIREMENTS)) for child in packages if randomizer.random() < .28]
                            graph[package][version] = dependencies
                        records = [{'version': version, 'url': f'{server.url}/{package}-{version}.tar.gz',
                                    'sha256': '0' * 64, 'entry': 'lib.goose', 'yanked': False,
                                    'dependencies': [{'alias': child.replace('-', '_'), 'package': child, 'version': requested}
                                                     for child, requested in dependencies]}
                                   for version, dependencies in graph[package].items()]
                        server.index(package, records)
                    requirement = randomizer.choice(REQUIREMENTS[:-1])
                    expected = satisfiable(graph, packages[0], requirement)
                    result = subprocess.run([str(NEST), 'resolve', server.url + '/index', packages[0], requirement,
                                             str(directory / 'cache')], text=True, capture_output=True, timeout=10)
                    with self.subTest(case=case, graph=graph, requirement=requirement):
                        self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)
                        if expected:
                            assignment = {}
                            for line in result.stdout.splitlines():
                                package, version, _ = line.split()
                                self.assertNotIn(package, assignment)
                                assignment[package] = version
                            self.assertTrue(valid_assignment(graph, assignment, packages[0], requirement, True))
                            successes += 1
                        else:
                            self.assertIn('no compatible registry graph', result.stderr)
                            failures += 1
                self.assertGreater(successes, 20)
                self.assertGreater(failures, 20)
                print(f'Exhaustive oracle: {successes} satisfiable and {failures} unsatisfiable seeded graphs')
            finally:
                server.close()
