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

See [benchmark methodology](benchmark.md) for reproduction commands and measurement limits. The live [CI workflow](https://github.com/IamAngusU/shapediff/actions/workflows/ci.yml) runs tests on Linux, Windows and macOS and verifies an installed wheel on Linux. The badge in the README reflects the latest workflow result for `main` once GitHub has run it; this page's local measurements remain a separate record.
