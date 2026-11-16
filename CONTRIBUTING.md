# Contributing

All project content and diagnostics are in English. Keep the native client in
Goose; Python is only for authoring, fixtures and benchmarks. Prefer bounded data
structures and measured improvements to speculative abstractions.

Install Git, Make, CMake 3.27+, C/C++20 tools, pkg-config, Python 3.11+, and development
headers for libcurl 7.85+, OpenSSL 3+ and libarchive 3+. Build the pinned compiler
with `make setup`, or provide that exact compiler through `GOOSE`.

Run `make check test native-test` before submitting code. Run `make bench` with
`HONK` pointing at a Honk build containing Nest integration to measure full fetch.
Do not commit temporary toolchains, generated archives, cache files, or tokens.

For a package submission, use tools/registry.py to inspect a local release archive
and prepare its index entry, then open a pull request. Maintainers must verify
that the submitter controls the package's upstream repository, review name
collisions and provenance, and download/hash the actual hosted archive. CI does
not establish ownership. Published records may only change the yanked field.
Do not delete versions, repoint URLs, or replace bytes behind an accepted URL.
