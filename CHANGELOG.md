# Changelog

## 0.1.0a3 (unreleased)

- Added `shapediff suite` for named response contracts. Each case compares status, explicitly selected headers, and JSON body samples or saved profiles without pooling unrelated endpoints.
- Status and tracked header changes now produce directional findings; header values are never copied into reports.
- Suite manifests are versioned, bounded, reject duplicate response IDs and case-insensitive duplicate header names, and keep sample paths inside the manifest directory.
- Profile loading now rejects stored map layouts and ignored fields that contradict the saved processing rules.
- Added endpoint-suite integration and adversarial profile tests, examples, and a reproducible suite benchmark.

## 0.1.0a2 (unreleased)

- Added versioned `.sdshape` observation profiles that omit response scalar values and source byte lengths.
- Added incremental `profile --update` to accumulate baselines without retaining previous raw responses.
- Saved profiles preserve and automatically reapply map, ignore, format, and strict-number settings; incompatible inference rules now fail explicitly.
- Profile capture refuses obvious identifier-like object keys unless mapped, ignored, or explicitly permitted.
- Profile capture guards against accidental overwrite, mismatched map selectors, malformed profile counters and unsupported versions.
- Corrected integer-subtype compatibility when `--strict-integers` is enabled.
- Extended offline tests, profile round-trip fixtures, corrupted-input checks and reproducible benchmark coverage.

## 0.1.0a1 (unreleased candidate)

- Response-only structural comparison with ERROR/WARN/INFO findings.
- Support for JSON, JSONL, NDJSON, directories and standard input.
- Explicit map and ignore selectors, nested arrays and field observation counts.
- Text, JSON and Markdown reports with configurable CI gates.
- Standard-library-only runtime, offline tests and deterministic benchmarking.

Neither entry implies a GitHub tag or public release exists.
