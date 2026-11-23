"""Figma-styled touchscreen ActionButton widget for VitalSense5."""

from __future__ import annotations

from typing import Literal

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QPushButton, QWidget

from vitalsense5.theme import (
    COLORS,
    FONT_FAMILY,
    LAYOUT,
    RADII,
    TYPOGRAPHY,
    action_button_qss,
    font_from_token,
)

ActionButtonVariant = Literal["default", "danger", "success", "save", "recording_active"]


def _recording_active_qss(*, pressed: bool = False) -> str:
    initial_bg = COLORS.BTN_DANGER_PRESSED_BG if pressed else COLORS.ALARM_CRITICAL
    return (
        f"QPushButton {{"
        f" background-color: {initial_bg};"
        f" color: {COLORS.TEXT_PRIMARY};"
        f" border: 2px solid {COLORS.BTN_PRESSED_BG};"
        f" border-radius: {RADII.ACTION_BUTTON}px;"
        f" font-family: '{FONT_FAMILY}';"
        f" font-size: 24px;"
        f" font-weight: 300;"
        f"}}"
        f"QPushButton:pressed, QPushButton[pressed=\"true\"] {{"
        f" background-color: {COLORS.BTN_DANGER_PRESSED_BG};"
        f" color: {COLORS.TEXT_PRIMARY};"
        f"}}"
    )


class ActionButton(QPushButton):
    """212x51 rounded touchscreen action button with Figma pressed states."""

    def __init__(
        self,
        text: str = "",
        *,
        variant: ActionButtonVariant = "default",
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        if object_name is not None:
            self.setObjectName(object_name)

        self._variant: ActionButtonVariant = variant
        self._pressed_visual = False

        self.setFixedSize(LAYOUT.ACTION_BTN_WIDTH, LAYOUT.ACTION_BTN_HEIGHT)
        self.setMinimumHeight(LAYOUT.TOUCH_MIN_TARGET)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFont(font_from_token(TYPOGRAPHY.ACTION_BUTTON))
        self.setProperty("pressed", False)
        self._apply_qss()

    @property
    def variant(self) -> ActionButtonVariant:
        return self._variant

    def set_variant(self, variant: ActionButtonVariant) -> None:
        self._variant = variant
        self._apply_qss()

    def set_pressed_state(self, pressed: bool) -> None:
        new_val = bool(pressed)
        if bool(self._pressed_visual) != new_val or bool(self.property("pressed")) != new_val:
            self._pressed_visual = new_val
            self.setProperty("pressed", new_val)
            self._repolish()

    def set_recording_active(self, active: bool, elapsed_s: int = 0) -> None:
        if active:
            mins = max(0, int(elapsed_s)) // 60
            secs = max(0, int(elapsed_s)) % 60
            self.setText(f"REC {mins:02d}:{secs:02d}")
            self.set_variant("recording_active")
        else:
            self.setText("RECORD")
            self.set_variant("danger")

    def set_recording(self, active: bool, elapsed_s: int = 0) -> None:
        self.set_recording_active(active, elapsed_s)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.set_pressed_state(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.set_pressed_state(False)
        super().mouseReleaseEvent(event)

    def _apply_qss(self) -> None:
        normalized = "success" if self._variant == "save" else self._variant
        if normalized == "recording_active":
            self.setStyleSheet(_recording_active_qss(pressed=self._pressed_visual))
        else:
            self.setStyleSheet(action_button_qss(normalized, pressed=self._pressed_visual))
        self._repolish()

    def _repolish(self) -> None:
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.update()


__all__ = ["ActionButton", "ActionButtonVariant"]
