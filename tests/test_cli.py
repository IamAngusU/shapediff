"""Command-line, I/O, installation, and output-safety tests."""

from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import shapediff as sd

SCRIPT = Path(sd.__file__).resolve()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def sample(self, name, data):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data), encoding="utf-8")
        return str(target)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = sd.main(args)
        return status, out.getvalue(), err.getvalue()

    def test_exit_one_on_breaking(self):
        a = self.sample("old.json", {"user": {"id": 1, "email": "a"}})
        b = self.sample("new.json", {"user": {"id": "a", "avatar": 1}})
        rc, stdout, stderr = self.run_cli(a, b)
        self.assertEqual(rc, 1)
        self.assertIn("ERROR", stdout)
        self.assertIn("user.email", stdout)
        self.assertIn("user.id", stdout)
        self.assertIn("user.avatar", stdout)
        self.assertIn("2 breaking", stderr)

    def test_breaking_only_hides_info_but_keeps_gating(self):
        a = self.sample("old.json", {"a": 1})
        b = self.sample("new.json", {"a": "1", "b": 3})
        rc, stdout, _ = self.run_cli(a, b, "--breaking-only")
        self.assertEqual(rc, 1)
        self.assertNotIn("INFO", stdout)
        self.assertNotIn("  b  ", stdout)
        self.assertIn("number -> string", stdout)

    def test_unchanged_values_exit_zero(self):
        a = self.sample("a.json", {"id": 1})
        b = self.sample("b.json", {"id": 2})
        rc, stdout, stderr = self.run_cli(a, b)
        self.assertEqual(rc, 0)
        self.assertEqual(stdout, "")
        self.assertIn("0 breaking", stderr)

    def test_fail_on_warning(self):
        a = self.sample("a.json", {"field": None})
        b = self.sample("b.json", {"field": "x"})
        self.assertEqual(self.run_cli(a, b)[0], 0)
        self.assertEqual(self.run_cli(a, b, "--fail-on", "warning")[0], 1)
        self.assertEqual(self.run_cli(a, b, "--fail-on", "any")[0], 1)
        self.assertEqual(self.run_cli(a, b, "--fail-on", "never")[0], 0)

    def test_fail_on_any_for_addition(self):
        a = self.sample("a.json", {"a": 1})
        b = self.sample("b.json", {"a": 1, "b": 2})
        self.assertEqual(self.run_cli(a, b)[0], 0)
        self.assertEqual(self.run_cli(a, b, "--fail-on", "any")[0], 1)

    def test_json_report_fields_and_no_raw_values(self):
        a = self.sample("a.json", {"secret": "VERY_PRIVATE_SAMPLE_444"})
        b = self.sample("b.json", {"secret": 1})
        rc, stdout, stderr = self.run_cli(a, b, "--format", "json")
        self.assertEqual(rc, 1)
        self.assertEqual(stderr, "")
        report = json.loads(stdout)
        self.assertEqual(report["report_version"], 1)
        self.assertEqual(report["evidence_model"], "observed-samples-not-schema")
        self.assertEqual(report["findings"][0]["pointer"], "/secret")
        self.assertEqual(report["summary"]["errors"], 1)
        self.assertNotIn("VERY_PRIVATE_SAMPLE_444", stdout)

    def test_json_breaking_only_keeps_full_summary(self):
        a = self.sample("a.json", {"id": 1})
        b = self.sample("b.json", {"id": "1", "extra": "x"})
        _, stdout, _ = self.run_cli(a, b, "--format", "json", "--breaking-only")
        r = json.loads(stdout)
        self.assertEqual(r["summary"]["infos"], 1)
        self.assertEqual(len(r["findings"]), 1)
        self.assertEqual(r["findings"][0]["level"], sd.ERROR)

    def test_markdown_pipe_is_escaped(self):
        a = self.sample("a.json", {"k|v": 1})
        b = self.sample("b.json", {"k|v": "2"})
        _, out, _ = self.run_cli(a, b, "--format", "markdown")
        self.assertIn("\\|", out)
        self.assertIn("Sampled responses", out)

    def test_jsonl_multiple_records(self):
        a = self.root / "base.jsonl"
        a.write_text('{"id":1,"promo":"a"}\n\n{"id":2}\n', encoding="utf-8")
        b = self.sample("new.json", {"id": 3})
        rc, stdout, _ = self.run_cli(str(a), b, "--format", "json")
        self.assertEqual(rc, 0)
        r = json.loads(stdout)
        self.assertEqual(r["baseline"]["documents"], 2)
        self.assertEqual(r["baseline"]["files"], 1)
        self.assertEqual(r["baseline"]["bytes_read"], a.stat().st_size)
        self.assertEqual(r["summary"]["warnings"], 1)

    def test_directory_nonrecursive_default(self):
        self.sample("baseline/a.json", {"x": 1})
        self.sample("baseline/inner/b.json", {"x": "str"})
        new = self.sample("new.json", {"x": 2})
        rc, out, _ = self.run_cli(str(self.root / "baseline"), new, "--format", "json")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["baseline"]["documents"], 1)
        _, out, _ = self.run_cli(str(self.root / "baseline"), new, "--recursive", "--format", "json")
        self.assertEqual(json.loads(out)["baseline"]["documents"], 2)

    def test_multiple_baseline_files_optional(self):
        self.sample("baseline/a.json", {"id": 1, "optional": "x"})
        self.sample("baseline/b.json", {"id": 2})
        new = self.sample("new.json", {"id": 3})
        rc, out, _ = self.run_cli(str(self.root / "baseline"), new)
        self.assertEqual(rc, 0)
        self.assertIn("WARN", out)
        self.assertIn("optional", out)

    def test_bad_json_and_duplicate_rejected(self):
        bad = self.root / "bad.json"
        bad.write_text('{"x":1, "x":2}', encoding="utf-8")
        good = self.sample("good.json", {"x": 1})
        self.assertEqual(self.run_cli(str(bad), good)[0], 3)
        self.assertIn("duplicate", self.run_cli(str(bad), good)[2])
        bad.write_text('{"x": ', encoding="utf-8")
        rc, stdout, stderr = self.run_cli(str(bad), good)
        self.assertEqual((rc, stdout), (3, ""))
        self.assertIn("invalid JSON", stderr)

    def test_missing_file_and_empty_directory(self):
        good = self.sample("good.json", {"x": 1})
        self.assertEqual(self.run_cli("/not-found-shape-diff-example.json", good)[0], 3)
        empty = self.root / "empty"
        empty.mkdir()
        self.assertEqual(self.run_cli(str(empty), good)[0], 3)

    def test_input_bom_supported(self):
        a = self.root / "bom.json"
        a.write_bytes(b"\xef\xbb\xbf" + b'{"a":1}')
        b = self.sample("b.json", {"a": 1})
        self.assertEqual(self.run_cli(str(a), b)[0], 0)

    def test_nonstandard_nonfinite_invalid(self):
        a = self.root / "bad.json"
        a.write_text('{"n":Infinity}', encoding="utf-8")
        good = self.sample("good.json", {"n": 3})
        self.assertEqual(self.run_cli(str(a), good)[0], 3)

    def test_size_limit(self):
        a = self.sample("big.json", {"x": "x" * (1024 * 1024 + 1)})
        b = self.sample("b.json", {"x": "y"})
        self.assertEqual(self.run_cli(a, b, "--max-document-mib", "1")[0], 3)

    def test_sample_limit(self):
        a = self.root / "a.jsonl"
        a.write_text('{"x":1}\n{"x":2}\n', encoding="utf-8")
        b = self.sample("b.json", {"x": 2})
        self.assertEqual(self.run_cli(str(a), b, "--max-samples", "1")[0], 3)

    def test_empty_jsonl_fails(self):
        a = self.root / "empty.ndjson"
        a.write_text('\n\n', encoding="utf-8")
        b = self.sample("b.json", {})
        self.assertEqual(self.run_cli(str(a), b)[0], 3)

    def test_ndjson_line_error(self):
        a = self.root / "a.ndjson"
        a.write_text('{"a":1}\ninvalid\n', encoding="utf-8")
        b = self.sample("b.json", {})
        rc, _, err = self.run_cli(str(a), b)
        self.assertEqual(rc, 3)
        self.assertIn(":2", err)

    def test_stdin_and_conflicting_stdin(self):
        b = self.sample("b.json", {"a": "2"})
        stream = io.TextIOWrapper(io.BytesIO(b'{"a":1}'), encoding="utf-8")
        with patch.object(sys, "stdin", stream):
            self.assertEqual(self.run_cli("-", b)[0], 1)
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli("-", "-")
        self.assertEqual(ctx.exception.code, 2)

    def test_stdin_jsonl(self):
        b = self.sample("b.json", {"a": 2})
        stream = io.TextIOWrapper(io.BytesIO(b'{"a":1}\n{"a":2}\n'), encoding="utf-8")
        with patch.object(sys, "stdin", stream):
            self.assertEqual(self.run_cli("-", b, "--stdin-format", "jsonl")[0], 0)

    def test_output_atomic_and_report_saved(self):
        a = self.sample("a.json", {"a": 1})
        b = self.sample("b.json", {"a": "1"})
        report = self.root / "report.json"
        rc, out, _ = self.run_cli(a, b, "--format", "json", "--output", str(report))
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(report.read_text())["summary"]["errors"], 1)
        old_contents = report.read_bytes()
        missing = str(self.root / "not_here.json")
        self.assertEqual(self.run_cli(a, missing, "--output", str(report))[0], 3)
        self.assertEqual(report.read_bytes(), old_contents)

    def test_output_directory_error(self):
        a = self.sample("a.json", {"a": 1})
        rc, _, err = self.run_cli(a, a, "--output", str(self.root / "absent" / "report.txt"))
        self.assertEqual(rc, 3)
        self.assertIn("cannot write report", err)

    def test_cli_arg_errors_code_two(self):
        a = self.sample("a.json", {"a": 1})
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli(a, a, "--max-depth", "0")
        self.assertEqual(ctx.exception.code, 2)
        with self.assertRaises(SystemExit):
            self.run_cli(a, a, "--coverage-drop", "2")
        with self.assertRaises(SystemExit):
            self.run_cli(a, a, "--ignore", "/invalid~4foo")
        with self.assertRaises(SystemExit):
            self.run_cli(a, a, "--ignore", "")

    def test_script_direct_subprocess(self):
        a = self.sample("a.json", {"a": 1})
        b = self.sample("b.json", {"a": "2"})
        proc = subprocess.run([sys.executable, str(SCRIPT), a, b, "--quiet"], text=True, capture_output=True, check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("a", proc.stdout)
        self.assertEqual(proc.stderr, "")

    def test_ignored_path_never_in_report(self):
        a = self.sample("a.json", {"secret": {"foo": 1}, "id": 2})
        b = self.sample("b.json", {"secret": {"foo": "x"}, "id": 3})
        rc, out, _ = self.run_cli(a, b, "--format", "json", "--ignore", "/secret")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["findings"], [])

    def test_text_evidence_counts(self):
        a = self.sample("a.json", {"x": 1, "y": 1})
        b = self.sample("b.json", {"x": "a"})
        rc, out, _ = self.run_cli(a, b, "--evidence")
        self.assertEqual(rc, 1)
        self.assertIn("observed 1/1 -> 0/1", out)
        self.assertIn("counts", out)

    def test_refuse_to_overwrite_an_input(self):
        a = self.sample("a.json", {"a": 1})
        b = self.sample("b.json", {"a": 2})
        prior = Path(a).read_bytes()
        rc, _, err = self.run_cli(a, b, "--output", a)
        self.assertEqual(rc, 3)
        self.assertIn("must not overwrite", err)
        self.assertEqual(Path(a).read_bytes(), prior)

    def test_refuse_output_inside_sample_folder(self):
        a = self.sample("samples/a.json", {"a": 1})
        b = self.sample("b.json", {"a": 2})
        rc, _, err = self.run_cli(str(Path(a).parent), b, "--output", str(Path(a).parent / "report.txt"))
        self.assertEqual(rc, 3)
        self.assertIn("input directory", err)

    def test_shape_node_limit_cli(self):
        a = self.sample("a.json", {"a": 1, "b": 2})
        b = self.sample("b.json", {"a": 1})
        self.assertEqual(self.run_cli(a, b, "--max-shape-nodes", "2")[0], 3)

    def test_long_paths_are_never_truncated(self):
        field = "nested_field_" * 12
        a = self.sample("a.json", {field: 1})
        b = self.sample("b.json", {field: "2"})
        _, out, _ = self.run_cli(a, b)
        self.assertIn(field, out)
        self.assertNotIn("…", out)

    def test_force_color(self):
        a = self.sample("a.json", {"x": 1})
        b = self.sample("b.json", {"x": "2"})
        _, out, _ = self.run_cli(a, b, "--color", "always")
        self.assertIn("\x1b[31m", out)
        _, out, _ = self.run_cli(a, b, "--color", "never")
        self.assertNotIn("\x1b[31m", out)

    def test_directory_symlinks_not_followed(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        original = self.sample("origin.json", {"a": 1})
        base = self.root / "samples"
        base.mkdir()
        link = base / "leak.json"
        try:
            link.symlink_to(original)
        except OSError:
            self.skipTest("cannot create symlink")
        good = self.sample("good.json", {"a": 1})
        self.assertEqual(self.run_cli(str(base), good)[0], 3)


if __name__ == "__main__":
    unittest.main()
