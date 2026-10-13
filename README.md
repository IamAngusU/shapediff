<p align="center">
  <img src="docs/assets/shapediff-wordmark.svg" width="360" alt="ShapeDiff">
</p>

<h1 align="center">Compare responses. Not the noise.</h1>
<p align="center">Find API shape regressions without maintaining a schema.</p>

<p align="center">
  <a href="https://github.com/IamAngusU/shapediff/actions/workflows/ci.yml"><img src="https://github.com/IamAngusU/shapediff/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"></a>
  <a href="https://github.com/IamAngusU/shapediff/releases/tag/v0.1.0a3"><img src="https://img.shields.io/badge/release-0.1.0a3-blue" alt="Release 0.1.0a3"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT license"></a>
</p>

<p align="center">
  <a href="README.de.md">Deutsch</a> ·
  <a href="#get-running">Get running</a> ·
  <a href="#more-than-two-samples">Multiple samples</a> ·
  <a href="#compare-multiple-endpoints">Endpoint suites</a> ·
  <a href="#what-the-results-mean">Compatibility rules</a> ·
  <a href="docs/compatibility.md">Exact semantics</a> ·
  <a href="docs/security.md">Security</a> ·
  <a href="docs/metrics.md">Measured results</a>
</p>

ShapeDiff compares **observed JSON API response structures**. IDs, timestamps, names and every other ordinary value can change without producing a finding. Types, missing fields and changes inside nested objects or arrays are checked.

It runs locally, reads files or stdin, and has **no runtime dependencies**, account, telemetry or network calls.

```text
$ python3 shapediff.py examples/production.json examples/staging.json

ERROR  user.email   missing
ERROR  user.id      number -> string
INFO   user.avatar  added

shapediff: 2 breaking, 0 warning, 1 info  |  samples 1 -> 1
```

The summary is printed to stderr; findings are printed to stdout. Exit code `1` means a breaking finding was observed. A summary of what was observed is not a proof that an undocumented endpoint has a stable contract.

## Get running

**Python 3.10 or newer.** The [GitHub release](https://github.com/IamAngusU/shapediff/releases/tag/v0.1.0a3) offers an installable wheel and a standalone `shapediff.py`. There are no runtime packages to resolve. `pipx` installs the command into its own environment:

```sh
pipx install 'https://github.com/IamAngusU/shapediff/releases/download/v0.1.0a3/shapediff-0.1.0a3-py3-none-any.whl'
shapediff production.json staging.json
```

Install [pipx](https://pipx.pypa.io/stable/installation/) first if needed. For a project virtual environment, use `python -m pip install` with the same wheel URL. The release includes `SHA256SUMS.txt` for checking downloaded artifacts. Use a release URL in automation so the installed version stays fixed.

The single-file option needs no package installation:

### macOS / Linux

```sh
curl -fsSL https://github.com/IamAngusU/shapediff/releases/download/v0.1.0a3/shapediff.py -o shapediff.py && python3 shapediff.py production.json staging.json
```

### Windows PowerShell

```powershell
Invoke-WebRequest -ErrorAction Stop 'https://github.com/IamAngusU/shapediff/releases/download/v0.1.0a3/shapediff.py' -OutFile shapediff.py; py -3 shapediff.py production.json staging.json
```

The download saves readable Python source; it does not pipe remote code into a shell. Review it and verify its SHA-256 before running it when your environment requires that assurance. From a clone, `python3 shapediff.py` and `python3 -m shapediff` work without installing anything.

## Reusable baselines without keeping response values

Capture a versioned `.sdshape` profile once, then compare later responses directly against it. The profile stores observed type counts, field presence counts, and nested shapes. **No scalar response values or source byte lengths are saved.**

```sh
# First capture: a response file, a JSONL stream, or a directory
python3 shapediff.py profile production.json -o production.sdshape

# Check a new response against the stored observations
python3 shapediff.py production.sdshape staging.json --breaking-only

# Add another observation without retaining the original response
curl -fsS https://api.example.test/users/1 | python3 shapediff.py profile - --update production.sdshape

# Review the accumulated baseline against new data
python3 shapediff.py production.sdshape current/ --format markdown
```

Profiles can also be compared against each other: `shapediff old.sdshape new.sdshape`. Comparison automatically inherits the original `--map`, `--ignore`, `--formats` and `--strict-integers` rules from the profile. If two profiles disagree, the comparison stops instead of returning misleading findings. Updates merge presence and type counts and use an atomic file replacement. A failed update leaves the original intact.

`--output` on `profile` refuses to replace an existing baseline unless you supply `--force`. Use `--update` to add observations rather than rebuilding from raw responses.

**Privacy boundary:** literal JSON *object keys* are preserved. A key that is itself an email address, UUID or other identifier can be sensitive. Capture refuses obvious email/UUID/hex-style identifiers as keys by default and directs you to `--map` or `--ignore`. `--allow-identifier-keys` is an explicit escape hatch. This is a heuristic, not a guarantee that every potentially sensitive key is detected; inspect profiles before sharing them.

```sh
# User IDs in object keys become one value-shape, without recording the IDs
python3 shapediff.py profile users.jsonl -o users.sdshape --map /usersById
```

A profile is **not** a JSON Schema, a contract certificate, or an authorization-safe data export. Its counters only describe the responses you sampled. See [profile safety and limitations](docs/security.md).

## More than two samples

One response cannot establish optionality. Multiple responses give a better **observed frequency**, but still cannot prove an API field is required or optional. ShapeDiff keeps these distinctions visible.

```sh
shapediff examples/baseline/ examples/current/
```

```text
ERROR  tags[*].count  number -> string
WARN   avatar         not seen in current samples (baseline 1/3)
```

Here, `avatar` appeared in one of three baseline object observations. It is a warning, not a guaranteed breaking change and not a proven optional field. A field present in all baseline observations and absent in all current observations is reported as `ERROR missing`, together with counts when `--evidence` is enabled.

Each directory is a **collection of samples of the same response contract**. Do not put multiple unrelated endpoints in one directory: that would mix their structures. Directory scanning is non-recursive unless `--recursive` is set.

`.json`, `.jsonl`, `.ndjson` and `-` (stdin) are supported. JSONL and NDJSON use one response per non-empty line. A JSON array remains one response containing an array, not a collection of independent responses.

```sh
shapediff baseline.jsonl current.ndjson --evidence
curl -fsS https://api.example.test/users/1 | shapediff production.json -
shapediff production.json staging.json --breaking-only
shapediff production.json staging.json --format json --output report.json
shapediff baseline/ current/ --coverage-drop 0.5 --fail-on warning
```

The URL example uses `curl`, not built-in HTTP fetching. ShapeDiff itself never contacts the network and never handles API credentials. Use `curl -f` or equivalent so failed HTTP requests do not accidentally become valid baseline responses.

## What the results mean

| Observed difference in a **response** | Default |
| --- | --- |
| Field seen in every baseline object but missing everywhere in current | `ERROR` |
| `number` becomes `string` | `ERROR` |
| New possible type, including `string` becoming `string\|null` | `ERROR` |
| Previously intermittent field is not seen in current samples | `WARN` |
| `null`-only baseline becomes a populated type | `WARN` |
| Array has elements on one side and only empty arrays on the other | `WARN` |
| New field appears | `INFO` |
| An observed type disappears but remaining types are still supported | `INFO` |
| Only values change | No finding |

A response consumer must be able to handle all new values; **adding a possible output type can therefore break it**. Conversely, the disappearance of one previously observed type is generally a narrowing of observed output behavior, not a new consumer burden.

These classifications are conservative regression signals, not formal backward-compatibility proofs. See [the precise evidence and grading rules](docs/compatibility.md), including what ShapeDiff cannot know from data alone.

## Compare multiple endpoints

Use `suite` when a test run covers several response contracts. A suite file names each response, records its observed HTTP status, and points to JSON samples, a sample directory, a `.sdshape` profile, or `null` for a bodyless response. ShapeDiff matches cases by `id` and compares their bodies **independently**.

```sh
python3 shapediff.py suite examples/baseline.sdsuite examples/current.sdsuite
python3 shapediff.py suite before.sdsuite after.sdsuite --format json --output report.json
```

```json
{
  "suite_version": 1,
  "responses": [
    {
      "id": "GET /users/{id}",
      "status": 200,
      "body": "samples/users.jsonl",
      "headers": {"content-type": "application/json"}
    },
    {"id": "DELETE /users/{id}", "status": 204, "body": null}
  ]
}
```

Save the manifest with a `.sdsuite` suffix. Body paths are relative to its directory and must stay within it. A case can use a saved profile as its body baseline; its inference rules are inherited for that case. `--max-samples` and `--max-shape-nodes` apply **per case**. Suites are read locally and do not make HTTP requests.

Only headers listed in the manifest are compared. Header names are case-insensitive; values are compared exactly, so include stable values such as `content-type`, not request IDs or timestamps. A changed status, removed case, missing tracked header, or changed tracked header value is an `ERROR`. A new case or header is `INFO`. Header values are never copied into reports, but **the manifest itself contains them**; do not put credentials or private header values there. See [suite semantics](docs/compatibility.md) and [security guidance](docs/security.md).

## Dynamic keys, on purpose

Dynamic object members are common in maps keyed by UUIDs, region IDs or usernames. Without a schema, there is no reliable general-purpose way to distinguish that pattern from removed fields. **ShapeDiff never guesses by default.**

```sh
shapediff before.json after.json --map /usersById
shapediff before.json after.json --map /regions --ignore '/regions/*/traceId'
```

`--map /usersById` treats the keys at that object path as entries, compares the merged **value shapes** at `usersById{*}`, and does not report key turnover as removals/additions. Map values still produce breaking findings for structural regressions. If one side contains no map entries, coverage is marked `WARN`, not falsely clean.

Both `--ignore` and `--map` accept JSON Pointer-style selectors. `*` matches one path segment, `**` matches zero or more. Escape literal `/` as `~1` and `~` as `~0`. For simple names, `items[*].etag` is also accepted. Prefer pointers for keys containing dots or brackets.

## Use it in CI

```sh
shapediff tests/contracts/production/ tests/contracts/staging/ --breaking-only --quiet
```

Exit codes are stable and deliberate:

| Exit | Meaning |
| --- | --- |
| `0` | No findings at the selected failure level |
| `1` | A finding matched `--fail-on` |
| `2` | Invalid command-line usage |
| `3` | Invalid JSON, inaccessible input, limit exceeded or output I/O error |
| `130` | Interrupted |

`--fail-on error` is the default. Select `warning`, `any` or `never` to choose the gate; `--breaking-only` filters the **display** and does not change the exit logic. JSON and Markdown outputs are available for build artifacts and PR reviews.

| Option | Purpose |
| --- | --- |
| `--evidence` | Show observation counts beside text findings |
| `--format text\|json\|markdown` | Text, structured JSON or PR-ready Markdown |
| `--output FILE` | Atomic report write, rejects overwriting input files |
| `--ignore SELECTOR` | Skip a subtree before inference; repeatable |
| `--map SELECTOR` | Explicitly treat an object as a dynamic-key map |
| `--formats` | Opt into string-format drift warnings |
| `--strict-integers` | Distinguish integer and number observations (integer is a number subtype) |
| `--coverage-drop 0.5` | Warn on large observed drops in field presence |
| `--recursive` | Also include sample files in subdirectories |
| `--max-document-mib N` | Bound each JSON document / JSONL line; default 32 |
| `--max-samples N` | Bound observations per side; default 100,000 |
| `--max-shape-nodes N` | Bound inferred shape size; default 250,000 |
| `--max-depth N` | Bound nesting depth; default 128 |
| `--color auto\|always\|never` | ANSI colors in terminal reports |

Run `shapediff --help` or `shapediff profile --help` for the full interface. Profile capture supports `--update`, `--force` and `--allow-identifier-keys` in addition to the relevant ingestion flags.

## Development and verification

```sh
python3 -m unittest discover -s tests -v
python3 scripts/benchmark.py --documents 5000 --repetitions 5
python3 shapediff.py examples/production.json examples/staging.json --fail-on never
```

Tests are standard-library-only, offline and repeatable. [Local verification](docs/verification-local.json), [comparison benchmark](docs/benchmark-local.json) and [saved-profile benchmark](docs/benchmark-profile-local.json) record what actually ran. The optional GitHub Actions workflow performs the same test suite, but a workflow file alone is not proof that CI ran. This alpha has not been represented as a published or externally audited release.

## License

[MIT](LICENSE) · © 2026 Angus Uelsmann · [angusu.de](https://angusu.de)
