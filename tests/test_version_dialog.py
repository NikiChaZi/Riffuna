"""Offline dialog regressions: no visible desktop, network or audio playback."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QThread, QThreadPool, QTimer, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget
from shiboken6 import isValid

import musicdesk.version_dialog as module
from musicdesk.models import Track
from musicdesk.recording_versions import RecordingVersion
from musicdesk.style import STYLE
from musicdesk.youtube import SourceError

ORIGINAL = Track('aaaaaaaaaaa', 'Песня', 'Слава КПСС', 180)
OTHER = Track('bbbbbbbbbbb', 'Песня (uncensored)', 'Слава КПСС', 181)
VERSION = RecordingVersion(OTHER, '«Без цензуры» — заявлено',
                           'Совпадают название и исполнитель; заявлено в названии. Содержание не проверено.')


@pytest.fixture(scope='module')
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyle('Fusion')
    fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for name in ('segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf'):
        if (fonts / name).exists():
            QFontDatabase.addApplicationFont(str(fonts / name))
    application.setFont(QFont('Segoe UI', 10))
    application.setStyleSheet(STYLE)
    assert application.platformName() == 'offscreen'
    return application


def wait_for(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError('Dialog worker/state did not settle')


@pytest.fixture
def make_dialog(app, monkeypatch):
    controls, dialogs = [], []
    def make(payload=None, blocked=False, parent=None):
        control = SimpleNamespace(payload=[VERSION] if payload is None else payload,
                                  calls=[], threads=[], active=0, peak=0,
                                  gate=threading.Event(), entered=threading.Event(), returned=threading.Event())
        if not blocked:
            control.gate.set()
        class Finder:
            def __init__(self, source): pass
            def find(self, original, limit=12):
                assert QThread.currentThread() != app.thread()
                control.calls.append((original, limit))
                control.threads.append(threading.get_ident())
                control.active += 1
                control.peak = max(control.peak, control.active)
                control.entered.set()
                try:
                    assert control.gate.wait(4), 'Test did not release blocked finder'
                    if isinstance(control.payload, Exception):
                        raise control.payload
                    return control.payload
                finally:
                    control.active -= 1
                    control.returned.set()
        monkeypatch.setattr(module, 'VersionFinder', Finder)
        dialog = module.RecordingVersionsDialog(ORIGINAL, object(), parent)
        controls.append(control)
        dialogs.append(dialog)
        return dialog, control
    yield make
    for control in controls:
        control.gate.set()
    for dialog in dialogs:
        if isValid(dialog):
            dialog.close()
    assert QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    for dialog in dialogs:
        if isValid(dialog):
            dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def ready(dialog):
    dialog.open()
    wait_for(lambda: dialog.state == 'ready')


def test_constructor_does_not_start_search_and_open_is_nonmodal_and_nonblocking(make_dialog, app):
    parent = QWidget()
    parent.resize(300, 200)
    button = QPushButton('Main player remains usable', parent)
    parent.show()
    dialog, control = make_dialog(blocked=True, parent=parent)
    assert dialog.state == 'idle' and not control.calls
    started = time.monotonic()
    dialog.open()
    assert time.monotonic() - started < .5
    wait_for(control.entered.is_set)
    assert not dialog.isModal()
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert QApplication.activeModalWidget() is None
    assert dialog.state == 'loading' and dialog.busy.isVisible()
    clicked = QSignalSpy(button.clicked)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert clicked.count() == 1
    beats = []
    QTimer.singleShot(5, lambda: beats.append(True))
    wait_for(lambda: bool(beats))
    assert control.active == 1 and not dialog.listen_button.isEnabled()
    control.gate.set()
    wait_for(lambda: dialog.state == 'ready')
    parent.close()


def test_open_starts_one_job_only_before_and_after_completion(make_dialog):
    dialog, control = make_dialog(blocked=True)
    for _ in range(4):
        dialog.open()
    wait_for(control.entered.is_set)
    assert len(control.calls) == 1
    control.gate.set()
    wait_for(lambda: dialog.state == 'ready')
    dialog.open()
    assert control.calls == [(ORIGINAL, 12)]
    dialog.close()
    dialog.open()
    assert not dialog.isVisible() and len(control.calls) == 1


def test_results_show_all_metadata_and_false_is_not_a_guarantee(make_dialog):
    dialog, _ = make_dialog()
    emitted = QSignalSpy(dialog.selected)
    ready(dialog)
    assert not dialog.busy.isVisible()
    assert dialog.results.count() == 1
    row = dialog.results.itemWidget(dialog.results.item(0))
    assert row.title.text() == OTHER.title
    assert row.artist.text() == OTHER.artist
    assert row.duration_label.text() == '3:01'
    assert row.version_label.text() == VERSION.label
    assert row.evidence.text() == VERSION.evidence
    assert row.assurance.text() == 'Отсутствие цензуры не проверено'
    assert 'не подтверждает отсутствие цензуры' in dialog.notice.text()
    assert dialog.results.currentRow() == -1
    assert not dialog.listen_button.isEnabled() and emitted.count() == 0


def test_single_click_does_not_select_for_playback_but_listen_emits_snapshot_once(make_dialog):
    dialog, _ = make_dialog()
    emitted = QSignalSpy(dialog.selected)
    ready(dialog)
    point = dialog.results.visualItemRect(dialog.results.item(0)).center()
    QTest.mouseClick(dialog.results.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert dialog.listen_button.isEnabled() and emitted.count() == 0
    QTest.mouseClick(dialog.listen_button, Qt.MouseButton.LeftButton)
    assert emitted.count() == 1 and emitted.at(0) == [ORIGINAL, OTHER]
    assert dialog.state == 'closed'
    dialog._choose(dialog.results.item(0))
    assert emitted.count() == 1


def test_double_click_explicitly_emits_selection(make_dialog):
    dialog, _ = make_dialog()
    emitted = QSignalSpy(dialog.selected)
    ready(dialog)
    point = dialog.results.visualItemRect(dialog.results.item(0)).center()
    QTest.mouseClick(dialog.results.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(dialog.results.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert emitted.count() == 1 and emitted.at(0) == [ORIGINAL, OTHER]


def test_enter_on_list_does_not_implicitly_accept_or_play(make_dialog):
    dialog, _ = make_dialog()
    emitted = QSignalSpy(dialog.selected)
    ready(dialog)
    dialog.results.setCurrentRow(0)
    dialog.results.setFocus()
    QTest.keyClick(dialog.results, Qt.Key.Key_Return)
    assert emitted.count() == 0 and dialog.isVisible() and dialog.state == 'ready'
    dialog.listen_button.setFocus()
    QTest.keyClick(dialog.listen_button, Qt.Key.Key_Return)
    assert emitted.count() == 1


@pytest.mark.parametrize('payload', [[], SourceError('PRIVATE_ERROR_DETAIL')])
def test_empty_and_error_states_offer_explicit_retry_without_automatic_restarts(make_dialog, payload):
    dialog, control = make_dialog(payload)
    dialog.open()
    expected = 'error' if isinstance(payload, Exception) else 'empty'
    wait_for(lambda: dialog.state == expected)
    assert dialog.retry_button.isVisible() and dialog.retry_button.isEnabled()
    assert not dialog.listen_button.isEnabled() and not dialog.busy.isVisible()
    assert 'PRIVATE_ERROR_DETAIL' not in dialog.details.text()
    dialog.open()
    assert len(control.calls) == 1


def test_retry_and_repeated_open_never_overlap_jobs_and_old_token_is_ignored(make_dialog):
    dialog, control = make_dialog(SourceError('offline'))
    dialog.open()
    old = dialog._active_token
    wait_for(lambda: dialog.state == 'error')
    control.payload = [VERSION]
    control.gate.clear()
    QTest.mouseClick(dialog.retry_button, Qt.MouseButton.LeftButton)
    dialog.retry_button.click()
    dialog.open()
    wait_for(lambda: len(control.calls) == 2)
    token = dialog._active_token
    assert token != old and control.peak == 1
    dialog._found(old, [])
    dialog._failed(old, 'late error')
    assert dialog.state == 'loading' and dialog._active_token == token
    control.gate.set()
    wait_for(lambda: dialog.state == 'ready')
    assert len(control.calls) == 2 and control.peak == 1


@pytest.mark.parametrize('payload', [[VERSION], SourceError('late error')])
@pytest.mark.parametrize('close', ['close', 'reject', 'escape'])
def test_close_does_not_wait_and_late_results_or_errors_are_ignored(make_dialog, payload, close):
    dialog, control = make_dialog(payload, blocked=True)
    emitted = QSignalSpy(dialog.selected)
    dialog.open()
    wait_for(control.entered.is_set)
    before = time.monotonic()
    if close == 'escape':
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
    else:
        getattr(dialog, close)()
    assert time.monotonic() - before < .5
    assert dialog.state == 'closed' and not dialog.isVisible()
    control.gate.set()
    wait_for(lambda: not dialog._running)
    assert dialog.state == 'closed' and dialog.results.count() == 0 and emitted.count() == 0


def test_destroying_dialog_while_worker_runs_does_not_access_deleted_widgets(make_dialog, app):
    dialog, control = make_dialog(blocked=True)
    dialog.open()
    wait_for(control.entered.is_set)
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(dialog)
    control.gate.set()
    wait_for(control.returned.is_set)
    assert QThreadPool.globalInstance().waitForDone(1000)
    app.processEvents()


def test_untrusted_metadata_uses_plain_text_and_duplicates_or_current_id_cannot_play(make_dialog):
    marked = RecordingVersion(Track('ccccccccccc', '<b>Песня</b>', 'Слава КПСС', 180),
                               '<b>REMIX</b>', '<a href="https://example.invalid">Evidence</a>')
    dialog, _ = make_dialog([RecordingVersion(ORIGINAL, 'Current', ''), marked, marked, None])
    ready(dialog)
    assert dialog.results.count() == 1
    row = dialog.results.itemWidget(dialog.results.item(0))
    for label in (row.title, row.artist, row.version_label, row.evidence, row.assurance):
        assert label.textFormat() == Qt.TextFormat.PlainText
    assert row.title.text() == '<b>Песня</b>'
    assert row.evidence.text().startswith('<a ')


@pytest.mark.parametrize('width', [540, 760])
def test_long_metadata_wraps_inside_rows_and_controls_fit(make_dialog, app, width):
    long = RecordingVersion(Track('ccccccccccc', 'Песня с длинным названием ' * 8, 'Слава КПСС', 180),
                             'REMIX · «Без цензуры» — заявлено', 'Описание записи и доказательства совпадения. ' * 12)
    dialog, _ = make_dialog([long] * 2)
    dialog.resize(width, 600)
    ready(dialog)
    app.processEvents()
    row = dialog.results.itemWidget(dialog.results.item(0))
    assert row.assurance.geometry().bottom() < row.height()
    for label in (row.title, row.artist, row.evidence, row.assurance):
        assert label.geometry().right() < row.width()
    for button in (dialog.close_button, dialog.listen_button):
        assert dialog.rect().contains(button.geometry())


def test_real_version_finder_is_called_off_gui_thread_without_resolving_audio(app):
    class Source:
        calls = []
        def search(self, query, limit=40, order='relevance'):
            assert QThread.currentThread() != app.thread()
            self.calls.append(query)
            return [ORIGINAL, OTHER]
        def resolve(self, track):
            pytest.fail('dialog must not resolve or play audio')
    source = Source()
    dialog = module.RecordingVersionsDialog(ORIGINAL, source)
    try:
        ready(dialog)
        assert len(source.calls) == 4 and dialog.results.count() == 1
        selected = QSignalSpy(dialog.selected)
        dialog.results.setCurrentRow(0)
        dialog.listen_button.click()
        assert selected.count() == 1
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
