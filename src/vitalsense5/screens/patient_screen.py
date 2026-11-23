"""Scrollable 1280x720 patient list and selection screen for VitalSense5."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from vitalsense5.contracts import DeviceStatus, PatientRecord
from vitalsense5.theme import (
    COLORS,
    FONT_FAMILY,
    LAYOUT,
    RADII,
    TYPOGRAPHY,
    font_from_token,
    jetbrains_mono_font,
    modal_card_qss,
    patient_card_qss,
)
from vitalsense5.widgets import ActionButton, StatusHeaderBar, TouchScrollArea


class _PatientCard(QFrame):
    """1166x71 Figma patient record card with tap selection."""

    clicked = pyqtSignal(str)

    def __init__(
        self,
        patient: PatientRecord,
        *,
        index: int,
        selected: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.patient_id = patient.patient_id
        self._selected = bool(selected)
        self._pressed = False
        self._press_global = QPoint()

        card_name = f"patient_card_{index}"
        self.setObjectName(card_name)
        self.setFixedSize(LAYOUT.PATIENT_CARD_WIDTH, LAYOUT.PATIENT_CARD_HEIGHT)

        self.lbl_name = QLabel("", self)
        self.lbl_name.setObjectName(f"{card_name}_name")
        self.lbl_name.setFont(font_from_token(TYPOGRAPHY.PATIENT_CARD_NAME))
        self.lbl_name.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; background: transparent;")
        self.lbl_name.setGeometry(29, 13, 450, 45)
        self.lbl_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_meta = QLabel("", self)
        self.lbl_meta.setObjectName(f"{card_name}_meta")
        self.lbl_meta.setFont(font_from_token(TYPOGRAPHY.PATIENT_CARD_META))
        self.lbl_meta.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; background: transparent;")
        self.lbl_meta.setGeometry(490, 20, 650, 31)
        self.lbl_meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.update_patient(patient, selected=selected)

    def update_patient(self, patient: PatientRecord, *, selected: bool) -> None:
        self.patient_id = patient.patient_id
        elided_name = self.lbl_name.fontMetrics().elidedText(
            patient.name,
            Qt.TextElideMode.ElideRight,
            max(40, self.lbl_name.width() - 4),
        )
        self.lbl_name.setText(elided_name)
        meta_text = (
            f"Gender: {patient.gender.value}  "
            f"Age: {patient.age}  Height: {patient.height_cm}cm  Weight: {patient.weight_kg}kg"
        )
        elided_meta = self.lbl_meta.fontMetrics().elidedText(
            meta_text,
            Qt.TextElideMode.ElideRight,
            max(40, self.lbl_meta.width() - 4),
        )
        self.lbl_meta.setText(elided_meta)
        self.set_selected(selected)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        obj = self.objectName()
        self.setStyleSheet(patient_card_qss(selected=self._selected, selector=f"#{obj}"))

    def cancel_press(self) -> None:
        self._pressed = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._press_global = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            delta = event.globalPosition().toPoint() - self._press_global
            if (
                self.rect().contains(event.position().toPoint())
                and delta.manhattanLength() < LAYOUT.TOUCH_DRAG_THRESHOLD_PX * 2
            ):
                self.clicked.emit(self.patient_id)
        else:
            self._pressed = False
        super().mouseReleaseEvent(event)


class PatientScreen(QWidget):
    """Patient list, selection, and creation/editing navigation screen."""

    back_requested = pyqtSignal()
    delete_patient_requested = pyqtSignal()
    edit_patient_requested = pyqtSignal()
    new_patient_requested = pyqtSignal()
    patient_selected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("patient_screen")
        self.setFixedSize(LAYOUT.WINDOW_WIDTH, LAYOUT.WINDOW_HEIGHT)
        self.setStyleSheet(
            f"#patient_screen {{ background-color: {COLORS.SCREEN_BG}; border: none; }}"
        )

        self._cards: list[_PatientCard] = []
        self._active_patient_id: str | None = None

        # Header bar with "Patient List" title and hidden UART text
        self.header_bar = StatusHeaderBar(
            show_connection_status=False,
            title="Patient List",
            parent=self,
        )
        self.header_bar.setObjectName("patient_header_bar")
        self.header_bar.setStyleSheet(
            "#patient_header_bar { background-color: transparent; border: none; }"
        )
        self.header_bar.vs5_logo.setObjectName("ps_vs5_logo")
        self.header_bar.vs5_logo.setStyleSheet(
            "#ps_vs5_logo { background-color: transparent; border: none; }"
        )
        self.header_bar.lbl_active_patient.setObjectName("ps_lbl_active_patient")
        self.header_bar.lbl_datetime.setObjectName("ps_lbl_datetime")
        self.header_bar.cloud_icon.setObjectName("ps_cloud_icon")
        self.header_bar.cloud_icon.setStyleSheet(
            "#ps_cloud_icon { background-color: transparent; border: none; }"
        )
        self.header_bar.lbl_cloud_status.setObjectName("ps_lbl_cloud_status")
        self.header_bar.lbl_uart_status.setObjectName("ps_lbl_uart_status")
        self.header_bar.lbl_compact_conn_badge.setObjectName("ps_lbl_compact_conn_badge")
        self.header_bar.lbl_battery_pct.setObjectName("ps_lbl_battery_pct")
        self.header_bar.battery_icon.setObjectName("ps_battery_icon")
        self.header_bar.battery_icon.setStyleSheet(
            "#ps_battery_icon { background-color: transparent; border: none; }"
        )
        self.header_bar.move(0, 0)

        # Touch-scrollable patient list at (62, 134, 1206, 476)
        self.patient_scroll_area = TouchScrollArea(
            scrollbar_variant="patient",
            parent=self,
        )
        self.patient_scroll_area.setObjectName("patient_scroll_area")
        self.patient_scroll_area.setGeometry(62, 134, 1206, 476)
        self.patient_scroll_area.setStyleSheet(
            "#patient_scroll_area { background-color: transparent; border: none; }"
        )
        vp = self.patient_scroll_area.viewport()
        vp.setObjectName("patient_scroll_viewport")
        vp.setStyleSheet(
            "#patient_scroll_viewport { background-color: transparent; border: none; }"
        )

        self._scroll_content = QWidget()
        self._scroll_content.setObjectName("patient_scroll_content")
        self._scroll_content.setStyleSheet(
            "#patient_scroll_content { background-color: transparent; border: none; }"
        )
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(LAYOUT.PATIENT_CARD_GAP)
        self._scroll_layout.addStretch(1)
        self.patient_scroll_area.setWidget(self._scroll_content)

        # Empty-state notice placed outside patient_scroll_area so card detection stays clean
        self.lbl_empty_patients = QLabel(
            "No patients registered. Tap NEW PATIENT to add one.",
            self,
        )
        self.lbl_empty_patients.setObjectName("lbl_empty_patients")
        self.lbl_empty_patients.setFont(jetbrains_mono_font(size_px=20, weight=300))
        self.lbl_empty_patients.setStyleSheet(
            f"color: {COLORS.TEXT_SECONDARY}; background: transparent;"
        )
        self.lbl_empty_patients.setGeometry(140, 340, 1000, 36)
        self.lbl_empty_patients.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_patients.setVisible(False)

        # Bottom action bar (y=628, 212x51)
        self.btn_back = ActionButton(
            "BACK",
            variant="default",
            object_name="btn_back",
            parent=self,
        )
        self.btn_back.move(62, 628)

        self.btn_delete_patient = ActionButton(
            "DELETE",
            variant="danger",
            object_name="btn_delete_patient",
            parent=self,
        )
        self.btn_delete_patient.move(572, 628)

        self.btn_edit_patient = ActionButton(
            "EDIT PATIENT",
            variant="default",
            object_name="btn_edit_patient",
            parent=self,
        )
        self.btn_edit_patient.move(794, 628)

        self.btn_new_patient = ActionButton(
            "NEW PATIENT",
            variant="default",
            object_name="btn_new_patient",
            parent=self,
        )
        self.btn_new_patient.move(1016, 628)

        self.btn_back.clicked.connect(self.back_requested.emit)
        self.btn_delete_patient.clicked.connect(self.delete_patient_requested.emit)
        self.btn_edit_patient.clicked.connect(self.edit_patient_requested.emit)
        self.btn_new_patient.clicked.connect(self.new_patient_requested.emit)

    def set_patients(
        self,
        patients: list[PatientRecord],
        active_patient_id: str | None,
    ) -> None:
        self._active_patient_id = active_patient_id

        for card in self._cards:
            self._scroll_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        for idx, patient in enumerate(patients):
            is_selected = patient.patient_id == active_patient_id
            card = _PatientCard(
                patient,
                index=idx,
                selected=is_selected,
                parent=self._scroll_content,
            )
            card.clicked.connect(self.patient_selected.emit)
            self._scroll_layout.insertWidget(idx, card)
            self._cards.append(card)

        self.patient_scroll_area.refresh_touch_targets()

        has_patients = len(patients) > 0
        has_active_match = active_patient_id is not None and any(
            p.patient_id == active_patient_id for p in patients
        )
        self.lbl_empty_patients.setVisible(not has_patients)
        self.btn_edit_patient.setEnabled(has_patients and has_active_match)
        self.btn_delete_patient.setEnabled(has_patients and has_active_match)

    def set_selected_patient(self, patient_id: str | None) -> None:
        self._active_patient_id = patient_id
        matched = False
        for card in self._cards:
            is_sel = card.patient_id == patient_id
            if is_sel:
                matched = True
            card.set_selected(is_sel)
        self.btn_edit_patient.setEnabled(bool(self._cards) and matched)
        self.btn_delete_patient.setEnabled(bool(self._cards) and matched)

    def update_device_status(self, status: DeviceStatus) -> None:
        self.header_bar.update_device_status(status)

    def refresh_clock(self, now: datetime | None = None) -> None:
        self.header_bar.refresh_clock(now)


class ConfirmDeleteDialog(QFrame):
    """Non-blocking 540x200 confirmation modal before deleting a patient record."""

    cancelled = pyqtSignal()
    confirmed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._patient_id: str | None = None

        self.setObjectName("confirm_delete_dialog")
        self.setFixedSize(540, 200)
        self.setStyleSheet(
            modal_card_qss(
                radius=RADII.MODAL_CARD,
                background=COLORS.SURFACE_CARD,
                selector="#confirm_delete_dialog",
            )
        )

        self.lbl_confirm_title = QLabel("Delete Patient?", self)
        self.lbl_confirm_title.setObjectName("lbl_confirm_title")
        self.lbl_confirm_title.setGeometry(24, 18, 492, 34)
        self.lbl_confirm_title.setFont(jetbrains_mono_font(size_px=24, weight=600))
        self.lbl_confirm_title.setStyleSheet(
            f"color: {COLORS.TEXT_PRIMARY}; background: transparent;"
        )
        self.lbl_confirm_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_confirm_message = QLabel("", self)
        self.lbl_confirm_message.setObjectName("lbl_confirm_message")
        self.lbl_confirm_message.setGeometry(24, 58, 492, 54)
        self.lbl_confirm_message.setWordWrap(True)
        self.lbl_confirm_message.setFont(jetbrains_mono_font(size_px=18, weight=300))
        self.lbl_confirm_message.setStyleSheet(
            f"color: {COLORS.TEXT_PRIMARY}; background: transparent;"
        )
        self.lbl_confirm_message.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_confirm_cancel = ActionButton(
            "CANCEL",
            variant="default",
            object_name="btn_confirm_cancel",
            parent=self,
        )
        self.btn_confirm_cancel.move(36, 128)
        self.btn_confirm_cancel.setStyleSheet(
            f"#btn_confirm_cancel {{"
            f" background-color: {COLORS.SETTINGS_PILL_BG};"
            f" color: {COLORS.TEXT_PRIMARY};"
            f" border: 1px solid #B5B5B5;"
            f" border-radius: {RADII.ACTION_BUTTON}px;"
            f" font-family: '{FONT_FAMILY}';"
            f" font-size: 24px;"
            f" font-weight: 300;"
            f"}}"
            f"#btn_confirm_cancel:pressed {{"
            f" background-color: {COLORS.BTN_PRESSED_BG};"
            f" color: {COLORS.BTN_PRESSED_TEXT};"
            f"}}"
        )

        self.btn_confirm_delete = ActionButton(
            "DELETE",
            variant="danger",
            object_name="btn_confirm_delete",
            parent=self,
        )
        self.btn_confirm_delete.move(292, 128)

        self.btn_confirm_cancel.clicked.connect(self.cancelled.emit)
        self.btn_confirm_delete.clicked.connect(self._on_confirm_clicked)

    def open_for_patient(self, patient: PatientRecord) -> None:
        self._patient_id = patient.patient_id
        elided_name = self.lbl_confirm_message.fontMetrics().elidedText(
            patient.name,
            Qt.TextElideMode.ElideRight,
            340,
        )
        self.lbl_confirm_message.setText(f'Are you sure you want to delete "{elided_name}"?')

    def _on_confirm_clicked(self) -> None:
        if self._patient_id is not None:
            self.confirmed.emit(self._patient_id)


__all__ = ["ConfirmDeleteDialog", "PatientScreen"]
