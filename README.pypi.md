# ShapeDiff

Compare observed JSON API response structures without maintaining a schema.
For developers checking undocumented endpoints, legacy APIs and response
regressions in CI. Python 3.10+, no runtime dependencies, network calls or telemetry.

```sh
shapediff production.json staging.json
```

Types, missing fields and nested object/array changes are checked; ordinary scalar
values such as IDs and timestamps can change without producing findings.
Exit code 1 means a breaking finding was observed. A clean diff describes the
sampled responses and does not prove a complete API contract.

The CLI also supports JSONL/directories, value-free saved profiles, endpoint
suites, ignore/map rules and JSON/Markdown output.

[Quick start, examples and screenshots](https://github.com/IamAngusU/shapediff#readme) ·
[Compatibility rules](https://github.com/IamAngusU/shapediff/blob/main/docs/compatibility.md) ·
[Security and profile privacy](https://github.com/IamAngusU/shapediff/blob/main/docs/security.md) ·
[MIT license](https://github.com/IamAngusU/shapediff/blob/main/LICENSE)
