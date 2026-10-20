"""Release checks must reject a changed or unexpected registry artifact."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

script = Path(__file__).resolve().parents[1] / "scripts/verify_registry_release.py"
spec = importlib.util.spec_from_file_location("registry_verifier", script)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class RegistryVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.expected = Path(self.temporary.name)
        self.version = "0.1.0a4"
        self.files = {
            "shapediff-0.1.0a4-py3-none-any.whl": b"reviewed wheel",
            "shapediff-0.1.0a4.tar.gz": b"reviewed source archive",
        }
        self.metadata = {"info": {"name": "shapediff", "version": self.version}, "urls": []}
        self.responses = {}
        for name, data in self.files.items():
            (self.expected / name).write_bytes(data)
            url = "https://files.pythonhosted.org/packages/" + name
            self.metadata["urls"].append({"filename": name, "url": url, "digests": {"sha256": hashlib.sha256(data).hexdigest()}})
            self.responses[url] = data

    def verify(self, metadata=None, fetch=None):
        verifier.verify_distributions(self.version, self.expected, metadata or self.metadata, fetch or self.responses.__getitem__)

    def test_exact_reviewed_files_pass(self):
        self.verify()

    def test_changed_metadata_hash_is_rejected_before_download(self):
        metadata = copy.deepcopy(self.metadata)
        metadata["urls"][0]["digests"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "metadata digest mismatch"):
            self.verify(metadata, lambda _: self.fail("Must reject metadata before downloading"))

    def test_changed_download_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Downloaded registry file mismatch"):
            self.verify(fetch=lambda _: b"different archive")

    def test_missing_or_additional_file_is_rejected(self):
        for entries in [self.metadata["urls"][:1], self.metadata["urls"] * 2]:
            with self.subTest(count=len(entries)), self.assertRaisesRegex(ValueError, "inventory"):
                self.verify({**self.metadata, "urls": entries})

    def test_filename_cannot_escape_expected_directory(self):
        metadata = copy.deepcopy(self.metadata)
        metadata["urls"][0]["filename"] = "../outside.whl"
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.verify(metadata)

    def test_wrong_identity_and_runtime_dependencies_are_rejected(self):
        for change in [{"name": "other"}, {"version": "0.1.0a5"}, {"requires_dist": ["unexpected"]}]:
            metadata = copy.deepcopy(self.metadata)
            metadata["info"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(metadata)

    def test_downloads_are_confined_to_public_pypi_file_origin(self):
        for url in ["http://files.pythonhosted.org/a", "https://localhost/a", "https://files.pythonhosted.org.evil.test/a", "https://files.pythonhosted.org:8443/a", "https://user@files.pythonhosted.org/a"]:
            metadata = copy.deepcopy(self.metadata)
            metadata["urls"][0]["url"] = url
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "origin"):
                self.verify(metadata)

    def test_version_rejects_ranges_and_paths(self):
        for version in ["latest", "../other", "0.1.0a4?x=1", "0.1.0a4/", ">=0.1.0"]:
            with self.subTest(version=version), self.assertRaises(ValueError):
                verifier.validate_version(version)


if __name__ == "__main__":
    unittest.main()
