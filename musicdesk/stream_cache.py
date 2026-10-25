"""Bounded in-memory signed-stream cache with concurrent request coalescing."""
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import replace
import threading
import time
from urllib.parse import parse_qs, urlparse


class StreamCache:
    def __init__(self, resolver, max_entries=32, clock=time.time):
        self.resolver = resolver
        self.max_entries = max_entries
        self.clock = clock
        self._lock = threading.RLock()
        self._values = OrderedDict()
        self._pending = {}

    def peek(self, video_id):
        with self._lock:
            item = self._values.get(video_id)
            if item is None:
                return None
            expires, stream = item
            if expires <= self.clock():
                self._values.pop(video_id, None)
                return None
            self._values.move_to_end(video_id)
            return stream

    def is_pending(self, video_id):
        with self._lock:
            return video_id in self._pending

    def invalidate(self, video_id):
        with self._lock:
            self._values.pop(video_id, None)

    def resolve(self, track):
        with self._lock:
            cached = self.peek(track.video_id)
            if cached is not None:
                return cached
            future = self._pending.get(track.video_id)
            owner = future is None
            if owner:
                future = Future()
                self._pending[track.video_id] = future
        if not owner:
            return future.result(timeout=60)
        try:
            stream = replace(self.resolver(track), cache_key=track.video_id)
            now = self.clock()
            expires = now + 300
            try:
                signed_expiry = float(parse_qs(urlparse(stream.url).query).get("expire", [""])[0])
                expires = min(now + 900, signed_expiry - 30)
            except (ValueError, TypeError):
                pass
            with self._lock:
                if expires > now:
                    self._values[track.video_id] = (expires, stream)
                    self._values.move_to_end(track.video_id)
                    while len(self._values) > self.max_entries:
                        self._values.popitem(last=False)
                future.set_result(stream)
            return stream
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._pending.pop(track.video_id, None)

