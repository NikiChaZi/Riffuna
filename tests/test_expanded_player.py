import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from test_ui_search import app, wait_for

from musicdesk.expanded_player import ExpandedPlayer, ExpandableCover
from musicdesk.lyrics_view import LyricCue, LyricsDocument, LyricsState, document_from_payload
from musicdesk.models import Track
from musicdesk.motion import MotionPolicy
from musicdesk.widgets import Artwork


FIRST = Track("aaaaaaaaaaa", "Тестовая запись (Slowed)", "Синтетический исполнитель", 180)
SECOND = Track("bbbbbbbbbbb", "Тестовая запись (Slowed)", "Синтетический исполнитель", 180)
CUES = (LyricCue(1000, "Тихий свет ложится на дома"), LyricCue(4500, "Город дышит медленнее ветра"),
        LyricCue(8000, "Мы оставим шум за поворотом"), LyricCue(12000, "И услышим утро за окном"))


@pytest.fixture
def panel(app):
    host = QWidget()
    host.resize(1280, 800)
    source = ExpandableCover(Artwork(host), 56, host)
    source.move(20, 724)
    background = QPushButton("Underlying navigation", host)
    background.move(400, 740)
    host.show()
    host.activateWindow()
    source.setFocus()
    view = ExpandedPlayer(host, policy=MotionPolicy(True))
    view.set_track(FIRST)
    app.processEvents()
    yield host, source, view
    view.hide()
    host.close()
    host.deleteLater()
    app.processEvents()


def synced(view):
    assert view.set_lyrics(FIRST.video_id, view.request_token,
                           LyricsDocument(LyricsState.SYNCED, CUES, timing_confirmed=True))
    view.set_seekable(True)


def payload(state="synced", recording_id=FIRST.video_id, quality="metadata_duration"):
    return {"recording_id": recording_id, "state": state,
            "lines": [{"start_ms": cue.at_ms, "text": cue.text} for cue in CUES] if state == "synced" else [],
            "plain_text": "Тихий свет ложится на дома\nГород дышит медленнее ветра", "source": "LRCLIB",
            "timing_source": "provider_lrc", "match_quality": quality}


@pytest.mark.parametrize("size", [(1280, 800), (1000, 650)])
def test_two_columns_and_all_controls_fit_without_audio(panel, app, size):
    host, source, view = panel
    host.resize(*size)
    synced(view)
    view.open_from(source)
    app.processEvents()
    assert (view.width(), view.height()) == size
    assert view.left.geometry().right() < view.lyrics.geometry().left()
    for widget in (view.cover, view.play_button, view.seek, view.volume, view.title, view.lyrics.canvas):
        assert widget.parentWidget().rect().contains(widget.geometry())
    assert view.cover.width() >= 200
    assert view.lyrics.width() >= 480
    assert not view.version_button.isVisible()


def test_trigger_supports_click_enter_and_space(panel):
    host, source, view = panel
    requests = QSignalSpy(source.activated)
    QTest.mouseClick(source, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    QTest.keyClick(source, Qt.Key.Key_Return)
    QTest.keyClick(source, Qt.Key.Key_Space)
    assert requests.count() == 3


def test_rapid_reverse_and_reduced_motion_restore_focus(panel, app):
    host, source, view = panel
    view.policy.set_reduced(False)
    opened, closed = QSignalSpy(view.opened), QSignalSpy(view.closed)
    view.open_from(source)
    QTest.qWait(45)
    assert view._travel.running
    middle = view._travel.value
    view.collapse()
    assert view._travel.animation.startValue() == middle
    QTest.qWait(25)
    view.open_from(source)
    view.policy.set_reduced(True)
    app.processEvents()
    assert view.isVisible() and not view._travel.running
    assert not view.cover.suppress_paint and not view.flight.isVisible()
    assert opened.count() == 1 and closed.count() == 0
    view.collapse()
    app.processEvents()
    assert not view.isVisible() and source.hasFocus()
    assert closed.count() == 1


def test_resize_during_flight_settles_at_current_cover(panel, app):
    host, source, view = panel
    view.policy.set_reduced(False)
    view.open_from(source)
    QTest.qWait(30)
    view.resize(1000, 650)
    app.processEvents()
    assert not view._travel.running
    assert view._travel.value == view._cover_rect()
    assert not view.cover.suppress_paint


def test_tab_cannot_reach_hidden_background_and_escape_returns_to_cover(panel, app):
    host, source, view = panel
    view.open_from(source)
    for _ in range(30):
        focused = QApplication.focusWidget()
        assert focused is view or view.isAncestorOf(focused)
        QTest.keyClick(focused, Qt.Key.Key_Tab)
        app.processEvents()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    app.processEvents()
    assert not view.isVisible()
    assert source.hasFocus()


def test_space_activates_focused_control_without_double_toggle(panel):
    host, source, view = panel
    synced(view)
    view.open_from(source)
    toggle, likes = QSignalSpy(view.toggle_requested), QSignalSpy(view.like_requested)
    view.like_button.setFocus()
    QTest.keyClick(view.like_button, Qt.Key.Key_Space)
    assert likes.count() == 1 and toggle.count() == 0
    view.lyrics.canvas.setFocus()
    QTest.keyClick(view.lyrics.canvas, Qt.Key.Key_Space)
    assert toggle.count() == 1


@pytest.mark.parametrize("position,expected", [(0, ()), (999, ()), (1000, (0,)), (4499, (0,)),
                                              (4500, (1,)), (8000, (2,)), (30000, (3,))])
def test_exact_actual_position_boundaries(panel, position, expected):
    host, source, view = panel
    synced(view)
    view.set_position(position)
    assert view.lyrics.canvas.active_indices == expected


def test_pause_and_seek_do_not_use_an_invented_clock(panel):
    host, source, view = panel
    synced(view)
    view.set_playback_state("playing")
    view.set_position(4500)
    QTest.qWait(120)
    assert view.lyrics.canvas.active_indices == (1,)
    assert view.position == 4500
    view.set_playback_state("paused")
    view.set_position(12000)
    assert view.lyrics.canvas.active_indices == (3,)
    assert not view.lyrics.canvas._scroll.running
    view.set_position(1000)
    assert view.lyrics.canvas.active_indices == (0,)
    assert not view.lyrics.canvas._highlight.running


def test_seek_intent_waits_for_actual_position_before_highlight(panel):
    host, source, view = panel
    synced(view)
    view.open_from(source)
    view.set_position(1000)
    requests = QSignalSpy(view.seek_requested)
    canvas = view.lyrics.canvas
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_Down)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert requests.count() == 1 and requests.at(0)[0] == 4500
    assert canvas.active_indices == (0,)
    view.set_position(4500)
    assert canvas.active_indices == (1,)


def test_track_identity_and_request_token_reject_old_lyrics_and_art(panel):
    host, source, view = panel
    synced(view)
    old_token = view.request_token
    view.request_lyrics()
    assert not view.set_lyrics(FIRST.video_id, old_token, LyricsDocument(LyricsState.SYNCED, CUES, timing_confirmed=True))
    current_token = view.request_token
    view.set_track(SECOND)
    assert view.lyrics.document.state == LyricsState.LOADING
    assert not view.lyrics.canvas.active_indices
    assert not view.set_lyrics(FIRST.video_id, current_token, LyricsDocument(LyricsState.PLAIN, text="old"))
    assert not view.apply_lyrics_payload(FIRST.video_id, payload())
    art = QPixmap(32, 32)
    art.fill(QColor("red"))
    view.set_artwork(FIRST.video_id, art)
    assert view.cover.pixmap.isNull()
    view.set_artwork(SECOND.video_id, art)
    assert not view.cover.pixmap.isNull()


def test_same_title_does_not_imply_same_recording_or_censorship(panel):
    host, source, view = panel
    view.set_track(SECOND)
    assert view.title.toolTip() == FIRST.title
    assert view.lyrics.document.state == LyricsState.LOADING
    assert not view.version_button.isVisible()
    view.set_version_selection_available(True)
    view.open_from(source)
    requests = QSignalSpy(view.version_requested)
    view.version_button.click()
    assert requests.at(0)[0] == SECOND.video_id
    assert "цензур" not in view.title.toolTip().lower()


@pytest.mark.parametrize("state", list(LyricsState))
@pytest.mark.parametrize("size", [(1280, 800), (1000, 650)])
def test_all_lyric_states_and_import_intent(panel, app, state, size):
    host, source, view = panel
    host.resize(*size)
    data = LyricsDocument(state, cues=CUES if state == LyricsState.SYNCED else (),
                          text="Выдуманная строка\nЕщё одна строка", timing_confirmed=state == LyricsState.SYNCED)
    view.set_lyrics(FIRST.video_id, view.request_token, data)
    view.open_from(source)
    app.processEvents()
    assert view.lyrics.document.state == state
    assert (view.lyrics.stack.currentWidget() is view.lyrics.canvas) == (state in (LyricsState.SYNCED, LyricsState.PLAIN))
    assert view.lyrics.retry.isVisible() == (state in (LyricsState.ERROR, LyricsState.NOTFOUND))
    imported = QSignalSpy(view.import_requested)
    view.lyrics.import_button.click()
    assert imported.at(0)[0] == FIRST.video_id


def test_unconfirmed_timings_become_plain_for_processed_recording(panel):
    host, source, view = panel
    view.set_lyrics(FIRST.video_id, view.request_token, LyricsDocument(LyricsState.SYNCED, CUES, timing_confirmed=False))
    view.set_position(8000)
    assert view.lyrics.document.state == LyricsState.PLAIN
    assert not view.lyrics.canvas.active_indices
    assert "Без синхронизации" in view.lyrics.caption.text()


def test_controller_payload_supports_metadata_local_lrc_and_not_found(panel):
    host, source, view = panel
    assert view.apply_lyrics_payload(FIRST.video_id, payload())
    assert view.lyrics.document.state == LyricsState.SYNCED
    assert "метаданным" in view.lyrics.footer.text()
    local = payload(quality="user_import")
    local.update(source="local", timing_source="local_lrc")
    view.apply_lyrics_payload(FIRST.video_id, local)
    assert "LRC" in view.lyrics.footer.text()
    assert "Локальный LRC" in view.lyrics.caption.text()
    view.apply_lyrics_payload(FIRST.video_id, payload("not_found"))
    assert view.lyrics.document.state == LyricsState.NOTFOUND
    assert "метаданным" not in view.lyrics.footer.text()
    assert not view.apply_lyrics_payload(FIRST.video_id, payload(recording_id=SECOND.video_id))


def test_unmatched_controller_timings_and_malformed_payload_are_not_synced(panel):
    host, source, view = panel
    view.apply_lyrics_payload(FIRST.video_id, payload(quality="none"))
    assert view.lyrics.document.state == LyricsState.PLAIN
    bad = payload()
    bad["lines"] = [{"start_ms": -100, "text": "not valid"}]
    view.apply_lyrics_payload(FIRST.video_id, bad)
    assert view.lyrics.document.state == LyricsState.ERROR


def test_simultaneous_lines_and_instrumental_gap_use_supplied_times(panel):
    host, source, view = panel
    cues = (LyricCue(0, "Первая строка"), LyricCue(0, "Одновременный перевод"), LyricCue(5000, ""), LyricCue(9000, "Возврат вокала"))
    view.set_lyrics(FIRST.video_id, view.request_token, LyricsDocument(LyricsState.SYNCED, cues, timing_confirmed=True))
    view.set_position(2000)
    assert view.lyrics.canvas.active_indices == (0, 1)
    view.set_position(6000)
    assert view.lyrics.canvas.active_indices == (2,)
    assert view.lyrics.canvas.accessibleDescription() == "Музыкальная пауза"


def test_open_close_hide_does_not_emit_playback_intent(panel):
    host, source, view = panel
    playing = QSignalSpy(view.toggle_requested)
    seeking = QSignalSpy(view.seek_requested)
    view.open_from(source)
    view.collapse()
    view.open_from(source)
    view.hide()
    assert not view._travel.running and not view._fade.running
    assert playing.count() == 0 and seeking.count() == 0



def test_overlay_is_opaque_and_flight_uses_full_resolution_cover(panel, app):
    host, source, view = panel
    art = QPixmap(512, 512)
    art.fill(QColor("#FF875F"))
    source.pixmap = art
    view.set_artwork(FIRST.video_id, art)
    view.policy.set_reduced(False)
    view.open_from(source)
    assert view.flight.pixmap.size() == art.size()
    view.policy.set_reduced(True)
    app.processEvents()
    image = host.grab().toImage()
    assert image.pixelColor(30, 730).name() == "#111615"


def test_hidden_position_updates_have_no_background_animations(panel):
    host, source, view = panel
    view.policy.set_reduced(False)
    synced(view)
    view.set_playback_state("playing")
    view.set_position(4500)
    assert view.lyrics.canvas.active_indices == (1,)
    assert not view.lyrics.canvas._scroll.running
    assert not view.lyrics.canvas._highlight.running


def test_manual_browsing_does_not_fight_active_line_updates(panel):
    host, source, view = panel
    synced(view)
    view.open_from(source)
    view.set_position(1000)
    canvas = view.lyrics.canvas
    canvas._select_cursor(3)
    previous_scroll = canvas._scroll.value
    view.set_position(4500)
    assert canvas.active_indices == (1,)
    assert canvas.cursor == 3
    assert canvas._scroll.value == previous_scroll
    assert view.lyrics.follow_button.isVisible()
    view.lyrics.follow_button.click()
    assert canvas.follow
    assert not view.lyrics.follow_button.isVisible()
    assert canvas._scroll.value != previous_scroll


def test_controller_payload_from_worker_is_dispatched_in_gui_thread(panel, app, monkeypatch):
    from PySide6.QtCore import QObject, QThread, Signal, Slot

    host, source, view = panel
    applied = []
    original = view.lyrics.set_document

    def checked(document):
        assert QThread.currentThread() == app.thread()
        applied.append(document.state)
        original(document)

    monkeypatch.setattr(view.lyrics, "set_document", checked)

    class Provider(QObject):
        changed = Signal(str, object)
        @Slot()
        def run(self):
            self.changed.emit(FIRST.video_id, payload())
            self.thread().quit()

    thread = QThread()
    worker = Provider()
    worker.moveToThread(thread)
    worker.changed.connect(view.apply_lyrics_payload)
    thread.started.connect(worker.run)
    thread.finished.connect(worker.deleteLater)
    thread.start()
    try:
        wait_for(lambda: bool(applied))
        assert applied == [LyricsState.SYNCED]
    finally:
        thread.quit()
        assert thread.wait(2000)



def test_track_change_clears_like_version_and_accessible_lyric_state(panel):
    host, source, view = panel
    synced(view)
    view.set_position(4500)
    assert view.lyrics.canvas.accessibleDescription()
    view.set_liked(True)
    view.set_version_selection_available(True)
    view.set_track(SECOND)
    assert view.like_button.accessibleName() == "Мне нравится"
    assert not view.version_button.isVisible()
    assert not view.lyrics.canvas.accessibleDescription()


def test_playback_error_disables_seek_without_synthesizing_position(panel):
    host, source, view = panel
    synced(view)
    view.set_position(4500)
    view.set_playback_state("error")
    assert not view.seek.isEnabled()
    assert not view.lyrics.canvas.seek_enabled
    assert view.position == 4500
    assert view.lyrics.canvas.active_indices == (1,)
