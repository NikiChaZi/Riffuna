"""Offline pointer controls: geometry, one seek per gesture and preview."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QHelpEvent, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QToolTip

from musicdesk.models import time_label
from musicdesk.style import STYLE
from musicdesk.widgets import PointerSlider


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    return application


@pytest.fixture
def slider(app):
    control = PointerSlider(formatter=lambda value: time_label(value // 1000))
    control.setRange(0, 180000)
    control.resize(410, 30)
    control.show()
    app.processEvents()
    yield control
    control.close()
    control.deleteLater()


def test_click_seeks_to_exact_pointer_and_endpoints(slider):
    commits = QSignalSpy(slider.committed)
    releases = QSignalSpy(slider.sliderReleased)
    for point, expected in [(QPoint(0, 15), 0), (QPoint(409, 15), 180000), (QPoint(205, 15), 90000)]:
        QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=point)
        assert abs(slider.value() - expected) <= 500
    assert commits.count() == releases.count() == 3


def test_drag_changes_preview_but_commits_only_on_release(slider):
    commits = QSignalSpy(slider.committed)
    moved = QSignalSpy(slider.sliderMoved)
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(90, 15))
    QTest.mouseMove(slider, QPoint(180, 15))
    QTest.mouseMove(slider, QPoint(300, 15))
    assert slider.isSliderDown()
    assert commits.count() == 0
    assert moved.count() >= 2
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(300, 15))
    assert not slider.isSliderDown()
    assert commits.count() == 1
    assert commits.at(0)[0] == slider.value()
    assert slider.value() > 120000


def test_hover_uses_pointer_time_without_seeking(slider, app):
    slider.setValue(12000)
    commits = QSignalSpy(slider.committed)
    point = QPoint(205, 15)
    event = QHelpEvent(QEvent.Type.ToolTip, point, slider.mapToGlobal(point))
    app.sendEvent(slider, event)
    assert QToolTip.text() == "1:30"
    assert slider.value() == 12000
    assert commits.count() == 0


def test_volume_updates_immediately_and_hover_has_percent(slider, app):
    slider.setRange(0, 100)
    slider.formatter = lambda value: f"{value}%"
    values = QSignalSpy(slider.valueChanged)
    commits = QSignalSpy(slider.committed)
    point = QPoint(305, 15)
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=point)
    assert 74 <= slider.value() <= 76
    assert values.count() == 1
    assert commits.count() == 0
    app.sendEvent(slider, QHelpEvent(QEvent.Type.ToolTip, point, slider.mapToGlobal(point)))
    assert QToolTip.text() == "75%"
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=point)
    assert commits.count() == 1


def test_keyboard_and_wheel_commit_but_programmatic_progress_does_not(slider, app):
    slider.setSingleStep(1000)
    commits = QSignalSpy(slider.committed)
    slider.setValue(10000)
    assert commits.count() == 0
    QTest.keyClick(slider, Qt.Key.Key_Right)
    assert slider.value() == 11000
    assert commits.count() == 1
    QTest.keyClick(slider, Qt.Key.Key_End)
    assert slider.value() == 180000
    assert commits.count() == 2
    point = QPointF(200, 15)
    wheel = QWheelEvent(point, slider.mapToGlobal(point.toPoint()), QPoint(), QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(slider, wheel)
    assert slider.value() < 180000
    assert commits.count() == 3


def test_rtl_pointer_mapping_follows_native_slider_direction(slider):
    slider.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    assert slider.value_at(QPoint(0, 15)) == slider.maximum()
    assert slider.value_at(QPoint(409, 15)) == slider.minimum()
