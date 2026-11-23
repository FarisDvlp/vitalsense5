"""Non-blocking 875x231 New / Edit Patient modal dialog overlay."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from vitalsense5.contracts import Gender, PatientRecord, PatientStorePort
from vitalsense5.theme import (
    COLORS,
    FONT_FAMILY,
    LAYOUT,
    RADII,
    TYPOGRAPHY,
    apply_input_placeholder_palette,
    clamp_pill_radius,
    font_from_token,
    get_icon_path,
    input_pill_qss,
    jetbrains_mono_font,
    modal_card_qss,
)
from vitalsense5.widgets import ActionButton

_AGE_MIN, _AGE_MAX = 1, 120
_HEIGHT_MIN, _HEIGHT_MAX = 30, 250
_WEIGHT_MIN, _WEIGHT_MAX = 1, 300


def _gender_arrow_pixmap() -> QPixmap:
    renderer = QSvgRenderer(str(get_icon_path("dropdown_arrow.svg")))
    pm = QPixmap(14, 12)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter, QRectF(0, 0, 14, 12))
    painter.end()
    return pm


class NewPatientDialog(QFrame):
    """875x231 modal card for creating or editing a patient record."""

    cancelled = pyqtSignal()
    saved = pyqtSignal(object)

    def __init__(
        self,
        *,
        patient_store: PatientStorePort,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._patient_store = patient_store
        self._editing_patient_id: str | None = None
        self._selected_gender: Gender = Gender.MALE

        self.setObjectName("new_patient_dialog")
        self.setFixedSize(LAYOUT.NEW_PATIENT_MODAL_WIDTH, LAYOUT.NEW_PATIENT_MODAL_HEIGHT)
        self.setStyleSheet(
            modal_card_qss(
                radius=RADII.MODAL_CARD,
                background=COLORS.SURFACE_CARD,
                selector="#new_patient_dialog",
            )
        )

        # Pill input fields (59px tall, radius clamped to 29px)
        self.input_patient_name = QLineEdit(self)
        self.input_patient_name.setObjectName("input_patient_name")
        self.input_patient_name.setGeometry(19, 20, LAYOUT.INPUT_NAME_WIDTH, LAYOUT.INPUT_PILL_HEIGHT)
        self.input_patient_name.setPlaceholderText("Name")
        self.input_patient_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.input_patient_name.setFont(font_from_token(TYPOGRAPHY.INPUT_TEXT))

        # Gender selector pill (595, 20, 264 x 59) with downward triangle at (614, 29)
        pill_radius = clamp_pill_radius(RADII.INPUT_PILL, LAYOUT.INPUT_PILL_HEIGHT)
        self.btn_patient_gender = QPushButton(Gender.MALE.value, self)
        self.btn_patient_gender.setObjectName("btn_patient_gender")
        self.btn_patient_gender.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_patient_gender.setGeometry(595, 20, LAYOUT.INPUT_GENDER_WIDTH, LAYOUT.INPUT_PILL_HEIGHT)
        self.btn_patient_gender.setFont(font_from_token(TYPOGRAPHY.INPUT_TEXT))
        self.btn_patient_gender.setStyleSheet(
            f"#btn_patient_gender {{"
            f" background-color: {COLORS.INPUT_BG};"
            f" color: {COLORS.TEXT_PRIMARY};"
            f" border-radius: {pill_radius}px;"
            f" border: none;"
            f" padding: 0 20px 0 42px;"
            f" font-family: '{FONT_FAMILY}';"
            f" font-size: 20px;"
            f" font-weight: 200;"
            f" text-align: center;"
            f"}}"
            f"#btn_patient_gender:pressed {{"
            f" background-color: {COLORS.SETTINGS_PILL_BG};"
            f"}}"
        )
        self.lbl_gender_arrow = QLabel(self.btn_patient_gender)
        self.lbl_gender_arrow.setObjectName("lbl_gender_arrow")
        self.lbl_gender_arrow.setPixmap(_gender_arrow_pixmap())
        self.lbl_gender_arrow.setGeometry(19, 9, 16, 41)
        self.lbl_gender_arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_gender_arrow.setStyleSheet("background: transparent; border: none;")
        self.lbl_gender_arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.input_patient_age = QLineEdit(self)
        self.input_patient_age.setObjectName("input_patient_age")
        self.input_patient_age.setGeometry(19, 97, LAYOUT.INPUT_METRIC_WIDTH, LAYOUT.INPUT_PILL_HEIGHT)
        self.input_patient_age.setPlaceholderText("Age")
        self.input_patient_age.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_patient_age.setFont(font_from_token(TYPOGRAPHY.INPUT_TEXT))

        self.input_patient_height = QLineEdit(self)
        self.input_patient_height.setObjectName("input_patient_height")
        self.input_patient_height.setGeometry(307, 97, LAYOUT.INPUT_METRIC_WIDTH, LAYOUT.INPUT_PILL_HEIGHT)
        self.input_patient_height.setPlaceholderText("Height")
        self.input_patient_height.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_patient_height.setFont(font_from_token(TYPOGRAPHY.INPUT_TEXT))

        self.input_patient_weight = QLineEdit(self)
        self.input_patient_weight.setObjectName("input_patient_weight")
        self.input_patient_weight.setGeometry(595, 97, LAYOUT.INPUT_METRIC_WIDTH, LAYOUT.INPUT_PILL_HEIGHT)
        self.input_patient_weight.setPlaceholderText("Weight")
        self.input_patient_weight.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_patient_weight.setFont(font_from_token(TYPOGRAPHY.INPUT_TEXT))

        self._inputs = (
            self.input_patient_name,
            self.input_patient_age,
            self.input_patient_height,
            self.input_patient_weight,
        )
        for field in self._inputs:
            self._set_field_invalid(field, False)

        # Inline error label centered in the 348px gap between CANCEL and SAVE
        self.lbl_patient_error = QLabel("", self)
        self.lbl_patient_error.setObjectName("lbl_patient_error")
        self.lbl_patient_error.setGeometry(265, 168, 348, 51)
        self.lbl_patient_error.setWordWrap(True)
        self.lbl_patient_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_patient_error.setFont(jetbrains_mono_font(size_px=13, weight=500))
        self.lbl_patient_error.setStyleSheet("color: #B00020; background: transparent;")
        self.lbl_patient_error.setVisible(False)

        # CANCEL (#FF7F7F) and SAVE (#90FF93) action buttons
        self.btn_patient_cancel = ActionButton(
            "CANCEL",
            variant="danger",
            object_name="btn_patient_cancel",
            parent=self,
        )
        self.btn_patient_cancel.move(45, 168)

        self.btn_patient_save = ActionButton(
            "SAVE",
            variant="success",
            object_name="btn_patient_save",
            parent=self,
        )
        self.btn_patient_save.move(621, 168)

        self._current_width: int = LAYOUT.NEW_PATIENT_MODAL_WIDTH

        # Non-blocking dropdown popover for Gender selection (Male / Female)
        self._gender_popover = QFrame(self)
        self._gender_popover.setObjectName("patient_gender_popover")
        self._gender_popover.setStyleSheet(
            f"#patient_gender_popover {{"
            f" background-color: {COLORS.INPUT_BG};"
            f" border: 2px solid {COLORS.BRAND_BLUE};"
            f" border-radius: 12px;"
            f"}}"
        )
        pop_layout = QVBoxLayout(self._gender_popover)
        pop_layout.setContentsMargins(6, 6, 6, 6)
        pop_layout.setSpacing(4)

        self._gender_option_buttons: dict[Gender, QPushButton] = {}
        for g in (Gender.MALE, Gender.FEMALE):
            opt_btn = QPushButton(g.value, self._gender_popover)
            opt_btn.setObjectName(f"btn_gender_opt_{g.value.lower()}")
            opt_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            opt_btn.setFixedHeight(LAYOUT.TOUCH_MIN_TARGET)
            opt_btn.setFont(font_from_token(TYPOGRAPHY.INPUT_TEXT))
            opt_btn.clicked.connect(lambda _=False, val=g: self._select_gender(val))
            pop_layout.addWidget(opt_btn)
            self._gender_option_buttons[g] = opt_btn
        self._gender_popover.hide()

        self.btn_patient_gender.clicked.connect(self._toggle_gender_popover)
        self.btn_patient_cancel.clicked.connect(self._on_cancel)
        self.btn_patient_save.clicked.connect(self._on_save)
        self._sync_gender_option_styles()

    def fit_to_width(self, max_width: int) -> None:
        """Keep exact 875x231 Figma geometry when >= 875px; compactly fit narrower viewports."""
        target_w = (
            LAYOUT.NEW_PATIENT_MODAL_WIDTH
            if max_width >= LAYOUT.NEW_PATIENT_MODAL_WIDTH
            else max(540, int(max_width))
        )
        if target_w == self._current_width and self.width() == target_w:
            return
        self._current_width = target_w
        self.setFixedSize(target_w, LAYOUT.NEW_PATIENT_MODAL_HEIGHT)

        if target_w >= LAYOUT.NEW_PATIENT_MODAL_WIDTH:
            self.input_patient_name.setGeometry(
                19, 20, LAYOUT.INPUT_NAME_WIDTH, LAYOUT.INPUT_PILL_HEIGHT
            )
            self.btn_patient_gender.setGeometry(
                595, 20, LAYOUT.INPUT_GENDER_WIDTH, LAYOUT.INPUT_PILL_HEIGHT
            )
            self.input_patient_age.setGeometry(
                19, 97, LAYOUT.INPUT_METRIC_WIDTH, LAYOUT.INPUT_PILL_HEIGHT
            )
            self.input_patient_height.setGeometry(
                307, 97, LAYOUT.INPUT_METRIC_WIDTH, LAYOUT.INPUT_PILL_HEIGHT
            )
            self.input_patient_weight.setGeometry(
                595, 97, LAYOUT.INPUT_METRIC_WIDTH, LAYOUT.INPUT_PILL_HEIGHT
            )
            self.btn_patient_cancel.setFixedSize(
                LAYOUT.ACTION_BTN_WIDTH, LAYOUT.ACTION_BTN_HEIGHT
            )
            self.btn_patient_cancel.move(45, 168)
            self.lbl_patient_error.setGeometry(265, 168, 348, 51)
            self.btn_patient_save.setFixedSize(
                LAYOUT.ACTION_BTN_WIDTH, LAYOUT.ACTION_BTN_HEIGHT
            )
            self.btn_patient_save.move(621, 168)
            self._reposition_gender_popover()
            return

        margin_x = 16
        inner_w = target_w - 2 * margin_x
        gap = 16
        gender_w = min(LAYOUT.INPUT_GENDER_WIDTH, max(140, (inner_w - gap) // 3))
        name_w = inner_w - gap - gender_w
        self.input_patient_name.setGeometry(margin_x, 20, name_w, LAYOUT.INPUT_PILL_HEIGHT)
        self.btn_patient_gender.setGeometry(
            margin_x + name_w + gap, 20, gender_w, LAYOUT.INPUT_PILL_HEIGHT
        )

        metric_w = (inner_w - 2 * gap) // 3
        self.input_patient_age.setGeometry(margin_x, 97, metric_w, LAYOUT.INPUT_PILL_HEIGHT)
        self.input_patient_height.setGeometry(
            margin_x + metric_w + gap, 97, metric_w, LAYOUT.INPUT_PILL_HEIGHT
        )
        self.input_patient_weight.setGeometry(
            margin_x + 2 * (metric_w + gap), 97, metric_w, LAYOUT.INPUT_PILL_HEIGHT
        )

        btn_inset = margin_x + 12
        btn_w = min(LAYOUT.ACTION_BTN_WIDTH, max(140, (inner_w - 32) // 3))
        self.btn_patient_cancel.setFixedSize(btn_w, LAYOUT.ACTION_BTN_HEIGHT)
        self.btn_patient_cancel.move(btn_inset, 168)

        save_x = target_w - btn_inset - btn_w
        self.btn_patient_save.setFixedSize(btn_w, LAYOUT.ACTION_BTN_HEIGHT)
        self.btn_patient_save.move(save_x, 168)

        err_x = btn_inset + btn_w + 8
        err_w = max(80, save_x - 8 - err_x)
        self.lbl_patient_error.setGeometry(err_x, 168, err_w, 51)
        self._reposition_gender_popover()

    def input_fields(self) -> tuple[QLineEdit, QLineEdit, QLineEdit, QLineEdit]:
        return self._inputs

    def selected_gender(self) -> Gender:
        return self._selected_gender

    def set_gender(self, gender: Gender) -> None:
        self._selected_gender = gender
        self.btn_patient_gender.setText(gender.value)
        self._sync_gender_option_styles()

    def _sync_gender_option_styles(self) -> None:
        for g, opt_btn in self._gender_option_buttons.items():
            is_cur = g == self._selected_gender
            bg = "#DCEAF6" if is_cur else COLORS.SETTINGS_PILL_BG
            border = f"2px solid {COLORS.BRAND_BLUE}" if is_cur else "none"
            opt_btn.setStyleSheet(
                f"QPushButton {{"
                f" background-color: {bg};"
                f" color: {COLORS.TEXT_PRIMARY};"
                f" border: {border};"
                f" border-radius: 8px;"
                f" font-family: '{FONT_FAMILY}';"
                f" font-size: 18px;"
                f" font-weight: 300;"
                f" padding: 0 12px;"
                f"}}"
                f"QPushButton:pressed {{"
                f" background-color: {COLORS.BTN_PRESSED_BG};"
                f" color: {COLORS.BTN_PRESSED_TEXT};"
                f"}}"
            )

    def _reposition_gender_popover(self) -> None:
        pop_h = 2 * LAYOUT.TOUCH_MIN_TARGET + 4 + 16
        self._gender_popover.setGeometry(
            self.btn_patient_gender.x(),
            self.btn_patient_gender.y() + self.btn_patient_gender.height() + 4,
            self.btn_patient_gender.width(),
            pop_h,
        )

    def _toggle_gender_popover(self) -> None:
        if self._gender_popover.isVisible():
            self._gender_popover.hide()
            return
        self._reposition_gender_popover()
        self._sync_gender_option_styles()
        self._gender_popover.show()
        self._gender_popover.raise_()

    def _select_gender(self, gender: Gender) -> None:
        self.set_gender(gender)
        self._gender_popover.hide()

    def open_create(self) -> None:
        self._editing_patient_id = None
        for field in self._inputs:
            field.clear()
            self._set_field_invalid(field, False)
        self.set_gender(Gender.MALE)
        self._gender_popover.hide()
        self._clear_error()

    def open_edit(self, patient: PatientRecord) -> None:
        self._editing_patient_id = patient.patient_id
        self.input_patient_name.setText(patient.name)
        self.input_patient_age.setText(str(patient.age))
        self.input_patient_height.setText(str(patient.height_cm))
        self.input_patient_weight.setText(str(patient.weight_kg))
        self.set_gender(patient.gender)
        self._gender_popover.hide()
        for field in self._inputs:
            self._set_field_invalid(field, False)
        self._clear_error()

    def _set_field_invalid(self, field: QLineEdit, invalid: bool) -> None:
        field.setStyleSheet(
            input_pill_qss(height_px=LAYOUT.INPUT_PILL_HEIGHT, invalid=invalid)
        )
        apply_input_placeholder_palette(field)

    def _show_error(self, message: str) -> None:
        self.lbl_patient_error.setText(message)
        self.lbl_patient_error.setVisible(True)

    def _clear_error(self) -> None:
        self.lbl_patient_error.setText("")
        self.lbl_patient_error.setVisible(False)

    def _on_cancel(self) -> None:
        self._gender_popover.hide()
        self._clear_error()
        for field in self._inputs:
            self._set_field_invalid(field, False)
        self.cancelled.emit()

    @staticmethod
    def _parse_int_in_bounds(raw: str, low: int, high: int) -> int | None:
        cleaned = raw.strip()
        if not cleaned:
            return None
        try:
            val = int(cleaned)
        except ValueError:
            return None
        if val < low or val > high:
            return None
        return val

    def _on_save(self) -> None:
        self._gender_popover.hide()
        name = self.input_patient_name.text().strip()
        age = self._parse_int_in_bounds(
            self.input_patient_age.text(), _AGE_MIN, _AGE_MAX
        )
        height_cm = self._parse_int_in_bounds(
            self.input_patient_height.text(), _HEIGHT_MIN, _HEIGHT_MAX
        )
        weight_kg = self._parse_int_in_bounds(
            self.input_patient_weight.text(), _WEIGHT_MIN, _WEIGHT_MAX
        )

        invalid_reasons: list[str] = []
        name_invalid = not bool(name)
        if name_invalid:
            invalid_reasons.append("Name required")

        age_invalid = age is None
        if age_invalid:
            invalid_reasons.append(f"Age {_AGE_MIN}-{_AGE_MAX}")

        height_invalid = height_cm is None
        if height_invalid:
            invalid_reasons.append(f"Height {_HEIGHT_MIN}-{_HEIGHT_MAX}")

        weight_invalid = weight_kg is None
        if weight_invalid:
            invalid_reasons.append(f"Weight {_WEIGHT_MIN}-{_WEIGHT_MAX}")

        self._set_field_invalid(self.input_patient_name, name_invalid)
        self._set_field_invalid(self.input_patient_age, age_invalid)
        self._set_field_invalid(self.input_patient_height, height_invalid)
        self._set_field_invalid(self.input_patient_weight, weight_invalid)

        if invalid_reasons or age is None or height_cm is None or weight_kg is None:
            self._show_error("Invalid: " + ", ".join(invalid_reasons))
            return

        try:
            if self._editing_patient_id is None:
                record = self._patient_store.create_patient(
                    name,
                    age,
                    height_cm,
                    weight_kg,
                    gender=self._selected_gender,
                )
            else:
                record = self._patient_store.update_patient(
                    self._editing_patient_id,
                    name,
                    age,
                    height_cm,
                    weight_kg,
                    gender=self._selected_gender,
                )
        except Exception as exc:
            self._show_error(str(exc) or "Could not save patient record")
            return

        self._clear_error()
        self.saved.emit(record)


__all__ = ["NewPatientDialog"]
