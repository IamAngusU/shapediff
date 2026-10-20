# Measured quality and performance

These are recorded local results for ShapeDiff `0.1.0a3`, not promises for other machines or API payloads. The JSON files in this directory contain the full inputs to each measurement, environment and repeated timings.

| Check | Measured result | Evidence |
| --- | ---: | --- |
| Automated tests | 115 passed | `python -m unittest discover -s tests -v` on Windows, Python 3.12.14 |
| Direct comparison | 10,000 responses in 0.248 s median (8 runs) | [direct benchmark](benchmark-windows-a3.json) |
| Endpoint suite | 100 cases, 20,000 responses in 0.303 s median (8 runs) | [suite benchmark](benchmark-suite-local.json) |
| Suite fixture regressions | 3 of 3 detected | [suite benchmark](benchmark-suite-local.json) |
| Saved profile size | 4,517 B from a 685,280 B baseline (99.341% smaller) | [profile benchmark](benchmark-profile-windows-a3.json) |
| Installed wheel | Fresh virtual environment, offline install, CLI and suite smoke check passed | `scripts/verify_wheel.py` |

The comparison timings cover parsing and shape inference, not network requests. The direct and suite fixtures have different structures, so their throughputs cannot be compared as an optimization result. The profile ratio comes from repeated, synthetic shapes and will vary with field and object-key diversity. The 115 tests verify documented behaviors and regressions, but they do not establish correctness for every JSON input.

The local baseline-to-current direct comparison measured 0.258 s versus 0.254 s median with interleaved runs on identical fixtures. That small difference is within normal local variability; no speedup is claimed.

See [benchmark methodology](benchmark.md) for reproduction commands and measurement limits. [Runner account context](https://github.com/IamAngusU/IamAngusU/blob/main/ci.md). The [public CI mirror](https://github.com/angusu-de/shapediff-ci/actions/workflows/ci.yml) runs tests on Linux, Windows and macOS and verifies an installed wheel on Linux. Its first passing [five-job run](https://github.com/angusu-de/shapediff-ci/actions/runs/38393567734) tested source commit `3b42dd3fe5e154e17d54215559881bb6afc83422`, identical to the then-published commit in `IamAngusU/shapediff`. Compare the commit SHA in both repositories for later runs. The README badge shows the mirror's latest `main` result; it is not a status claim for the blocked workflow on `IamAngusU`.

## Python compatibility verification for 0.1.0a4

All 115 offline tests passed on Windows x64 with CPython 3.10.22, 3.11.9,
3.12.10, 3.13.16 and 3.14.8. [Per-runtime output and source hash](verification-windows-a4.json).
The CI matrix now also covers every Python minor from 3.10 through 3.14 on
Linux, the minimum 3.10 and 3.12 on Windows, and 3.12 on macOS, plus an installed
wheel check. The mirror rejects a SHA that differs from canonical main.
The earlier benchmarks above retain their original environments and versions.

The README image renders the actual stdout/stderr from the included example
command; [plain transcript](cli-output.txt). It is a presentation of CLI output,
not a screenshot of a user's terminal or a performance benchmark.
