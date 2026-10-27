"""Event-driven surface feedback. No effects, layout scaling or idle timers."""
from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget
from shiboken6 import isValid

from .motion import MotionPolicy, Tween


class _FeedbackOverlay(QWidget):
    def __init__(self, button, motion):
        super().__init__(button)
        self._motion_ref = weakref.ref(motion)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(button.rect())

    def paintEvent(self, event):
        motion = self._motion_ref()
        if motion is None or not getattr(motion, '_ready', False):
            return
        hover = float(motion.hover.value)
        press = float(motion.press.value)
        if hover <= 0 and press <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = min(12, self.height() / 2 - 1)
        painter.setPen(QPen(QColor(255, 213, 191, round(48 * hover)), 1))
        painter.setBrush(QColor(255, 239, 222, round(7 * hover + 13 * press)))
        painter.drawRoundedRect(rect, radius, radius)


class SurfaceMotion(QObject):
    """Attach to a button; interruption starts from the current visual value.

    If policy is omitted, discover window.motion_policy on the first interaction.
    Reuse the existing shared policy; changing reduced motion settles immediately.
    """
    def __init__(self, button: QAbstractButton, policy=None):
        super().__init__(button)
        self._button_ref = weakref.ref(button)
        self.policy = MotionPolicy(parent=self)
        self._shared_policy = None
        self.hover = Tween(0.0, self.policy, self)
        self.press = Tween(0.0, self.policy, self)
        self.overlay = _FeedbackOverlay(button, self)
        self.hover.value_changed.connect(self._changed)
        self.press.value_changed.connect(self._changed)
        self._inside = False
        self._focused = False
        self._explicit_policy = policy
        self._sync_policy()
        self._ready = True
        button.installEventFilter(self)

    @property
    def button(self):
        return self._button_ref()

    def _sync_policy(self):
        button = self.button
        if button is None or not isValid(button):
            return
        shared = self._explicit_policy or getattr(button.window(), 'motion_policy', None)
        if shared is not None and shared is not self._shared_policy:
            if self._shared_policy is not None:
                self._shared_policy.changed.disconnect(self.policy.set_reduced)
            self._shared_policy = shared
            shared.changed.connect(self.policy.set_reduced)
            self.policy.set_reduced(shared.reduced)

    def set_policy(self, policy):
        self._explicit_policy = policy
        self._sync_policy()

    def _changed(self, value):
        if not getattr(self, '_ready', False) or not isValid(self.overlay):
            return
        self.overlay.update()
        # Cover tiles use the same channel for their painted play affordance.
        callback = getattr(self.button, '_surface_progress', None)
        if callback:
            callback(float(self.hover.value), float(self.press.value))

    def eventFilter(self, watched, event):
        # Python GC can clear the wrapper before Qt emits its final Hide events.
        # Never touch child wrappers while that parent is being dismantled.
        if not getattr(self, '_ready', False) or not hasattr(self, 'hover') or not isValid(self.hover):
            return False
        kind = event.type()
        if kind == QEvent.Type.Resize:
            self.overlay.setGeometry(self.button.rect())
        elif kind == QEvent.Type.Show:
            self.overlay.raise_()
            self.overlay.show()
        elif kind in (QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self._sync_policy()
            if kind == QEvent.Type.Enter:
                self._inside = True
            elif kind == QEvent.Type.Leave:
                self._inside = False
            elif kind == QEvent.Type.FocusIn:
                self._focused = True
            else:
                self._focused = False
            target = 1.0 if self.button.isEnabled() and (self._inside or self._focused) else 0.0
            self.hover.to(target, 150 if target else 120)
        elif kind in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            is_press = (kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton
                        or kind == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return))
            if is_press and self.button.isEnabled():
                self._sync_policy()
                self.press.to(1.0, 75)
        elif kind in (QEvent.Type.MouseButtonRelease, QEvent.Type.KeyRelease):
            self.press.to(0.0, 120)
        elif kind in (QEvent.Type.Hide, QEvent.Type.EnabledChange):
            self._inside = self._focused = False
            self.hover.snap(0.0)
            self.press.snap(0.0)
        return False


def attach_surface_motion(button, policy=None):
    motion = getattr(button, '_surface_motion', None)
    if motion is None:
        motion = button._surface_motion = SurfaceMotion(button, policy)
    elif policy is not None:
        motion.set_policy(policy)
    return motion


def install_surface_motion(root, policy=None):
    """Idempotent parent integration for navigation and ordinary action buttons."""
    buttons = root.findChildren(QAbstractButton)
    if isinstance(root, QAbstractButton):
        buttons.insert(0, root)
    return [attach_surface_motion(button, policy) for button in buttons]
