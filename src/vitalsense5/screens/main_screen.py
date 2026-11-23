"""Primary 1280x720 VitalSense5 monitoring screen."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from vitalsense5.contracts import DeviceStatus, PatientRecord, VitalSnapshot, WaveformBatch
from vitalsense5.theme import COLORS, LAYOUT
from vitalsense5.widgets import (
    ActionButton,
    BPColumnWidget,
    PPGCanvasWidget,
    StatusHeaderBar,
    VitalColumnWidget,
)


class MainScreen(QWidget):
    """Main patient vital-sign and live PPG waveform monitoring screen."""

    patient_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    save_requested = pyqtSignal()
    record_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("main_screen")
        self.setFixedSize(LAYOUT.WINDOW_WIDTH, LAYOUT.WINDOW_HEIGHT)
        self.setStyleSheet(
            f"#main_screen {{ background-color: {COLORS.SCREEN_BG}; border: none; }}"
        )

        # Header bar (0, 0, 1280, 124)
        self.header_bar = StatusHeaderBar(
            show_connection_status=True,
            title=None,
            parent=self,
        )
        self.header_bar.move(0, 0)

        # Five vital columns (y=133, h=195)
        self.vital_prv = VitalColumnWidget(
            vital_key="PRV",
            title="PRV",
            unit="ms",
            accent_color=COLORS.ACCENT_PRV,
            object_name="vital_prv",
            sublabel="RMSSD",
            show_bpm=True,
            width_px=178,
            height_px=195,
            parent=self,
        )
        self.vital_prv.move(80, 133)

        self.vital_rr = VitalColumnWidget(
            vital_key="RR",
            title="RR",
            unit="brpm",
            accent_color=COLORS.ACCENT_RR,
            object_name="vital_rr",
            width_px=218,
            height_px=195,
            parent=self,
        )
        self.vital_rr.move(266, 133)

        # width_px=174 keeps right edge at 496+174=670 < 674 (vital_spo2)
        self.vital_pi = VitalColumnWidget(
            vital_key="PI",
            title="PI",
            unit="%",
            accent_color=COLORS.ACCENT_PI,
            object_name="vital_pi",
            letter_spacing_px=-3.84,
            width_px=174,
            height_px=195,
            parent=self,
        )
        self.vital_pi.move(496, 133)

        self.vital_spo2 = VitalColumnWidget(
            vital_key="SpO2",
            title="SpO2",
            unit="%",
            accent_color=COLORS.ACCENT_SPO2,
            object_name="vital_spo2",
            width_px=184,
            height_px=195,
            parent=self,
        )
        self.vital_spo2.move(674, 133)

        self.vital_bp = BPColumnWidget(
            object_name="vital_bp",
            accent_color=COLORS.ACCENT_BP,
            width_px=348,
            height_px=195,
            parent=self,
        )
        self.vital_bp.move(866, 133)

        self._vital_columns = (
            self.vital_prv,
            self.vital_rr,
            self.vital_pi,
            self.vital_spo2,
            self.vital_bp,
        )

        # Live PPG waveform canvas (80, 348, 1124, 250) — 10s @ 125Hz with 0.25s ICU sweep gap
        self.ppg_canvas = PPGCanvasWidget(
            sample_rate_hz=125.0,
            window_seconds=10.0,
            gap_seconds=0.25,
            parent=self,
        )
        self.ppg_canvas.move(LAYOUT.PPG_X, LAYOUT.PPG_Y)

        # Bottom action bar (y=628, 212x51)
        self.btn_patient = ActionButton(
            "PATIENT",
            variant="default",
            object_name="btn_patient",
            parent=self,
        )
        self.btn_patient.move(62, 628)

        self.btn_settings = ActionButton(
            "SETTINGS",
            variant="default",
            object_name="btn_settings",
            parent=self,
        )
        self.btn_settings.move(293, 628)

        self.btn_save = ActionButton(
            "SAVE",
            variant="default",
            object_name="btn_save",
            parent=self,
        )
        self.btn_save.move(779, 628)

        self.btn_record = ActionButton(
            "RECORD",
            variant="danger",
            object_name="btn_record",
            parent=self,
        )
        self.btn_record.move(1016, 628)

        self.btn_patient.clicked.connect(self.patient_requested.emit)
        self.btn_settings.clicked.connect(self.settings_requested.emit)
        self.btn_save.clicked.connect(self.save_requested.emit)
        self.btn_record.clicked.connect(self.record_requested.emit)

    def update_vitals(
        self,
        snapshot: VitalSnapshot,
        status: DeviceStatus | None = None,
    ) -> None:
        for col in self._vital_columns:
            col.update_from_snapshot(snapshot, status)

    def append_waveform(self, batch: WaveformBatch) -> None:
        self.ppg_canvas.append_batch(batch)

    def update_device_status(self, status: DeviceStatus) -> None:
        self.header_bar.update_device_status(status)
        self.ppg_canvas.update_device_status(status)

    def set_active_patient(self, patient: PatientRecord | None) -> None:
        self.header_bar.set_active_patient_name(
            patient.name if patient is not None else None
        )

    def set_recording_active(self, active: bool, elapsed_s: int = 0) -> None:
        self.btn_record.set_recording_active(active, elapsed_s)

    def refresh_clock(self, now: datetime | None = None) -> None:
        self.header_bar.refresh_clock(now)


__all__ = ["MainScreen"]
