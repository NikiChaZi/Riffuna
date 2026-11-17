import tempfile
import unittest
import zipfile
from pathlib import Path

from check_release_payload import PrivatePayload, check_path


class ReleasePrivacyTest(unittest.TestCase):
    def test_blocks_nested_database_and_signing_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, content in (("database.db", b"SQLite format 3\0"), ("signing.jks", b"synthetic")):
                with self.subTest(name=name):
                    jar = root / "inner.jar"
                    with zipfile.ZipFile(jar, "w") as nested:
                        nested.writestr(name, content)
                    apk = root / "example.apk"
                    with zipfile.ZipFile(apk, "w") as outer:
                        outer.write(jar, "opaque-payload")
                    with self.assertRaises(PrivatePayload):
                        check_path(apk)

    def test_blocks_private_log_without_reprinting_it(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "ci.log"
            log.write_text("https://r1---fixture.googlevideo.com/videoplayback?sig=FAKE_SIGNATURE_01234567")
            with self.assertRaisesRegex(PrivatePayload, "^signed media URL$"):
                check_path(log)

    def test_blocks_utf16_and_unrecognized_credentials(self):
        cases = (
            ("signed media URL", "https://r1---fixture.googlevideo.com/videoplayback?sig=FAKE_SIGNATURE_01234567"),
            ("absolute database path", r"C:\private\library.sqlite3"),
            ("Google API key", "AI" + "za" + "0" * 35),
            ("Bearer token", "Authorization: Bearer " + "TEST" * 8),
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bundle.log"
            for label, value in cases:
                for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
                    with self.subTest(label=label, encoding=encoding):
                        path.write_bytes(value.encode(encoding))
                        with self.assertRaisesRegex(PrivatePayload, f"^{label}$"):
                            check_path(path)

    def test_accepts_runtime_code_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "example.jar"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("org/sqlite/SQLite.class", b"fixture class")
                archive.writestr("org/provider/keystore/Provider.class", b"fixture class")
            check_path(path)
