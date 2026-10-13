#!/usr/bin/env python3
"""Reproducible local end-to-end JSONL benchmark. No external dependencies."""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import platform
from statistics import median
import tempfile
import time
import tracemalloc
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import shapediff as sd  # noqa: E402


def make_samples(directory: Path, docs: int, new: bool) -> Path:
    path = directory / ("staging.jsonl" if new else "production.jsonl")
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for i in range(docs):
            payload = {
                "user": {
                    "id": str(i) if new else i,
                    "email": f"person{i}@example.test" if not new else None,
                    "username": f"user-{i}",
                },
                "meta": {"generation": i, "valid": True},
                "items": [
                    {"code": i, "qty": 1, "active": (i % 2 == 0)},
                    {"code": i + 1, "qty": 2, "active": (i % 2 != 0)},
                ],
            }
            # Here email changes from string to null; the benchmark tests this
            # structural regression rather than suppressing it as value noise.
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return path


def execute(baseline: str, current: str) -> dict[str, object]:
    opts = sd.Options()
    before = sd.load_dataset(baseline, opts)
    after = sd.load_dataset(current, opts)
    return sd.build_report(before, after, opts)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--documents", type=int, default=5000, help="records per environment")
    p.add_argument("--repetitions", type=int, default=5)
    p.add_argument("--output", type=Path, help="write the benchmark measurements as JSON")
    args = p.parse_args()
    if args.documents < 1 or args.repetitions < 1:
        p.error("documents and repetitions must be positive")
    with tempfile.TemporaryDirectory() as temp:
        old = make_samples(Path(temp), args.documents, False)
        new = make_samples(Path(temp), args.documents, True)
        total_bytes = old.stat().st_size + new.stat().st_size
        execute(str(old), str(new))  # warm-up
        timings = []
        for _ in range(args.repetitions):
            gc.collect()
            start = time.perf_counter()
            report = execute(str(old), str(new))
            timings.append(time.perf_counter() - start)
        gc.collect()
        tracemalloc.start()
        execute(str(old), str(new))
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        middle = median(timings)
        result = {
            "tool_version": sd.__version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "documents_per_side": args.documents,
            "documents_total": args.documents * 2,
            "input_bytes": total_bytes,
            "repetitions": args.repetitions,
            "median_seconds": round(middle, 5),
            "min_seconds": round(min(timings), 5),
            "max_seconds": round(max(timings), 5),
            "documents_per_second": round(args.documents * 2 / middle),
            "input_megabytes_per_second": round(total_bytes / 1024 / 1024 / middle, 2),
            "tracemalloc_peak_mebibytes": round(peak / 1024 / 1024, 2),
            "findings": report["summary"],
        }
        print(json.dumps(result, indent=2))
        if args.output is not None:
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
