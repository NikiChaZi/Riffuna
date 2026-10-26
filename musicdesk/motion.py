"""Small, interruptible GUI-only transitions. They never keep a playback clock."""
from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QEvent, QEasingCurve, QObject, QSignalBlocker, QVariantAnimation, Signal


class MotionPolicy(QObject):
    changed = Signal(bool)

    def __init__(self, reduced: bool = False, parent=None):
        super().__init__(parent)
        self._reduced = bool(reduced)

    @property
    def reduced(self) -> bool:
        return self._reduced

    def set_reduced(self, reduced: bool):
        reduced = bool(reduced)
        if self._reduced != reduced:
            self._reduced = reduced
            self.changed.emit(reduced)


class Tween(QObject):
    value_changed = Signal(object)
    settled = Signal()

    def __init__(self, value, policy: MotionPolicy, parent=None):
        super().__init__(parent)
        self.value = value
        self.target = value
        self.policy = policy
        self.animation = QVariantAnimation(self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._changed)
        self.animation.finished.connect(self.settled)
        policy.changed.connect(self._policy_changed)

    @property
    def running(self):
        return self.animation.state() == QAbstractAnimation.State.Running

    def _changed(self, value):
        self.value = value
        self.value_changed.emit(value)

    def to(self, target, duration: int = 180):
        self.animation.stop()
        self.target = target
        if self.policy.reduced or duration <= 0 or target == self.value:
            self.snap(target)
            self.settled.emit()
            return
        start = self.value
        blocker = QSignalBlocker(self.animation)
        self.animation.setStartValue(start)
        self.animation.setEndValue(target)
        self.animation.setDuration(duration)
        self.animation.setCurrentTime(0)
        del blocker
        self.animation.start()

    def snap(self, value):
        self.animation.stop()
        self.target = value
        self._changed(value)

    def finish(self):
        running = self.running
        self.snap(self.target)
        if running:
            self.settled.emit()

    def _policy_changed(self, reduced):
        if reduced:
            self.finish()



class PageFade(QObject):
    """Immediate page selection plus a 160ms reveal; does not delay navigation.

    Attach once per QStackedWidget. A running reveal continues at its current
    opacity on rapid switches. Call detach() before replacing this helper.
    """
    def __init__(self, stack, policy: MotionPolicy, *, duration: int = 160):
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        if stack.graphicsEffect() is not None:
            raise ValueError("PageFade requires a container without an existing graphics effect")
        if not 150 <= duration <= 180:
            raise ValueError("Page fade duration must be between 150 and 180 milliseconds")
        super().__init__(stack)
        self.stack = stack
        self.duration = duration
        self.attached = True
        self.effect = QGraphicsOpacityEffect(stack)
        self.effect.setOpacity(1.0)
        stack.setGraphicsEffect(self.effect)
        self.opacity = Tween(1.0, policy, self)
        self.opacity.value_changed.connect(self.effect.setOpacity)
        stack.currentChanged.connect(self._page_changed)
        stack.installEventFilter(self)

    def _page_changed(self, index):
        self.fade_current()

    def fade_current(self):
        if not self.attached:
            return
        if not self.stack.isVisible() or self.opacity.policy.reduced or self.stack.currentIndex() < 0:
            self.stop()
            return
        if not self.opacity.running:
            self.opacity.snap(0.0)
        self.opacity.to(1.0, self.duration)

    def stop(self):
        if self.attached:
            self.opacity.snap(1.0)

    def detach(self):
        if self.attached:
            self.stop()
            self.stack.currentChanged.disconnect(self._page_changed)
            self.stack.removeEventFilter(self)
            self.stack.setGraphicsEffect(None)
            self.attached = False

    def eventFilter(self, watched, event):
        if watched is self.stack and event.type() == QEvent.Type.Hide:
            self.stop()
        return False
