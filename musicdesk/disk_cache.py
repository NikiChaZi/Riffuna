"""Persistent LRU cache for complete audio; keys never contain signed URLs."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import threading
import uuid

log = logging.getLogger(__name__)


class DiskAudioCache:
    def __init__(self, directory, *, max_bytes=1024 * 1024 * 1024):
        self.directory = Path(directory)
        self.max_bytes = max_bytes
        self._lock = threading.RLock()

    def _paths(self, key, extension=".m4a"):
        name = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.directory / (name + extension), self.directory / (name + ".json")

    def get(self, key):
        if not key:
            return None
        with self._lock:
            audio, metadata = self._paths(key)
            try:
                info = json.loads(metadata.read_text(encoding="utf-8"))
                extension = info.get("extension", ".m4a")
                if extension not in {".m4a", ".webm", ".mp3", ".ogg", ".flac"}:
                    raise ValueError("Invalid audio format")
                audio, _ = self._paths(key, extension)
                if audio.stat().st_size != info["size"] or info["size"] <= 0:
                    raise ValueError("Incomplete cached audio")
                digest = hashlib.sha256()
                with audio.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != info["sha256"]:
                    raise ValueError("Corrupted cached audio")
                os.utime(audio, None)
                return audio.resolve()
            except FileNotFoundError:
                return None
            except (OSError, ValueError, KeyError, TypeError):
                self._remove(audio, metadata)
                return None

    def invalidate(self, key):
        if not key:
            return
        with self._lock:
            for extension in {".m4a", ".webm", ".mp3", ".ogg", ".flac"}:
                audio, metadata = self._paths(key, extension)
                self._remove(audio, metadata)

    def put(self, key, data, content_type="audio/mp4"):
        if not key or not data or len(data) > self.max_bytes:
            return
        with self._lock:
            extension = next((extension for kind, extension in (
                ("webm", ".webm"), ("mpeg", ".mp3"), ("ogg", ".ogg"), ("flac", ".flac")
            ) if kind in content_type.lower()), ".m4a")
            audio, metadata = self._paths(key, extension)
            suffix = "." + uuid.uuid4().hex + ".part"
            temporary_audio = audio.with_name(audio.name + suffix)
            temporary_metadata = metadata.with_name(metadata.name + suffix)
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                temporary_audio.write_bytes(data)
                temporary_metadata.write_text(json.dumps({
                    "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                    "content_type": content_type, "extension": extension,
                }), encoding="utf-8")
                os.replace(temporary_audio, audio)
                os.replace(temporary_metadata, metadata)
                for other_extension in {".m4a", ".webm", ".mp3", ".ogg", ".flac"} - {extension}:
                    old_audio, _ = self._paths(key, other_extension)
                    self._remove(old_audio)
                self._trim()
            except OSError as exc:
                log.info("Audio disk cache unavailable (%s)", type(exc).__name__)
            finally:
                self._remove(temporary_audio, temporary_metadata)

    def _trim(self):
        files = []
        for path in self.directory.iterdir():
            if path.suffix not in {".m4a", ".webm", ".mp3", ".ogg", ".flac"}:
                continue
            try:
                stat = path.stat()
                files.append((stat.st_mtime_ns, path, stat.st_size))
            except OSError:
                pass
        total = sum(item[2] for item in files)
        for _, audio, size in sorted(files):
            if total <= self.max_bytes:
                break
            if self._remove(audio, audio.with_suffix(".json")):
                total -= size

    @staticmethod
    def _remove(*paths):
        removed = True
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                removed = False
        return removed
