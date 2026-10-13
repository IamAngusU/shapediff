#!/usr/bin/env python3
"""Measure repeatable profile capture and comparison on synthetic JSONL fixtures."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shapediff  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--documents", type=int, default=10000)
    p.add_argument("--repetitions", type=int, default=5)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    if args.documents < 1 or args.repetitions < 1:
        p.error("document count and repetition count must be positive")

    def run(*argv: str) -> tuple[int, float]:
        start = perf_counter()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            exit_code = shapediff.main(argv)
        return exit_code, perf_counter() - start

    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        old, current = root / "old.jsonl", root / "new.jsonl"
        with old.open("w", encoding="utf-8") as a, current.open("w", encoding="utf-8") as b:
            for i in range(args.documents):
                item = {
                    "user": {
                        "id": i,
                        "name": f"user-{i}",
                        "active": i % 2 == 0,
                        "timestamp": f"2026-01-{1 + i % 27:02d}T12:34:56Z",
                        "profile": {"rank": i % 9, "tags": ["first", "second"]},
                    }
                }
                a.write(json.dumps(item, separators=(",", ":")) + "\n")
                # A deliberate type drift in one out of N current responses.
                if i == args.documents // 2:
                    item["user"]["profile"]["rank"] = "wrong-type"
                b.write(json.dumps(item, separators=(",", ":")) + "\n")
        output = root / "baseline.sdshape"
        report = root / "report.json"
        capture: list[float] = []
        compare_raw: list[float] = []
        compare_profile: list[float] = []
        update: list[float] = []
        for _ in range(args.repetitions + 1):
            values = (
                run("profile", str(old), "-o", str(output), "--force", "--quiet"),
                run(str(old), str(current), "--format", "json", "--output", str(report), "--quiet"),
                run(str(output), str(current), "--format", "json", "--output", str(report), "--quiet"),
                run("profile", str(current), "--update", str(output), "--quiet"),
            )
            if tuple(code for code, _ in values) != (0, 1, 1, 0):
                raise RuntimeError(f"unexpected benchmark exit codes: {[code for code, _ in values]}")
            if _:
                capture.append(values[0][1])
                compare_raw.append(values[1][1])
                compare_profile.append(values[2][1])
                update.append(values[3][1])

        size_raw = old.stat().st_size
        size_profile = output.stat().st_size
        result_report = json.loads(report.read_text(encoding="utf-8"))
        result = {
            "tool_version": shapediff.__version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "dataset": "synthetic stable-shape JSONL with one rank type drift",
            "documents_per_side": args.documents,
            "repetitions": args.repetitions,
            "bytes_in_original_baseline": size_raw,
            "bytes_in_saved_profile": size_profile,
            "profile_size_reduction_percent": round((1 - size_profile / size_raw) * 100, 3),
            "median_seconds": {
                "capture_from_raw": round(statistics.median(capture), 6),
                "compare_two_raw_jsonl": round(statistics.median(compare_raw), 6),
                "compare_profile_to_raw_jsonl": round(statistics.median(compare_profile), 6),
                "update_profile_with_more_jsonl": round(statistics.median(update), 6),
            },
            "findings": result_report["summary"],
            "finding_paths": [item["path"] for item in result_report["findings"]],
            "notes": "Local timing, not a cross-machine or competitor benchmark. Warm-up excluded. Updated profile is reset at the start of each repetition. No raw values retained by saved profile.",
        }
        text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
