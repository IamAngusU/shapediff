"""Profile round trips, interpretation safety, and corrupted baseline handling."""

from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import copy
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch
import sys

import shapediff as sd


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write_json(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def command(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sd.main(argv)
        return code, out.getvalue(), err.getvalue()

    def create_profile(self, source, name="baseline.sdshape", *flags):
        output = str(self.root / name)
        code, out, err = self.command("profile", source, "--output", output, *flags)
        self.assertEqual(code, 0, (out, err))
        self.assertTrue(Path(output).exists())
        return output

    def test_profile_rejects_layout_that_disagrees_with_saved_rules(self):
        raw = self.write_json("input.json", {"byId": {"alice": {"rank": 1}}, "secret": 1})
        profile = self.create_profile(raw, "mapped.sdshape", "--map", "/byId")
        content = json.loads(Path(profile).read_text(encoding="utf-8"))
        content["processing"]["maps"] = []
        corrupted = self.root / "bad-map.sdshape"
        corrupted.write_text(json.dumps(content), encoding="utf-8")
        self.assertEqual(self.command(str(corrupted), raw)[0], 3)

        profile = self.create_profile(raw, "ordinary.sdshape")
        content = json.loads(Path(profile).read_text(encoding="utf-8"))
        content["processing"]["ignore"] = ["/secret"]
        corrupted = self.root / "bad-ignore.sdshape"
        corrupted.write_text(json.dumps(content), encoding="utf-8")
        self.assertEqual(self.command(str(corrupted), raw)[0], 3)

    def test_profile_matches_direct_comparison(self):
        a = self.write_json("a.json", {"user": {"id": 11, "email": "person@example.com"}})
        b = self.write_json("b.json", {"user": {"id": "11", "avatar": "https://cdn.example/a.png"}})
        profile = self.create_profile(a)
        direct = self.command(a, b, "--format", "json")
        replay = self.command(profile, b, "--format", "json")
        self.assertEqual(direct[0], replay[0])
        self.assertEqual(json.loads(direct[1])["findings"], json.loads(replay[1])["findings"])
        self.assertEqual(json.loads(replay[1])["baseline"]["bytes_read"], 0)
        self.assertIn("type_changed", replay[1])

    def test_profile_to_profile_preserves_findings(self):
        a = self.write_json("old.json", {"items": [{"id": 1, "status": "a"}]})
        b = self.write_json("new.json", {"items": [{"id": "2", "extra": 8}]})
        old_profile = self.create_profile(a, "old.sdshape")
        new_profile = self.create_profile(b, "new.sdshape")
        direct = json.loads(self.command(a, b, "--format", "json")[1])["findings"]
        profile_diff = json.loads(self.command(old_profile, new_profile, "--format", "json")[1])["findings"]
        self.assertEqual(direct, profile_diff)

    def test_scalar_values_never_stored(self):
        a = self.write_json("secret.json", {"id": "PERSONAL_DATA_VERY_PRIVATE_19371", "balance": 929.20, "token": "ak-SECRET_TOKEN"})
        profile = self.create_profile(a)
        saved = Path(profile).read_text(encoding="utf-8")
        self.assertNotIn("PERSONAL_DATA_VERY_PRIVATE_19371", saved)
        self.assertNotIn("ak-SECRET_TOKEN", saved)
        self.assertNotIn("929.2", saved)
        self.assertNotIn(str(a), saved)
        self.assertEqual(json.loads(saved)["kind"], sd.PROFILE_KIND)
        self.assertEqual(json.loads(saved)["profile_version"], 1)
        self.assertNotIn("bytes_read", json.loads(saved)["observations"])

    def test_value_changes_yield_byte_identical_profiles(self):
        a = self.write_json("a.json", {"a": "short", "b": 1, "flag": True})
        b = self.write_json("b.json", {"a": "a much longer private string", "b": 72398, "flag": False})
        old_prof = self.create_profile(a, "old.sdshape")
        new_prof = self.create_profile(b, "new.sdshape")
        self.assertEqual(Path(old_prof).read_bytes(), Path(new_prof).read_bytes())

    def test_jsonl_frequency_survives_profile(self):
        raw = self.root / "samples.jsonl"
        raw.write_text('{"id":1,"promo":"a"}\n{"id":2}\n{"id":3,"promo":"c"}\n', encoding="utf-8")
        profile = self.create_profile(str(raw))
        new = self.write_json("new.json", {"id": 4})
        report = json.loads(self.command(profile, new, "--format", "json")[1])
        self.assertEqual(report["baseline"]["documents"], 3)
        self.assertEqual(report["summary"], {"errors": 0, "warnings": 1, "infos": 0, "total": 1})
        self.assertEqual(report["findings"][0]["baseline"], {"present": 2, "objects": 3})

    def test_map_is_inherited_and_identifier_keys_omitted(self):
        key = "9c8a7b6d-1111-4222-8333-444455556666"
        a = self.write_json("old.json", {"byId": {key: {"age": 1, "name": "x"}}})
        b = self.write_json("new.json", {"byId": {"b4ca7b6d-1111-4222-8333-444455556666": {"age": "old", "name": "y"}}})
        profile = self.create_profile(a, "old.sdshape", "--map", "/byId")
        self.assertNotIn(key, Path(profile).read_text(encoding="utf-8"))
        code, report, _ = self.command(profile, b, "--format", "json")
        self.assertEqual(code, 1)
        found = json.loads(report)["findings"]
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["code"], found[0]["path"]), ("type_changed", "byId{*}.age"))
        self.assertEqual(json.loads(Path(profile).read_text())["processing"]["maps"], ["/byId"])

    def test_missing_map_selector_fails_profile(self):
        a = self.write_json("old.json", {"user": {"id": 12}})
        code, out, err = self.command("profile", a, "--map", "/wrong", "--output", str(self.root / "base.sdshape"))
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("did not match an observed object", err)
        self.assertFalse((self.root / "base.sdshape").exists())

    def test_sensitive_literal_key_blocked_by_default(self):
        key = "alice@example.com"
        a = self.write_json("old.json", {"users": {key: {"name": "Alice"}}})
        path = self.root / "base.sdshape"
        code, _, err = self.command("profile", a, "-o", str(path))
        self.assertEqual(code, 3)
        self.assertIn("identifier-like", err)
        self.assertFalse(path.exists())
        profile = self.create_profile(a, "allowed.sdshape", "--allow-identifier-keys")
        self.assertIn(key, Path(profile).read_text())

    def test_sensitive_key_ignored_in_saved_profile(self):
        key = "alice@example.com"
        a = self.write_json("old.json", {"users": {key: {"name": "Alice"}}})
        profile = self.create_profile(a, "saved.sdshape", "--ignore", "/users")
        self.assertNotIn(key, Path(profile).read_text())

    def test_report_does_not_adopt_mismatched_cli_rules(self):
        a = self.write_json("old.json", {"byId": {"a": {"id": 1}}})
        b = self.write_json("new.json", {"byId": {"b": {"id": 2}}})
        profile = self.create_profile(a, "old.sdshape", "--map", "/byId")
        code, _, err = self.command(profile, b, "--map", "/wrong")
        self.assertEqual(code, 3)
        self.assertIn("selectors differ", err)

    def test_profile_versus_profile_with_different_rules_fails(self):
        a = self.write_json("old.json", {"data": {"x": 1}})
        one = self.create_profile(a, "one.sdshape")
        two = self.create_profile(a, "two.sdshape", "--map", "/data")
        code, _, err = self.command(one, two)
        self.assertEqual(code, 3)
        self.assertIn("processing settings differ", err)

    def test_format_inherits_from_profile(self):
        a = self.write_json("old.json", {"ts": "2024-06-03T10:00:00Z"})
        b = self.write_json("new.json", {"ts": "2025-06-03"})
        profile = self.create_profile(a, "fmt.sdshape", "--formats")
        code, report, _ = self.command(profile, b, "--format", "json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(report)["findings"][0]["code"], "format_drift")
        self.assertEqual(json.loads(report)["summary"]["warnings"], 1)

    def test_strict_integer_inherits_from_profile(self):
        a = self.write_json("old.json", {"v": 100})
        b = self.write_json("new.json", {"v": 100.1})
        profile = self.create_profile(a, "int.sdshape", "--strict-integers")
        code, out, _ = self.command(profile, b)
        self.assertEqual(code, 1)
        self.assertIn("integer -> number", out)

    def test_legacy_flags_against_default_profile_are_refused(self):
        a = self.write_json("old.json", {"v": 100})
        profile = self.create_profile(a)
        self.assertEqual(self.command(profile, a, "--strict-integers")[0], 3)
        self.assertEqual(self.command(profile, a, "--formats")[0], 3)

    def test_existing_profile_requires_explicit_force(self):
        a = self.write_json("old.json", {"v": 1})
        profile = self.create_profile(a)
        original = Path(profile).read_bytes()
        a = self.write_json("old.json", {"v": "changed"})
        self.assertEqual(self.command("profile", a, "-o", profile)[0], 3)
        self.assertEqual(Path(profile).read_bytes(), original)
        self.assertEqual(self.command("profile", a, "-o", profile, "--force")[0], 0)
        self.assertNotEqual(Path(profile).read_bytes(), original)

    def test_does_not_write_profile_inside_source_directory(self):
        self.write_json("examples/a.json", {"v": 1})
        code, _, error = self.command("profile", str(self.root / "examples"), "-o", str(self.root / "examples" / "old.sdshape"))
        self.assertEqual(code, 3)
        self.assertIn("inside an input directory", error)

    def test_invalid_file_extension_for_profile_creation(self):
        a = self.write_json("a.json", {"v": 1})
        with self.assertRaises(SystemExit) as error:
            self.command("profile", a, "-o", str(self.root / "bad.json"))
        self.assertEqual(error.exception.code, 2)

    def test_profile_capture_from_jsonl_stdin(self):
        stream = io.TextIOWrapper(io.BytesIO(b'{"a":1}\n{"a":2,"b":true}\n'), encoding="utf-8")
        with patch.object(sys, "stdin", stream):
            code, raw, _ = self.command("profile", "-", "--stdin-format", "jsonl")
        self.assertEqual(code, 0)
        content = json.loads(raw)
        self.assertEqual(content["observations"]["documents"], 2)
        self.assertEqual(content["shape"]["fields"]["b"]["present"], 1)

    def test_profile_rejects_corrupted_metadata_and_counters(self):
        a = self.write_json("a.json", {"v": 1})
        b = self.write_json("b.json", {"v": 2})
        profile = self.create_profile(a)
        source = json.loads(Path(profile).read_text())
        corruptions = [
            lambda x: x.update(profile_version=999),
            lambda x: x["observations"].update(documents=2),
            lambda x: x["observations"].update(object_observations=22),
            lambda x: x["observations"].update(shape_nodes=999),
            lambda x: x["shape"]["fields"]["v"].update(present=4),
            lambda x: x["shape"].update(types={"invalid_type": 1}),
            lambda x: x["shape"].update(types={"object": True}),
            lambda x: x["shape"].update(unexpected="x"),
            lambda x: x["processing"].update(formats="yes"),
            lambda x: x["processing"].update(ignore=["/malformed~2"]),
        ]
        for i, mutate in enumerate(corruptions):
            with self.subTest(i=i):
                test = copy.deepcopy(source)
                mutate(test)
                path = self.root / f"corrupt_{i}.sdshape"
                path.write_text(json.dumps(test))
                code, _, err = self.command(str(path), b)
                self.assertEqual(code, 3, (i, err))

    def test_bound_shape_nodes_during_profile_loading(self):
        a = self.write_json("a.json", {"deep": {"a": {"b": 1}}})
        profile = self.create_profile(a)
        code, _, err = self.command(profile, a, "--max-shape-nodes", "2")
        self.assertEqual(code, 3)
        self.assertIn("max-shape-nodes", err)

    def test_incremental_update_equals_single_capture(self):
        inputs = [
            {"items": [{"age": 2, "name": "A"}], "active": True},
            {"items": [], "active": True, "note": None},
            {"items": [{"age": "three", "name": "B", "extra": 1}], "active": False},
        ]
        files = [self.write_json(f"sample{i}.json", data) for i, data in enumerate(inputs)]
        saved = self.create_profile(files[0], "updated.sdshape")
        for source in files[1:]:
            status, out, err = self.command("profile", source, "--update", saved)
            self.assertEqual(status, 0, (out, err))
            self.assertEqual(out, "")
        samples = self.root / "samples"
        samples.mkdir()
        for i, obj in enumerate(inputs):
            (samples / f"{i}.json").write_text(json.dumps(obj))
        from_scratch = self.create_profile(str(samples), "full.sdshape")
        updated = json.loads(Path(saved).read_text())
        scratch = json.loads(Path(from_scratch).read_text())
        self.assertEqual(updated["shape"], scratch["shape"])
        self.assertEqual(updated["observations"], scratch["observations"])
        new = self.write_json("new.json", {"items": [{"age": True}], "active": True})
        self.assertEqual(
            json.loads(self.command(saved, new, "--format", "json")[1])["findings"],
            json.loads(self.command(from_scratch, new, "--format", "json")[1])["findings"],
        )

    def test_incremental_update_inherits_rules_and_format_tracking(self):
        a = self.write_json("initial.json", {"byId": {"a": {"date": "2024-01-01"}}})
        profile = self.create_profile(a, "profile.sdshape", "--map", "/byId", "--formats")
        b = self.write_json("next.json", {"byId": {"different": {"date": "2025-02-02"}}})
        self.assertEqual(self.command("profile", b, "--update", profile)[0], 0)
        contents = json.loads(Path(profile).read_text())
        self.assertEqual(contents["processing"]["maps"], ["/byId"])
        self.assertEqual(contents["processing"]["formats"], True)
        self.assertEqual(contents["observations"]["documents"], 2)
        self.assertNotIn("different", json.dumps(contents))
        self.assertEqual(contents["shape"]["fields"]["byId"]["shape"]["map_values"]["fields"]["date"]["shape"]["string_formats"], {"date": 2})

    def test_update_does_not_require_map_presence_in_every_batch(self):
        a = self.write_json("a.json", {"byId": {"u1": 1}})
        profile = self.create_profile(a, "save.sdshape", "--map", "/byId")
        b = self.write_json("b.json", {"other": 1})
        self.assertEqual(self.command("profile", b, "--update", profile)[0], 0)
        content = json.loads(Path(profile).read_text())
        self.assertEqual(content["observations"]["documents"], 2)

    def test_update_does_not_overwrite_on_failure(self):
        a = self.write_json("a.json", {"k": 1})
        b = self.write_json("b.json", {"k": 2})
        profile = self.create_profile(a)
        original = Path(profile).read_bytes()
        self.assertEqual(self.command("profile", b, "--update", profile, "--max-samples", "1")[0], 3)
        self.assertEqual(original, Path(profile).read_bytes())
        self.assertEqual(self.command("profile", b, "--update", profile, "--map", "/mismatch")[0], 3)
        self.assertEqual(original, Path(profile).read_bytes())
        invalid = self.root / "invalid.json"
        invalid.write_text("broken-json!")
        self.assertEqual(self.command("profile", str(invalid), "--update", profile)[0], 3)
        self.assertEqual(original, Path(profile).read_bytes())

    def test_update_rejects_conflicting_output(self):
        a = self.write_json("a.json", {"k": 1})
        profile = self.create_profile(a)
        with self.assertRaises(SystemExit):
            self.command("profile", a, "--update", profile, "--force")
        with self.assertRaises(SystemExit):
            self.command("profile", a, "--update", profile, "--output", str(self.root / "other.sdshape"))

    def test_update_refuses_source_inside_destination_directory(self):
        a = self.write_json("data/a.json", {"x": 2})
        target = self.create_profile(a)
        # Updating from an independent input source is allowed.
        self.assertEqual(self.command("profile", a, "--update", target)[0], 0)

    def test_sensitive_selectors_are_not_stored_without_explicit_permission(self):
        email_key = "contact@example.com"
        a = self.write_json("a.json", {"directory": {email_key: {"active": True}}})
        code, out, err = self.command("profile", a, "--ignore", f"/directory/{email_key}")
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("identifier-like", err)
        safe_code, safe_output, _ = self.command("profile", a, "--ignore", "/directory")
        self.assertEqual(safe_code, 0)
        self.assertNotIn(email_key, safe_output)

    def test_profile_strict_integer_narrowing_is_not_breaking(self):
        opts = sd.Options(strict_integers=True)
        a = sd.Dataset("a")
        b = sd.Dataset("b")
        sd.observe(a.shape, {"v": 1.2}, (), opts, a)
        sd.observe(b.shape, {"v": 2}, (), opts, b)
        results = sd.compare(a.shape, b.shape, opts)
        self.assertFalse(any(x.level == sd.ERROR for x in results))
        reverse = sd.compare(b.shape, a.shape, opts)
        self.assertTrue(any(x.level == sd.ERROR for x in reverse))

    def test_strict_integer_nullable_widening_is_error(self):
        opts = sd.Options(strict_integers=True)
        a = sd.Dataset("a")
        b = sd.Dataset("b")
        sd.observe(a.shape, {"v": 1.2}, (), opts, a)
        sd.observe(b.shape, {"v": 2}, (), opts, b)
        sd.observe(b.shape, {"v": None}, (), opts, b)
        results = sd.compare(a.shape, b.shape, opts)
        self.assertTrue(any(x.level == sd.ERROR and "null" in x.message for x in results))

    def test_incremental_update_order_independent(self):
        inputs = [
            {"byId": {"a": {"name": "x", "level": 1}}},
            {"byId": {"b": {"name": "y"}}},
            {"byId": {}, "active": True},
            {"byId": {"c": {"name": None, "level": "a"}}},
        ]
        files = [self.write_json(f"inc-{i}.json", content) for i, content in enumerate(inputs)]
        a = self.create_profile(files[0], "ordered.sdshape", "--map", "/byId")
        b = self.create_profile(files[-1], "reversed.sdshape", "--map", "/byId")
        for src in files[1:]:
            self.assertEqual(self.command("profile", src, "--update", a)[0], 0)
        for src in reversed(files[:-1]):
            self.assertEqual(self.command("profile", src, "--update", b)[0], 0)
        self.assertEqual(Path(a).read_bytes(), Path(b).read_bytes())

    def test_randomized_round_trip_preserves_all_findings(self):
        rng = random.Random(912801)
        for iteration in range(35):
            def generate(d=0):
                if d > 2:
                    return rng.choice([None, True, False, 1, 1.2, "x", "another value"])
                t = rng.randrange(4)
                if t == 0:
                    return {f"k{i}": generate(d+1) for i in range(rng.randrange(4))}
                if t == 1:
                    return [generate(d+1) for _ in range(rng.randrange(4))]
                return rng.choice([None, True, False, 1, 2.2, "x", "other value"])
            before, after = [generate() for _ in range(3)], [generate() for _ in range(3)]
            old_ds, new_ds = sd.Dataset("old"), sd.Dataset("new")
            for document in before:
                sd.observe(old_ds.shape, document, (), sd.Options(), old_ds)
                old_ds.documents += 1
            for document in after:
                sd.observe(new_ds.shape, document, (), sd.Options(), new_ds)
                new_ds.documents += 1
            for ds in (old_ds, new_ds):
                ds.files = ds.documents
            old_file = self.root / f"old_{iteration}.sdshape"
            new_file = self.root / f"new_{iteration}.sdshape"
            old_file.write_text(sd.export_profile(old_ds, sd.Options()))
            new_file.write_text(sd.export_profile(new_ds, sd.Options()))
            old_profile = sd._read_profile(str(old_file), sd.Options())
            new_profile = sd._read_profile(str(new_file), sd.Options())
            direct = [f.as_dict() for f in sd.compare(old_ds.shape, new_ds.shape, sd.Options())]
            replayed = [f.as_dict() for f in sd.compare(old_profile.dataset.shape, new_profile.dataset.shape, sd.Options())]
            self.assertEqual(direct, replayed)


if __name__ == "__main__":
    unittest.main()
