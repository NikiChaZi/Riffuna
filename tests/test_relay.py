from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from musicdesk.relay import MediaRelay
from musicdesk.youtube import AudioStream


class Response:
    def __init__(self, headers):
        self.status_code = 206 if headers.get("Range") else 200
        self.body = b"test audio bytes"[5:] if headers.get("Range") else b"test audio bytes"
        self.headers = {"Content-Type": "audio/mp4", "Content-Length": str(len(self.body)), "Accept-Ranges": "bytes"}
        if self.status_code == 206:
            self.headers["Content-Range"] = "bytes 5-15/16"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield self.body


class Session:
    captured = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, url, **kwargs):
        self.captured.append(kwargs["headers"])
        return Response(kwargs["headers"])

    head = get


def test_loopback_stream_forwards_ranges_and_invalidates_old_urls():
    relay = MediaRelay(Session)
    try:
        first = relay.bind(AudioStream("https://example.googlevideo.com/test", {"User-Agent": "Fixture"}))
        with urlopen(Request(first, headers={"Range": "bytes=5-"}), timeout=3) as response:
            assert response.status == 206
            assert response.read() == b"audio bytes"
            assert response.headers["Content-Range"] == "bytes 5-15/16"
        assert Session.captured[-1]["Range"] == "bytes=5-"
        assert Session.captured[-1]["User-Agent"] == "Fixture"
        assert Session.captured[-1]["Accept-Encoding"] == "identity"
        second = relay.bind(AudioStream("https://example.googlevideo.com/other"))
        assert second != first
        with pytest.raises(HTTPError) as error:
            urlopen(first, timeout=3)
        assert error.value.code == 404
        with urlopen(Request(second, method="HEAD"), timeout=3) as response:
            assert response.headers["Content-Length"] == "16"
            assert response.read() == b""
    finally:
        relay.close()
