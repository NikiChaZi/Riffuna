import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from musicdesk.disk_cache import DiskAudioCache
from musicdesk.relay import MediaRelay
from musicdesk.youtube import AudioStream
from musicdesk.stream_cache import StreamCache
from musicdesk.models import Track

from test_audio_buffer import BODY, Session, wait_done


def test_completed_track_survives_ram_eviction_signature_expiry_and_restart(tmp_path):
    Session.calls = []
    relay = MediaRelay(Session, cache_directory=tmp_path)
    relay.buffers.max_entries = 1
    track = Track("ewCPQeAtICk", "Song")
    streams = StreamCache(lambda _: AudioStream("https://example.googlevideo.com/one?expire=9000000000"))
    stream = streams.resolve(track)
    assert stream.cache_key == track.video_id
    try:
        first = relay.buffers.prepare(stream)
        wait_done(first)
        wait_done(relay.buffers.prepare(AudioStream("https://example.googlevideo.com/two", cache_key="second")))
        assert first.cancelled.is_set()
        streams.invalidate(track.video_id)
    finally:
        relay.close()
    calls = len(Session.calls)
    restarted = MediaRelay(Session, cache_directory=tmp_path)
    try:
        cached = restarted.cached(track.video_id)
        assert cached is not None and cached.url.startswith("file:")
        path = Path(url2pathname(urlparse(cached.url).path))
        assert path.read_bytes() == BODY
        assert cached.cache_key == track.video_id
        assert len(Session.calls) == calls
        assert "googlevideo" not in "".join(p.read_text() for p in tmp_path.glob("*.json"))
    finally:
        restarted.close()


def test_lru_limit_counts_bytes_and_access_keeps_recent_track(tmp_path):
    cache = DiskAudioCache(tmp_path, max_bytes=8)
    cache.put("a", b"aaaa")
    cache.put("b", b"bbbb")
    a, _ = cache._paths("a")
    b, _ = cache._paths("b")
    os.utime(a, (1, 1))
    os.utime(b, (2, 2))
    assert cache.get("a") is not None
    cache.put("c", b"cccc")
    assert cache.get("a") is not None
    assert cache.get("b") is None
    assert cache.get("c") is not None
    assert sum(p.stat().st_size for p in tmp_path.glob("*.m4a")) <= 8


def test_partial_corrupted_and_oversized_audio_are_never_reused(tmp_path):
    cache = DiskAudioCache(tmp_path, max_bytes=8)
    cache.put("corrupt", b"1234")
    audio, _ = cache._paths("corrupt")
    audio.write_bytes(b"5678")  # Same length still fails integrity verification.
    assert cache.get("corrupt") is None
    cache.put("truncated", b"1234")
    audio, _ = cache._paths("truncated")
    audio.write_bytes(b"12")
    assert cache.get("truncated") is None
    cache.put("huge", b"1" * 9)
    assert cache.get("huge") is None
    (tmp_path / "interrupted.audio.part").write_bytes(b"1234")
    assert cache.get("interrupted") is None
    cache.put("missing", b"1234")
    audio, _ = cache._paths("missing")
    audio.unlink()
    assert cache.get("missing") is None


def test_ram_prefix_of_long_audio_is_not_saved_as_complete_track(tmp_path):
    relay = MediaRelay(Session, cache_directory=tmp_path)
    relay.buffers.max_bytes = 1024
    try:
        wait_done(relay.buffers.prepare(AudioStream("https://example.googlevideo.com/long", cache_key="long")))
        assert relay.cached("long") is None
        assert not list(tmp_path.glob("*.m4a"))
    finally:
        relay.close()


def test_file_extension_matches_stream_container(tmp_path):
    cache = DiskAudioCache(tmp_path)
    cache.put("webm-track", b"webm-payload", "audio/webm; codecs=opus")
    assert cache.get("webm-track").suffix == ".webm"
    cache.put("webm-track", b"mp4-payload", "audio/mp4")
    assert cache.get("webm-track").suffix == ".m4a"
    assert not list(tmp_path.glob("*.webm"))


def test_decoder_failure_invalidation_discards_cached_file(tmp_path):
    relay = MediaRelay(Session, cache_directory=tmp_path)
    try:
        relay.disk_cache.put("invalid-track", b"not-a-decodable-container")
        stream = relay.cached("invalid-track")
        assert stream is not None
        relay.invalidate(stream)
        assert relay.cached("invalid-track") is None
    finally:
        relay.close()
