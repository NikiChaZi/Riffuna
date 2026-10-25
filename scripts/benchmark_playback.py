"""Opt-in real, muted decoded-audio latency and seek benchmark."""
import argparse
import json
import logging
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QAudioBufferOutput
from PySide6.QtWidgets import QApplication

from musicdesk.models import PlayQueue, Track
from musicdesk.playback import Playback
from musicdesk.storage import Library
from musicdesk.youtube import YouTubeSource


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--prepared", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = QApplication([])
    library = Library(Path(".test-data/latency-benchmark/library.sqlite3"))
    library.save_queue(PlayQueue())
    player = Playback(library, YouTubeSource())
    player.output.setMuted(True)
    output = QAudioBufferOutput(player)
    player.player.setAudioBufferOutput(output)
    track = Track(args.video, "Latency check")
    report = {"video_id": args.video, "prepared": args.prepared, "ok": False}
    phase = "preparing" if args.prepared else "starting"
    clicked = 0.0
    seek_started = 0.0
    finished = False
    target = 60000
    prepared_started = time.perf_counter()

    def finish(error=None):
        nonlocal finished
        if finished:
            return
        finished = True
        report["error"] = error
        report["ok"] = not error and "seek_audio_ms" in report
        print(json.dumps(report), flush=True)
        player.shutdown()
        app.quit()

    def start():
        nonlocal phase, clicked
        if phase == "preparing":
            stream = player.streams.peek(track.video_id)
            if stream is None:
                QTimer.singleShot(100, start)
                return
            buffered = player.relay.buffers.prepare(stream)
            if not buffered.finished or buffered.failed or not buffered.data:
                QTimer.singleShot(100, start)
                return
            report["prepared_bytes"] = buffered.buffered_bytes
            report["preparation_ms"] = round((time.perf_counter() - prepared_started) * 1000)
        phase = "starting"
        clicked = time.perf_counter()
        player.play(track)

    def seek():
        nonlocal phase, seek_started, target
        if player.player.duration() < target + 5000:
            target = player.player.duration() // 2
        stream = player.streams.peek(track.video_id)
        cached = player.relay.buffers.prepare(stream) if stream is not None else None
        report["buffered_before_seek_bytes"] = cached.buffered_bytes if cached else 0
        phase = "seeking"
        seek_started = time.perf_counter()
        player.seek(target)

    def audio(buffer):
        nonlocal phase
        if not buffer.isValid():
            return
        if phase == "starting":
            report["first_decoded_audio_ms"] = round((time.perf_counter() - clicked) * 1000)
            report["playing_state_ms"] = player.last_start_ms
            phase = "playing"
            QTimer.singleShot(1200, seek)
        elif phase == "seeking" and (target - 100) * 1000 <= buffer.startTime() <= (target + 1500) * 1000:
            report["seek_audio_ms"] = round((time.perf_counter() - seek_started) * 1000)
            report["seek_audio_position_ms"] = buffer.startTime() // 1000
            QTimer.singleShot(100, finish)
            phase = "finished"

    output.audioBufferReceived.connect(audio)
    player.error.connect(finish)
    if args.prepared:
        player.prefetch(track)
    QTimer.singleShot(0, start)
    QTimer.singleShot(60000, lambda: finish("Benchmark timed out"))
    app.exec()
    player.pool.waitForDone(1000)
    player.prefetch_pool.waitForDone(1000)
    library.close()
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
