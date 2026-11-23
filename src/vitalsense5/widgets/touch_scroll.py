"""Touch-friendly drag scroll container with tap-vs-drag discrimination."""

from __future__ import annotations

import math
from typing import Literal

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PyQt6.QtGui import QInputDevice, QMouseEvent, QTouchEvent
from PyQt6.QtWidgets import QAbstractButton, QApplication, QFrame, QLineEdit, QScrollArea, QWidget

from vitalsense5.theme import LAYOUT, scrollbar_qss

_UNSET = object()


class TouchScrollArea(QScrollArea):
    """QScrollArea supporting finger/mouse drag scrolling over interactive children."""

    def __init__(
        self,
        *,
        scrollbar_variant: Literal["patient", "settings"] = "patient",
        variant: Literal["patient", "settings"] | None = None,
        drag_threshold_px: int = LAYOUT.TOUCH_DRAG_THRESHOLD_PX,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        resolved_variant = variant if variant is not None else scrollbar_variant
        self._scrollbar_variant = resolved_variant
        self._drag_threshold_px = max(1, int(drag_threshold_px))

        self._active_source: Literal["mouse", "touch", None] = None
        self._active_touch_id: int | None = None
        self._tracking = False
        self._dragging = False
        self._replaying_event = False
        self._press_global = QPoint()
        self._press_timestamp: int | None = None
        self._press_scroll = 0
        self._pressed_widget: QObject | None = None

        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.verticalScrollBar().setStyleSheet(scrollbar_qss(resolved_variant))

        vp = self.viewport()
        vp.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        vp.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        vp.installEventFilter(self)

    def setWidget(self, widget: QWidget) -> None:  # noqa: N802
        super().setWidget(widget)
        self._install_filters_recursively(widget)

    def refresh_touch_targets(self) -> None:
        content = self.widget()
        if content is not None:
            self._install_filters_recursively(content)

    def _install_filters_recursively(self, obj: QObject) -> None:
        if obj is self.verticalScrollBar():
            return
        if isinstance(obj, QWidget):
            obj.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
            if isinstance(obj, QLineEdit) and bool(obj.focusPolicy() & Qt.FocusPolicy.ClickFocus):
                obj.setProperty("_touch_defer_click_focus", True)
                obj.setFocusPolicy(
                    Qt.FocusPolicy(obj.focusPolicy().value & ~Qt.FocusPolicy.ClickFocus.value)
                )
        obj.removeEventFilter(self)
        obj.installEventFilter(self)
        for child in obj.children():
            self._install_filters_recursively(child)

    def _cancel_pressed_ancestors(self, pressed_widget: object = _UNSET) -> None:
        target = self._pressed_widget if pressed_widget is _UNSET else pressed_widget
        if not isinstance(target, QWidget) or sip.isdeleted(target):
            return
        w: QWidget | None = target
        vp = self.viewport()
        while w is not None and not sip.isdeleted(w) and w is not vp and w is not self:
            if isinstance(w, QAbstractButton):
                w.setDown(False)
                if hasattr(w, "set_pressed_state"):
                    w.set_pressed_state(False)
                elif w.property("pressed") is True:
                    w.setProperty("pressed", False)
                    style = w.style()
                    if style is not None:
                        style.unpolish(w)
                        style.polish(w)
            elif hasattr(w, "cancel_press"):
                w.cancel_press()
            if sip.isdeleted(w):
                break
            parent = w.parentWidget()
            if parent is not None and sip.isdeleted(parent):
                break
            w = parent

    def _scroll_by_delta_y(self, delta_y: int) -> None:
        sb = self.verticalScrollBar()
        target = max(sb.minimum(), min(sb.maximum(), self._press_scroll - delta_y))
        sb.setValue(target)

    def _synthesize_tap(self, target: QWidget, press_global: QPoint) -> None:
        local_pt = target.mapFromGlobal(press_global)
        if target.rect().contains(local_pt):
            local_pos = QPointF(local_pt)
            global_pos = QPointF(press_global)
        else:
            center = target.rect().center()
            local_pos = QPointF(center)
            global_pos = QPointF(target.mapToGlobal(center))

        if target is self.viewport():
            child = target.childAt(local_pos.toPoint())
            if child is not None:
                target = child
                local_pos = QPointF(target.mapFromGlobal(global_pos.toPoint()))

        if not sip.isdeleted(target) and target.isEnabled():
            vp = self.viewport()
            content = self.widget()
            focus_target: QWidget | None = target
            while (
                focus_target is not None
                and not sip.isdeleted(focus_target)
                and focus_target is not vp
                and focus_target is not self
            ):
                if focus_target.isEnabled() and (
                    bool(focus_target.focusPolicy() & Qt.FocusPolicy.ClickFocus)
                    or focus_target.property("_touch_defer_click_focus") is True
                ):
                    focus_target.setFocus(Qt.FocusReason.MouseFocusReason)
                    break
                if focus_target is content:
                    break
                parent = focus_target.parentWidget()
                if parent is not None and sip.isdeleted(parent):
                    break
                focus_target = parent

        if sip.isdeleted(target):
            return

        self._replaying_event = True
        try:
            press_ev = QMouseEvent(
                QEvent.Type.MouseButtonPress,
                local_pos,
                local_pos,
                global_pos,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(target, press_ev)
            if not sip.isdeleted(target):
                release_ev = QMouseEvent(
                    QEvent.Type.MouseButtonRelease,
                    local_pos,
                    local_pos,
                    global_pos,
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                QApplication.sendEvent(target, release_ev)
        finally:
            self._replaying_event = False

    def _reset_tracking_state(self) -> None:
        self._cancel_pressed_ancestors()
        self._active_source = None
        self._active_touch_id = None
        self._tracking = False
        self._dragging = False
        self._press_timestamp = None
        self._pressed_widget = None

    def event(self, ev: QEvent) -> bool:
        if ev.type() in (QEvent.Type.Hide, QEvent.Type.WindowDeactivate):
            self._reset_tracking_state()
        return super().event(ev)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if self._replaying_event:
            return False
        if watched is self.verticalScrollBar():
            return super().eventFilter(watched, event)

        etype = event.type()

        if etype in (QEvent.Type.Hide, QEvent.Type.WindowDeactivate) and watched is self.viewport():
            self._reset_tracking_state()
            return super().eventFilter(watched, event)

        if etype == QEvent.Type.ChildAdded:
            child = event.child()  # type: ignore[attr-defined]
            if isinstance(child, QObject):
                self._install_filters_recursively(child)
            return False

        if etype == QEvent.Type.TouchBegin and isinstance(event, QTouchEvent):
            points = event.points()
            if not points:
                return False
            if (
                self._active_source == "mouse"
                and not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton)
            ):
                self._reset_tracking_state()
            if self._active_source is None:
                pt = points[0]
                self._active_source = "touch"
                self._active_touch_id = pt.id()
                self._tracking = True
                self._dragging = False
                self._press_global = pt.globalPosition().toPoint()
                self._press_scroll = self.verticalScrollBar().value()
                self._pressed_widget = watched
            event.accept()
            return True

        if etype == QEvent.Type.TouchUpdate and isinstance(event, QTouchEvent):
            if self._active_source != "touch" or not self._tracking:
                return False
            tracked = None
            for pt in event.points():
                if pt.id() == self._active_touch_id:
                    tracked = pt
                    break
            if tracked is None:
                event.accept()
                return True
            cur = tracked.globalPosition().toPoint()
            dx = cur.x() - self._press_global.x()
            dy = cur.y() - self._press_global.y()
            if not self._dragging and math.hypot(dx, dy) >= self._drag_threshold_px:
                self._dragging = True
                self._cancel_pressed_ancestors()
            if self._dragging:
                self._scroll_by_delta_y(dy)
            event.accept()
            return True

        if etype in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel) and isinstance(event, QTouchEvent):
            if self._active_source != "touch":
                return False
            was_dragging = self._dragging
            pressed_widget = self._pressed_widget
            press_global = self._press_global
            self._active_source = None
            self._active_touch_id = None
            self._tracking = False
            self._dragging = False
            self._press_timestamp = None
            self._pressed_widget = None
            if was_dragging or etype == QEvent.Type.TouchCancel:
                self._cancel_pressed_ancestors(pressed_widget)
            if (
                etype == QEvent.Type.TouchEnd
                and not was_dragging
                and isinstance(pressed_widget, QWidget)
                and not sip.isdeleted(pressed_widget)
            ):
                self._synthesize_tap(pressed_widget, press_global)
            event.accept()
            return True

        if etype == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                if (
                    self._active_source == "touch"
                    and event.deviceType() != QInputDevice.DeviceType.Mouse
                ):
                    return False
                if (
                    self._tracking
                    and self._active_source == "mouse"
                    and not isinstance(self._pressed_widget, QLineEdit)
                    and self._press_timestamp == event.timestamp()
                    and self._press_global == event.globalPosition().toPoint()
                    and isinstance(self._pressed_widget, QWidget)
                    and not sip.isdeleted(self._pressed_widget)
                    and isinstance(watched, QWidget)
                    and watched.isAncestorOf(self._pressed_widget)
                ):
                    return False
                if self._tracking:
                    self._reset_tracking_state()
                self._active_source = "mouse"
                self._active_touch_id = None
                self._tracking = True
                self._dragging = False
                self._press_global = event.globalPosition().toPoint()
                self._press_timestamp = event.timestamp()
                self._press_scroll = self.verticalScrollBar().value()
                self._pressed_widget = watched
                if isinstance(watched, QLineEdit):
                    return True
            return False

        if etype == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            if (
                self._active_source == "touch"
                and event.deviceType() != QInputDevice.DeviceType.Mouse
            ):
                return False
            if self._active_source != "mouse" or not self._tracking:
                return False
            cur = event.globalPosition().toPoint()
            dx = cur.x() - self._press_global.x()
            dy = cur.y() - self._press_global.y()
            if not self._dragging and math.hypot(dx, dy) >= self._drag_threshold_px:
                self._dragging = True
                self._cancel_pressed_ancestors()
            if self._dragging:
                self._scroll_by_delta_y(dy)
                return True
            return False

        if etype == QEvent.Type.MouseButtonRelease and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                if (
                    self._active_source == "touch"
                    and event.deviceType() != QInputDevice.DeviceType.Mouse
                ):
                    return False
                if self._active_source == "mouse" and self._tracking:
                    was_dragging = self._dragging
                    pressed_widget = self._pressed_widget
                    press_global = self._press_global
                    self._active_source = None
                    self._active_touch_id = None
                    self._tracking = False
                    self._dragging = False
                    self._press_timestamp = None
                    self._pressed_widget = None
                    if was_dragging:
                        self._cancel_pressed_ancestors(pressed_widget)
                        return True
                    if (
                        isinstance(pressed_widget, QLineEdit)
                        and not sip.isdeleted(pressed_widget)
                        and pressed_widget.isEnabled()
                    ):
                        self._synthesize_tap(pressed_widget, press_global)
                        return True
                    return False
            return False

        return super().eventFilter(watched, event)


__all__ = ["TouchScrollArea"]
