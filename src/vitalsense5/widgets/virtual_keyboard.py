"""On-screen touchscreen virtual keyboard and numpad overlay for VitalSense5."""

from __future__ import annotations

from typing import Literal

from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtProperty, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from vitalsense5.theme import COLORS, FONT_FAMILY, LAYOUT, jetbrains_mono_font

KeyboardMode = Literal["qwerty", "numpad"]


def _key_qss(
    *,
    bg: str = COLORS.INPUT_BG,
    fg: str = COLORS.TEXT_PRIMARY,
    pressed_bg: str = COLORS.BTN_PRESSED_BG,
    pressed_fg: str = COLORS.BTN_PRESSED_TEXT,
    border: str = "1px solid #B5B5B5",
    font_size_px: int = 20,
) -> str:
    return (
        f"QPushButton {{"
        f" background-color: {bg};"
        f" color: {fg};"
        f" border: {border};"
        f" border-radius: 8px;"
        f" font-family: '{FONT_FAMILY}';"
        f" font-size: {font_size_px}px;"
        f" font-weight: 500;"
        f"}}"
        f"QPushButton:pressed {{"
        f" background-color: {pressed_bg};"
        f" color: {pressed_fg};"
        f"}}"
        f"QPushButton:disabled {{"
        f" background-color: #E0E0E0;"
        f" color: #9E9E9E;"
        f"}}"
    )


class VirtualKeyboardOverlay(QFrame):
    """1280x280 touchscreen virtual keyboard supporting QWERTY and Numpad modes."""

    keyboard_shown = pyqtSignal(int)
    keyboard_hidden = pyqtSignal()
    done_clicked = pyqtSignal()
    mode_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("virtual_keyboard_overlay")
        self.setFixedHeight(280)
        self.setMinimumWidth(600)
        self.resize(LAYOUT.WINDOW_WIDTH, 280)
        self.setStyleSheet(
            f"#virtual_keyboard_overlay {{"
            f" background-color: {COLORS.SURFACE_CARD};"
            f" border-top: 2px solid #838383;"
            f"}}"
        )

        self._mode: KeyboardMode = "qwerty"
        self._shift_active = False
        self._allow_decimal = True
        self._allow_mode_switch = True
        self._target: QLineEdit | None = None
        self._letter_buttons: list[tuple[QPushButton, str]] = []

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 4, 10, 6)
        root_layout.setSpacing(4)

        self.lbl_keyboard_mode = QLabel("KEYBOARD — QWERTY", self)
        self.lbl_keyboard_mode.setObjectName("lbl_keyboard_mode")
        self.lbl_keyboard_mode.setFont(jetbrains_mono_font(size_px=12, weight=500))
        self.lbl_keyboard_mode.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
        self.lbl_keyboard_mode.setFixedHeight(18)
        root_layout.addWidget(self.lbl_keyboard_mode)

        self._stack = QStackedWidget(self)
        self._stack.setObjectName("virtual_keyboard_stack")
        self._stack.setStyleSheet("#virtual_keyboard_stack { background: transparent; border: none; }")
        root_layout.addWidget(self._stack, 1)

        self._qwerty_page = self._build_qwerty_page()
        self._numpad_page = self._build_numpad_page()
        self._stack.addWidget(self._qwerty_page)
        self._stack.addWidget(self._numpad_page)

        self.set_mode("qwerty")

    @pyqtProperty(str)
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if value in ("qwerty", "numpad"):
            self.set_mode(value)  # type: ignore[arg-type]

    def target(self) -> QLineEdit | None:
        if self._target is not None and sip.isdeleted(self._target):
            self._target = None
        return self._target

    def is_shifted(self) -> bool:
        return self._shift_active

    def attach_target(
        self,
        target: QLineEdit,
        *,
        mode: KeyboardMode = "qwerty",
        allow_decimal: bool = True,
        allow_mode_switch: bool = True,
    ) -> None:
        old_target = self._target
        if old_target is not None and old_target is not target:
            if not sip.isdeleted(old_target):
                try:
                    old_target.destroyed.disconnect(self._on_target_destroyed)
                except (TypeError, RuntimeError):
                    pass
            if self._shift_active:
                self._toggle_shift()
        self._target = target
        try:
            target.destroyed.disconnect(self._on_target_destroyed)
        except (TypeError, RuntimeError):
            pass
        target.destroyed.connect(self._on_target_destroyed)
        self._allow_decimal = bool(allow_decimal)
        self._allow_mode_switch = bool(allow_mode_switch)

        self._btn_numpad_decimal.setEnabled(self._allow_decimal)
        self._btn_to_numpad.setEnabled(self._allow_mode_switch)
        self._btn_to_qwerty.setEnabled(self._allow_mode_switch)

        self.set_mode(mode)
        self.show()
        self.raise_()
        self.keyboard_shown.emit(self.height())

    def _on_target_destroyed(self, _obj: object = None) -> None:
        self._target = None

    def set_mode(self, mode: KeyboardMode) -> None:
        if mode not in ("qwerty", "numpad"):
            raise ValueError(f"Unsupported keyboard mode: {mode!r}")
        changed = self._mode != mode
        self._mode = mode
        if mode == "qwerty":
            self._stack.setCurrentWidget(self._qwerty_page)
            self.lbl_keyboard_mode.setText("KEYBOARD — QWERTY")
        else:
            self._stack.setCurrentWidget(self._numpad_page)
            self.lbl_keyboard_mode.setText("KEYBOARD — NUMPAD")
        if changed:
            self.mode_changed.emit(mode)

    def hide_keyboard(self) -> None:
        was_visible = self.isVisible()
        self.hide()
        if was_visible:
            target = self.target()
            if target is not None and target.hasFocus():
                target.clearFocus()
            self.keyboard_hidden.emit()

    def _make_key(
        self,
        label: str,
        *,
        height: int = 44,
        qss: str | None = None,
    ) -> QPushButton:
        btn = QPushButton(label, self)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setMinimumHeight(height)
        btn.setMaximumHeight(height)
        btn.setStyleSheet(qss if qss is not None else _key_qss())
        return btn

    def _build_qwerty_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("qwerty_page")
        page.setStyleSheet("#qwerty_page { background: transparent; border: none; }")
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)

        # Row 1: digits 1-0
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        for digit in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0"):
            btn = self._make_key(digit, height=44)
            btn.clicked.connect(lambda _=False, ch=digit: self._insert_text(ch))
            row1.addWidget(btn, 1)
        vbox.addLayout(row1)

        # Row 2: q-p
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        for ch in ("q", "w", "e", "r", "t", "y", "u", "i", "o", "p"):
            btn = self._make_key(ch, height=44)
            self._letter_buttons.append((btn, ch))
            btn.clicked.connect(lambda _=False, b=btn: self._insert_text(b.text()))
            row2.addWidget(btn, 1)
        vbox.addLayout(row2)

        # Row 3: a-l
        row3 = QHBoxLayout()
        row3.setSpacing(6)
        row3.addStretch(1)
        for ch in ("a", "s", "d", "f", "g", "h", "j", "k", "l"):
            btn = self._make_key(ch, height=44)
            self._letter_buttons.append((btn, ch))
            btn.clicked.connect(lambda _=False, b=btn: self._insert_text(b.text()))
            row3.addWidget(btn, 2)
        row3.addStretch(1)
        vbox.addLayout(row3)

        # Row 4: SHIFT, z-m, BACKSPACE
        row4 = QHBoxLayout()
        row4.setSpacing(6)
        self._btn_shift = self._make_key("SHIFT", height=44, qss=_key_qss(bg="#E9E9E9", font_size_px=16))
        self._btn_shift.clicked.connect(self._toggle_shift)
        row4.addWidget(self._btn_shift, 3)

        for ch in ("z", "x", "c", "v", "b", "n", "m"):
            btn = self._make_key(ch, height=44)
            self._letter_buttons.append((btn, ch))
            btn.clicked.connect(lambda _=False, b=btn: self._insert_text(b.text()))
            row4.addWidget(btn, 2)

        btn_bksp = self._make_key(
            "BACKSPACE",
            height=44,
            qss=_key_qss(bg="#FFB3B3", pressed_bg=COLORS.BTN_DANGER_PRESSED_BG, pressed_fg=COLORS.TEXT_PRIMARY, font_size_px=16),
        )
        btn_bksp.clicked.connect(self._backspace)
        row4.addWidget(btn_bksp, 3)
        vbox.addLayout(row4)

        # Row 5: 123, CLEAR, SPACE, ., DONE
        row5 = QHBoxLayout()
        row5.setSpacing(6)
        self._btn_to_numpad = self._make_key("123", height=44, qss=_key_qss(bg="#E9E9E9", font_size_px=18))
        self._btn_to_numpad.clicked.connect(self._switch_to_numpad)
        row5.addWidget(self._btn_to_numpad, 2)

        btn_clear = self._make_key(
            "CLEAR",
            height=44,
            qss=_key_qss(bg="#E9E9E9", font_size_px=16),
        )
        btn_clear.clicked.connect(self._clear_target)
        row5.addWidget(btn_clear, 2)

        btn_space = self._make_key("SPACE", height=44, qss=_key_qss(font_size_px=16))
        btn_space.clicked.connect(lambda _=False: self._insert_text(" "))
        row5.addWidget(btn_space, 7)

        btn_dot = self._make_key(".", height=44)
        btn_dot.clicked.connect(lambda _=False: self._insert_text("."))
        row5.addWidget(btn_dot, 1)

        btn_done = self._make_key(
            "DONE",
            height=44,
            qss=_key_qss(
                bg=COLORS.BTN_SUCCESS_BG,
                pressed_bg=COLORS.BTN_SUCCESS_PRESSED_BG,
                pressed_fg=COLORS.TEXT_PRIMARY,
                font_size_px=18,
            ),
        )
        btn_done.clicked.connect(self._finish)
        row5.addWidget(btn_done, 3)
        vbox.addLayout(row5)

        return page

    def _build_numpad_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("numpad_page")
        page.setStyleSheet("#numpad_page { background: transparent; border: none; }")
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        grid_host = QWidget(page)
        grid_host.setObjectName("numpad_grid_host")
        grid_host.setStyleSheet("#numpad_grid_host { background: transparent; border: none; }")
        grid_host.setFixedWidth(720)
        vbox = QVBoxLayout(grid_host)
        vbox.setContentsMargins(0, 2, 0, 2)
        vbox.setSpacing(6)

        # Row 1: 1 2 3 BACKSPACE
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        for d in ("1", "2", "3"):
            btn = self._make_key(d, height=52, qss=_key_qss(font_size_px=22))
            btn.clicked.connect(lambda _=False, ch=d: self._insert_text(ch))
            r1.addWidget(btn, 1)
        btn_bksp = self._make_key(
            "BACKSPACE",
            height=52,
            qss=_key_qss(bg="#FFB3B3", pressed_bg=COLORS.BTN_DANGER_PRESSED_BG, pressed_fg=COLORS.TEXT_PRIMARY, font_size_px=17),
        )
        btn_bksp.clicked.connect(self._backspace)
        r1.addWidget(btn_bksp, 1)
        vbox.addLayout(r1)

        # Row 2: 4 5 6 CLEAR
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        for d in ("4", "5", "6"):
            btn = self._make_key(d, height=52, qss=_key_qss(font_size_px=22))
            btn.clicked.connect(lambda _=False, ch=d: self._insert_text(ch))
            r2.addWidget(btn, 1)
        btn_clr = self._make_key("CLEAR", height=52, qss=_key_qss(bg="#E9E9E9", font_size_px=17))
        btn_clr.clicked.connect(self._clear_target)
        r2.addWidget(btn_clr, 1)
        vbox.addLayout(r2)

        # Row 3: 7 8 9 .
        r3 = QHBoxLayout()
        r3.setSpacing(8)
        for d in ("7", "8", "9"):
            btn = self._make_key(d, height=52, qss=_key_qss(font_size_px=22))
            btn.clicked.connect(lambda _=False, ch=d: self._insert_text(ch))
            r3.addWidget(btn, 1)
        self._btn_numpad_decimal = self._make_key(".", height=52, qss=_key_qss(font_size_px=22))
        self._btn_numpad_decimal.clicked.connect(lambda _=False: self._insert_text("."))
        r3.addWidget(self._btn_numpad_decimal, 1)
        vbox.addLayout(r3)

        # Row 4: ABC 0 DONE
        r4 = QHBoxLayout()
        r4.setSpacing(8)
        self._btn_to_qwerty = self._make_key("ABC", height=52, qss=_key_qss(bg="#E9E9E9", font_size_px=18))
        self._btn_to_qwerty.clicked.connect(self._switch_to_qwerty)
        r4.addWidget(self._btn_to_qwerty, 1)

        btn_zero = self._make_key("0", height=52, qss=_key_qss(font_size_px=22))
        btn_zero.clicked.connect(lambda _=False: self._insert_text("0"))
        r4.addWidget(btn_zero, 1)

        btn_done = self._make_key(
            "DONE",
            height=52,
            qss=_key_qss(
                bg=COLORS.BTN_SUCCESS_BG,
                pressed_bg=COLORS.BTN_SUCCESS_PRESSED_BG,
                pressed_fg=COLORS.TEXT_PRIMARY,
                font_size_px=18,
            ),
        )
        btn_done.clicked.connect(self._finish)
        r4.addWidget(btn_done, 2)
        vbox.addLayout(r4)

        outer.addWidget(grid_host)
        outer.addStretch(1)
        return page

    def _toggle_shift(self) -> None:
        self._shift_active = not self._shift_active
        for btn, base_ch in self._letter_buttons:
            btn.setText(base_ch.upper() if self._shift_active else base_ch.lower())
        if self._shift_active:
            self._btn_shift.setStyleSheet(
                _key_qss(
                    bg=COLORS.BRAND_BLUE,
                    fg="#FFFFFF",
                    pressed_bg=COLORS.BTN_PRESSED_BG,
                    pressed_fg=COLORS.BTN_PRESSED_TEXT,
                    border=f"2px solid {COLORS.BRAND_BLUE}",
                    font_size_px=16,
                )
            )
        else:
            self._btn_shift.setStyleSheet(_key_qss(bg="#E9E9E9", font_size_px=16))

    def _switch_to_numpad(self) -> None:
        if self._allow_mode_switch:
            self.set_mode("numpad")

    def _switch_to_qwerty(self) -> None:
        if self._allow_mode_switch:
            self.set_mode("qwerty")

    def _insert_text(self, text: str) -> None:
        if self._target is None or sip.isdeleted(self._target):
            self._target = None
            return
        self._target.insert(text)

    def _backspace(self) -> None:
        if self._target is None or sip.isdeleted(self._target):
            self._target = None
            return
        self._target.backspace()

    def _clear_target(self) -> None:
        if self._target is None or sip.isdeleted(self._target):
            self._target = None
            return
        self._target.clear()

    def _finish(self) -> None:
        self.hide_keyboard()
        self.done_clicked.emit()


__all__ = ["KeyboardMode", "VirtualKeyboardOverlay"]
