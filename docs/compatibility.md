# How compatibility is graded

ShapeDiff is a response-focused regression detector. It is **not** a JSON Schema or OpenAPI validator, and it does not infer formal `required`, `additionalProperties`, enum constraints or business invariants. It distinguishes observed facts from guarantees.

## Evidence

Each JSON document represents one sampled response. Every object increments the object count at its shape path; each field present in that object increments that field's presence count. For arrays, **each observed object element** contributes to the nested object's field counts. A JSONL line is one response; an array is one response with many elements. This avoids labeling a key seen in 1 of 100 array objects as appearing in 1 of 1 responses.

The numbers are observations, not statistical confidence intervals. There is no unbiased-sampling assumption. A key seen in 10 of 10 responses may still be optional, and a key seen in 4 of 10 may be required for a particular object subtype.

## Response compatibility direction

For backwards-compatible **response** behavior, new outputs must remain within the range that existing consumers can handle. Suppose the old observed type set is `T_old` and the new observed set is `T_new`:

- A new output type (`T_new` not contained in `T_old`) can break existing consumers. This is `ERROR` unless the baseline provides only `null`, in which case the non-null type is *unverified* and receives `WARN`.
- A type no longer observed in `T_new` generally reduces output variety. That is `INFO`, not a breaking error, provided a shared kind is left.
- Completely disjoint non-null kinds (e.g. `number` to `string`, `object` to `array`) are `ERROR`.
- `null` is a distinct JSON type. New `null` in a previously non-null response is `ERROR`.
- `boolean` is not a number even though Python's `bool` inherits from `int`.
- Integers and floating-point numbers both count as `number` by default. `--strict-integers` can separate them.

This is intentionally not the request-body direction. Whether a server accepts new request fields, removed parameters or changed request types cannot be reliably determined by comparing two example **requests**. ShapeDiff grades **responses only**.

## Presence

| Evidence | Signal | Why |
| --- | --- | --- |
| Field seen in 1/1 or N/N baseline objects, never seen in current | `ERROR missing` | It disappeared from all observed current objects; baseline obligation remains unproven |
| Field seen in K/N baseline objects where K < N, never seen in current | `WARN field_unobserved` | Could be conditional, could still be a regression |
| Field observed on both sides | Recurse into the value shape | Presence alone does not imply structure matches |
| Field first appears in current | `INFO field_added` | New response member; strict closed-schema consumers may still reject it |
| `--coverage-drop 0.5`: presence ratio falls by at least 50 points | `WARN presence_drop` | Opt-in distribution signal; requires at least three parent objects each side |

The CLI never claims that any observed field is definitively required or optional. `--evidence` adds observed counts to terminal output; JSON output includes those counts by default.

## Arrays and maps

An array with no observed entries has no element-type evidence. If another side contains entries, emit `WARN unverified_array_elements` rather than `ERROR` or silent success. Empty on both sides does not imply a change.

`--map /some/object` is an explicit declaration by the caller that object keys at that path are dynamic identifiers. Only the values are compared, at `some.object{*}`. Automatic map inference is deliberately absent because a same-shaped object key rename can be a real breaking change.

If a map on one side has no entries and the other does, a warning records this gap. Maps are not learned from unrelated endpoints or different URL routes.

## Formats

The default compares base JSON kinds, so different IDs or timestamps of the same kind do not create reports. With `--formats`, strings can be recognized as `uuid`, `date-time`, `date`, `email`, `url` or `plain`. A changed observed format set gets a `WARN`, never `ERROR`: these are hints from individual values, not format guarantees.

## Persisted evidence profiles

Use `shapediff profile SOURCE -o baseline.sdshape` to save the inferred observation counters without response scalar values. `shapediff profile SOURCE --update baseline.sdshape` merges new observations into that profile without access to the original data. Updates preserve the `present` counts from both batches and the total number of parent object observations, including nested arrays and explicitly mapped objects.

The profile format is versioned. `.sdshape` files are distinguished by extension, checked for malformed counters and incompatible settings, and bounded by the same resource limits as other inputs. The profile carries its processing rules: saved `--ignore`, `--map`, `--formats`, and `--strict-integers` are automatically applied to newly compared or accumulated raw samples. Incompatible rules cause an error, not an apparent success.

Profiles store member names as written. If user IDs or email addresses are *object keys* rather than values, configure `--map` or `--ignore` before capture. Some identifier-looking keys are blocked by default, but that detection is deliberately not a privacy guarantee.

With `--strict-integers`, new `number` observations can widen an integer-only response and are an error. Narrowing an old `number` response to new `integer` observations is not a breaking type expansion, because integer is a subtype of number. This is about observed JSON kinds, not a proof of any numeric range or generated-client behavior.

## Limits

- Value changes, array order and field order never create findings.
- Field **presence frequencies** are observational and may reflect different datasets rather than an API change.
- Schema-level constraints such as enum membership, lengths, numeric bounds, patterns, cross-field dependencies and authentication outcomes are not inferred.
- The direct two-input comparison checks only the selected response body. Use a suite manifest to keep method/endpoint identities separate and to compare status and selected headers.
- Objects with literal dynamic keys must be configured using `--map` to avoid key churn masquerading as removals.
- Sample directories are collections for **one** endpoint/response contract. Do not pool unrelated contracts.

Treat a clean result as "no structural regression detected in the supplied evidence", not as a certificate of compatibility.

## Endpoint suites

`shapediff suite` matches cases by their explicit `id`; use a stable method-and-route label such as `GET /users/{id}`. Case identity is caller supplied and never inferred from payload contents. Missing current cases are `ERROR`, newly listed cases are `INFO`. A changed HTTP status is `ERROR`, including changes between successful status codes. This is an exact observed-status comparison, not an HTTP semantics engine.

`headers` are an explicit allowlist represented by name/value pairs in each case. Header names are matched case-insensitively. A tracked header missing from current, or one whose value differs exactly, is `ERROR`; a newly tracked header is `INFO`. Volatile headers should be omitted. Multi-value headers, content negotiation, authentication, and request-to-response relationships are outside the model.

Bodies are compared by the same evidence rules as direct mode. A body removed entirely is `ERROR`; a body added is `INFO`. If one body is a `.sdshape` profile, its saved processing rules apply to the other body in that case. Different cases may use different rules. Source paths cannot escape the suite directory. ShapeDiff does not fetch endpoints, construct requests, or assert that supplied samples are representative.
