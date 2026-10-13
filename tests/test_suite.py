"""Endpoint suite behavior, safety, and profile interoperability."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

import shapediff as sd


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def suite(self, name, responses):
        return self.write(name, {"suite_version": 1, "responses": responses})

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = sd.main(args)
        return result, out.getvalue(), err.getvalue()

    def test_isolates_endpoints_and_detects_status_header_and_body(self):
        self.write("old/users.json", {"id": 1, "email": "a"})
        self.write("new/users.json", {"id": "1"})
        self.write("old/health.json", {"ok": True})
        self.write("new/health.json", {"ok": True})
        before = self.suite("old/api.sdsuite", [
            {"id": "GET /users/{id}", "status": 200, "body": "users.json",
             "headers": {"Content-Type": "application/json", "X-Secret": "secret-before"}},
            {"id": "GET /health", "status": 200, "body": "health.json"},
        ])
        after = self.suite("new/api.sdsuite", [
            {"id": "GET /users/{id}", "status": 204, "body": "users.json",
             "headers": {"content-type": "text/plain", "x-secret": "secret-after"}},
            {"id": "GET /health", "status": 200, "body": "health.json"},
        ])
        rc, stdout, _ = self.run_cli("suite", str(before), str(after), "--format", "json")
        self.assertEqual(rc, 1)
        report = json.loads(stdout)
        self.assertEqual({row["case"] for row in report["findings"]}, {"GET /users/{id}"})
        self.assertEqual({row["code"] for row in report["findings"]},
                         {"status_changed", "header_changed", "field_missing", "type_changed"})
        self.assertNotIn("secret-before", stdout)
        self.assertNotIn("secret-after", stdout)

    def test_missing_and_added_cases_have_directional_severity(self):
        a = self.suite("a.sdsuite", [{"id": "GET /old", "status": 200, "body": None}])
        b = self.suite("b.sdsuite", [{"id": "GET /new", "status": 200, "body": None}])
        rc, output, _ = self.run_cli("suite", str(a), str(b), "--format", "json")
        self.assertEqual(rc, 1)
        findings = {f["code"]: f["level"] for f in json.loads(output)["findings"]}
        self.assertEqual(findings, {"response_missing": "ERROR", "response_added": "INFO"})

    def test_profile_rules_are_inherited_per_endpoint(self):
        old_body = self.write("old/users.json", {"byId": {"alice": {"rank": 1}}})
        self.write("new/users.json", {"byId": {"bob": {"rank": "first"}}})
        profile = self.root / "old" / "users.sdshape"
        rc, _, err = self.run_cli("profile", str(old_body), "-o", str(profile), "--map", "/byId")
        self.assertEqual(rc, 0, err)
        a = self.suite("old/api.sdsuite", [{"id": "GET /users", "status": 200, "body": "users.sdshape"}])
        b = self.suite("new/api.sdsuite", [{"id": "GET /users", "status": 200, "body": "users.json"}])
        rc, output, _ = self.run_cli("suite", str(a), str(b), "--format", "json")
        self.assertEqual(rc, 1)
        rows = json.loads(output)["findings"]
        self.assertEqual([f["code"] for f in rows], ["type_changed"])
        self.assertEqual(rows[0]["path"], "byId{*}.rank")

    def test_rejects_escape_duplicate_ids_and_case_insensitive_headers(self):
        self.write("body.json", {"ok": True})
        examples = [
            [{"id": "x", "status": 200, "body": "../outside.json"}],
            [{"id": "x", "status": 200, "body": None}, {"id": "x", "status": 200, "body": None}],
            [{"id": "x", "status": 200, "body": "body.json", "headers": {"ETag": "a", "etag": "b"}}],
        ]
        for i, cases in enumerate(examples):
            manifest = self.suite(f"bad{i}.sdsuite", cases)
            rc, _, _ = self.run_cli("suite", str(manifest), str(manifest))
            self.assertEqual(rc, 3)

    def test_report_output_cannot_replace_body_or_manifest(self):
        body = self.write("body.json", {"ok": True})
        manifest = self.suite("api.sdsuite", [{"id": "GET /", "status": 200, "body": "body.json"}])
        for target in (body, manifest):
            rc, _, _ = self.run_cli("suite", str(manifest), str(manifest), "--output", str(target))
            self.assertEqual(rc, 3)

    def test_bodyless_responses_and_header_value_change(self):
        a = self.suite("a.sdsuite", [{"id": "DELETE /item", "status": 204, "body": None,
                                      "headers": {"Cache-Control": "no-store"}}])
        b = self.suite("b.sdsuite", [{"id": "DELETE /item", "status": 204, "body": None,
                                      "headers": {"cache-control": "private"}}])
        rc, out, _ = self.run_cli("suite", str(a), str(b))
        self.assertEqual(rc, 1)
        self.assertIn("header value changed", out)

    def test_added_case_still_validates_its_body(self):
        broken = self.root / "broken.json"
        broken.write_text("not JSON", encoding="utf-8")
        a = self.suite("a.sdsuite", [{"id": "GET /old", "status": 200, "body": None}])
        b = self.suite("b.sdsuite", [
            {"id": "GET /old", "status": 200, "body": None},
            {"id": "GET /new", "status": 200, "body": "broken.json"},
        ])
        rc, _, stderr = self.run_cli("suite", str(a), str(b))
        self.assertEqual(rc, 3)
        self.assertIn("invalid JSON", stderr)

    def test_markdown_escapes_untrusted_case_names(self):
        identifier = "GET /<script>|`"
        a = self.suite("a.sdsuite", [{"id": identifier, "status": 200, "body": None}])
        b = self.suite("b.sdsuite", [{"id": identifier, "status": 201, "body": None}])
        rc, output, _ = self.run_cli("suite", str(a), str(b), "--format", "markdown")
        self.assertEqual(rc, 1)
        self.assertIn("&lt;script&gt;", output)
        self.assertIn("\\|", output)
        self.assertIn("\\`", output)
        self.assertNotIn("<script>", output)


if __name__ == "__main__":
    unittest.main()
