"""Vital sign display column widgets (PRV, RR, PI, SpO2, BP) for VitalSense5."""

from __future__ import annotations

import math

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QWidget

from vitalsense5.contracts.models import (
    AlarmLevel,
    ConnectionState,
    DeviceStatus,
    SensorState,
    VitalSnapshot,
)
from vitalsense5.theme import (
    BORDERS,
    COLORS,
    LAYOUT,
    TYPOGRAPHY,
    font_from_token,
    jetbrains_mono_font,
    vital_accent_bar_qss,
)

_DEFAULT_VALUE_SCALE_STEPS: tuple[int, ...] = (96, 76, 62, 50, 42)
_BP_VALUE_SCALE_STEPS: tuple[int, ...] = (64, 54, 46, 38)
_PR_VALUE_SCALE_STEPS: tuple[int, ...] = (36, 30, 24)


def _is_finite_number(val: object) -> bool:
    if val is None or isinstance(val, bool):
        return False
    try:
        return math.isfinite(float(val))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return False


def _is_device_stale(status: DeviceStatus | None) -> bool:
    if status is None:
        return False
    return (
        status.uart_state != ConnectionState.CONNECTED
        or status.esp32_state != ConnectionState.CONNECTED
        or status.sensor_state == SensorState.FINGER_OFF
    )


def _fit_font_size(
    label: QLabel,
    text: str,
    *,
    max_width_px: int,
    steps: tuple[int, ...],
    weight: int,
    letter_spacing_px: float = 0.0,
) -> None:
    chosen_size = steps[-1]
    for size_px in steps:
        font = jetbrains_mono_font(
            size_px=size_px,
            weight=weight,
            letter_spacing_px=letter_spacing_px,
        )
        label.setFont(font)
        if label.fontMetrics().horizontalAdvance(text) <= max_width_px:
            chosen_size = size_px
            break
    else:
        label.setFont(
            jetbrains_mono_font(
                size_px=chosen_size,
                weight=weight,
                letter_spacing_px=letter_spacing_px,
            )
        )


def _apply_column_alarm_qss(frame: QFrame, alarm: AlarmLevel) -> None:
    obj = frame.objectName()
    if not obj:
        return
    if alarm == AlarmLevel.CRITICAL:
        frame.setStyleSheet(
            f"#{obj} {{"
            f" background-color: rgba(255, 97, 97, 36);"
            f" border: 2px solid {COLORS.ALARM_CRITICAL};"
            f" border-radius: 6px;"
            f"}}"
        )
    elif alarm == AlarmLevel.WARNING:
        frame.setStyleSheet(
            f"#{obj} {{"
            f" background-color: rgba(233, 141, 98, 28);"
            f" border: 2px solid {COLORS.ALARM_WARNING};"
            f" border-radius: 6px;"
            f"}}"
        )
    else:
        frame.setStyleSheet(f"#{obj} {{ background-color: transparent; border: none; }}")


def _alarm_value_fg(alarm: AlarmLevel) -> str:
    if alarm == AlarmLevel.CRITICAL:
        return COLORS.ALARM_CRITICAL
    if alarm == AlarmLevel.WARNING:
        return COLORS.ALARM_WARNING
    return COLORS.TEXT_PRIMARY


class VitalColumnWidget(QFrame):
    """Single-metric vital column (PRV, RR, PI, or SpO2) matching Figma specs."""

    def __init__(
        self,
        *,
        vital_key: str,
        title: str,
        unit: str,
        accent_color: str,
        object_name: str,
        sublabel: str | None = None,
        show_bpm: bool = False,
        letter_spacing_px: float = 0.0,
        width_px: int = 184,
        height_px: int = 195,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.vital_key = vital_key
        self._accent_color = accent_color
        self._letter_spacing_px = letter_spacing_px
        self._show_bpm = show_bpm
        self._alarm = AlarmLevel.NORMAL

        self.setObjectName(object_name)
        self.setFixedSize(width_px, height_px)

        self.accent_bar = QFrame(self)
        bar_name = f"{object_name}_bar"
        self.accent_bar.setObjectName(bar_name)
        self.accent_bar.setGeometry(0, 5, BORDERS.VITAL_ACCENT_WIDTH, LAYOUT.VITAL_ACCENT_HEIGHT)
        self.accent_bar.setStyleSheet(vital_accent_bar_qss(accent_color, selector=f"#{bar_name}"))

        self.lbl_header = QLabel(title, self)
        self.lbl_header.setObjectName(f"{object_name}_header")
        self.lbl_header.setFont(font_from_token(TYPOGRAPHY.VITAL_HEADER))
        self.lbl_header.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
        self.lbl_header.setGeometry(8, 0, width_px - 10, 50)
        self.lbl_header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.lbl_sublabel: QLabel | None = None
        if sublabel is not None:
            self.lbl_sublabel = QLabel(sublabel, self)
            self.lbl_sublabel.setObjectName(f"{object_name}_sublabel")
            self.lbl_sublabel.setFont(font_from_token(TYPOGRAPHY.PRV_SUBLABEL))
            self.lbl_sublabel.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
            self.lbl_sublabel.setGeometry(9, 50, width_px - 12, 22)
            self.lbl_sublabel.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_value = QLabel("--", self)
        self.lbl_value.setObjectName(f"{object_name}_value")
        self.lbl_value.setFont(
            jetbrains_mono_font(
                size_px=TYPOGRAPHY.VITAL_VALUE_LARGE.size_px,
                weight=TYPOGRAPHY.VITAL_VALUE_LARGE.weight,
                letter_spacing_px=letter_spacing_px,
            )
        )
        self.lbl_value.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; background: transparent;")
        self.lbl_value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_unit = QLabel(unit, self)
        self.lbl_unit.setObjectName(f"{object_name}_unit")
        self.lbl_unit.setFont(font_from_token(TYPOGRAPHY.VITAL_UNIT_LARGE))
        self.lbl_unit.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
        self.lbl_unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

        self.lbl_bpm: QLabel | None = None
        if show_bpm:
            self.lbl_bpm = QLabel("HR -- BPM", self)
            self.lbl_bpm.setObjectName("lbl_bpm")
            self.lbl_bpm.setFont(jetbrains_mono_font(size_px=15, weight=200))
            self.lbl_bpm.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
            self.lbl_bpm.setGeometry(8, height_px - 23, width_px - 12, 21)
            self.lbl_bpm.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        _apply_column_alarm_qss(self, AlarmLevel.NORMAL)
        self._layout_value_and_unit("--")

    def set_value(
        self,
        value: float | int | None,
        *,
        alarm: AlarmLevel = AlarmLevel.NORMAL,
        stale: bool = False,
        bpm: int | float | None = None,
    ) -> None:
        if stale or not _is_finite_number(value):
            text = "--"
            effective_alarm = AlarmLevel.NORMAL
        else:
            numeric = float(value)  # type: ignore[arg-type]
            if self.vital_key == "PI":
                if abs(numeric - round(numeric)) < 0.05 and 0.0 <= numeric < 10.0:
                    text = f"{int(round(numeric)):02d}"
                else:
                    text = f"{numeric:.1f}"
            else:
                text = f"{round(numeric)}"
            effective_alarm = alarm

        self._alarm = effective_alarm
        _apply_column_alarm_qss(self, effective_alarm)
        self.lbl_value.setStyleSheet(
            f"color: {_alarm_value_fg(effective_alarm)}; background: transparent;"
        )
        self.lbl_value.setText(text)
        self._layout_value_and_unit(text)

        if self.lbl_bpm is not None:
            if stale or not _is_finite_number(bpm):
                self.lbl_bpm.setText("HR -- BPM")
            else:
                self.lbl_bpm.setText(f"HR {int(float(bpm))} BPM")  # type: ignore[arg-type]

    def update_vital(
        self,
        value: float | int | None,
        alarm: AlarmLevel = AlarmLevel.NORMAL,
        stale: bool = False,
        bpm: int | None = None,
    ) -> None:
        self.set_value(value, alarm=alarm, stale=stale, bpm=bpm)

    def update_from_snapshot(
        self,
        snapshot: VitalSnapshot,
        status: DeviceStatus | None = None,
    ) -> None:
        stale = _is_device_stale(status)
        if self.vital_key == "PRV":
            val = snapshot.prv_rmssd_ms
        elif self.vital_key == "RR":
            val = snapshot.rr_brpm
        elif self.vital_key == "PI":
            val = snapshot.pi_percent
        elif self.vital_key == "SpO2":
            val = snapshot.spo2_percent
        else:
            val = None
        alarm = snapshot.alarms.get(self.vital_key, AlarmLevel.NORMAL)
        self.set_value(val, alarm=alarm, stale=stale, bpm=snapshot.bpm)

    def _layout_value_and_unit(self, text: str) -> None:
        unit_txt = self.lbl_unit.text().strip()
        unit_w = max(24, self.lbl_unit.fontMetrics().horizontalAdvance(unit_txt) + 6)
        right_pad = 4
        gap = 4
        left_x = 8
        max_val_w = max(48, self.width() - left_x - right_pad - unit_w - gap)

        _fit_font_size(
            self.lbl_value,
            text,
            max_width_px=max_val_w,
            steps=_DEFAULT_VALUE_SCALE_STEPS,
            weight=TYPOGRAPHY.VITAL_VALUE_LARGE.weight,
            letter_spacing_px=self._letter_spacing_px,
        )
        val_w = min(
            max_val_w,
            max(40, self.lbl_value.fontMetrics().horizontalAdvance(text) + 6),
        )
        val_y = 73 if self.lbl_sublabel is not None else 63
        val_h = 96 if self.lbl_sublabel is not None else 106
        self.lbl_value.setGeometry(left_x, val_y, val_w, val_h)
        unit_x = min(self.width() - unit_w - right_pad, left_x + val_w + gap)
        self.lbl_unit.setGeometry(unit_x, 128, unit_w, 38)


class BPColumnWidget(QFrame):
    """Dual SYS / DIA blood pressure vital column matching Figma specs."""

    def __init__(
        self,
        *,
        object_name: str = "vital_bp",
        accent_color: str = COLORS.ACCENT_BP,
        width_px: int = 348,
        height_px: int = 195,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.vital_key = "BP"
        self._accent_color = accent_color
        self._alarm = AlarmLevel.NORMAL

        self.setObjectName(object_name)
        self.setFixedSize(width_px, height_px)

        self.accent_bar = QFrame(self)
        bar_name = f"{object_name}_bar"
        self.accent_bar.setObjectName(bar_name)
        self.accent_bar.setGeometry(0, 5, BORDERS.VITAL_ACCENT_WIDTH, LAYOUT.VITAL_ACCENT_HEIGHT)
        self.accent_bar.setStyleSheet(vital_accent_bar_qss(accent_color, selector=f"#{bar_name}"))

        self.lbl_header = QLabel("BP", self)
        self.lbl_header.setObjectName(f"{object_name}_header")
        self.lbl_header.setFont(font_from_token(TYPOGRAPHY.VITAL_HEADER))
        self.lbl_header.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
        self.lbl_header.setGeometry(8, 0, 100, 54)
        self.lbl_header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # PR readout in upper-right (global x=989, y=133 -> local x=123, y=0)
        self.pr_accent_bar = QFrame(self)
        pr_bar_name = f"{object_name}_pr_bar"
        self.pr_accent_bar.setObjectName(pr_bar_name)
        self.pr_accent_bar.setGeometry(123, 5, BORDERS.VITAL_ACCENT_WIDTH, 58)
        self.pr_accent_bar.setStyleSheet(
            vital_accent_bar_qss(COLORS.ACCENT_PR, selector=f"#{pr_bar_name}")
        )

        self.lbl_pr_header = QLabel("PR", self)
        self.lbl_pr_header.setObjectName(f"{object_name}_pr_header")
        self.lbl_pr_header.setFont(font_from_token(TYPOGRAPHY.VITAL_HEADER))
        self.lbl_pr_header.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
        self.lbl_pr_header.setGeometry(131, 0, 68, 54)
        self.lbl_pr_header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.lbl_pr_value = QLabel("--", self)
        self.lbl_pr_value.setObjectName(f"{object_name}_pr_value")
        self.lbl_pr_value.setFont(font_from_token(TYPOGRAPHY.PR_VALUE))
        self.lbl_pr_value.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; background: transparent;")
        self.lbl_pr_value.setGeometry(203, 8, 66, 46)
        self.lbl_pr_value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_pr_unit = QLabel("bpm", self)
        self.lbl_pr_unit.setObjectName(f"{object_name}_pr_unit")
        self.lbl_pr_unit.setFont(font_from_token(TYPOGRAPHY.PR_UNIT))
        self.lbl_pr_unit.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
        self.lbl_pr_unit.setGeometry(268, 32, 46, 24)
        self.lbl_pr_unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # SYS block
        self.lbl_sys_title = QLabel("SYS", self)
        self.lbl_sys_title.setObjectName(f"{object_name}_sys_title")
        self.lbl_sys_title.setFont(font_from_token(TYPOGRAPHY.BP_SUBLABEL_UNIT))
        self.lbl_sys_title.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
        self.lbl_sys_title.setGeometry(15, 67, 60, 28)

        self.lbl_sys_value = QLabel("--", self)
        self.lbl_sys_value.setObjectName(f"{object_name}_sys_value")
        self.lbl_sys_value.setFont(font_from_token(TYPOGRAPHY.VITAL_VALUE_BP))
        self.lbl_sys_value.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; background: transparent;")
        self.lbl_sys_value.setGeometry(15, 96, 116, 72)
        self.lbl_sys_value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_sys_unit = QLabel("mmHg", self)
        self.lbl_sys_unit.setObjectName(f"{object_name}_sys_unit")
        self.lbl_sys_unit.setFont(font_from_token(TYPOGRAPHY.BP_SUBLABEL_UNIT))
        self.lbl_sys_unit.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
        self.lbl_sys_unit.setGeometry(132, 136, 62, 30)

        # DIA block (both mmHg aligned to local y=136 -> global y=269)
        self.lbl_dia_title = QLabel("DIA", self)
        self.lbl_dia_title.setObjectName(f"{object_name}_dia_title")
        self.lbl_dia_title.setFont(font_from_token(TYPOGRAPHY.BP_SUBLABEL_UNIT))
        self.lbl_dia_title.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
        self.lbl_dia_title.setGeometry(199, 67, 60, 28)

        self.lbl_dia_value = QLabel("--", self)
        self.lbl_dia_value.setObjectName(f"{object_name}_dia_value")
        self.lbl_dia_value.setFont(font_from_token(TYPOGRAPHY.VITAL_VALUE_BP))
        self.lbl_dia_value.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; background: transparent;")
        self.lbl_dia_value.setGeometry(200, 96, 80, 72)
        self.lbl_dia_value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_dia_unit = QLabel("mmHg", self)
        self.lbl_dia_unit.setObjectName(f"{object_name}_dia_unit")
        self.lbl_dia_unit.setFont(font_from_token(TYPOGRAPHY.BP_SUBLABEL_UNIT))
        self.lbl_dia_unit.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; background: transparent;")
        self.lbl_dia_unit.setGeometry(282, 136, 62, 30)

        _apply_column_alarm_qss(self, AlarmLevel.NORMAL)

    def set_bp(
        self,
        sys_mmhg: int | float | None,
        dia_mmhg: int | float | None,
        *,
        alarm: AlarmLevel = AlarmLevel.NORMAL,
        stale: bool = False,
    ) -> None:
        if stale or not _is_finite_number(sys_mmhg) or not _is_finite_number(dia_mmhg):
            sys_txt = "--"
            dia_txt = "--"
            effective_alarm = AlarmLevel.NORMAL
        else:
            sys_txt = str(int(float(sys_mmhg)))  # type: ignore[arg-type]
            dia_txt = str(int(float(dia_mmhg)))  # type: ignore[arg-type]
            effective_alarm = alarm

        self._alarm = effective_alarm
        _apply_column_alarm_qss(self, effective_alarm)
        fg = _alarm_value_fg(effective_alarm)
        self.lbl_sys_value.setStyleSheet(f"color: {fg}; background: transparent;")
        self.lbl_dia_value.setStyleSheet(f"color: {fg}; background: transparent;")

        _fit_font_size(
            self.lbl_sys_value,
            sys_txt,
            max_width_px=self.lbl_sys_value.width() - 2,
            steps=_BP_VALUE_SCALE_STEPS,
            weight=TYPOGRAPHY.VITAL_VALUE_BP.weight,
        )
        _fit_font_size(
            self.lbl_dia_value,
            dia_txt,
            max_width_px=self.lbl_dia_value.width() - 2,
            steps=_BP_VALUE_SCALE_STEPS,
            weight=TYPOGRAPHY.VITAL_VALUE_BP.weight,
        )
        self.lbl_sys_value.setText(sys_txt)
        self.lbl_dia_value.setText(dia_txt)

    def set_pr(
        self,
        bpm: int | float | None,
        *,
        stale: bool = False,
    ) -> None:
        if stale or not _is_finite_number(bpm):
            pr_txt = "--"
        else:
            pr_txt = str(round(float(bpm)))  # type: ignore[arg-type]

        _fit_font_size(
            self.lbl_pr_value,
            pr_txt,
            max_width_px=self.lbl_pr_value.width() - 2,
            steps=_PR_VALUE_SCALE_STEPS,
            weight=TYPOGRAPHY.PR_VALUE.weight,
        )
        self.lbl_pr_value.setText(pr_txt)

    def update_bp(
        self,
        sys_mmhg: int | None,
        dia_mmhg: int | None,
        alarm: AlarmLevel = AlarmLevel.NORMAL,
        stale: bool = False,
    ) -> None:
        self.set_bp(sys_mmhg, dia_mmhg, alarm=alarm, stale=stale)

    def update_from_snapshot(
        self,
        snapshot: VitalSnapshot,
        status: DeviceStatus | None = None,
    ) -> None:
        stale = _is_device_stale(status)
        alarm = snapshot.alarms.get("BP", AlarmLevel.NORMAL)
        self.set_bp(snapshot.bp_sys_mmhg, snapshot.bp_dia_mmhg, alarm=alarm, stale=stale)
        self.set_pr(snapshot.bpm, stale=stale)


__all__ = ["BPColumnWidget", "VitalColumnWidget"]
