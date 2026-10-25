"""Opt-in real-source playback check. It is muted and uses a separate library."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from musicdesk.models import Track, video_id_from_url
from musicdesk.playback import Playback
from musicdesk.storage import Library
from musicdesk.youtube import YouTubeSource


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="YouTube URL or video ID")
    parser.add_argument("--seek", type=int, default=0, help="Seek target in seconds")
    args = parser.parse_args()
    video_id = video_id_from_url(args.video)
    if not video_id:
        parser.error("Expected a YouTube video URL or ID")
    app = QApplication([])
    data = Path(__file__).resolve().parent.parent / ".test-data" / "live-check"
    library = Library(data / "library.sqlite3")
    player = Playback(library, YouTubeSource())
    player.output.setMuted(True)
    result = {"ok": False, "video_id": video_id, "error": None}
    finishing = False
    first_play = True

    def finish():
        nonlocal finishing
        if finishing:
            return
        finishing = True
        position = player.player.position()
        result["position_ms"] = position
        result["duration_ms"] = player.player.duration()
        result["ok"] = not result["error"] and position > args.seek * 1000
        print(json.dumps(result, ensure_ascii=True), flush=True)
        player.shutdown()
        app.quit()

    def started(state):
        nonlocal first_play
        if state != "playing" or not first_play:
            return
        first_play = False
        if args.seek:
            QTimer.singleShot(700, lambda: player.seek(args.seek * 1000))
            QTimer.singleShot(4000, finish)
        else:
            QTimer.singleShot(1800, finish)

    def failed(message):
        result["error"] = message
        finish()

    player.state_changed.connect(started)
    player.error.connect(failed)
    player.play(Track(video_id, "Live playback check"))
    QTimer.singleShot(45000, finish)
    app.exec()
    player.pool.waitForDone(1000)
    library.close()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
