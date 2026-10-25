"""Explicit, muted end-to-end check of search, decoded audio and real seeking."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

from PySide6.QtCore import QThreadPool, QTimer

from .models import PlayQueue
from .playback import Playback
from .storage import Library
from .workers import Task
from .youtube import YouTubeSource


def run(app, data: Path) -> int:
    library = Library(data / "diagnostic.sqlite3")
    library.save_queue(PlayQueue())
    library.save_current(None)
    source = YouTubeSource()
    player = Playback(library, source)
    player.output.setMuted(True)
    pool = QThreadPool()
    prepared = "--prepared" in sys.argv
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)),
              "prepared": prepared, "search_count": 0, "error": None}
    finished = False
    phase = "searching"
    selected = None
    clicked = 0.0
    prepare_started = 0.0
    seek_started = 0.0
    target = 60000

    def finish(error=None):
        nonlocal finished
        if finished:
            return
        finished = True
        report["error"] = error
        report["position_ms"] = player.player.position()
        report["duration_ms"] = player.player.duration()
        report["ok"] = not error and report["search_count"] > 0 and "seek_audio_ms" in report
        (data / "diagnostic.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        player.shutdown()
        app.quit()

    def click():
        nonlocal phase, clicked
        if finished:
            return
        phase = "starting"
        clicked = time.perf_counter()
        player.play(selected)

    def wait_prepared():
        if finished:
            return
        stream = player.streams.peek(selected.video_id)
        if stream is not None:
            buffer = player.relay.buffers.prepare(stream)
            if buffer.finished and not buffer.failed and buffer.data:
                report["preparation_ms"] = round((time.perf_counter() - prepare_started) * 1000)
                report["prepared_bytes"] = len(buffer.data)
                click()
                return
        QTimer.singleShot(100, wait_prepared)

    def found(token, tracks):
        nonlocal selected, phase, prepare_started
        if finished:
            return
        report["search_count"] = len(tracks)
        report["sample"] = [track.title for track in tracks[:3]]
        if not tracks:
            finish("Music search returned no tracks")
            return
        selected = tracks[0]
        report["video_id"] = selected.video_id
        if prepared:
            phase = "preparing"
            prepare_started = time.perf_counter()
            player.prefetch(selected)
            wait_prepared()
        else:
            click()

    def seek():
        nonlocal phase, seek_started, target
        if finished:
            return
        if player.player.duration() < target + 5000:
            target = player.player.duration() // 2
        stream = player.streams.peek(selected.video_id)
        buffer = player.relay.buffers.prepare(stream) if stream else None
        report["buffered_before_seek_bytes"] = buffer.buffered_bytes if buffer else 0
        phase = "seeking"
        seek_started = time.perf_counter()
        player.seek(target)

    def audio(buffer):
        nonlocal phase
        if finished or not buffer.isValid():
            return
        if phase == "starting":
            report["first_decoded_audio_ms"] = round((time.perf_counter() - clicked) * 1000)
            report["playing_state_ms"] = player.last_start_ms
            phase = "playing"
            QTimer.singleShot(1200, seek)
        elif phase == "seeking" and (target - 100) * 1000 <= buffer.startTime() <= (target + 1500) * 1000:
            report["seek_audio_ms"] = round((time.perf_counter() - seek_started) * 1000)
            report["seek_audio_position_ms"] = buffer.startTime() // 1000
            phase = "finishing"
            QTimer.singleShot(100, finish)

    player.seek_guard.audio_buffer_received.connect(audio)
    player.error.connect(finish)
    task = Task("diagnostic-search", lambda: source.search("Дора ЁК", limit=40))
    task.signals.finished.connect(found)
    task.signals.failed.connect(lambda token, error: finish(error))
    pool.start(task)
    QTimer.singleShot(75000, lambda: finish("Diagnostic timed out"))
    app.exec()
    pool.waitForDone(1000)
    player.pool.waitForDone(1000)
    player.prefetch_pool.waitForDone(1000)
    library.close()
    return 0 if report["ok"] else 1
