# Security and privacy

ShapeDiff operates locally and does not perform HTTP requests. File comparison, directory scanning, JSONL processing and report export do not use accounts or telemetry. The tool records structural evidence (type counts, member names and observation counts), **not response values**. Field *names* can still be sensitive and appear in reports. Reports also include the input path labels.

## Input handling

- Only UTF-8 JSON is accepted. An initial UTF-8 BOM is tolerated.
- Duplicate object keys are rejected, preventing silent last-key-wins inference.
- Nonstandard `NaN` and `Infinity` constants are rejected.
- Individual JSON documents and JSONL lines are capped at 32 MiB by default.
- A side is capped at 100,000 documents, 250,000 distinct shape nodes and depth 128. All limits can be tuned in the CLI.
- Directory input examines supported sample extensions only. It is non-recursive by default, skips symlink files and does not traverse symlinked directories.
- `--ignore` is applied **before** a subtree is observed. Excluded values do not affect inference or reporting.
- No sample values, URLs in values, API keys or passwords are intentionally emitted in findings.

This is not a streaming parser for a single giant `.json` document. It reads one whole document into memory to parse it. `.jsonl` and `.ndjson` process each record as a separate document and do not retain previous raw record values. Peak process RSS will exceed the traced allocation metric in the benchmark, and resource limits are safeguards, not a sandbox for arbitrary untrusted files.

## Output handling

`--output` writes a same-directory temporary file and atomically renames it when complete. It refuses to overwrite a direct input path, a path within a sampled input directory, or an output symlink. An input or decoding failure does not replace the prior report. The user controls file permissions on saved reports; do not publish them blindly when field names or local paths are confidential.

## Endpoint suite manifests

Suite manifests must end in `.sdsuite`. They are size-bounded, have at most 1,000 response cases by default, reject duplicate case IDs and header names that differ only by case, and require body paths to stay within the manifest directory. Referenced bodies are parsed with the normal sample/profile limits. Added and removed cases are also validated before a report is produced.

Headers are opt-in and their values are compared exactly. Reports identify changed headers but do **not** include their values. The suite manifest itself contains the literal selected header values. Do not include credentials, tokens, cookies, or other private values in a manifest that might be committed or shared. The suite does not issue HTTP requests.

## Value-free profiles

A `.sdshape` profile stores JSON member keys, type and format counters, field presence counts, and aggregate document/object/array counts. It intentionally omits scalar response values, source paths and original byte lengths. Different scalar values with the same observed types, structure and counts produce byte-identical profiles when heuristic string formats are disabled.

**JSON keys can themselves contain private data.** Email-, UUID- and hex-like keys are blocked by default during capture; use `--map` for objects with dynamic identity keys, `--ignore` to discard paths, or `--allow-identifier-keys` after reviewing what would be retained. Other identifiers, secrets and personal data embedded in keys might escape these simple checks. Do not describe saved profiles as guaranteed anonymized or safe to publish without review.

Profiles are not executable and do not contain arbitrary code. Loading rejects unsupported versions, duplicate JSON keys, invalid counters, inconsistent node observations and mismatched processing semantics. A profile remains untrusted input; resource limits are applied before and during loading. Updating uses the same atomic file-replacement mechanism as reports. Existing profiles are not replaced by initial capture unless `--force` was explicitly provided. The user is responsible for protecting their baseline from unauthorized modification.

## Downloads

The README supports downloading the transparent, single-file CLI directly. For automated systems pin to a commit SHA or a reviewed release tag, inspect the script, and obtain it over HTTPS. A `main`-branch URL is convenient for exploration but mutable and not a supply-chain guarantee. No package signing or external security audit is claimed for this alpha.

## Reporting a security issue

Open a private GitHub security advisory for the repository after it is created. Do not attach API responses, access tokens or customer data to public issues. Reproduce issues with sanitized synthetic JSON fixtures when possible.
