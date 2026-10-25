"""Bounded RAM audio cache with seek-priority blocks and persistent HTTP."""
from __future__ import annotations

from collections import OrderedDict
import logging
import re
import threading
import time
from urllib.parse import parse_qs, urlparse

from .youtube import AudioStream, TimedSession

log = logging.getLogger(__name__)
BLOCK_SIZE = 128 * 1024


class AudioBuffer:
    def __init__(self, stream, limit, expires):
        self.stream = stream
        self.limit = limit
        self.expires = expires
        self.condition = threading.Condition()
        self.cancelled = threading.Event()
        self.priority = threading.Event()
        self.data = bytearray()
        self.buffered_bytes = 0
        self.total = None
        self.content_type = "audio/mp4"
        self.finished = False
        self.failed = False
        self._filled = {}
        self._urgent = None
        self._reader_generation = 0

    def cancel(self):
        self.cancelled.set()
        with self.condition:
            self.condition.notify_all()

    def metadata(self, timeout=12):
        with self.condition:
            self.condition.wait_for(
                lambda: self.total is not None or self.finished or self.cancelled.is_set(), timeout)
            return self.total is not None and not self.cancelled.is_set()

    def _available(self, offset):
        block, within = divmod(offset, BLOCK_SIZE)
        return max(0, self._filled.get(block, 0) - within)

    def read(self, offset, size, timeout=12, reader_id=None):
        with self.condition:
            if offset >= len(self.data) or offset < 0:
                return b""
            reader_id = time.monotonic() if reader_id is None else reader_id
            if reader_id >= self._reader_generation:
                self._reader_generation = reader_id
                if not self._available(offset):
                    self._urgent = offset // BLOCK_SIZE
                    self.condition.notify_all()
            self.condition.wait_for(
                lambda: self._available(offset) or self.finished or self.cancelled.is_set(), timeout)
            if self.cancelled.is_set():
                return b""
            available = self._available(offset)
            return bytes(self.data[offset:offset + min(size, available)]) if available else b""

    def _store(self, offset, chunk):
        with self.condition:
            chunk = chunk[:max(0, len(self.data) - offset)]
            self.data[offset:offset + len(chunk)] = chunk
            position, remaining = offset, len(chunk)
            while remaining:
                block, within = divmod(position, BLOCK_SIZE)
                count = min(remaining, BLOCK_SIZE - within)
                before = self._filled.get(block, 0)
                self._filled[block] = max(before, within + count)
                self.buffered_bytes += self._filled[block] - before
                position += count
                remaining -= count
            self.condition.notify_all()

    def _next_block(self):
        with self.condition:
            def missing(block):
                start = block * BLOCK_SIZE
                return start < len(self.data) and self._filled.get(block, 0) < min(BLOCK_SIZE, len(self.data) - start)
            if self._urgent is not None and missing(self._urgent):
                block, self._urgent = self._urgent, None
                return block
            return next((block for block in range((len(self.data) + BLOCK_SIZE - 1) // BLOCK_SIZE)
                         if missing(block)), None)


class AudioBuffers:
    def __init__(self, session_factory=TimedSession, *, max_entries=3,
                 max_bytes=24 * 1024 * 1024, ttl=300, clock=time.time, disk_cache=None):
        self.session_factory = session_factory
        self.disk_cache = disk_cache
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.ttl = ttl
        self.clock = clock
        self._entries = OrderedDict()
        self._lock = threading.RLock()
        self._slots = threading.Semaphore(2)
        self._foreground_slot = threading.Semaphore(1)
        self._pinned = None
        self._closed = False

    def prepare(self, stream: AudioStream, *, pin=False):
        if not stream.url.startswith("https://"):
            return None
        with self._lock:
            if self._closed:
                return None
            now = self.clock()
            entry = self._entries.get(stream.url)
            if entry and (entry.expires <= now or entry.failed or entry.cancelled.is_set()):
                entry.cancel()
                self._entries.pop(stream.url)
                entry = None
            if entry is None:
                expires = now + self.ttl
                try:
                    expires = min(expires, float(parse_qs(urlparse(stream.url).query)["expire"][0]) - 30)
                except (KeyError, ValueError, TypeError):
                    pass
                entry = AudioBuffer(stream, self.max_bytes, expires)
                self._entries[stream.url] = entry
                if pin:
                    entry.priority.set()
                threading.Thread(target=self._download, args=(entry,), daemon=True,
                                 name="audio-read-ahead").start()
            if pin:
                entry.priority.set()
                self._pinned = stream.url
            self._entries.move_to_end(stream.url)
            while len(self._entries) > self.max_entries:
                key = next(key for key in self._entries if key != self._pinned)
                self._entries.pop(key).cancel()
            return entry

    def unpin(self):
        with self._lock:
            self._pinned = None

    def invalidate(self, stream):
        with self._lock:
            entry = self._entries.pop(stream.url, None)
            if entry:
                entry.cancel()

    def _fetch_block(self, session, entry, block):
        start = block * BLOCK_SIZE
        end = min(entry.limit, start + BLOCK_SIZE) - 1
        if entry.total is not None:
            end = min(end, entry.total - 1)
        headers = {**entry.stream.headers, "Accept-Encoding": "identity", "Range": f"bytes={start}-{end}"}
        with session.get(entry.stream.url, headers=headers, stream=True, allow_redirects=True,
                         timeout=(4, 4)) as response:
            if response.status_code == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                if not match or int(match[1]) != start or int(match[2]) != min(end, int(match[3]) - 1):
                    raise ValueError("Audio range was not honored")
                total = int(match[3])
                expected = int(match[2]) - start + 1
            elif response.status_code == 200 and start == 0:
                total = int(response.headers.get("Content-Length", "0"))
                expected = min(total, entry.limit)
            else:
                raise ValueError("Audio source unavailable")
            if total <= 0 or (entry.total is not None and entry.total != total):
                raise ValueError("Inconsistent audio length")
            with entry.condition:
                if entry.total is None:
                    entry.total = total
                    entry.data = bytearray(min(total, entry.limit))
                    entry.content_type = response.headers.get("Content-Type", "audio/mp4")
                    entry.condition.notify_all()
            received = 0
            for chunk in response.iter_content(16 * 1024):
                if entry.cancelled.is_set():
                    return
                if chunk:
                    chunk = chunk[:expected - received]
                    entry._store(start + received, chunk)
                    received += len(chunk)
                    if received >= expected:
                        return
            if received != expected:
                raise OSError("Incomplete audio block")

    def _download(self, entry):
        acquired = None
        started = time.perf_counter()
        try:
            while not entry.cancelled.is_set():
                if entry.priority.is_set() and self._foreground_slot.acquire(blocking=False):
                    acquired = self._foreground_slot
                    break
                if self._slots.acquire(timeout=0.1):
                    acquired = self._slots
                    break
            if not acquired or entry.cancelled.is_set():
                return
            with self.session_factory() as session:
                block = 0
                while block is not None and not entry.cancelled.is_set():
                    for attempt in range(2):
                        try:
                            self._fetch_block(session, entry, block)
                            break
                        except Exception:
                            if attempt or entry.cancelled.is_set():
                                raise
                    block = entry._next_block()
        except Exception as exc:
            with entry.condition:
                entry.failed = True
            if not entry.cancelled.is_set():
                log.info("Audio read-ahead unavailable (%s); falling back to streaming", type(exc).__name__)
        finally:
            if (self.disk_cache is not None and not entry.failed and not entry.cancelled.is_set()
                    and entry.total is not None and entry.buffered_bytes == entry.total
                    and len(entry.data) == entry.total):
                self.disk_cache.put(entry.stream.cache_key, entry.data, entry.content_type)
            with entry.condition:
                entry.finished = True
                entry.condition.notify_all()
            if acquired:
                acquired.release()
            log.info("Audio read-ahead: %s bytes in %sms", entry.buffered_bytes,
                     round((time.perf_counter() - started) * 1000))

    def close(self):
        with self._lock:
            self._closed = True
            for entry in self._entries.values():
                entry.cancel()
            self._entries.clear()
            self._pinned = None
