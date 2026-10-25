import re
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from musicdesk.audio_buffer import AudioBuffers
from musicdesk.relay import MediaRelay
from musicdesk.youtube import AudioStream


BODY = bytes(range(256)) * 64


class Response:
    def __init__(self, headers):
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", headers.get("Range", ""))
        self.start = int(match[1]) if match else 0
        self.end = min(len(BODY) - 1, int(match[2]) if match and match[2] else len(BODY) - 1)
        self.status_code = 206 if match else 200
        self.headers = {"Content-Type": "audio/mp4", "Content-Length": str(self.end - self.start + 1)}
        if match:
            self.headers["Content-Range"] = f"bytes {self.start}-{self.end}/{len(BODY)}"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield BODY[self.start:self.end + 1]


class Session:
    calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, url, **kwargs):
        self.calls.append((url, dict(kwargs["headers"])))
        return Response(kwargs["headers"])

    head = get


def wait_done(buffer):
    with buffer.condition:
        assert buffer.condition.wait_for(lambda: buffer.finished, timeout=3)
    assert not buffer.failed


@pytest.fixture(autouse=True)
def reset_calls():
    Session.calls = []


def test_warm_play_head_and_repeated_seeks_never_reopen_upstream():
    relay = MediaRelay(Session)
    stream = AudioStream("https://example.googlevideo.com/audio", {"User-Agent": "Fixture"})
    try:
        ready = relay.buffers.prepare(stream)
        wait_done(ready)
        url = relay.bind(stream)
        for bounds in ["bytes=0-99", "bytes=9000-9999", "bytes=10-29", "bytes=-123"]:
            with urlopen(Request(url, headers={"Range": bounds}), timeout=2) as response:
                start, end = map(int, response.headers["Content-Range"].split()[1].split("/")[0].split("-"))
                assert response.read() == BODY[start:end + 1]
        with urlopen(Request(url, method="HEAD"), timeout=2) as response:
            assert int(response.headers["Content-Length"]) == len(BODY)
            assert response.read() == b""
        assert len(Session.calls) == 1
        assert Session.calls[0][1]["User-Agent"] == "Fixture"
        assert Session.calls[0][1]["Accept-Encoding"] == "identity"
    finally:
        relay.close()


def test_initial_bytes_can_play_while_read_ahead_is_still_downloading():
    gate = threading.Event()
    class ProgressiveResponse(Response):
        def iter_content(self, size):
            yield BODY[:256]
            gate.wait(3)
            yield BODY[256:]
    class ProgressiveSession(Session):
        def get(self, url, **kwargs):
            self.calls.append((url, dict(kwargs["headers"])))
            return ProgressiveResponse(kwargs["headers"])
    relay = MediaRelay(ProgressiveSession)
    try:
        url = relay.bind(AudioStream("https://example.googlevideo.com/progressive"))
        with urlopen(Request(url, headers={"Range": "bytes=0-127"}), timeout=2) as response:
            assert response.read() == BODY[:128]
        assert not gate.is_set()
        assert len(Session.calls) == 1
    finally:
        gate.set()
        relay.close()


def test_memory_cap_and_unbuffered_seek_return_the_correct_bytes():
    relay = MediaRelay(Session)
    relay.buffers.close()
    relay.buffers = AudioBuffers(Session, max_bytes=1024)
    try:
        stream = AudioStream("https://example.googlevideo.com/long")
        cached = relay.buffers.prepare(stream)
        wait_done(cached)
        assert len(cached.data) == 1024
        url = relay.bind(stream)
        with urlopen(Request(url, headers={"Range": "bytes=5000-5999"}), timeout=2) as response:
            assert response.read() == BODY[5000:6000]
        assert len(Session.calls) == 2
        assert Session.calls[-1][1]["Range"] == "bytes=5000-5999"
    finally:
        relay.close()


def test_coalescing_expiry_lru_and_current_track_protection():
    now = [1000]
    cache = AudioBuffers(Session, max_entries=2, max_bytes=1024, clock=lambda: now[0])
    a, b, c = [AudioStream(f"https://example.googlevideo.com/{name}?expire=1300") for name in "abc"]
    try:
        current = cache.prepare(a, pin=True)
        wait_done(current)
        assert cache.prepare(a) is current
        evicted = cache.prepare(b)
        wait_done(evicted)
        following = cache.prepare(c)
        wait_done(following)
        assert evicted.cancelled.is_set()
        assert not current.cancelled.is_set()
        now[0] = 1271
        renewed = cache.prepare(a)
        assert renewed is not current
        assert current.cancelled.is_set()
        wait_done(renewed)
    finally:
        cache.close()
    assert renewed.cancelled.is_set()


@pytest.mark.parametrize("value", ["bytes=16384-", "bytes=8-3", "bytes=-0"])
def test_unsatisfiable_cached_ranges_are_416(value):
    relay = MediaRelay(Session)
    try:
        stream = AudioStream("https://example.googlevideo.com/track")
        wait_done(relay.buffers.prepare(stream))
        with pytest.raises(HTTPError) as error:
            urlopen(Request(relay.bind(stream), headers={"Range": value}), timeout=2)
        assert error.value.code == 416
        assert error.value.headers["Content-Range"] == f"bytes */{len(BODY)}"
    finally:
        relay.close()


def test_expired_bindings_cannot_access_buffered_audio():
    relay = MediaRelay(Session)
    try:
        first = relay.bind(AudioStream("https://example.googlevideo.com/first"))
        relay.bind(AudioStream("https://example.googlevideo.com/second"))
        with pytest.raises(HTTPError) as error:
            urlopen(first, timeout=2)
        assert error.value.code == 404
    finally:
        relay.close()


def test_selected_track_is_not_blocked_behind_two_background_downloads():
    gate = threading.Event()
    started = set()
    lock = threading.Lock()
    class BlockedResponse(Response):
        def iter_content(self, size):
            yield BODY[:256]
            gate.wait(3)
            yield BODY[256:]
    class BusySession(Session):
        def get(self, url, **kwargs):
            with lock:
                started.add(url)
            return Response(kwargs["headers"]) if url.endswith("/selected") else BlockedResponse(kwargs["headers"])
    buffers = AudioBuffers(BusySession)
    try:
        first = buffers.prepare(AudioStream("https://example.googlevideo.com/one"))
        second = buffers.prepare(AudioStream("https://example.googlevideo.com/two"))
        assert first.metadata(2) and second.metadata(2)
        selected = buffers.prepare(AudioStream("https://example.googlevideo.com/selected"), pin=True)
        wait_done(selected)
        assert not gate.is_set()
        assert len(started) == 3
    finally:
        gate.set()
        buffers.close()


def test_a_short_download_stall_does_not_reopen_or_truncate_the_audio():
    gate = threading.Event()
    class StallingResponse(Response):
        def iter_content(self, size):
            yield BODY[:256]
            threading.Timer(0.6, gate.set).start()
            assert gate.wait(2)
            yield BODY[256:]
    class StallingSession(Session):
        def get(self, url, **kwargs):
            self.calls.append((url, dict(kwargs["headers"])))
            assert len(self.calls) == 1, "A sequential reader must share its downloader"
            return StallingResponse(kwargs["headers"])
    relay = MediaRelay(StallingSession)
    try:
        url = relay.bind(AudioStream("https://example.googlevideo.com/stalling"))
        with urlopen(url, timeout=3) as response:
            assert response.read() == BODY
        assert len(Session.calls) == 1
    finally:
        gate.set()
        relay.close()


def test_distant_seek_block_precedes_background_and_stale_reader(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from musicdesk.audio_buffer import BLOCK_SIZE
    gate = threading.Event()
    big_body = bytes(range(256)) * (BLOCK_SIZE * 4 // 256)
    monkeypatch.setitem(globals(), "BODY", big_body)
    ranges = []
    class OrderedResponse(Response):
        def iter_content(self, size):
            if self.start == 0:
                yield BODY[:256]
                assert gate.wait(3)
                yield BODY[256:self.end + 1]
            else:
                yield BODY[self.start:self.end + 1]
    class OrderedSession(Session):
        def get(self, url, **kwargs):
            ranges.append(kwargs["headers"]["Range"])
            return OrderedResponse(kwargs["headers"])
    buffers = AudioBuffers(OrderedSession)
    try:
        cached = buffers.prepare(AudioStream("https://example.googlevideo.com/seek-priority"))
        assert cached.metadata(2)
        target = BLOCK_SIZE * 3 + 100
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(cached.read, target, 512, 3, 20)
            with cached.condition:
                assert cached.condition.wait_for(lambda: cached._urgent == 3, 2)
            assert cached.read(BLOCK_SIZE + 100, 512, timeout=0.01, reader_id=10) == b""
            gate.set()
            assert future.result(3) == BODY[target:target + 512]
        wait_done(cached)
        assert ranges[1] == f"bytes={BLOCK_SIZE * 3}-{len(BODY) - 1}"
        assert cached.buffered_bytes == len(BODY)
        assert cached.read(0, 512) == BODY[:512]
    finally:
        gate.set()
        buffers.close()
