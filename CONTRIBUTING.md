# Contributing

ShapeDiff is intentionally small and standard-library-only. Open an issue with a minimal, sanitized before/after pair that demonstrates the intended contract behavior. Include the actual CLI flags and observed exit code.

Before proposing a change:

```sh
python3 -m unittest discover -s tests -v
python3 shapediff.py examples/production.json examples/staging.json --fail-on never
```

Any change to detection or grading should have a regression test showing why it is safe. In particular, do not turn an uncertain result into a guaranteed compatibility statement, automatically infer map keys, or silently ignore empty-array coverage gaps.

Runtime third-party dependencies are not accepted for the core CLI without an explicit performance, security and distribution rationale. Docs and examples must use real output from the implementation.
