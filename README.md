# Goose Nest

The package registry for [Goose](https://github.com/aardappel/goose), integrated
with [Honk](https://github.com/carabistouflette/honk). Experimental
**v0.1.0-alpha.1**, Apache-2.0. Project code, documentation and diagnostics are English.

[Browse packages](https://carabistouflette.github.io/goose-nest/) ·
[Protocol and limits](docs/PROTOCOL.md) · [Performance](bench/README.md) ·
[Cargo parity plan](docs/CARGO-PARITY.md)

Nest serves a static index and verified source archives. The client is native
Goose, with a small C adapter for HTTP, SHA-256, archive extraction and local
cache operations. Python is used for registry authoring and test tooling only;
Honk does not start Python, Git, or a shell to fetch registry dependencies.
Nest follows Goose's flat, root-owned package model and `.build` sidecars; it adds
optional registry policy in Honk without changing the compiler's import syntax.

## Use with Honk

The first registry-enabled Honk source is provided by the integration branch
`feat/nest-registry` in `carabistouflette/honk`. Existing Honk v0.4.0 binaries do
not implement registry dependencies. Build that branch using its pinned compiler:

```sh
git clone --branch feat/nest-registry https://github.com/carabistouflette/honk.git
cd honk
make setup build
export PATH="$PWD/.build:$PATH"
export GOOSE="$PWD/.toolchain/goose/build/goose"
honk new ../hello-nest
cd ../hello-nest
honk search semver
honk info goose-semver
honk add goose-semver --as semver --version '^0.1.1'
honk fetch
honk check --frozen
```

Install development headers for libcurl, libsodium, OpenSSL and libarchive before
building Honk. On Ubuntu: `sudo apt-get install libcurl4-openssl-dev libsodium-dev
libssl-dev libarchive-dev pkg-config`. See Honk's remaining compiler requirements.

The resulting `Honk.toml` dependency is:

```toml
[dependencies]
semver = { package = "goose-semver", version = "^0.1.1", registry = "https://carabistouflette.github.io/goose-nest/index" }
```

Use `import semver;` in your root source. Commit `Honk.lock`. Repeated locked
fetches need no index access; `--frozen` also forbids all network. An online
`honk update` deliberately resolves current, non-yanked versions. `--registry`
can select another compatible index for add/search/info.

Import aliases are currently global to the Honk graph. One version per package
is selected; aliases for different packages must not conflict. The development Honk branch discovers registry dependencies inside Git/path
packages without repeating them at the application root. It aggregates their
constraints before selecting or downloading registry packages. Published
registry packages use only same-registry dependencies in Honk.toml, not sourced
imports. Packages pinning another Goose compiler revision fail explicitly.

## Build the standalone client

Validated on Linux x86-64/glibc. Requires Git, Make, CMake 3.27+, C/C++20 tools,
pkg-config, Python 3.11+, libcurl 7.85+, OpenSSL 3+, and libarchive 3+ development
headers. `GOOSE_REVISION` pins the compiler; no third-party Python dependencies.

```sh
git clone https://github.com/carabistouflette/goose-nest.git
cd goose-nest
make setup
make check test native-test
.build/nest version
.build/nest fetch \
  https://carabistouflette.github.io/goose-nest/index \
  goose-semver '^0.1.1' "$PWD/.build/cache"
```

`nest resolve` resolves metadata without fetching archives; `nest fetch` also
verifies/extracts sources; `nest offline` uses only the cache. The standalone
client is a protocol diagnostic tool; Honk owns the application's portable lock.

## Publish a package

There is no account service or publish backend in this alpha. Publication uses
GitHub Releases plus reviewed index pull requests. This keeps public hosting
free under GitHub's applicable limits and conditions, without Git LFS.

1. Track a library Honk.toml, entry, LICENSE and distributable sources in Git.
2. Produce an archive with `honk package` or the offline authoring tool:

   ```sh
   python3 tools/registry.py pack /absolute/path/to/library /tmp/example-1.0.0.tar.gz
   ```

3. Upload those exact bytes to a public GitHub Release. Do not use a generated
   branch/tag source tarball as the checksum-pinned package artifact.
4. Prepare and validate the index entry:

   ```sh
   python3 tools/registry.py add /tmp/example-1.0.0.tar.gz \
     --url https://github.com/OWNER/REPO/releases/download/v1.0.0/example-1.0.0.tar.gz
   python3 tools/registry.py validate
   ```

5. Open an index PR. Maintainers verify upstream control, archive bytes and
   metadata before merging. Versions cannot be overwritten; yanking only removes
   a version from new resolution, preserving existing locks.

The included goose-semver 0.1.1 package is the unmodified public upstream release
with a registry manifest wrapper. [Provenance](examples/semver/SOURCE.json) records
its exact source commit. It is the first real package used to verify publication.

## Design

- Per-package indexes: fetch only the reachable graph, with conditional ETag requests.
- Lock records: resolve a valid locked graph without an index or network request.
- Content-addressed sources: one extracted tree per archive SHA-256.
- Verified cache hits: hash actual source bytes, including same-size/mtime changes.
- Safe publication: bounded staging, private-cache flock, and atomic rename.
- Small solver: bounded backtracking with cycle checks and explicit exhaustion.

These choices target low package-management overhead. They do not imply that
Goose compiles faster than Rust or that Nest wins every Cargo workload. See the
reproducible benchmark and its recorded scope before making comparisons.
