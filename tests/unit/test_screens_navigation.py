"""Comprehensive unit and integration tests for VitalSense5 M4 screens & navigation."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QAbstractButton, QApplication, QLabel, QPushButton, QWidget

from vitalsense5.adapters import (
    InMemoryPatientStore,
    InMemorySettingsStore,
    MockSessionCommandHandler,
    MockVitalDataAdapter,
)
from vitalsense5.contracts import (
    AlarmLevel,
    CloudState,
    ConnectionState,
    DeviceStatus,
    PatientRecord,
    SensorState,
    SettingControlType,
    SettingSlot,
    VitalSnapshot,
    WaveformBatch,
)
from vitalsense5.main import create_app, main
from vitalsense5.screens import (
    MainScreen,
    MainWindow,
    NewPatientDialog,
    PatientScreen,
    SettingsModal,
)
from vitalsense5.theme import COLORS, LAYOUT, app_base_qss, load_bundled_fonts

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCREENS_DIR = PROJECT_ROOT / "src" / "vitalsense5" / "screens"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    prev_qss = app.styleSheet() if isinstance(app, QApplication) else ""
    load_bundled_fonts()
    if isinstance(app, QApplication):
        app.setStyleSheet(app_base_qss())
    yield app
    if isinstance(app, QApplication):
        app.setStyleSheet(prev_qss)


def _grab(widget: QWidget) -> QImage:
    QApplication.processEvents()
    return widget.grab().toImage()


def _count_color(
    img: QImage,
    hex_color: str,
    *,
    rect: QRect | None = None,
    tolerance: int = 20,
    stride: int = 2,
) -> int:
    target = QColor(hex_color)
    tr, tg, tb = target.red(), target.green(), target.blue()
    bounds = (rect if rect is not None else img.rect()).intersected(img.rect())
    tol_sq = tolerance * tolerance
    hits = 0
    for y in range(bounds.top(), bounds.bottom() + 1, stride):
        for x in range(bounds.left(), bounds.right() + 1, stride):
            c = img.pixelColor(x, y)
            dr = c.red() - tr
            dg = c.green() - tg
            db = c.blue() - tb
            if dr * dr + dg * dg + db * db <= tol_sq:
                hits += 1
    return hits


def _find_visible_kb_key(win: MainWindow, label: str) -> QAbstractButton:
    for btn in win.virtual_keyboard.findChildren(QAbstractButton):
        if btn.isVisible() and btn.text() == label:
            return btn
    raise AssertionError(f"Virtual keyboard key {label!r} not found")


class _FaultyVitalPort:
    """Custom VitalDataPort test double raising transient exceptions and never mutating recording_active."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.raise_on_poll = False
        self._vitals = VitalSnapshot(
            prv_rmssd_ms=72.0,
            rr_brpm=15.0,
            pi_percent=3.0,
            spo2_percent=99.0,
            bp_sys_mmhg=118,
            bp_dia_mmhg=78,
            bpm=68,
            alarms={"PRV": AlarmLevel.NORMAL},
        )
        self._status = DeviceStatus()

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def latest_vitals(self) -> VitalSnapshot:
        if self.raise_on_poll:
            raise RuntimeError("Transient UART timeout")
        return self._vitals

    def pop_waveform_samples(self) -> WaveformBatch:
        if self.raise_on_poll:
            raise RuntimeError("Transient stream error")
        return WaveformBatch(samples=[0.1, 0.4, 0.2, -0.2])

    def device_status(self) -> DeviceStatus:
        if self.raise_on_poll:
            raise RuntimeError("Transient status read error")
        return self._status


class _RejectingCommandHandler:
    """SessionCommandPort test double that rejects or accepts commands cleanly."""

    def __init__(self, *, allow_save: bool = True, allow_record: bool = True) -> None:
        self.allow_save = allow_save
        self.allow_record = allow_record
        self.save_calls = 0
        self.record_calls: list[bool] = []

    def save_snapshot(self, patient: PatientRecord | None, vitals: VitalSnapshot) -> tuple[bool, str]:
        self.save_calls += 1
        if not self.allow_save:
            return False, "Storage full"
        return True, f"Saved {patient.name if patient else 'none'}"

    def toggle_recording(self, active: bool, patient: PatientRecord | None) -> tuple[bool, str]:
        self.record_calls.append(active)
        if not self.allow_record:
            return False, "Sensor not ready"
        return True, "Recording started" if active else "Recording stopped"


# ===========================================================================
# 1. Exports, Architecture Boundary & CLI
# ===========================================================================


def test_screens_exports_and_import_boundary() -> None:
    for cls in (MainWindow, MainScreen, PatientScreen, SettingsModal, NewPatientDialog):
        assert cls is not None

    forbidden = {
        "adapters",
        "scipy",
        "numpy",
        "serial",
        "pyserial",
        "sqlite3",
        "sqlalchemy",
        "sklearn",
        "torch",
        "tensorflow",
    }
    py_files = list(SCREENS_DIR.glob("*.py"))
    assert len(py_files) == 6
    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0].lower())
                    if "adapters" in alias.name.lower():
                        imported.add("adapters")
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0].lower())
                if "adapters" in node.module.lower():
                    imported.add("adapters")
        assert not (imported & forbidden), f"Forbidden import {imported & forbidden} in {py_file.name}"


def test_cli_module_help_and_unknown_flag() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    proc_ok = subprocess.run(
        [sys.executable, "-m", "vitalsense5", "--help"],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc_ok.returncode == 0
    for flag in ("--windowed", "--kiosk", "--mock", "--tick-ms"):
        assert flag in proc_ok.stdout

    proc_bad = subprocess.run(
        [sys.executable, "-m", "vitalsense5", "--nonexistent-flag"],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc_bad.returncode != 0


# ===========================================================================
# 2. MainScreen Geometry, Zero Overlap, Live Polling & Recording Resilience
# ===========================================================================


def test_main_screen_geometry_zero_overlap_and_button_colors(qapp: QApplication) -> None:
    win = create_app(kiosk=False, tick_ms=50)
    win.show()
    QApplication.processEvents()

    assert win.objectName() == "main_window"
    assert win.width() == 1280 and win.height() == 720
    assert not win.isFullScreen()

    ms = win.main_screen
    assert ms.objectName() == "main_screen"
    assert ms.ppg_canvas.geometry() == QRect(80, 348, 1124, 250)

    # Verify zero pairwise overlap across header, 5 vital columns, PPG canvas, and 4 bottom buttons
    items = [
        ms.header_bar,
        ms.vital_prv,
        ms.vital_rr,
        ms.vital_pi,
        ms.vital_spo2,
        ms.vital_bp,
        ms.ppg_canvas,
        ms.btn_patient,
        ms.btn_settings,
        ms.btn_save,
        ms.btn_record,
    ]
    for i, a in enumerate(items):
        assert ms.rect().contains(a.geometry()), f"{a.objectName()} exceeds 1280x720"
        for b in items[i + 1 :]:
            inter = a.geometry().intersected(b.geometry())
            assert inter.width() <= 0 or inter.height() <= 0, (
                f"Overlap between {a.objectName()} and {b.objectName()}: {inter}"
            )

    # MainScreen btn_save uses default (#D9D9D9), btn_record uses danger (#FF7F7F)
    assert ms.btn_save.variant == "default"
    assert ms.btn_record.variant == "danger"
    assert _count_color(_grab(ms.btn_save), COLORS.BTN_DEFAULT_BG, stride=2) >= 50
    assert _count_color(_grab(ms.btn_record), COLORS.BTN_DANGER_BG, stride=2) >= 50

    win.close()


def test_polling_resilience_decoupled_recording_and_save_toast(qapp: QApplication) -> None:
    port = _FaultyVitalPort()
    cmd = _RejectingCommandHandler(allow_save=True, allow_record=False)
    win = create_app(
        vital_port=port,
        patient_store=InMemoryPatientStore(),
        settings_store=InMemorySettingsStore(),
        command_handler=cmd,
        kiosk=False,
        tick_ms=50,
    )
    win.show()
    QApplication.processEvents()

    assert port.started
    assert win.main_screen.vital_prv.lbl_value.text() == "72"

    # Transient exceptions during poll do not crash UI
    port.raise_on_poll = True
    win._on_poll_tick()
    port.raise_on_poll = False
    win._on_poll_tick()

    # Rejected toggle_recording keeps RECORD inactive
    QTest.mouseClick(win.main_screen.btn_record, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert cmd.record_calls == [True]
    assert win.main_screen.btn_record.text() == "RECORD"

    # Accepted toggle_recording stays active even when port.device_status().recording_active is False
    cmd.allow_record = True
    QTest.mouseClick(win.main_screen.btn_record, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert win.main_screen.btn_record.text().startswith("REC ")
    win._on_poll_tick()
    assert win.main_screen.btn_record.text().startswith("REC ")

    # SAVE shows non-blocking toast without overlapping buttons or PPG
    QTest.mouseClick(win.main_screen.btn_save, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert cmd.save_calls == 1
    assert win.toast_banner.isVisible()
    assert "Saved" in win.toast_banner.text()
    for btn in (
        win.main_screen.btn_settings,
        win.main_screen.btn_save,
        win.main_screen.ppg_canvas,
    ):
        assert not win.toast_banner.geometry().intersects(btn.geometry())

    # Toggle recording off cleanly
    QTest.mouseClick(win.main_screen.btn_record, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert win.main_screen.btn_record.text() == "RECORD"

    win.close()
    assert port.stopped
    assert not win._poll_timer.isActive()


# ===========================================================================
# 3. PatientScreen Navigation, Selection, Empty State & Drag Scroll
# ===========================================================================


def test_patient_screen_navigation_selection_drag_and_empty_state(qapp: QApplication) -> None:
    store = InMemoryPatientStore()
    win = create_app(patient_store=store, kiosk=False, tick_ms=100)
    win.show()
    QApplication.processEvents()

    # Navigate to PatientScreen
    QTest.mouseClick(win.main_screen.btn_patient, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    ps = win.patient_screen
    assert win.screen_stack.currentWidget() is ps
    assert ps.header_bar.lbl_screen_title.text() == "Patient List"
    assert not ps.header_bar.lbl_uart_status.isVisible()

    # Cards present & scrollable
    cards = ps._cards
    assert len(cards) == 8
    assert ps.patient_scroll_area.verticalScrollBar().maximum() > 0

    # Drag >= 8px scrolls without selecting card[1]
    card1 = cards[1]
    start = card1.rect().center()
    QTest.mousePress(card1, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(card1, QPoint(start.x(), start.y() - 40))
    QTest.mouseRelease(card1, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(start.x(), start.y() - 40))
    QApplication.processEvents()
    assert ps.patient_scroll_area.verticalScrollBar().value() > 0
    assert store.get_active_patient().patient_id == "p-1"

    # Scroll back and tap card[1]
    ps.patient_scroll_area.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    QTest.mouseClick(card1, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert store.get_active_patient().patient_id == "p-2"

    # Back to MainScreen updates header active patient
    QTest.mouseClick(ps.btn_back, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert win.screen_stack.currentWidget() is win.main_screen
    assert win.main_screen.header_bar.lbl_active_patient.text() == "Patient Number 2"
    win.close()

    # Empty patient store disables EDIT PATIENT and exposes zero cards in scroll area
    empty_win = create_app(patient_store=InMemoryPatientStore(patients=[]), kiosk=False, tick_ms=100)
    empty_win.show()
    QTest.mouseClick(empty_win.main_screen.btn_patient, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert len(empty_win.patient_screen._cards) == 0
    assert not empty_win.patient_screen.btn_edit_patient.isEnabled()
    assert empty_win.main_screen.header_bar.lbl_active_patient.text() == "No Active Patient"
    empty_win.close()


# ===========================================================================
# 4. NewPatientDialog Validation, Edit Mode & Virtual Keyboard Shift
# ===========================================================================


def test_new_patient_dialog_validation_keyboard_shift_and_edit(qapp: QApplication) -> None:
    store = InMemoryPatientStore()
    win = create_app(patient_store=store, kiosk=False, tick_ms=100)
    win.show()
    QTest.mouseClick(win.main_screen.btn_patient, Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    # Open NewPatientDialog
    QTest.mouseClick(win.patient_screen.btn_new_patient, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    dlg = win.new_patient_dialog
    assert dlg.isVisible()
    assert win.modal_scrim.isVisible()
    assert dlg.width() == 875 and dlg.height() == 231
    assert dlg.btn_patient_save.variant == "success"
    assert dlg.btn_patient_cancel.variant == "danger"
    assert dlg.input_patient_height.maxLength() > 3

    # Focus name -> opens QWERTY keyboard and shifts dialog above y=440
    QTest.mouseClick(dlg.input_patient_name, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert win.virtual_keyboard.isVisible()
    assert win.virtual_keyboard.property("mode") == "qwerty"
    assert dlg.y() + dlg.height() <= win.virtual_keyboard.y()

    # Type via virtual keyboard
    QTest.mouseClick(_find_visible_kb_key(win, "SHIFT"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_kb_key(win, "A"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_kb_key(win, "SHIFT"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_kb_key(win, "l"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_kb_key(win, "i"), Qt.MouseButton.LeftButton)
    assert dlg.input_patient_name.text() == "Ali"

    # Tap DONE -> keyboard hides; re-tapping same field re-opens keyboard
    QTest.mouseClick(_find_visible_kb_key(win, "DONE"), Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not win.virtual_keyboard.isVisible()
    QTest.mouseClick(dlg.input_patient_name, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert win.virtual_keyboard.isVisible()

    # Focus age -> locked numpad
    QTest.mouseClick(dlg.input_patient_age, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert win.virtual_keyboard.property("mode") == "numpad"
    assert not _find_visible_kb_key(win, ".").isEnabled()
    assert not _find_visible_kb_key(win, "ABC").isEnabled()

    # Invalid bounds keep dialog open & show error
    dlg.input_patient_age.setText("999")
    dlg.input_patient_height.setText("175")
    dlg.input_patient_weight.setText("70")
    QTest.mouseClick(dlg.btn_patient_save, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert dlg.isVisible()
    assert dlg.lbl_patient_error.isVisible()

    # Fix age -> saves and closes modal + keyboard
    dlg.input_patient_age.setText("29")
    QTest.mouseClick(dlg.btn_patient_save, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not dlg.isVisible()
    assert not win.modal_scrim.isVisible()
    assert not win.virtual_keyboard.isVisible()
    assert store.get_active_patient().name == "Ali"

    # Edit active patient pre-fills fields and updates record
    QTest.mouseClick(win.patient_screen.btn_edit_patient, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert dlg.isVisible()
    assert dlg.input_patient_name.text() == "Ali"
    assert dlg.input_patient_age.text() == "29"
    dlg.input_patient_weight.setText("75")
    QTest.mouseClick(dlg.btn_patient_save, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not dlg.isVisible()
    assert store.get_active_patient().weight_kg == 75

    win.close()


# ===========================================================================
# 5. SettingsModal Toggles, VALUE, DROPDOWN & Upward Shift
# ===========================================================================


def test_settings_modal_controls_scroll_popover_and_shift(qapp: QApplication) -> None:
    slots = [
        SettingSlot(1, "SETTINGS 1", "SETTINGS 1", SettingControlType.TOGGLE, False),
        SettingSlot(2, "SETTINGS 2", "SETTINGS 2", SettingControlType.TOGGLE, True),
        SettingSlot(3, "SETTINGS 3", "SETTINGS 3", SettingControlType.VALUE, "000"),
        SettingSlot(
            4,
            "SETTINGS 4",
            "SETTINGS 4",
            SettingControlType.DROPDOWN,
            "Option A",
            options=["Option A", "Option B", "Option C"],
        ),
        SettingSlot(5, "SETTINGS 5", "SETTINGS 5", SettingControlType.DROPDOWN, "Empty", options=[]),
        SettingSlot(6, "SETTINGS 6", "SETTINGS 6", SettingControlType.TOGGLE, False),
        SettingSlot(7, "SETTINGS 7", "SETTINGS 7", SettingControlType.TOGGLE, False),
        SettingSlot(8, "SETTINGS 8", "SETTINGS 8", SettingControlType.TOGGLE, False),
    ]
    store = InMemorySettingsStore(slots=slots)
    win = create_app(settings_store=store, kiosk=False, tick_ms=100)
    win.show()
    QApplication.processEvents()

    QTest.mouseClick(win.main_screen.btn_settings, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    sm = win.settings_modal
    assert sm.isVisible()
    assert win.modal_scrim.isVisible()
    assert sm.width() == 669 and sm.height() == 383
    assert sm.settings_scroll_area.verticalScrollBar().maximum() > 0

    # btn_settings_close is in header and does not overlap scroll rows
    assert not sm.btn_settings_close.geometry().intersects(sm.settings_scroll_area.geometry())

    # Toggle slot 1 OFF -> ON
    toggle1 = sm.findChild(QAbstractButton, "settings_toggle_1")
    assert toggle1 is not None and toggle1.text() == "OFF"
    QTest.mouseClick(toggle1, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert toggle1.text() == "ON"
    assert store.list_settings()[0].value is True

    # Dropdown slot 4 opens popover and persists selection; empty dropdown slot 5 is safe no-op
    dd4 = sm.findChild(QPushButton, "settings_dropdown_4")
    assert dd4 is not None and dd4.text() == "Option A"
    QTest.mouseClick(dd4, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert sm._dropdown_popover.isVisible()
    opt_b = sm.findChild(QPushButton, "settings_dropdown_opt_4_1")
    assert opt_b is not None and opt_b.height() >= 44
    QTest.mouseClick(opt_b, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert dd4.text() == "Option B"
    assert store.list_settings()[3].value == "Option B"

    dd5 = sm.findChild(QPushButton, "settings_dropdown_5")
    assert dd5 is not None
    QTest.mouseClick(dd5, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not sm._dropdown_popover.isVisible()

    # VALUE slot 3 opens numpad keyboard & shifts SettingsModal upward above keyboard
    val3 = sm.get_value_line_edits()[0]
    QTest.mouseClick(val3, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert win.virtual_keyboard.isVisible()
    assert win.virtual_keyboard.property("mode") == "numpad"
    assert sm.y() + sm.height() <= win.virtual_keyboard.y()

    # Empty string restores last valid value on DONE
    val3.clear()
    QTest.mouseClick(sm.btn_settings_close, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not sm.isVisible()
    assert not win.virtual_keyboard.isVisible()
    assert store.list_settings()[2].value == "000"

    win.close()


# ===========================================================================
# 6. Kiosk Mode Toggle (F11) & Smoke Entrypoint
# ===========================================================================


def test_f11_kiosk_toggle_and_main_window_lifecycle(qapp: QApplication) -> None:
    win = create_app(kiosk=False, tick_ms=100)
    win.show()
    QApplication.processEvents()
    assert not win.isFullScreen()
    assert win.size().width() == 1280 and win.size().height() == 720

    QTest.keyClick(win, Qt.Key.Key_F11)
    QApplication.processEvents()
    assert win.isFullScreen()

    QTest.keyClick(win, Qt.Key.Key_F11)
    QApplication.processEvents()
    assert not win.isFullScreen()
    assert win.width() == 1280 and win.height() == 720

    win.close()
    assert callable(main)


def test_create_app_cold_start_without_precreated_qapplication() -> None:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from PyQt6.QtWidgets import QApplication; "
                "from vitalsense5.main import create_app; "
                "w = create_app(kiosk=False); "
                "assert not w.isVisible(); "
                "w.show(); "
                "QApplication.processEvents(); "
                "assert (w.width(), w.height()) == (1280, 720); "
                "w.close()"
            ),
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr


# ===========================================================================
# 7. Regression Coverage (Header Disambiguation, Caret End, 800x800, Settings)
# ===========================================================================


def test_findchild_header_labels_resolve_to_main_screen_after_navigation(
    qapp: QApplication,
) -> None:
    store = InMemoryPatientStore()
    win = create_app(patient_store=store, kiosk=False, tick_ms=100)
    assert not win.isVisible()
    win.show()
    QApplication.processEvents()

    # Navigate Main -> Patient -> select p-2 -> Back to Main
    QTest.mouseClick(win.main_screen.btn_patient, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    QTest.mouseClick(win.patient_screen._cards[1], Qt.MouseButton.LeftButton)
    QTest.mouseClick(win.patient_screen.btn_back, Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    for name in ("lbl_active_patient", "lbl_datetime", "lbl_uart_status", "lbl_battery_pct"):
        lbl = win.findChild(QLabel, name)
        assert lbl is not None and lbl.isVisible(), f"{name} did not resolve to MainScreen"
        assert lbl.parent() is win.main_screen.header_bar

    assert "Patient Number 2" in win.findChild(QLabel, "lbl_active_patient").text()
    assert win.findChild(QWidget, "vs5_logo").parent() is win.main_screen.header_bar
    assert win.patient_screen.findChild(QLabel, "lbl_screen_title") is not None
    win.close()


def test_prefilled_fields_place_caret_at_end_for_keyboard_backspace(
    qapp: QApplication,
) -> None:
    store = InMemoryPatientStore()
    settings_store = InMemorySettingsStore()
    win = create_app(
        patient_store=store,
        settings_store=settings_store,
        kiosk=False,
        tick_ms=100,
    )
    win.show()
    QApplication.processEvents()

    # SettingsModal pre-filled VALUE ("000")
    QTest.mouseClick(win.main_screen.btn_settings, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    val3 = win.settings_modal.get_value_line_edits()[0]
    QTest.mouseClick(val3, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    for _ in range(4):
        QTest.mouseClick(_find_visible_kb_key(win, "BACKSPACE"), Qt.MouseButton.LeftButton)
    for digit in "250":
        QTest.mouseClick(_find_visible_kb_key(win, digit), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_kb_key(win, "DONE"), Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert val3.text() == "250"
    assert str(settings_store.list_settings()[2].value) == "250"
    QTest.mouseClick(win.settings_modal.btn_settings_close, Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    # NewPatientDialog Edit mode pre-filled weight
    QTest.mouseClick(win.main_screen.btn_patient, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    QTest.mouseClick(win.patient_screen.btn_edit_patient, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    wt = win.new_patient_dialog.input_patient_weight
    QTest.mouseClick(wt, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    for _ in range(4):
        QTest.mouseClick(_find_visible_kb_key(win, "BACKSPACE"), Qt.MouseButton.LeftButton)
    for digit in "62":
        QTest.mouseClick(_find_visible_kb_key(win, digit), Qt.MouseButton.LeftButton)
    QTest.mouseClick(_find_visible_kb_key(win, "DONE"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(win.new_patient_dialog.btn_patient_save, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert store.get_active_patient().weight_kg == 62
    win.close()


def test_f11_fullscreen_contains_modals_and_keyboard_within_window_rect(
    qapp: QApplication,
) -> None:
    win = create_app(kiosk=False, tick_ms=100)
    win.show()
    QApplication.processEvents()

    QTest.keyClick(win, Qt.Key.Key_F11)
    QApplication.processEvents()
    assert win.isFullScreen()

    # SettingsModal fits inside fullscreen window rect
    QTest.mouseClick(win.main_screen.btn_settings, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    sm_rect = QRect(
        win.settings_modal.mapTo(win, QPoint(0, 0)),
        win.settings_modal.size(),
    )
    assert win.rect().contains(sm_rect)
    QTest.mouseClick(win.settings_modal.btn_settings_close, Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    # NewPatientDialog + VirtualKeyboard fit inside fullscreen rect with zero overlap
    QTest.mouseClick(win.main_screen.btn_patient, Qt.MouseButton.LeftButton)
    QTest.mouseClick(win.patient_screen.btn_new_patient, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    QTest.mouseClick(win.new_patient_dialog.input_patient_name, Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    kb_rect = QRect(
        win.virtual_keyboard.mapTo(win, QPoint(0, 0)),
        win.virtual_keyboard.size(),
    )
    assert win.rect().contains(kb_rect)
    dlg = win.new_patient_dialog
    for ctrl in (
        dlg.input_patient_name,
        dlg.input_patient_age,
        dlg.input_patient_height,
        dlg.input_patient_weight,
        dlg.btn_patient_cancel,
        dlg.btn_patient_save,
    ):
        cr = QRect(ctrl.mapTo(win, QPoint(0, 0)), ctrl.size())
        assert win.rect().contains(cr)
        assert not cr.intersects(kb_rect)

    QTest.mouseClick(dlg.btn_patient_cancel, Qt.MouseButton.LeftButton)
    QTest.keyClick(win, Qt.Key.Key_F11)
    QApplication.processEvents()
    assert not win.isFullScreen()
    assert (win.width(), win.height()) == (1280, 720)
    win.close()


def test_settings_modal_eight_option_popover_error_survival_and_toggle_rollback(
    qapp: QApplication,
) -> None:
    class _FailingSettingsPort:
        def __init__(self) -> None:
            self._slots = [
                SettingSlot(1, "SETTINGS 1", "A" * 60, SettingControlType.TOGGLE, False),
                SettingSlot(2, "SETTINGS 2", "SETTINGS 2", SettingControlType.TOGGLE, True),
                SettingSlot(3, "SETTINGS 3", "SETTINGS 3", SettingControlType.VALUE, "000"),
                SettingSlot(
                    4,
                    "SETTINGS 4",
                    "SETTINGS 4",
                    SettingControlType.DROPDOWN,
                    "Opt 1",
                    options=[f"Opt {i}" for i in range(1, 9)],
                ),
            ]
            self.fail_updates = False

        def list_settings(self) -> list[SettingSlot]:
            return list(self._slots)

        def update_setting(self, slot_index: int, value: bool | str) -> SettingSlot:
            if self.fail_updates:
                raise RuntimeError("Simulated settings store error")
            for idx, s in enumerate(self._slots):
                if s.slot_index == slot_index:
                    updated = SettingSlot(s.slot_index, s.key, s.label, s.control_type, value, s.options)
                    self._slots[idx] = updated
                    return updated
            raise KeyError(slot_index)

    port = _FailingSettingsPort()
    win = create_app(settings_store=port, kiosk=False, tick_ms=100)
    win.show()
    QApplication.processEvents()

    QTest.mouseClick(win.main_screen.btn_settings, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    sm = win.settings_modal

    # Long label elided inside width
    lbl1 = sm.findChild(QLabel, "lbl_settings_slot_1")
    assert lbl1 is not None
    assert lbl1.fontMetrics().horizontalAdvance(lbl1.text()) <= lbl1.width()

    # 8-option dropdown popover stays strictly inside SettingsModal bounds
    dd4 = sm.findChild(QPushButton, "settings_dropdown_4")
    assert dd4 is not None
    QTest.mouseClick(dd4, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert sm._dropdown_popover.isVisible()
    assert sm.rect().contains(sm._dropdown_popover.geometry())

    # Focusing VALUE field closes dropdown popover
    val3 = sm.get_value_line_edits()[0]
    QTest.mouseClick(val3, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not sm._dropdown_popover.isVisible()

    # RuntimeError in update_setting: VALUE survives & TOGGLE reverts checked + text
    port.fail_updates = True
    val3.setText("999")
    QApplication.processEvents()
    assert port._slots[2].value == "000"

    toggle1 = sm.findChild(QAbstractButton, "settings_toggle_1")
    assert toggle1 is not None and not toggle1.isChecked() and toggle1.text() == "OFF"
    QTest.mouseClick(toggle1, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not toggle1.isChecked()
    assert toggle1.text() == "OFF"
    win.close()


def test_keyboard_shift_resets_across_modal_close_and_reopen(qapp: QApplication) -> None:
    win = create_app(kiosk=False, tick_ms=100)
    win.show()
    QApplication.processEvents()

    QTest.mouseClick(win.main_screen.btn_patient, Qt.MouseButton.LeftButton)
    QTest.mouseClick(win.patient_screen.btn_new_patient, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    QTest.mouseClick(win.new_patient_dialog.input_patient_name, Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    QTest.mouseClick(_find_visible_kb_key(win, "SHIFT"), Qt.MouseButton.LeftButton)
    assert win.virtual_keyboard.is_shifted()

    QTest.mouseClick(win.new_patient_dialog.btn_patient_cancel, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not win.virtual_keyboard.is_shifted()

    QTest.mouseClick(win.patient_screen.btn_new_patient, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    QTest.mouseClick(win.new_patient_dialog.input_patient_name, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not win.virtual_keyboard.is_shifted()
    win.close()


def test_patient_screen_set_patients_disables_edit_on_unmatched_active_id(
    qapp: QApplication,
) -> None:
    ps = PatientScreen()
    ps.set_patients([PatientRecord("p-1", "Alice", 30, 165, 60)], "nonexistent-id")
    assert not ps.btn_edit_patient.isEnabled()
    ps.set_patients([PatientRecord("p-1", "Alice", 30, 165, 60)], "p-1")
    assert ps.btn_edit_patient.isEnabled()
    ps.close()


def test_keyboard_target_meta_no_deleted_qlineedit_leak_on_settings_reopen(
    qapp: QApplication,
) -> None:
    from PyQt6 import sip
    from PyQt6.QtCore import QEvent

    win = create_app(kiosk=False, tick_ms=100)
    win.show()
    QApplication.processEvents()

    for _ in range(5):
        QTest.mouseClick(win.main_screen.btn_settings, Qt.MouseButton.LeftButton)
        QApplication.processEvents()
        assert win.settings_modal.isVisible()
        QTest.mouseClick(win.settings_modal.btn_settings_close, Qt.MouseButton.LeftButton)
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()

    deleted_keys = [k for k in win._keyboard_target_meta if sip.isdeleted(k)]  # noqa: SLF001
    assert deleted_keys == []
    # 4 NewPatientDialog inputs + 1 SettingsModal VALUE input
    assert len(win._keyboard_target_meta) == 5  # noqa: SLF001
    win.close()


def test_patient_card_drag_clears_internal_pressed_flag(qapp: QApplication) -> None:
    store = InMemoryPatientStore()
    win = create_app(patient_store=store, kiosk=False, tick_ms=100)
    win.show()
    QApplication.processEvents()

    QTest.mouseClick(win.main_screen.btn_patient, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    ps = win.patient_screen
    card1 = ps._cards[1]  # noqa: SLF001
    start = card1.rect().center()
    QTest.mousePress(card1, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    assert card1._pressed is True  # noqa: SLF001
    QTest.mouseMove(card1, QPoint(start.x(), start.y() - 40))
    QApplication.processEvents()
    assert card1._pressed is False  # noqa: SLF001
    QTest.mouseRelease(card1, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(start.x(), start.y() - 40))
    QApplication.processEvents()
    assert card1._pressed is False  # noqa: SLF001
    win.close()
