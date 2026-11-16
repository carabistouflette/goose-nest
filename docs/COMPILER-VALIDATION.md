# Pure-Goose compiler identity qualification

Date: 2026-11-16. Compiler fork
[`0ce3a5edb5679e10a490e9f66d5db5f6a30b9f63`](https://github.com/carabistouflette/goose/commit/0ce3a5edb5679e10a490e9f66d5db5f6a30b9f63),
[draft PR #1](https://github.com/carabistouflette/goose/pull/1), based on Honk's
existing `eadca409f68210893f366e60d0c2f0dc29a339be` compiler pin.

The opt-in graph mode can compile two incompatible pure-Goose package instances
in one executable. It separates their nominal types, globals and generated C
symbols, preserves definition-site dependency lookup, and deduplicates aliases
of one instance. This is a compiler foundation, not full Cargo parity or a new
Honk compiler pin.

## Passing local qualification

Linux x86-64, Clang 23.1.4, CMake Debug, `GOOSE_BUILTIN_LIBS=none`. The compiler
checkout was clean at the recorded commit. Both executables report that exact
full revision. [Machine receipt](validation/compiler-identity-2026-11-16.json)
includes binary/log SHA-256 digests and commands.

- [Targeted graph harness](validation/compiler-identity-2026-11-16.txt): 16 tests
  pass using real check, JIT and native build commands with isolated caches.
- [Same harness with the compiler under ASan/UBSan](validation/compiler-identity-asan-2026-11-16.txt):
  16 tests pass with leak detection and halt-on-error. Generated native programs
  in this harness use ordinary Clang; this run instruments the compiler itself.
- [Existing full native/JIT suite](validation/compiler-legacy-native-2026-11-16.txt):
  all checks pass, including 1,452 parse/roundtrip/typecheck checks, 694 native
  code-generation checks, 860 JIT checks, 204 debug-runtime checks, 54 driver/LSP
  checks, 14 native/package/runtime checks and 21 compiler bootstrap checks.
- [Existing suite with general native code generation disabled](validation/compiler-legacy-nocgen-2026-11-16.txt):
  all checks pass independently.

Graph cases include conflicting versions, wrong-version nominal rejection,
same physical source with different transitive bindings, generic/default scopes,
shared alias globals, imported-before-importer initialization, package-local
global lookup, method lookup, explicit target namespaces, stable identities
checked against Python's SHA-256, shuffled/relocated graphs, malformed metadata,
symlink containment, native/tooling rejection and legacy namespace/path packages.

## Limits and remaining work

These local runs exclude blessed audio/graphics/physics/UI native layers and
skip the existing JIT-incompatible thread cases; their normal native coverage
runs in the full native suite where applicable. Cross-platform/all-builtin CI
qualification and review are separate gates. No performance claim follows from
these correctness runs, and existing specialization numbering is not a stable
generated C ABI.

Graph mode rejects non-toolchain native sidecars, foreign extern/export surfaces,
sourced imports and unsupported dumps/editor modes. Honk graph emission,
multi-version solving, source-import migration and native-provider ownership are
unfinished. The compiler validates graph consistency but does not verify the
producer's asserted source snapshot/archive digests. See the
[implemented compiler contract](https://github.com/carabistouflette/goose/blob/0ce3a5edb5679e10a490e9f66d5db5f6a30b9f63/docs/design/package_graph.md)
and [design with subsequent acceptance gates](COMPILER-PACKAGE-IDENTITY.md).
