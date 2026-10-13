# Release checklist

Use this list for future ShapeDiff releases. The README install URLs, the packaged version and the tag must all refer to the same tested revision.

1. Update the version in `pyproject.toml`, `shapediff.py`, README install examples, release badge and changelog together.
2. Run `python -m unittest discover -s tests -v` on a supported Python version.
3. Build a wheel with `python -m pip wheel . --no-deps --wheel-dir dist` and run `python scripts/verify_wheel.py dist`. This checks an offline installation and the installed command in a fresh virtual environment.
4. Re-run relevant benchmarks if implementation or performance claims change; record the host, Python version, fixture size, repeated timings and limitations.
5. Push the tested commit and wait for all jobs in `.github/workflows/ci.yml` to pass on Linux, Windows and macOS. CI uses pinned action revisions and read-only repository permissions.
6. Tag the passing commit, create a GitHub prerelease for alpha versions, attach the wheel and standalone file, and publish SHA-256 checksums for the exact uploaded files.
7. Download the published assets and verify that their checksums and documented install URLs match the release.

PyPI publication requires separate project-name, ownership and trusted-publishing preparation; a GitHub release does not imply a PyPI package exists.
