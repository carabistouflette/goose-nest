# Mixed-source resolution delivery receipt

Date: 2026-11-16. Honk implementation:
[5f2963c](https://github.com/carabistouflette/honk/commit/5f2963c).
Compiler pin: `eadca409f68210893f366e60d0c2f0dc29a339be`.
This receipt covers the development integration, not released Honk v0.5.0-rc.1
or full Cargo parity.

## Behavior

Before the change, a registry dependency inside a Git/path dependency had to be
repeated at the application root. A direct registry choice could be made before
a later path dependency's constraints were known. The two regression tests
failed against the saved prior binary with the root-redeclaration error and
`conflicting dependency: answer` respectively.

Honk now discovers non-registry sources first, retains the owner of each registry
requirement, and solves all those constraints together before downloading any
registry archive. Registry edges are then attached to the original owners.
Normal/dev reachability and cycle checks remain in force. Registry requests are
bounded to 65,536. Existing lock row order is preserved independently of graph
construction order; old mixed locks can remain byte-identical under `--frozen`.
Failure diagnostics identify requesting owners, aliases, packages and ranges,
with bounded diagnostic output. This is not a minimal unsatisfiable-core engine.

## Correctness evidence

The [Honk registry suite](https://github.com/carabistouflette/honk/blob/5f2963c/tests/registry_cli.py)
passes eight real CLI tests:

- Original public-registry workflow, yanked lock retention and frozen compilation.
- Path to path to registry to registry, without root redeclarations; ignored
  transitive dev dependencies.
- A late narrow constraint selecting version 1 instead of version 2 before
  version 2's archive is downloaded; each index queried once.
- Existing mixed-source lock order preserved with no network and no lock edits.
- Unsatisfiable root/path constraints with owner diagnostics, no new archive
  download and byte-identical old lock.
- A newly introduced hidden registry dependency rejected under `--locked`, then
  resolved online and reused frozen after removing the index cache.
- Legacy sourced-path imports reaching a manifest with registry requirements.
- Real Git to path to registry, using a test-only local transport shim; frozen
  execution preserves the exact Git commit, lock bytes and network counts.

The same eight tests pass using the Clang ASan/UBSan build, with leak detection
and halt-on-error enabled. The full watch-fault sanitizer build is given a
600-second build budget instead of 180 seconds because the whole-CLI Clang
instrumentation exceeded the old limit on hosted CI. Runtime test/watch deadlines
were not increased. A successful local build/test is not a claim that every
future hosted run will finish within the larger budget.

Additional checks: `make check` in Honk, 78 existing CLI tests, eight Git-version
CLI tests, Nest interpreted/native core tests, integration/publication tests and
native ASan/UBSan cache tests. This is not a receipt for every Honk benchmark or
all compiler targets.

[The independent oracle](../tests/oracle.py) exhaustively enumerates assignments
for each of 160 deterministic randomly generated small graphs, using a separate
Python constraint model. The native resolver agrees on 68 satisfiable and
92 unsatisfiable cases, and every returned assignment is checked for reachability,
constraints and cycles. The model deliberately covers a small stable-version
subset; it does not prove all SemVer syntax or all graphs correct.

Commands, with `GOOSE` set to the pinned compiler and `HONK` to the new binary:

```sh
make -C honk check
python3 honk/tests/registry_cli.py
python3 honk/tests/cli.py
python3 honk/tests/version_deps_cli.py
make -C goose-nest check test native-test
```

## Performance regression evidence

[Raw samples and identities](validation/mixed-source-2026-11-16.json) compare the
saved pre-change Honk binary with the candidate on the same verified warm cache,
lock and 25-package registry fixture. Three warmups and 31 alternating samples
were taken after local compiler/test jobs completed. Warm HTTP requests were zero.
No unexplained warm latency regression was observed in this run; the submillisecond
median difference is not presented as a statistically significant improvement.

Reproduce the before/after operation with explicit binaries:

```sh
python3 goose-nest/bench/run.py \
  --nest goose-nest/.build/nest --honk /path/to/candidate/honk \
  --baseline-honk /path/to/previous/honk --skip-cargo \
  --samples 31 --packages 24 --output /tmp/mixed-source-regression.json
```

This shared-host synthetic measurement does not establish large-graph or cold
Internet performance. Cargo is disabled for this regression check; the historical
alpha Cargo comparison used nightly, and cannot establish stable-Cargo superiority.
