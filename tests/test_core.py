"""Contract-level tests for observed response comparison."""

from __future__ import annotations

import random
import unittest

import shapediff as sd


def dataset(*documents, opts=None):
    opts = opts or sd.Options()
    result = sd.Dataset("fixture")
    for document in documents:
        sd.observe(result.shape, document, (), opts, result)
        result.documents += 1
    return result


def findings(old, new, opts=None):
    opts = opts or sd.Options()
    a = dataset(*old, opts=opts)
    b = dataset(*new, opts=opts)
    return sd.compare(a.shape, b.shape, opts)


class CoreTests(unittest.TestCase):
    def assert_finding(self, report, code, level, path):
        matches = [f for f in report if (f.code, f.level, sd.render_path(f.path)) == (code, level, path)]
        self.assertEqual(len(matches), 1, [(f.code, f.level, sd.render_path(f.path), f.message) for f in report])

    def test_original_case(self):
        old = {"user": {"id": 101, "email": "e@example.org", "name": "Ada"}}
        new = {"user": {"id": "usr_101", "avatar": "https://cdn.test/avatar.jpg", "name": "Grace"}}
        f = findings([old], [new])
        self.assertEqual(len(f), 3)
        self.assert_finding(f, "field_missing", sd.ERROR, "user.email")
        self.assert_finding(f, "type_changed", sd.ERROR, "user.id")
        self.assert_finding(f, "field_added", sd.INFO, "user.avatar")
        self.assertEqual([x.level for x in f], [sd.ERROR, sd.ERROR, sd.INFO])

    def test_value_only_diff_is_silent(self):
        old = {"user": {"id": 1, "when": "2025-01-01T01:00:00Z", "name": "a", "score": 1.5}}
        new = {"user": {"id": 999, "when": "2029-02-02T01:00:00Z", "name": "b", "score": 3.5}}
        self.assertEqual(findings([old], [new]), [])

    def test_boolean_not_number(self):
        f = findings([{"v": True}], [{"v": 1}])
        self.assert_finding(f, "type_changed", sd.ERROR, "v")
        self.assertEqual(f[0].message, "boolean -> number")

    def test_narrowed_observed_type_nonbreaking(self):
        f = findings([{"v": 1}, {"v": "a"}], [{"v": 2}])
        self.assert_finding(f, "type_no_longer_observed", sd.INFO, "v")
        self.assertNotIn(sd.ERROR, [x.level for x in f])

    def test_new_type_in_union_breaking(self):
        f = findings([{"v": 1}], [{"v": 2}, {"v": "wrong"}])
        self.assert_finding(f, "type_added", sd.ERROR, "v")

    def test_string_to_nullable_breaking_for_response(self):
        f = findings([{"v": "ok"}], [{"v": "ok"}, {"v": None}])
        self.assert_finding(f, "type_added", sd.ERROR, "v")
        self.assertIn("null", f[0].message)

    def test_nullable_to_nonnull_observation_safe(self):
        f = findings([{"v": "ok"}, {"v": None}], [{"v": "new"}])
        self.assert_finding(f, "type_no_longer_observed", sd.INFO, "v")
        self.assertFalse(any(x.level == sd.ERROR for x in f))

    def test_null_only_baseline_is_inconclusive(self):
        f = findings([{"v": None}], [{"v": {"nested": "str"}}])
        self.assertEqual(len(f), 1)
        self.assert_finding(f, "null_only_baseline", sd.WARN, "v")
        self.assertFalse(any(x.level == sd.ERROR for x in f))

    def test_nonnull_to_null_is_breaking(self):
        f = findings([{"v": 3}], [{"v": None}])
        self.assert_finding(f, "type_changed", sd.ERROR, "v")

    def test_object_to_array_is_breaking(self):
        self.assert_finding(findings([{"x": {"id": 1}}], [{"x": [1]}]), "type_changed", sd.ERROR, "x")

    def test_inconsistent_baseline_shape_preserved(self):
        f = findings([{"x": {"id": 1}}, {"x": [2]}], [{"x": {"id": 3}}])
        self.assert_finding(f, "type_no_longer_observed", sd.INFO, "x")
        self.assertFalse(any(x.level == sd.ERROR for x in f))

    def test_required_in_samples_missing(self):
        f = findings([{"id": 1, "email": "a"}, {"id": 2, "email": "b"}], [{"id": 3}])
        self.assert_finding(f, "field_missing", sd.ERROR, "email")
        self.assertEqual(f[0].baseline, {"present": 2, "objects": 2})

    def test_intermittent_field_disappearance_is_warning(self):
        f = findings([{"id": 1, "promo": "x"}, {"id": 2}, {"id": 3}], [{"id": 5}])
        self.assert_finding(f, "field_unobserved", sd.WARN, "promo")
        self.assertEqual(f[0].baseline, {"present": 1, "objects": 3})

    def test_nested_presence_counts_objects_not_documents(self):
        old = {"items": [{"id": 1, "note": "yes"}, {"id": 2}]}
        new = {"items": [{"id": 3}]}
        f = findings([old], [new])
        self.assert_finding(f, "field_unobserved", sd.WARN, "items[*].note")
        self.assertEqual(f[0].baseline, {"present": 1, "objects": 2})

    def test_coverage_drop_with_samples(self):
        opts = sd.Options(coverage_drop=.5)
        before = [{"x": 1} for _ in range(6)]
        after = [{"x": 1}] + [{} for _ in range(5)]
        f = findings(before, after, opts)
        self.assert_finding(f, "presence_drop", sd.WARN, "x")
        self.assertFalse(any(x.code == "field_missing" for x in f))

    def test_coverage_not_emitted_for_small_sample(self):
        opts = sd.Options(coverage_drop=.5)
        f = findings([{"x": 1}, {"x": 2}], [{"x": 1}, {}], opts)
        self.assertEqual(f, [])

    def test_added_field_is_info(self):
        f = findings([{"id": 1}], [{"id": 2, "nick": "a"}])
        self.assert_finding(f, "field_added", sd.INFO, "nick")

    def test_empty_arrays_do_not_silently_pass(self):
        f = findings([{"items": [{"id": 1}]}], [{"items": []}])
        self.assert_finding(f, "unverified_array_elements", sd.WARN, "items")
        self.assertNotIn(sd.ERROR, [x.level for x in f])

    def test_unobserved_old_array_elements(self):
        f = findings([{"items": []}], [{"items": [1]}])
        self.assert_finding(f, "unverified_array_elements", sd.WARN, "items")

    def test_empty_arrays_on_both_sides_have_no_drift(self):
        self.assertEqual(findings([{"items": []}], [{"items": []}]), [])

    def test_nested_array_type_change(self):
        old = {"items": [{"tags": [1]}]}
        new = {"items": [{"tags": ["one"]}]}
        self.assert_finding(findings([old], [new]), "type_changed", sd.ERROR, "items[*].tags[*]")

    def test_map_mode_prevents_key_false_positives_only_when_explicit(self):
        old = [{"locations": {"us": {"region": "us", "load": 4}, "eu": {"region": "eu", "load": 2}}}]
        new = [{"locations": {"ap": {"region": "ap", "load": 6}}}]
        normal = findings(old, new)
        self.assertTrue(any(f.code == "field_missing" for f in normal))
        opts = sd.Options(maps=(sd.parse_selector("/locations"),))
        self.assertEqual(findings(old, new, opts), [])

    def test_map_mode_reports_value_break(self):
        opts = sd.Options(maps=(sd.parse_selector("/regions"),))
        f = findings([{"regions": {"r1": {"latency": 1}}}], [{"regions": {"r2": {"latency": "slow"}}}], opts)
        self.assert_finding(f, "type_changed", sd.ERROR, "regions{*}.latency")

    def test_empty_map_is_unverified(self):
        opts = sd.Options(maps=(sd.parse_selector("/regions"),))
        f = findings([{"regions": {"r": 1}}], [{"regions": {}}], opts)
        self.assert_finding(f, "unverified_map_values", sd.WARN, "regions")

    def test_escaped_json_keys_have_unambiguous_paths(self):
        self.assertEqual(sd.render_path(("a.b", "c/d", "it's", "quote\"")), '["a.b"]["c/d"]["it\'s"]["quote\\\""]')
        self.assertEqual(sd.render_pointer(("a/b", "tilde~", "id")), "/a~1b/tilde~0/id")
        f = findings([{"a.b": 1}], [{"a.b": "x"}])
        self.assertEqual(sd.render_path(f[0].path), '["a.b"]')

    def test_selectors_globstar_and_wildcard(self):
        self.assertTrue(sd.selector_matches(("items", sd.ARRAY, "secret"), sd.parse_selector("/items/*/secret")))
        self.assertTrue(sd.selector_matches(("a", "b", "c", "nonce"), sd.parse_selector("/**/nonce")))
        self.assertTrue(sd.selector_matches(("nonce",), sd.parse_selector("/**/nonce")))
        self.assertFalse(sd.selector_matches(("a", "b"), sd.parse_selector("/a/c")))
        self.assertEqual(sd.parse_selector("items[*].id"), ("items", "*", "id"))
        self.assertEqual(sd.parse_selector("/a~1b/~0c"), ("a/b", "~c"))

    def test_ignore_prefix_and_nested_with_globstar(self):
        opts = sd.Options(ignore=(sd.parse_selector("/items/*/secret"), sd.parse_selector("/profile")))
        before = [{"items": [{"id": 1, "secret": "a"}], "profile": {"id": 1}}]
        after = [{"items": [{"id": 2, "secret": 2}], "profile": None}]
        self.assertEqual(findings(before, after, opts), [])

    def test_format_detection_off_by_default(self):
        self.assertEqual(findings([{"when": "2026-01-01T00:00:00Z"}], [{"when": "not-a-date"}]), [])

    def test_format_detection_opt_in(self):
        opts = sd.Options(formats=True)
        f = findings([{"when": "2026-01-01T00:00:00Z"}], [{"when": "not-a-date"}], opts)
        self.assert_finding(f, "format_drift", sd.WARN, "when")

    def test_invalid_dates_not_classified_as_dates(self):
        self.assertEqual(sd.detect_string_format("2026-20-01"), "plain")
        self.assertEqual(sd.detect_string_format("2026-02-30T00:00:00Z"), "plain")
        self.assertEqual(sd.detect_string_format("ab7a3220-4b14-4fac-8865-c7acb4d72d6e"), "uuid")
        self.assertEqual(sd.detect_string_format("https://example.net/a"), "url")

    def test_numeric_default_and_strict(self):
        self.assertEqual(findings([{"n": 1}], [{"n": 1.2}]), [])
        strict = sd.Options(strict_integers=True)
        self.assert_finding(findings([{"n": 1}], [{"n": 1.2}], strict), "type_changed", sd.ERROR, "n")

    def test_root_primitive(self):
        f = findings([1], ["text"])
        self.assertEqual(len(f), 1)
        self.assertEqual(sd.render_path(f[0].path), "$")

    def test_values_are_not_stored_in_evidence(self):
        secret = "SENSITIVE-SERVER-TOKEN-9a851f"
        before = dataset({"token": secret, "id": 1})
        after = dataset({"token": 5, "id": "2"})
        report = sd.build_report(before, after, sd.Options())
        self.assertNotIn(secret, str(report))

    def test_same_document_invariant(self):
        cases = [None, True, 4, 3.5, "x", {}, [], {"a": [None, {"x": 3}, [True]]}]
        for case in cases:
            self.assertEqual(findings([case], [case]), [], case)

    def test_random_value_churn_keeps_structure(self):
        rng = random.Random(1234)
        for _ in range(180):
            original = {"list": [{"id": rng.randrange(1000000), "name": "n" + str(rng.randrange(1000)), "state": bool(rng.randrange(2))}], "meta": {"seen": rng.randrange(1000)}}
            updated = {"list": [{"id": rng.randrange(1000000), "name": "m" + str(rng.randrange(1000)), "state": bool(rng.randrange(2))}], "meta": {"seen": rng.randrange(1000)}}
            self.assertEqual(findings([original], [updated]), [])

    def test_surrogate_in_object_key_rejected(self):
        with self.assertRaisesRegex(sd.InputError, "Unicode surrogate"):
            sd.parse_json_document('{"\\ud800":123}', "test")

    def test_input_duplicate_keys_rejected(self):
        with self.assertRaisesRegex(sd.InputError, "duplicate JSON"):
            sd.parse_json_document('{"x":1,"x":2}', "test")
        with self.assertRaisesRegex(sd.InputError, "non-standard JSON"):
            sd.parse_json_document('{"a":NaN}', "test")
        with self.assertRaisesRegex(sd.InputError, "invalid JSON"):
            sd.parse_json_document('{"a":', "test")

    def test_depth_limit(self):
        opts = sd.Options(max_depth=2)
        with self.assertRaisesRegex(sd.InputError, "max-depth"):
            dataset({"a": [{"b": 1}]}, opts=opts)

    def test_shape_node_limit_blocks_dynamic_key_explosion(self):
        opts = sd.Options(max_shape_nodes=3)
        with self.assertRaisesRegex(sd.InputError, "max-shape-nodes"):
            dataset({"a": 1, "b": 2, "c": 3}, opts=opts)

    def test_map_limits_shape_nodes_for_dynamic_keys(self):
        opts = sd.Options(max_shape_nodes=4, maps=(sd.parse_selector(""),))
        d = dataset({f"entry-{i}": {"id": i} for i in range(100)}, opts=opts)
        self.assertLessEqual(d.shape_nodes, 4)

    def test_bad_url_does_not_crash_format_probe(self):
        self.assertEqual(sd.detect_string_format("http://[invalid"), "plain")

    def test_deterministic_finding_order(self):
        base = [{"z": 1, "a": 1, "q": {"k": 2}}]
        current = [{"z": "1", "x": 1, "q": {}, "a": "1"}]
        result = findings(base, current)
        levels = [f.level for f in result]
        self.assertEqual(levels, sorted(levels, key={sd.ERROR: 0, sd.WARN: 1, sd.INFO: 2}.get))
        self.assertEqual([sd.render_pointer(f.path) for f in result if f.level == sd.ERROR], sorted(sd.render_pointer(f.path) for f in result if f.level == sd.ERROR))


if __name__ == "__main__":
    unittest.main()
