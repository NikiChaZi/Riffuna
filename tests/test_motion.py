import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF
from PySide6.QtTest import QSignalSpy, QTest
from test_ui_search import app

from musicdesk.motion import MotionPolicy, Tween


def test_interruption_restarts_from_current_value(app):
    policy = MotionPolicy()
    tween = Tween(0.0, policy)
    tween.to(100.0, 300)
    QTest.qWait(70)
    current = tween.value
    assert 0 < current < 100
    tween.to(-10.0, 200)
    assert tween.animation.startValue() == current
    tween.finish()
    assert tween.value == -10.0
    assert not tween.running


def test_reduced_motion_finishes_all_channels_and_uses_no_timer(app):
    policy = MotionPolicy()
    opacity = Tween(0.0, policy)
    geometry = Tween(QRectF(0, 0, 56, 56), policy)
    target = QRectF(300, 200, 320, 320)
    opacity.to(1.0, 300)
    geometry.to(target, 300)
    policy.set_reduced(True)
    assert opacity.value == 1.0 and geometry.value == target
    assert not opacity.running and not geometry.running
    geometry.to(QRectF(1, 2, 3, 4))
    assert geometry.value == QRectF(1, 2, 3, 4)
    assert not geometry.running


def test_finishing_is_not_a_second_animation_completion(app):
    tween = Tween(0.0, MotionPolicy(True))
    completions = QSignalSpy(tween.settled)
    tween.to(1.0)
    assert completions.count() == 1
    tween.finish()
    tween.finish()
    assert completions.count() == 1



def test_page_fade_selects_immediately_and_interrupts_at_current_opacity(app):
    from PySide6.QtWidgets import QStackedWidget, QWidget
    from musicdesk.motion import PageFade

    stack = QStackedWidget()
    pages = [QWidget() for _ in range(3)]
    for page in pages:
        stack.addWidget(page)
    stack.resize(400, 240)
    stack.show()
    app.processEvents()
    fade = PageFade(stack, MotionPolicy())
    try:
        stack.setCurrentIndex(1)
        assert stack.currentWidget() is pages[1]
        assert fade.opacity.running
        assert fade.opacity.animation.duration() == 160
        QTest.qWait(35)
        previous_opacity = fade.opacity.value
        assert 0 < previous_opacity < 1
        stack.setCurrentIndex(2)
        assert stack.currentWidget() is pages[2]
        assert fade.opacity.animation.startValue() == previous_opacity
        fade.opacity.finish()
        assert fade.effect.opacity() == 1.0
    finally:
        fade.detach()
        stack.close()


def test_page_fade_reduced_hidden_and_detached_states_are_opaque(app):
    from PySide6.QtWidgets import QStackedWidget, QWidget
    from musicdesk.motion import PageFade

    stack = QStackedWidget()
    stack.addWidget(QWidget())
    stack.addWidget(QWidget())
    policy = MotionPolicy()
    fade = PageFade(stack, policy)
    stack.setCurrentIndex(1)
    assert not fade.opacity.running and fade.effect.opacity() == 1.0
    stack.show()
    app.processEvents()
    stack.setCurrentIndex(0)
    assert fade.opacity.running
    policy.set_reduced(True)
    assert not fade.opacity.running and fade.effect.opacity() == 1.0
    stack.setCurrentIndex(1)
    assert not fade.opacity.running and fade.effect.opacity() == 1.0
    policy.set_reduced(False)
    stack.setCurrentIndex(0)
    assert fade.opacity.running
    stack.hide()
    assert not fade.opacity.running and fade.effect.opacity() == 1.0
    fade.detach()
    fade.detach()
    assert stack.graphicsEffect() is None
    stack.setCurrentIndex(1)
    assert not fade.opacity.running
    stack.close()


def test_page_fade_does_not_replace_an_existing_effect(app):
    import pytest
    from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget
    from musicdesk.motion import PageFade

    stack = QStackedWidget()
    effect = QGraphicsOpacityEffect(stack)
    stack.setGraphicsEffect(effect)
    with pytest.raises(ValueError):
        PageFade(stack, MotionPolicy())
    assert stack.graphicsEffect() is effect
    stack.close()
