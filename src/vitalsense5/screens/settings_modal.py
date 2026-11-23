"""Non-blocking 669x437 Settings modal overlay for SETTINGS 1..8."""

from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vitalsense5.contracts import SettingControlType, SettingSlot, SettingsPort
from vitalsense5.theme import (
    BORDERS,
    COLORS,
    FONT_FAMILY,
    LAYOUT,
    RADII,
    TYPOGRAPHY,
    apply_input_placeholder_palette,
    font_from_token,
    get_icon_path,
    jetbrains_mono_font,
    modal_card_qss,
    settings_pill_qss,
)
from vitalsense5.widgets import TouchScrollArea


class _SettingsToggleButton(QPushButton):
    """Touch-sized (>=44px) Figma ON/OFF toggle pill returning 'ON'/'OFF' via text()."""

    def __init__(self, slot_index: int, checked: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(f"settings_toggle_{slot_index}")
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(84, 44)
        self.setChecked(bool(checked))
        self.setText("ON" if checked else "OFF")
        self.toggled.connect(self._sync_text)

    def _sync_text(self, checked: bool) -> None:
        self.setText("ON" if checked else "OFF")
        self.update()

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pill_w = float(LAYOUT.SETTINGS_TOGGLE_WIDTH)
        pill_h = float(LAYOUT.SETTINGS_PILL_HEIGHT)
        y_off = (float(self.height()) - pill_h) / 2.0
        radius = pill_h / 2.0

        checked = self.isChecked()
        track_color = QColor(COLORS.TOGGLE_ON if checked else COLORS.TOGGLE_OFF)

        # Pill track
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(QRectF(0.0, y_off, pill_w, pill_h), radius, radius)

        # White knob (46x31)
        knob_w = 46.0
        knob_x = pill_w - knob_w if checked else 0.0
        painter.setBrush(QColor(COLORS.TOGGLE_KNOB))
        painter.drawRoundedRect(QRectF(knob_x, y_off, knob_w, pill_h), radius, radius)

        # ON / OFF label on opposite side of knob
        painter.setPen(QColor(COLORS.TEXT_PRIMARY))
        painter.setFont(font_from_token(TYPOGRAPHY.SETTINGS_CONTROL))
        if checked:
            text_rect = QRectF(0.0, y_off, pill_w - knob_w, pill_h)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "ON")
        else:
            text_rect = QRectF(knob_w, y_off, pill_w - knob_w, pill_h)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "OFF")

        painter.end()


def _dropdown_arrow_icon() -> QIcon:
    renderer = QSvgRenderer(str(get_icon_path("dropdown_arrow.svg")))
    pm = QPixmap(12, 11)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter, QRectF(0, 0, 12, 11))
    painter.end()
    return QIcon(pm)


class SettingsModal(QFrame):
    """669x437 Settings modal overlay with 8 scrollable generic slots."""

    closed = pyqtSignal()
    setting_changed = pyqtSignal(int, object)
    inputs_rebuilt = pyqtSignal()

    def __init__(
        self,
        *,
        settings_store: SettingsPort,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_store = settings_store
        self._toggle_buttons: dict[int, _SettingsToggleButton] = {}
        self._value_edits: dict[int, QLineEdit] = {}
        self._last_valid_values: dict[int, str] = {}
        self._unpersisted_value_slots: set[int] = set()
        self._dropdown_buttons: dict[int, QPushButton] = {}
        self._dropdown_slots: dict[int, SettingSlot] = {}
        self._active_dropdown_slot: int | None = None
        self._row_widgets: list[QWidget] = []

        self.setObjectName("settings_modal")
        self.setFixedSize(LAYOUT.SETTINGS_MODAL_WIDTH, LAYOUT.SETTINGS_MODAL_HEIGHT)
        self.setStyleSheet(
            modal_card_qss(
                radius=RADII.MODAL_CARD,
                background=COLORS.SURFACE_CARD,
                selector="#settings_modal",
            )
        )

        # Header strip (0, 0, 669, 54) keeping DONE completely above scroll rows
        self._header = QWidget(self)
        self._header.setObjectName("settings_modal_header")
        self._header.setGeometry(0, 0, LAYOUT.SETTINGS_MODAL_WIDTH, 54)
        self._header.setStyleSheet(
            "#settings_modal_header { background-color: transparent; border: none; }"
        )

        self.lbl_settings_title = QLabel("SETTINGS", self._header)
        self.lbl_settings_title.setObjectName("lbl_settings_title")
        self.lbl_settings_title.setFont(font_from_token(TYPOGRAPHY.SETTINGS_TITLE))
        self.lbl_settings_title.setStyleSheet(
            f"color: {COLORS.TEXT_PRIMARY}; background: transparent;"
        )
        self.lbl_settings_title.setGeometry(13, 9, 240, 38)
        self.lbl_settings_title.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self.btn_settings_close = QPushButton("DONE", self._header)
        self.btn_settings_close.setObjectName("btn_settings_close")
        self.btn_settings_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_settings_close.setGeometry(511, 12, 141, 36)
        self.btn_settings_close.setStyleSheet(
            f"#btn_settings_close {{"
            f" background-color: {COLORS.SETTINGS_PILL_BG};"
            f" color: {COLORS.TEXT_PRIMARY};"
            f" border: none;"
            f" border-radius: 10px;"
            f" font-family: '{FONT_FAMILY}';"
            f" font-size: 20px;"
            f" font-weight: 300;"
            f"}}"
            f"#btn_settings_close:pressed {{"
            f" background-color: {COLORS.BTN_PRESSED_BG};"
            f" color: {COLORS.BTN_PRESSED_TEXT};"
            f"}}"
        )
        self.btn_settings_close.clicked.connect(self.request_close)

        self._header_divider = QFrame(self)
        self._header_divider.setObjectName("settings_header_divider")
        self._header_divider.setGeometry(8, 54, 633, BORDERS.SETTINGS_DIVIDER_WIDTH)
        self._header_divider.setStyleSheet(
            f"#settings_header_divider {{ background-color: {COLORS.DIVIDER}; border: none; }}"
        )

        # Scrollable rows container (0, 68, 661, 351) — scrollbar 13x351 at (648, 68)
        self.settings_scroll_area = TouchScrollArea(
            scrollbar_variant="settings",
            parent=self,
        )
        self.settings_scroll_area.setObjectName("settings_scroll_area")
        self.settings_scroll_area.setGeometry(0, 68, 661, 351)
        self.settings_scroll_area.setStyleSheet(
            "#settings_scroll_area { background-color: transparent; border: none; }"
        )
        vp = self.settings_scroll_area.viewport()
        vp.setObjectName("settings_scroll_viewport")
        vp.setStyleSheet(
            "#settings_scroll_viewport { background-color: transparent; border: none; }"
        )
        self.settings_scroll_area.verticalScrollBar().valueChanged.connect(
            self._close_dropdown_popover
        )

        self._scroll_content = QWidget()
        self._scroll_content.setObjectName("settings_scroll_content")
        self._scroll_content.setStyleSheet(
            "#settings_scroll_content { background-color: transparent; border: none; }"
        )
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(0)
        self.settings_scroll_area.setWidget(self._scroll_content)

        # In-window touch popover for DROPDOWN slots (never clipped by scroll viewport)
        self._dropdown_popover = QFrame(self)
        self._dropdown_popover.setObjectName("settings_dropdown_popover")
        self._dropdown_popover.setStyleSheet(
            f"#settings_dropdown_popover {{"
            f" background-color: {COLORS.INPUT_BG};"
            f" border: 2px solid {COLORS.BRAND_BLUE};"
            f" border-radius: 10px;"
            f"}}"
        )
        popover_outer = QVBoxLayout(self._dropdown_popover)
        popover_outer.setContentsMargins(4, 4, 4, 4)
        popover_outer.setSpacing(0)

        self._popover_scroll = TouchScrollArea(
            scrollbar_variant="settings",
            parent=self._dropdown_popover,
        )
        self._popover_scroll.setObjectName("settings_dropdown_scroll")
        self._popover_scroll.setStyleSheet(
            "#settings_dropdown_scroll { background-color: transparent; border: none; }"
        )
        pop_vp = self._popover_scroll.viewport()
        pop_vp.setObjectName("settings_dropdown_viewport")
        pop_vp.setStyleSheet(
            "#settings_dropdown_viewport { background-color: transparent; border: none; }"
        )

        self._popover_content = QWidget()
        self._popover_content.setObjectName("settings_dropdown_content")
        self._popover_content.setStyleSheet(
            "#settings_dropdown_content { background-color: transparent; border: none; }"
        )
        self._popover_layout = QVBoxLayout(self._popover_content)
        self._popover_layout.setContentsMargins(0, 0, 0, 0)
        self._popover_layout.setSpacing(4)
        self._popover_scroll.setWidget(self._popover_content)
        popover_outer.addWidget(self._popover_scroll)
        self._dropdown_popover.hide()

        self.load_settings()

    def get_value_line_edits(self) -> list[QLineEdit]:
        return list(self._value_edits.values())

    def load_settings(self) -> None:
        self.close_dropdown_popover()

        for widget in self._row_widgets:
            self._scroll_layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._row_widgets.clear()
        self._toggle_buttons.clear()
        self._value_edits.clear()
        self._last_valid_values.clear()
        self._unpersisted_value_slots.clear()
        self._dropdown_buttons.clear()
        self._dropdown_slots.clear()

        slots = self._settings_store.list_settings()
        for idx, slot in enumerate(slots):
            row = self._build_row(slot)
            self._scroll_layout.addWidget(row)
            self._row_widgets.append(row)

            if idx < len(slots) - 1:
                div = QFrame(self._scroll_content)
                div_name = f"settings_divider_{slot.slot_index}"
                div.setObjectName(div_name)
                div.setFixedHeight(BORDERS.SETTINGS_DIVIDER_WIDTH)
                div.setStyleSheet(
                    f"#{div_name} {{ background-color: {COLORS.DIVIDER}; border: none; }}"
                )
                self._scroll_layout.addWidget(div)
                self._row_widgets.append(div)

        self.settings_scroll_area.refresh_touch_targets()
        self.inputs_rebuilt.emit()

    def _build_row(self, slot: SettingSlot) -> QFrame:
        row_name = f"settings_row_{slot.slot_index}"
        row = QFrame(self._scroll_content)
        row.setObjectName(row_name)
        row.setFixedHeight(LAYOUT.SETTINGS_ROW_HEIGHT)
        row.setStyleSheet(f"#{row_name} {{ background-color: transparent; border: none; }}")

        lbl = QLabel("", row)
        lbl.setObjectName(f"lbl_settings_slot_{slot.slot_index}")
        lbl.setFont(font_from_token(TYPOGRAPHY.SETTINGS_LABEL))
        lbl.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; background: transparent;")
        lbl.setGeometry(13, 8, 460, 32)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        elided_label = lbl.fontMetrics().elidedText(
            slot.label,
            Qt.TextElideMode.ElideRight,
            max(40, lbl.width() - 4),
        )
        lbl.setText(elided_label)

        if slot.control_type == SettingControlType.TOGGLE:
            toggle = _SettingsToggleButton(slot.slot_index, bool(slot.value), parent=row)
            toggle.move(552, 2)
            self._toggle_buttons[slot.slot_index] = toggle
            toggle.clicked.connect(
                lambda checked, idx=slot.slot_index: self._on_toggle_clicked(idx, checked)
            )
        elif slot.control_type == SettingControlType.VALUE:
            edit_name = f"settings_value_{slot.slot_index}"
            edit = QLineEdit(str(slot.value), row)
            edit.setObjectName(edit_name)
            edit.setGeometry(504, 8, LAYOUT.SETTINGS_VALUE_WIDTH, LAYOUT.SETTINGS_PILL_HEIGHT)
            edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit.setPlaceholderText("VALUE000")
            edit.setFont(font_from_token(TYPOGRAPHY.SETTINGS_CONTROL))
            base_pill = settings_pill_qss(
                height_px=LAYOUT.SETTINGS_PILL_HEIGHT,
                selector=f"#{edit_name}",
            )
            edit.setStyleSheet(
                base_pill
                + f" #{edit_name} {{ text-decoration: underline; padding: 0 10px; }}"
            )
            apply_input_placeholder_palette(edit)
            edit.installEventFilter(self)
            self._value_edits[slot.slot_index] = edit
            self._last_valid_values[slot.slot_index] = str(slot.value).strip() or "000"
            edit.textChanged.connect(
                lambda text, idx=slot.slot_index: self._on_value_changed(idx, text)
            )
            edit.editingFinished.connect(
                lambda idx=slot.slot_index: self._commit_or_revert_value(idx)
            )
        elif slot.control_type == SettingControlType.DROPDOWN:
            btn_name = f"settings_dropdown_{slot.slot_index}"
            btn = QPushButton("", row)
            btn.setObjectName(btn_name)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setGeometry(500, 8, 132, LAYOUT.SETTINGS_PILL_HEIGHT)
            btn.setIcon(_dropdown_arrow_icon())
            btn.setIconSize(QSize(12, 11))
            btn.setFont(font_from_token(TYPOGRAPHY.SETTINGS_CONTROL))
            btn.setStyleSheet(
                settings_pill_qss(
                    height_px=LAYOUT.SETTINGS_PILL_HEIGHT,
                    selector=f"#{btn_name}",
                )
                + f" #{btn_name} {{ padding: 0 8px; text-align: center; }}"
                + f" #{btn_name}:pressed {{ background-color: {COLORS.BTN_PRESSED_BG}; color: {COLORS.BTN_PRESSED_TEXT}; }}"
            )
            btn.setText(self._elided_button_text(btn, str(slot.value), reserved_px=34))
            self._dropdown_buttons[slot.slot_index] = btn
            self._dropdown_slots[slot.slot_index] = slot
            btn.clicked.connect(
                lambda _=False, idx=slot.slot_index: self._toggle_dropdown_popover(idx)
            )

        return row

    @staticmethod
    def _elided_button_text(btn: QPushButton, raw_text: str, *, reserved_px: int) -> str:
        avail = max(32, btn.width() - reserved_px)
        return btn.fontMetrics().elidedText(
            raw_text,
            Qt.TextElideMode.ElideRight,
            avail,
        )

    def _on_toggle_clicked(self, slot_index: int, checked: bool) -> None:
        self.commit_or_revert_all_values()
        self.close_dropdown_popover()
        try:
            updated = self._settings_store.update_setting(slot_index, bool(checked))
            self.setting_changed.emit(slot_index, updated.value)
        except Exception:
            toggle = self._toggle_buttons.get(slot_index)
            if toggle is not None:
                prev = not bool(checked)
                toggle.blockSignals(True)
                toggle.setChecked(prev)
                toggle.setText("ON" if prev else "OFF")
                toggle.blockSignals(False)
                toggle.update()

    def _on_value_changed(self, slot_index: int, raw_text: str) -> None:
        cleaned = raw_text.strip()
        if not cleaned or cleaned != self._last_valid_values.get(slot_index, ""):
            self._unpersisted_value_slots.add(slot_index)
        else:
            self._unpersisted_value_slots.discard(slot_index)

    def _revert_to_last_valid(self, slot_index: int) -> None:
        edit = self._value_edits.get(slot_index)
        if edit is None or sip.isdeleted(edit):
            self._unpersisted_value_slots.discard(slot_index)
            return
        fallback = self._last_valid_values.get(slot_index, "000")
        if edit.text() != fallback:
            edit.blockSignals(True)
            edit.setText(fallback)
            edit.blockSignals(False)
        self._unpersisted_value_slots.discard(slot_index)

    def _commit_or_revert_value(self, slot_index: int) -> None:
        edit = self._value_edits.get(slot_index)
        if edit is None or sip.isdeleted(edit):
            self._unpersisted_value_slots.discard(slot_index)
            return
        cleaned = edit.text().strip()
        if not cleaned:
            self._revert_to_last_valid(slot_index)
            return
        if (
            slot_index in self._unpersisted_value_slots
            or cleaned != self._last_valid_values.get(slot_index, "")
        ):
            try:
                updated = self._settings_store.update_setting(slot_index, cleaned)
            except Exception:
                self._revert_to_last_valid(slot_index)
                return
            persisted_str = str(updated.value)
            self._last_valid_values[slot_index] = persisted_str
            if edit.text() != persisted_str:
                edit.blockSignals(True)
                edit.setText(persisted_str)
                edit.blockSignals(False)
            self._unpersisted_value_slots.discard(slot_index)
            self.setting_changed.emit(slot_index, updated.value)
        elif edit.text() != cleaned:
            edit.blockSignals(True)
            edit.setText(cleaned)
            edit.blockSignals(False)

    def commit_or_revert_all_values(self) -> None:
        for slot_index in list(self._value_edits):
            self._commit_or_revert_value(slot_index)

    def _toggle_dropdown_popover(self, slot_index: int) -> None:
        self.commit_or_revert_all_values()
        if (
            self._dropdown_popover.isVisible()
            and self._active_dropdown_slot == slot_index
        ):
            self._close_dropdown_popover()
            return

        slot = self._dropdown_slots.get(slot_index)
        btn = self._dropdown_buttons.get(slot_index)
        if slot is None or btn is None or not slot.options:
            self._close_dropdown_popover()
            return

        self._clear_popover_items()
        self._active_dropdown_slot = slot_index

        # Account for 4px top+bottom layout margins (8px) + 2px top+bottom frame border (4px)
        needed_h = (
            len(slot.options) * LAYOUT.TOUCH_MIN_TARGET
            + max(0, len(slot.options) - 1) * 4
            + 12
        )
        btn_top_left = btn.mapTo(self, QPoint(0, 0))
        y_below = btn_top_left.y() + btn.height() + 4
        avail_below = self.height() - y_below - 8
        avail_above = btn_top_left.y() - 56 - 4

        if needed_h <= avail_below:
            pop_y = y_below
            pop_h = needed_h
        elif needed_h <= avail_above:
            pop_h = needed_h
            pop_y = btn_top_left.y() - pop_h - 4
        elif avail_below >= avail_above:
            pop_y = y_below
            max_h = max(88, self.height() - pop_y - 8)
            pop_h = min(needed_h, max_h)
        else:
            max_h = max(88, avail_above)
            pop_h = min(needed_h, max_h)
            pop_y = max(56, btn_top_left.y() - pop_h - 4)

        has_scrollbar = needed_h > pop_h
        pop_w = max(180 if has_scrollbar else 168, btn.width())
        x = max(8, min(self.width() - pop_w - 8, btn_top_left.x() + btn.width() - pop_w))

        viewport_w = max(
            80,
            pop_w - 12 - (LAYOUT.SETTINGS_SCROLLBAR_WIDTH if has_scrollbar else 0),
        )
        opt_text_max_w = max(40, viewport_w - 24)
        opt_font = jetbrains_mono_font(size_px=16, weight=400)

        current_val = str(slot.value)
        for opt_idx, option in enumerate(slot.options):
            opt_btn = QPushButton("", self._popover_content)
            opt_btn.setObjectName(f"settings_dropdown_opt_{slot_index}_{opt_idx}")
            opt_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            opt_btn.setFixedHeight(LAYOUT.TOUCH_MIN_TARGET)
            opt_btn.setMaximumWidth(viewport_w)
            opt_btn.setFont(opt_font)
            is_cur = option == current_val
            bg = "#DCEAF6" if is_cur else COLORS.SETTINGS_PILL_BG
            border = f"2px solid {COLORS.BRAND_BLUE}" if is_cur else "none"
            opt_btn.setStyleSheet(
                f"QPushButton {{"
                f" background-color: {bg};"
                f" color: {COLORS.TEXT_PRIMARY};"
                f" border: {border};"
                f" border-radius: 8px;"
                f" font-family: '{FONT_FAMILY}';"
                f" font-size: 16px;"
                f" font-weight: 400;"
                f" padding: 0 10px;"
                f"}}"
                f"QPushButton:pressed {{"
                f" background-color: {COLORS.BTN_PRESSED_BG};"
                f" color: {COLORS.BTN_PRESSED_TEXT};"
                f"}}"
            )
            opt_btn.setText(
                opt_btn.fontMetrics().elidedText(
                    option,
                    Qt.TextElideMode.ElideRight,
                    opt_text_max_w,
                )
            )
            opt_btn.clicked.connect(
                lambda _=False, idx=slot_index, val=option: self._select_dropdown_option(
                    idx, val
                )
            )
            self._popover_layout.addWidget(opt_btn)

        self._dropdown_popover.setGeometry(x, pop_y, pop_w, pop_h)
        self._popover_scroll.verticalScrollBar().setValue(0)
        self._popover_scroll.refresh_touch_targets()
        self._dropdown_popover.show()
        self._dropdown_popover.raise_()

    def _select_dropdown_option(self, slot_index: int, option: str) -> None:
        self.close_dropdown_popover()
        try:
            updated = self._settings_store.update_setting(slot_index, option)
            btn = self._dropdown_buttons.get(slot_index)
            if btn is not None:
                btn.setText(
                    self._elided_button_text(btn, str(updated.value), reserved_px=34)
                )
            self._dropdown_slots[slot_index] = updated
            self.setting_changed.emit(slot_index, updated.value)
        except Exception:
            pass

    def _clear_popover_items(self) -> None:
        while self._popover_layout.count():
            item = self._popover_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def close_dropdown_popover(self) -> None:
        self._active_dropdown_slot = None
        if self._dropdown_popover.isVisible():
            focus_w = QApplication.focusWidget()
            if focus_w is not None and (
                focus_w is self._dropdown_popover
                or self._dropdown_popover.isAncestorOf(focus_w)
            ):
                focus_w.clearFocus()
            self._dropdown_popover.hide()

    def _close_dropdown_popover(self) -> None:
        self.close_dropdown_popover()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if isinstance(watched, QLineEdit) and watched in self._value_edits.values():
            if event.type() in (QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress):
                self.close_dropdown_popover()
        return super().eventFilter(watched, event)

    def request_close(self) -> None:
        self.commit_or_revert_all_values()
        self.close_dropdown_popover()
        self.closed.emit()


__all__ = ["SettingsModal"]
