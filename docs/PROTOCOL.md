# Registry protocol v1

The registry is static HTTPS, with no authentication required for public reads.
No Git clone or GitHub API request is needed to resolve or fetch a package.
`GET <registry>/<package>.toml` returns at most 1 MiB of UTF-8 TOML:

```toml
schema = 1
package = "example"

[[releases]]
version = "1.0.0"
url = "https://github.com/OWNER/REPO/releases/download/v1.0.0/example-1.0.0.tar.gz"
sha256 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
entry = "lib.goose"
yanked = false
dependencies = [{ alias = "text", package = "goose-text", version = "^0.1.0" }]
```

Dependencies inherit the registry of their parent. Names are lowercase ASCII
letters/digits/hyphens, start with a letter, end without a hyphen, and have at
most 64 bytes. Underscores are reserved for import aliases and internal files.
Versions are full SemVer with no build metadata; versions are never reused.
Requirements use the vendored goose-semver grammar: explicit full versions,
comparison operators, caret, tilde, and comma intersections. Wildcards and OR
are not supported. Prereleases require an explicit matching prerelease constraint.
There are at most 512 releases per package and 8192 releases per resolution.

The solver chooses the highest compatible release, one version per registry and
package. It backtracks on transitive conflicts and cycles. Work is bounded by
256 selected packages, 65536 pending dependency requests and 100000 candidate
decisions. Exhaustion is an error, never a partial solution. This is a small
bounded chronological solver, not PubGrub or a claim of optimal complexity on
adversarial graphs. Lock records contain complete selected metadata, allowing
resolution without an index cache or network. A valid lock can retain a yanked
release; new resolution excludes it. Adding/changing constraints may re-resolve
the graph. `update` deliberately excludes old lock candidates.

Archives are gzip-compressed tar, with exactly one `<package>-<version>/` root.
Only regular files and directories are accepted: no symlinks, hard links, device
files, traversal, absolute paths, backslashes, duplicate file paths, or sparse
expansion beyond limits. Compressed bytes are capped at 16 MiB; each file at
1 MiB; expanded content at 64 MiB; entries at 4096; source-tree depth at 32.
The archive contains a matching Honk library manifest and declared entry.
Honk verifies dependency metadata against that manifest before using it.
Registry packages declare dependencies in Honk.toml, not sourced import strings.
Native code compilation only happens when a user subsequently builds the package.

The per-package index cache uses SHA-256 of the full index URL as its key.
Unlocked online resolution revalidates each needed package once using ETag.
A CURL easy handle retains the connection pool between requests. Index content
and ETag are replaced atomically under a private-cache flock. Missing/offline
indexes fail without network. No time-based freshness heuristic is used.

Verified archives and extracted trees use the archive SHA-256 as their cache
key. Installation uses private temporary files/directories and atomic rename;
a completion seal is written after extraction. Cache hits recompute a digest
over sorted paths, file contents, and executable flags, catching additions,
removals and same-size/same-mtime edits. Incomplete/corrupt trees fail closed;
remove the affected digest directory and `.ready` file to repair from the blob.
A locally cached valid blob may be re-extracted offline. Cache writes are atomic
but no power-loss durability guarantee is made for directory renames.

The cache is trusted local state, owned by the current user and not writable by
other users; symlink cache paths are rejected. Same-user hostile concurrent
writers, coordinated replacement of both sources and seals, or rollback of the
whole trusted index/lock are outside the threat model. SHA-256 does not establish
publisher identity: maintainers review index changes and package ownership.

Transport verifies TLS, disables proxies/netrc, bounds headers to 64 KiB, uses
10-second connection and 60-second transfer budgets, and follows at most five
HTTPS redirects for release assets. It forwards no registry credentials.
Timeouts are not hard wall deadlines on every resolver/backend. Explicit IPv4
loopback `http://127.0.0.1:PORT` is allowed for local tests; redirects are disabled
on that transport. This is not an SSRF sandbox; registry URLs are trusted inputs.

`_catalog.toml` is a generated search catalog (`schema = 1`, `[[packages]]` with
`name` and `version`); it is not consulted during dependency resolution.

## Alignment with Goose packages

The compiler's [package documentation](https://aardappel.github.io/goose/docs/packages.html)
and [design](https://aardappel.github.io/goose/docs/design/packages.html) define a
flat root-owned package graph, one version of each package, entry modules and
optional `.build` sidecars. Nest is an optional Honk policy layer above these
facilities, not a replacement compiler package mechanism. Honk resolves the
registry graph and generates the compiler's root package declarations; the
compiler still owns Goose import lookup and native CMake compilation. No source
syntax extension is needed. Native source caches remain compiler-owned.

Nest's own `nest.build` declares `main_thread_only = true` because its reusable
CURL handle and native diagnostic buffer are process state. Goose rejects calls
from `thread_fn`; independent processes can safely share Nest's flocked cache.

The alpha registry manifest convention is additional to the compiler's Git/path
requirements. Existing compiler-native packages continue to work via Honk's
Git/path support. Importing a registry archive directly with bare `goose` does
not cause registry discovery; use Honk to generate the complete root mapping.

## Experimental feature metadata

The offline authoring tools can prepare a separate schema-2 index. This is the
authoring contract for feature-aware releases. Nest's metadata API can opt
into reading both schemas with `parse_index(..., true)` or `catalog(..., true)`.
`locked_record(..., true)` restores the feature fields emitted by `record_text`.
The existing resolver still uses schema 1 and rejects feature-bearing lock
records. Keep schema-2 entries in a staging index until the consumer resolver
supports feature activation. The default validator and site
generation continue to require schema 1.

```sh
python3 tools/registry.py add example-1.0.0.tar.gz --schema 2 \
    --index .build/index-v2 --url https://example.org/example-1.0.0.tar.gz
python3 tools/registry.py validate --schema 2 --index .build/index-v2
```

A package file declares `schema = 2`. It retains the schema-1 release
fields and can add a `features` table to each release. Each dependency
can include `optional = true`, `default-features = false`, and a `features`
array of target feature names. By default, the dependency is required and
requests the target's default group when one exists. The search catalog keeps its existing schema because it contains
names and versions only.

```toml
features = { default = ["text"], text = ["dep:codec"] }
dependencies = [
  { alias = "codec", package = "goose-codec", version = "^1.0.0", optional = true, default-features = false, features = ["pretty"] }
]
```

The authoring tool derives this metadata from the archived `Honk.toml`.
Group names start with a lowercase ASCII letter and may contain lowercase
letters, digits, hyphens, and underscores, up to 64 bytes. A group can
name a local group or activate a declared optional dependency with
`dep:<alias>`. An item `<alias>/<feature>` requests a feature on the
dependency and activates the edge if optional. An item
`<alias>?/<feature>` requests the feature only when that optional edge
is active. Limits match Honk's 256 groups, items per group, dependency
requests per edge, and production dependencies. Cross-package requests
are checked for valid names at authoring time. The resolver must check
whether the selected target release defines those names.

Feature names and members are emitted in sorted order with duplicates
removed from arrays. Feature metadata is immutable once an entry is
published. The existing yank field remains the mutable field. An index
cannot mix package-file schema versions or change schema in place.
