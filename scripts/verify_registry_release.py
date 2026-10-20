"""Check public PyPI bytes against reviewed artifacts and exercise a clean install."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import venv

MAX_DOWNLOAD = 10 * 1024 * 1024


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError("Registry response exceeds the 10 MiB limit")
    return data


def validate_version(version: str) -> None:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", version):
        raise ValueError("Select an exact ShapeDiff release version")


def verify_distributions(version: str, expected: Path, metadata: dict[str, Any], fetch=download) -> None:
    validate_version(version)
    info = metadata.get("info", {})
    if info.get("name") != "shapediff" or info.get("version") != version:
        raise ValueError("Registry project or version mismatch")
    if info.get("requires_dist"):
        raise ValueError("ShapeDiff must have no runtime dependencies")
    names = {f"shapediff-{version}-py3-none-any.whl", f"shapediff-{version}.tar.gz"}
    entries = metadata.get("urls", [])
    if len(entries) != len(names) or {entry.get("filename") for entry in entries} != names:
        raise ValueError("Unexpected registry distribution inventory")
    for entry in entries:
        name = entry["filename"]
        digest = hashlib.sha256((expected / name).read_bytes()).hexdigest()
        if entry.get("digests", {}).get("sha256") != digest:
            raise ValueError("Registry metadata digest mismatch: " + name)
        url = urllib.parse.urlsplit(entry.get("url", ""))
        if (url.scheme != "https" or url.netloc != "files.pythonhosted.org"
                or url.username is not None or url.fragment or url.query):
            raise ValueError("Unexpected registry file origin")
        data = fetch(entry["url"])
        if len(data) > MAX_DOWNLOAD or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Downloaded registry file mismatch: " + name)
        print("Verified public PyPI bytes:", name)


def registry_metadata(version: str, wait_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            return json.loads(download(f"https://pypi.org/pypi/shapediff/{version}/json"))
        except urllib.error.HTTPError as error:
            if error.code != 404 or time.monotonic() >= deadline:
                raise
            time.sleep(min(5, max(0, deadline - time.monotonic())))


def verify_install(version: str, examples: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="shapediff-registry-") as temporary:
        environment = Path(temporary) / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if sys.platform == "win32" else "bin")
        python = scripts / ("python.exe" if sys.platform == "win32" else "python")
        command = scripts / ("shapediff.exe" if sys.platform == "win32" else "shapediff")
        subprocess.run([
            str(python), "-m", "pip", "install", "--index-url", "https://pypi.org/simple",
            "--no-cache-dir", "--no-deps", "--only-binary=:all:", "--disable-pip-version-check",
            "shapediff==" + version,
        ], cwd=temporary, check=True, timeout=120)
        installed = subprocess.check_output([str(command), "--version"], cwd=temporary, text=True).strip()
        if installed != "shapediff " + version:
            raise ValueError("Installed CLI version mismatch")
        result = subprocess.run([
            str(command), "suite", str(examples / "baseline.sdsuite"),
            str(examples / "current.sdsuite"), "--format", "json", "--fail-on", "never",
        ], cwd=temporary, check=True, text=True, capture_output=True, timeout=30)
        report = json.loads(result.stdout)
        if report.get("mode") != "suite" or report["summary"]["errors"] != 3:
            raise ValueError("Installed CLI did not find the three expected suite regressions")
    print("Fresh public PyPI installation passed:", version)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-dir", type=Path, required=True)
    parser.add_argument("--examples-dir", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=int, default=180, choices=range(0, 601), metavar="0..600")
    args = parser.parse_args()
    validate_version(args.version)
    metadata = registry_metadata(args.version, args.wait_seconds)
    verify_distributions(args.version, args.expected_dir.resolve(), metadata)
    verify_install(args.version, args.examples_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
