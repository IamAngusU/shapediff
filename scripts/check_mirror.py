"""Require the public CI mirror to test the current canonical main commit."""
import os
import subprocess

if os.environ.get("GITHUB_REPOSITORY", "").lower() == "angusu-de/shapediff-ci":
    source = subprocess.check_output([
        "git", "ls-remote", "https://github.com/IamAngusU/shapediff.git", "refs/heads/main"
    ], text=True, timeout=30).split()[0]
    if source != os.environ.get("GITHUB_SHA"):
        raise SystemExit("Mirror source differs from canonical main; sync before claiming evidence.")
    print("Canonical source verified:", source)
