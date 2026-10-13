# Local performance benchmark

Benchmark results in this repository are produced by [`scripts/benchmark.py`](../scripts/benchmark.py), not estimated from code complexity. The script generates deterministic UTF-8 JSONL fixtures in a temporary directory and measures a complete **two-side parse, inference and comparison**. Sample values are discarded after observation. Both sides contain real type changes.

The script reports a median from repeated `time.perf_counter()` trials after a warm-up. Peak traced allocations are measured in a separate pass using `tracemalloc`. That figure is **not** total process RSS and must not be presented as such.

To reproduce:

```sh
python3 scripts/benchmark.py --documents 5000 --repetitions 4
python3 scripts/benchmark.py --documents 10000 --repetitions 5 --output my-benchmark.json
```

The recorded execution environment, number of documents, input bytes, observed findings, throughput and duration are all in [`benchmark-local.json`](benchmark-local.json). Numbers depend heavily on CPU, storage, Python version and concurrent system load. The benchmark does **not** establish superiority over any competing tool. Sample documents are small, with nested objects and arrays, so very wide or deeply nested payloads may perform differently.

## Baseline measurement for 0.1.0a1

The committed measurement was collected on the recorded Linux host using Python 3.13.5 and 5,000 generated JSONL documents per side. The script found two structural errors, `user.id` and `user.email`, as intended. See the machine-readable result for actual speed, repeated timings and traced allocations rather than treating a single run as a universal performance characteristic.

The 0.1.0a2 profile workflow has a separate capture/update benchmark. Profiles are smaller than the source dataset when the shape repeats many times; the size ratio depends strongly on object-key cardinality and field diversity. Profile size is not a measurement of total process memory.

The 0.1.0a3 Windows reruns of the direct and profile benchmarks are recorded in [`benchmark-windows-a3.json`](benchmark-windows-a3.json) and [`benchmark-profile-windows-a3.json`](benchmark-profile-windows-a3.json). They used Python 3.12.14; the direct run used 5,000 documents per side and eight timed repetitions. Host load affected a shorter three-run pass, so the committed direct figure uses the longer pass. These results should not be used as cross-machine speed comparisons.

## Endpoint suite measurement for 0.1.0a3

`python3 scripts/benchmark_suite.py --cases 100 --documents 100 --repetitions 8` generates 100 named contracts per side, with 100 JSONL samples in each contract. It measures suite manifest loading, body parsing, comparison and JSON report rendering together. The fixtures include one body type regression, one HTTP status change and one tracked header value change. The JSON result is stored in [`benchmark-suite-local.json`](benchmark-suite-local.json). Suite timings include per-file overhead and must be compared only with measurements using the same case and document counts.

## Reusable profile measurement for 0.1.0a2

`python3 scripts/benchmark_profiles.py --documents 10000 --repetitions 5` measures four operations separately: initial profile capture, two-raw-input comparison, saved-profile-versus-raw comparison and incremental update. It uses the same synthetic input shape for each repetition and excludes a warm-up. See [benchmark-profile-local.json](benchmark-profile-local.json). These timings are process-local and do not represent an independent cross-tool performance comparison.
