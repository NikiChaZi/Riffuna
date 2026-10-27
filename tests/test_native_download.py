import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest
import requests


def load_helper():
    path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_mpv.py"
    spec = importlib.util.spec_from_file_location("riffuna_native_fetch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, payload=b"", status=200):
        self.payload, self.status = payload, status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            response = requests.Response()
            response.status_code = self.status
            raise requests.HTTPError(response=response)

    def iter_content(self, size):
        for start in range(0, len(self.payload), size):
            yield self.payload[start:start + size]


def fixture_archive(helper, binary):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as package:
        package.writestr(helper.MIRROR_PREFIX + "libmpv-2.dll", binary)
        package.writestr(helper.MIRROR_PREFIX + "LICENSE.LGPL", b"License fixture")
        package.writestr(helper.MIRROR_PREFIX + "BUILD-MANIFEST.json", json.dumps({"license": "LGPL fixture"}))
    return stream.getvalue()


def test_removed_upstream_asset_uses_the_pinned_mirror(monkeypatch, tmp_path):
    helper = load_helper()
    binary = b"native DLL fixture"
    payload = fixture_archive(helper, binary)
    monkeypatch.setattr(helper, "MIRROR_SIZE", len(payload))
    monkeypatch.setattr(helper, "MIRROR_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(helper, "DLL_SHA256", hashlib.sha256(binary).hexdigest())
    monkeypatch.setattr(helper.requests, "get", lambda url, **kwargs: Response(status=404) if url == helper.URL else Response(payload))
    result = helper.fetch(tmp_path)
    assert result.read_bytes() == binary
    assert (tmp_path / "LICENSE.LGPL").read_bytes() == b"License fixture"
    assert not list(tmp_path.glob("*.part"))


def test_a_bad_archive_is_rejected_without_leaving_partial_files(monkeypatch, tmp_path):
    helper = load_helper()
    monkeypatch.setattr(helper.requests, "get", lambda *args, **kwargs: Response(b"corrupt"))
    with pytest.raises(RuntimeError, match="SHA256"):
        helper.download_pinned("https://example.invalid/archive", tmp_path / "archive.zip", 7, "0" * 64)
    assert not (tmp_path / "archive.zip").exists()
    assert not list(tmp_path.glob("*.part"))


def test_mirror_cannot_replace_an_existing_library_with_another_build(monkeypatch, tmp_path):
    helper = load_helper()
    original = tmp_path / "libmpv-2.dll"
    original.write_bytes(b"trusted build")
    payload = fixture_archive(helper, b"different build")
    monkeypatch.setattr(helper, "MIRROR_SIZE", len(payload))
    monkeypatch.setattr(helper, "MIRROR_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(helper, "DLL_SHA256", hashlib.sha256(original.read_bytes()).hexdigest())
    monkeypatch.setattr(helper.requests, "get", lambda *args, **kwargs: Response(payload))
    with pytest.raises(RuntimeError, match="differs"):
        helper.fetch_mirror(tmp_path)
    assert original.read_bytes() == b"trusted build"
