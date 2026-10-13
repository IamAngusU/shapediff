#!/usr/bin/env python3
"""Install a built wheel offline in a fresh venv and exercise the real CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import venv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel_directory", type=Path)
    args = parser.parse_args()
    wheels = sorted(args.wheel_directory.glob("shapediff-*.whl"))
    if len(wheels) != 1:
        parser.error("expected exactly one shapediff wheel")
    wheel = wheels[0].resolve()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temporary:
        environment = Path(temporary) / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if sys.platform == "win32" else "bin")
        python = scripts / ("python.exe" if sys.platform == "win32" else "python")
        command = scripts / ("shapediff.exe" if sys.platform == "win32" else "shapediff")
        subprocess.run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], check=True)
        version = subprocess.run([str(command), "--version"], check=True, text=True, capture_output=True).stdout.strip()
        expected_version = wheel.name.split("-")[1]
        if version != f"shapediff {expected_version}":
            raise RuntimeError(f"unexpected CLI version: {version!r}")
        result = subprocess.run(
            [str(command), "suite", str(root / "examples" / "baseline.sdsuite"),
             str(root / "examples" / "current.sdsuite"), "--format", "json", "--fail-on", "never"],
            check=True, text=True, capture_output=True,
        )
        report = json.loads(result.stdout)
        if report["summary"]["errors"] != 3 or report.get("mode") != "suite":
            raise RuntimeError(f"unexpected installed CLI report: {report['summary']}")
    print(f"verified installed {version}: 3 expected suite regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
