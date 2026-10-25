from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from musicdesk.models import Track
from musicdesk.stream_cache import StreamCache
from musicdesk.youtube import AudioStream


def test_prefetch_and_click_share_one_resolution():
    calls = []
    started = threading.Event()
    release = threading.Event()
    track = Track("ewCPQeAtICk", "Track")
    def resolve(value):
        calls.append(value)
        started.set()
        assert release.wait(3)
        return AudioStream("https://example.googlevideo.com/audio?expire=2000")
    cache = StreamCache(resolve, clock=lambda: 1000)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.resolve, track)
        assert started.wait(2)
        second = pool.submit(cache.resolve, track)
        release.set()
        assert first.result(3) == second.result(3)
    assert len(calls) == 1
    assert cache.resolve(track) == first.result()
    assert len(calls) == 1


def test_expiry_margin_invalidation_and_bounded_cache():
    now = [1000]
    calls = []
    def resolve(track):
        calls.append(track.video_id)
        return AudioStream("https://example.googlevideo.com/audio?expire=1100")
    cache = StreamCache(resolve, max_entries=1, clock=lambda: now[0])
    a, b = Track("ewCPQeAtICk", "A"), Track("lCKU-tI-upI", "B")
    cache.resolve(a)
    assert cache.peek(a.video_id)
    now[0] = 1071  # Never reuse a signature close to expiry.
    assert cache.peek(a.video_id) is None
    now[0] = 1000
    cache.resolve(a)
    cache.resolve(b)
    assert cache.peek(a.video_id) is None
    cache.invalidate(b.video_id)
    assert cache.peek(b.video_id) is None


def test_failed_resolutions_are_not_cached():
    attempts = []
    def resolve(track):
        attempts.append(track)
        raise RuntimeError("Expected failure")
    cache = StreamCache(resolve)
    track = Track("ewCPQeAtICk", "A")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cache.resolve(track)
    assert len(attempts) == 2
    assert not cache.is_pending(track.video_id)
