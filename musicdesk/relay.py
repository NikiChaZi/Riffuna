"""Loopback-only transport backed by a shared, bounded audio buffer in RAM."""
from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .audio_buffer import AudioBuffers
from .youtube import AudioStream, TimedSession

log = logging.getLogger(__name__)


@dataclass
class Binding:
    stream: AudioStream
    path: str
    buffer: object
    cancelled: threading.Event = field(default_factory=threading.Event)


def byte_range(value, total):
    """Return inclusive bounds, or None for a syntactically invalid range."""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value or "")
    if not match or not (match[1] or match[2]):
        return None
    if not match[1]:
        length = int(match[2])
        return (max(0, total - length), total - 1) if length else (total, total - 1)
    return int(match[1]), min(total - 1, int(match[2]) if match[2] else total - 1)


class MediaRelay:
    def __init__(self, session_factory=TimedSession):
        self.session_factory = session_factory
        self.buffers = AudioBuffers(session_factory)
        self._binding = None
        self._server = None
        self._thread = None

    def prepare(self, stream):
        self.buffers.prepare(stream)

    def invalidate(self, stream):
        self.buffers.invalidate(stream)

    def bind(self, stream: AudioStream) -> str:
        self.clear()
        if self._server is None:
            relay = self

            class Handler(BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.0"

                def log_message(self, *args):
                    pass

                def do_GET(self):
                    self._forward(False)

                def do_HEAD(self):
                    self._forward(True)

                def _forward(self, head):
                    binding = relay._binding
                    if binding is None or binding.cancelled.is_set() or not secrets.compare_digest(self.path, binding.path):
                        self.send_error(404)
                        return
                    self._sent = False
                    started = time.perf_counter()
                    try:
                        buffer = binding.buffer
                        if buffer is not None and buffer.metadata():
                            bounds = byte_range(self.headers.get("Range"), buffer.total)
                            start, end = bounds if bounds else (0, buffer.total - 1)
                            if start >= buffer.total or end < start:
                                self.send_response(416)
                                self.send_header("Content-Range", f"bytes */{buffer.total}")
                                self.send_header("Content-Length", "0")
                                self.end_headers()
                                return
                            self.send_response(206 if bounds else 200)
                            self.send_header("Content-Type", buffer.content_type)
                            self.send_header("Content-Length", str(end - start + 1))
                            self.send_header("Accept-Ranges", "bytes")
                            if bounds:
                                self.send_header("Content-Range", f"bytes {start}-{end}/{buffer.total}")
                            self.send_header("Cache-Control", "no-store")
                            self.send_header("Connection", "close")
                            self.end_headers()
                            self._sent = True
                            if not head:
                                offset = start
                                idle_deadline = time.monotonic() + 18
                                while offset <= end and not binding.cancelled.is_set():
                                    chunk = buffer.read(offset, min(64 * 1024, end - offset + 1), reader_id=started)
                                    if not chunk:
                                        # Wait for the shared priority downloader. A direct range
                                        # is needed only after failure or beyond the RAM limit.
                                        if (not buffer.finished and offset < len(buffer.data)
                                                and time.monotonic() < idle_deadline):
                                            continue
                                        self._tail(binding, offset, end, buffer.total)
                                        break
                                    self.wfile.write(chunk)
                                    offset += len(chunk)
                                    idle_deadline = time.monotonic() + 18
                        else:
                            self._direct(binding, head)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        pass
                    except Exception as exc:
                        log.warning("Audio relay connection failed (%s)", type(exc).__name__)
                        if not self._sent:
                            self.send_error(502, "Audio connection failed")
                    finally:
                        log.info("Audio HTTP request served in %sms",
                                 round((time.perf_counter() - started) * 1000))
                        self.close_connection = True

                def _tail(self, binding, start, end, total):
                    headers = dict(binding.stream.headers)
                    headers.update({"Accept-Encoding": "identity", "Range": f"bytes={start}-{end}"})
                    with relay.session_factory() as session:
                        with session.get(binding.stream.url, headers=headers, stream=True,
                                         allow_redirects=True) as response:
                            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                            if response.status_code != 206 or not match or int(match[1]) != start or int(match[3]) != total:
                                log.warning("Audio seek range rejected: status=%s range=%s expected_start=%s total=%s",
                                            response.status_code, response.headers.get("Content-Range"), start, total)
                                raise OSError("Audio seek range was not honored")
                            remaining = end - start + 1
                            for chunk in response.iter_content(16 * 1024):
                                if binding.cancelled.is_set():
                                    break
                                if chunk:
                                    self.wfile.write(chunk[:remaining])
                                    remaining -= min(remaining, len(chunk))
                                    if not remaining:
                                        break

                def _direct(self, binding, head):
                    headers = dict(binding.stream.headers)
                    headers["Accept-Encoding"] = "identity"
                    value = self.headers.get("Range")
                    if value and re.fullmatch(r"bytes=\d*-\d*", value):
                        headers["Range"] = value
                    with relay.session_factory() as session:
                        method = session.head if head else session.get
                        with method(binding.stream.url, headers=headers, stream=True, allow_redirects=True) as response:
                            if response.status_code not in {200, 206, 416}:
                                self.send_error(502, "Audio source unavailable")
                                return True
                            self.send_response(response.status_code)
                            for header in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                                if header in response.headers:
                                    self.send_header(header, response.headers[header])
                            self.send_header("Cache-Control", "no-store")
                            self.send_header("Connection", "close")
                            self.end_headers()
                            self._sent = True
                            if not head:
                                for chunk in response.iter_content(16 * 1024):
                                    if binding.cancelled.is_set():
                                        break
                                    if chunk:
                                        self.wfile.write(chunk)
                            return True

            self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            self._server.daemon_threads = True
            self._server.block_on_close = False
            self._thread = threading.Thread(target=self._server.serve_forever,
                                            kwargs={"poll_interval": 0.1}, daemon=True,
                                            name="audio-relay")
            self._thread.start()
        path = "/audio/" + secrets.token_urlsafe(24)
        self._binding = Binding(stream, path, self.buffers.prepare(stream, pin=True))
        return f"http://127.0.0.1:{self._server.server_port}{path}"

    def clear(self):
        binding, self._binding = self._binding, None
        if binding:
            binding.cancelled.set()
        self.buffers.unpin()

    def close(self):
        self.clear()
        self.buffers.close()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=0.3)
            self._thread = None
