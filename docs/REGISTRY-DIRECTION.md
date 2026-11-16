# Registry direction

Status: design direction, 2026-11-16. This does not change the alpha protocol or
claim endorsement from Goose's maintainers.

Goose already handles local and Git packages. Nest adds discovery, immutable
release metadata, archive integrity and reproducible Honk workflows. A registry
is optional infrastructure: ordinary Git/path projects must remain useful
without a Nest account, registry lookup or hosted service.

## Names and ownership

The next protocol should identify packages by registry, author and project:
`<registry>/alice/http`. Source imports use a local alias such as `http`; the
alias is not the globally allocated package name. Two authors may publish an
HTTP library without competing for ownership of a flat `http` slot. A registry
can curate recommendations without reserving generic names for preferred
third-party implementations. Compiler-owned names such as `std` remain a
separate toolchain concern.

The alpha currently validates flat package names and serves
`<registry>/<package>.toml`. It does **not** yet accept `alice/http`, verify
publisher ownership or implement a scoped publishing workflow. The migration
requires a versioned index format, explicit ownership checks, safe path encoding,
and lock/source identity migration. Do not silently reinterpret existing locks
or treat a GitHub username as authenticated just because it appears in JSON.

Goose's suggested `reg:author/project@version` syntax is a useful potential
compiler-facing interface. Nest does not reserve that prefix or require a
language syntax change. Honk can represent an optional registry in its manifest
and pass resolved dependency bindings to a qualified compiler instead.

## Initial hosting

Keep the index and discovery site static on GitHub Pages, with immutable source
archives in GitHub Releases and checksums in the index. No always-running
application server is required. GitHub LFS is unnecessary for this model and
would add a second quota/transport mechanism to package acquisition. GitHub
documents release assets as downloadable release attachments and separately
meters LFS storage/downloads. [Release assets](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases),
[LFS billing](https://docs.github.com/en/billing/concepts/product-billing/git-lfs).

GitHub hosting still has service limits and no permanent zero-cost guarantee.
Pages is available for public repositories on GitHub Free, subject to its
[usage limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits).
Preserve the protocol's ordinary HTTPS URLs so an index or archive mirror can
move independently of the client. Lock identities must include the registry
source, not just the package's short name. Support multiple explicit registries;
avoid searching unrelated registries implicitly for an unresolved dependency.
An index is a discovery and release service, not a requirement that package
source remain on GitHub.

## Compiler boundary

The compiler should consume a resolved, materialized graph and perform no
registry lookup in that mode. Honk owns acquisition, solving and lock policy;
the compiler owns package instance identity, name lookup, nominal types and
generated symbol isolation. This keeps registry deployment decisions outside
the language implementation.

Multiple incompatible versions need scoped compiler identities even when every
source is a direct Git checkout. That work is independent of whether a central
registry is desirable. The first compiler implementation is an opt-in pure-Goose
slice; foreign native libraries, graph-aware editor tooling and Honk's graph
emission still need qualification. Full Cargo parity remains a delivery target,
not an alpha release claim. See [the parity audit](CARGO-PARITY.md).
