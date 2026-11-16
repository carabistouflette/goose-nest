# Package-management benchmark

Compare warm locked offline `honk fetch --frozen` against
`cargo fetch --locked --offline` on the same synthetic graph: a root library and
24 small leaf libraries. Both fetch real registry archives first; Cargo uses a
local sparse HTTP registry, not path dependencies. Neither measured command
compiles source. The loopback server counts HTTP requests.

The harness alternates invocation order, performs three warmups, records every
process wall-time sample, and includes tool versions, platform and binary hashes.
Honk recomputes extracted source digests on every cache hit; Cargo uses its own
cache policy. Different languages, archive manifests and validation work mean
these are comparable user operations, not identical internal algorithms.

```sh
make build
python3 bench/run.py --nest .build/nest --honk /absolute/path/to/honk \
  --samples 31 --packages 24 --output bench/results.json
```

Set `HONK` for `make bench` when Honk is not at `../honk/.build/honk`.
The harness uses isolated temporary homes and no public network.

Cold times include loopback downloads and are single observations, not Internet
performance estimates. Warm timings are host-specific synthetic measurements.
They say nothing about compiler speed, large registries, adversarial constraint
solving, or universal performance versus Cargo. A bounded chronological solver
can perform worse than Cargo's solver on difficult graphs; work exhaustion is an
explicit error. This alpha does not claim general SOTA resolver complexity.

## Recorded alpha result

On Linux-7.2.15-arch1-1-x86_64-with-glibc2.44, with cargo 1.101.0-nightly (29c5daa1a 2026-10-07), 25 registry packages and
31 alternating samples, warm locked fetch median was **21.06 ms
for Honk** and **75.36 ms for Cargo** (3.58x lower
wall time in this scenario). The respective p95 values were 22.60 ms
and 80.59 ms. Counted warm HTTP requests: **0**.

[Raw samples and binary identities](results.json) are the evidence. This is a
package-fetch result, not a compilation benchmark or a general Cargo comparison.
