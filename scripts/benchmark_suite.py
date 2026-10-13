#!/usr/bin/env python3
"""End-to-end local benchmark for a multi-endpoint suite."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import platform
from statistics import median
import sys
import tempfile
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shapediff  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=100)
    parser.add_argument("--documents", type=int, default=100, help="responses per case and side")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min(args.cases, args.documents, args.repetitions) < 1:
        parser.error("case, document and repetition counts must be positive")

    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        manifests = []
        input_bytes = 0
        for side in ("old", "new"):
            root = base / side
            root.mkdir()
            responses = []
            for case in range(args.cases):
                body = root / f"case-{case}.jsonl"
                with body.open("w", encoding="utf-8", newline="\n") as stream:
                    for document in range(args.documents):
                        payload = {"item": {"id": document, "active": True,
                                            "labels": ["alpha", "beta"]}}
                        if side == "new" and case == 0 and document == 0:
                            payload["item"]["id"] = "changed-type"
                        stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
                input_bytes += body.stat().st_size
                responses.append({
                    "id": f"GET /cases/{case}",
                    "status": 201 if side == "new" and case == 1 else 200,
                    "body": body.name,
                    "headers": {"content-type": "text/plain" if side == "new" and case == 2 else "application/json"},
                })
            manifest = root / "suite.sdsuite"
            manifest.write_text(json.dumps({"suite_version": 1, "responses": responses}), encoding="utf-8")
            manifests.append(manifest)

        def run() -> tuple[dict[str, object], float]:
            out = io.StringIO()
            start = perf_counter()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = shapediff.main(("suite", str(manifests[0]), str(manifests[1]),
                                      "--format", "json", "--fail-on", "never", "--quiet"))
            elapsed = perf_counter() - start
            if code != 0:
                raise RuntimeError(f"unexpected suite exit code: {code}")
            report = json.loads(out.getvalue())
            codes = {finding["code"] for finding in report["findings"]}
            if report["summary"]["errors"] != 3 or codes != {"type_added", "status_changed", "header_changed"}:
                raise RuntimeError(f"unexpected suite findings: {report['summary']}")
            return report, elapsed

        run()  # warm-up
        timings = [run()[1] for _ in range(args.repetitions)]
        report, _ = run()
        middle = median(timings)
        result = {
            "tool_version": shapediff.__version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cases_per_side": args.cases,
            "documents_per_case_per_side": args.documents,
            "documents_total": args.cases * args.documents * 2,
            "input_bytes": input_bytes,
            "repetitions": args.repetitions,
            "median_seconds": round(middle, 6),
            "min_seconds": round(min(timings), 6),
            "max_seconds": round(max(timings), 6),
            "documents_per_second": round(args.cases * args.documents * 2 / middle),
            "findings": report["summary"],
        }
        output = json.dumps(result, indent=2) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
