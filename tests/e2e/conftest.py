"""Shared fixtures, opaque-box helpers, and protocol test doubles for VitalSense5 E2E tests.

Zero top-level imports of ``vitalsense5`` or ``PyQt6`` so that ``pytest --collect-only``
succeeds cleanly before M1-M4 source packages exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"


def ensure_src_on_path() -> None:
    """Insert ``<repo>/src`` on ``sys.path`` lazily when executing tests."""
    if SRC_DIR.is_dir():
        src_str = str(SRC_DIR)
        if src_str not in sys.path:
            sys.path.insert(0, src_str)


def load_contracts() -> SimpleNamespace:
    """Lazy-load DTOs and port protocols from ``vitalsense5.contracts``."""
    ensure_src_on_path()
    import vitalsense5.contracts as contracts_pkg
    import vitalsense5.contracts.models as models
    import vitalsense5.contracts.ports as ports

    def _get(name: str) -> Any:
        for mod in (models, ports, contracts_pkg):
            if hasattr(mod, name):
                return getattr(mod, name)
        raise AttributeError(f"Contract symbol {name!r} not found in vitalsense5.contracts")

    return SimpleNamespace(
        ConnectionState=_get("ConnectionState"),
        CloudState=_get("CloudState"),
        SensorState=_get("SensorState"),
        AlarmLevel=_get("AlarmLevel"),
        SettingControlType=_get("SettingControlType"),
        Gender=_get("Gender"),
        VitalSnapshot=_get("VitalSnapshot"),
        WaveformBatch=_get("WaveformBatch"),
        DeviceStatus=_get("DeviceStatus"),
        PatientRecord=_get("PatientRecord"),
        SettingSlot=_get("SettingSlot"),
        VitalDataPort=_get("VitalDataPort"),
        PatientStorePort=_get("PatientStorePort"),
        SettingsPort=_get("SettingsPort"),
        SessionCommandPort=_get("SessionCommandPort"),
    )


def load_main_module() -> Any:
    """Lazy-load ``vitalsense5.main``."""
    ensure_src_on_path()
    import vitalsense5.main as main_mod

    return main_mod


# ---------------------------------------------------------------------------
# Opaque-box test doubles (structural Protocol implementations)
# ---------------------------------------------------------------------------


class FakeVitalDataPort:
    """Deterministic VitalDataPort test double for opaque-box E2E tests."""

    def __init__(self, contracts: SimpleNamespace) -> None:
        self._c = contracts
        self.started: bool = False
        self.stopped: bool = False
        self.profile: str = "normal"
        self.transient_error: Exception | None = None
        self._phase: float = 0.0
        self._pending_batches: list[Any] = []
        self._snapshot = contracts.VitalSnapshot(
            prv_rmssd_ms=68.0,
            rr_brpm=16.0,
            pi_percent=3.0,
            spo2_percent=98.0,
            bp_sys_mmhg=120,
            bp_dia_mmhg=80,
            bpm=72,
            alarms={
                "PRV": contracts.AlarmLevel.NORMAL,
                "RR": contracts.AlarmLevel.NORMAL,
                "PI": contracts.AlarmLevel.NORMAL,
                "SpO2": contracts.AlarmLevel.NORMAL,
                "BP": contracts.AlarmLevel.NORMAL,
            },
            timestamp=datetime.now(),
        )
        self._status = contracts.DeviceStatus(
            uart_state=contracts.ConnectionState.CONNECTED,
            esp32_state=contracts.ConnectionState.CONNECTED,
            sensor_state=contracts.SensorState.OK,
            cloud_state=contracts.CloudState.ONLINE,
            battery_percent=95,
            battery_voltage=8.2,
            is_charging=False,
            recording_active=False,
            recording_elapsed_s=0,
            status_message="Connected",
        )

    def start(self) -> None:
        self.started = True
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def latest_vitals(self) -> Any:
        if self.transient_error is not None:
            exc = self.transient_error
            self.transient_error = None
            raise exc
        return self._snapshot

    def pop_waveform_samples(self) -> Any:
        if self._pending_batches:
            return self._pending_batches.pop(0)
        if (
            self._status.uart_state != self._c.ConnectionState.CONNECTED
            or self._status.sensor_state == self._c.SensorState.FINGER_OFF
        ):
            return self._c.WaveformBatch(
                samples=[],
                sample_rate_hz=200.0,
                timestamp=datetime.now(),
            )
        samples: list[float] = []
        for i in range(8):
            t = self._phase + i * 0.18
            # Realistic PPG-like systolic + dicrotic pulse shape in [-0.8, 0.9]
            val = 0.65 * math.sin(t) + 0.25 * math.sin(2.0 * t + 0.4)
            samples.append(val)
        self._phase += 8 * 0.18
        return self._c.WaveformBatch(
            samples=samples,
            sample_rate_hz=200.0,
            timestamp=datetime.now(),
        )

    def device_status(self) -> Any:
        return self._status

    def set_simulation_profile(self, profile: str) -> None:
        self.profile = profile

    # Test-side mutation helpers (never called by application code)
    def push_vitals(self, **kwargs: Any) -> Any:
        data = {
            "prv_rmssd_ms": self._snapshot.prv_rmssd_ms,
            "rr_brpm": self._snapshot.rr_brpm,
            "pi_percent": self._snapshot.pi_percent,
            "spo2_percent": self._snapshot.spo2_percent,
            "bp_sys_mmhg": self._snapshot.bp_sys_mmhg,
            "bp_dia_mmhg": self._snapshot.bp_dia_mmhg,
            "bpm": self._snapshot.bpm,
            "alarms": dict(self._snapshot.alarms),
            "timestamp": datetime.now(),
        }
        data.update(kwargs)
        self._snapshot = self._c.VitalSnapshot(**data)
        return self._snapshot

    def set_snapshot(self, snapshot: Any) -> None:
        self._snapshot = snapshot

    def push_waveform(self, samples: list[float], sample_rate_hz: float = 200.0) -> None:
        self._pending_batches.append(
            self._c.WaveformBatch(
                samples=list(samples),
                sample_rate_hz=sample_rate_hz,
                timestamp=datetime.now(),
            )
        )

    def set_status(self, **kwargs: Any) -> Any:
        data = {
            "uart_state": self._status.uart_state,
            "esp32_state": self._status.esp32_state,
            "sensor_state": self._status.sensor_state,
            "cloud_state": self._status.cloud_state,
            "battery_percent": self._status.battery_percent,
            "battery_voltage": self._status.battery_voltage,
            "is_charging": self._status.is_charging,
            "recording_active": self._status.recording_active,
            "recording_elapsed_s": self._status.recording_elapsed_s,
            "status_message": self._status.status_message,
        }
        data.update(kwargs)
        self._status = self._c.DeviceStatus(**data)
        return self._status

    def arm_transient_error(self, exc: Exception) -> None:
        self.transient_error = exc


class FakePatientStore:
    """In-memory PatientStorePort test double with call spy tracking."""

    def __init__(
        self,
        contracts: SimpleNamespace,
        patients: list[Any] | None = None,
        active_id: str | None = None,
    ) -> None:
        self._c = contracts
        if patients is None:
            self._patients = [
                contracts.PatientRecord("p-1", "Patient Number 1", 34, 170, 68),
                contracts.PatientRecord("p-2", "Patient Number 2", 42, 165, 60),
                contracts.PatientRecord("p-3", "Patient Number 3", 28, 175, 72),
            ]
        else:
            self._patients = list(patients)
        if active_id is not None:
            self._active_id: str | None = active_id
        elif self._patients:
            self._active_id = self._patients[0].patient_id
        else:
            self._active_id = None
        self._next_seq = len(self._patients) + 1
        self.create_calls: list[tuple[str, int, int, int]] = []
        self.update_calls: list[tuple[str, str, int, int, int]] = []
        self.set_active_calls: list[str] = []

    def list_patients(self) -> list[Any]:
        return list(self._patients)

    def get_active_patient(self) -> Any | None:
        for patient in self._patients:
            if patient.patient_id == self._active_id:
                return patient
        return None

    def set_active_patient(self, patient_id: str) -> Any:
        self.set_active_calls.append(patient_id)
        for patient in self._patients:
            if patient.patient_id == patient_id:
                self._active_id = patient_id
                return patient
        raise KeyError(f"Unknown patient_id: {patient_id}")

    def create_patient(
        self,
        name: str,
        age: int,
        height_cm: int,
        weight_kg: int,
        gender: Any | None = None,
    ) -> Any:
        resolved_gender = self._c.Gender.MALE if gender is None else gender
        self.create_calls.append((name, age, height_cm, weight_kg, resolved_gender))
        pid = f"p-{self._next_seq}"
        self._next_seq += 1
        rec = self._c.PatientRecord(
            pid, name, int(age), int(height_cm), int(weight_kg), resolved_gender
        )
        self._patients.append(rec)
        self._active_id = pid
        return rec

    def update_patient(
        self,
        patient_id: str,
        name: str,
        age: int,
        height_cm: int,
        weight_kg: int,
        gender: Any | None = None,
    ) -> Any:
        resolved_gender = self._c.Gender.MALE if gender is None else gender
        self.update_calls.append(
            (patient_id, name, age, height_cm, weight_kg, resolved_gender)
        )
        for idx, patient in enumerate(self._patients):
            if patient.patient_id == patient_id:
                updated = self._c.PatientRecord(
                    patient_id,
                    name,
                    int(age),
                    int(height_cm),
                    int(weight_kg),
                    resolved_gender,
                )
                self._patients[idx] = updated
                return updated
        raise KeyError(f"Unknown patient_id: {patient_id}")

    def delete_patient(self, patient_id: str) -> None:
        for idx, patient in enumerate(self._patients):
            if patient.patient_id == patient_id:
                self._patients.pop(idx)
                if self._active_id == patient_id:
                    self._active_id = self._patients[0].patient_id if self._patients else None
                return
        raise KeyError(f"Unknown patient_id: {patient_id}")


class FakeSettingsStore:
    """In-memory SettingsPort test double matching Figma's 8 slots."""

    def __init__(
        self,
        contracts: SimpleNamespace,
        slots: list[Any] | None = None,
    ) -> None:
        self._c = contracts
        if slots is None:
            t_toggle = contracts.SettingControlType.TOGGLE
            t_value = contracts.SettingControlType.VALUE
            t_drop = contracts.SettingControlType.DROPDOWN
            self._slots = [
                contracts.SettingSlot(1, "SETTINGS 1", "SETTINGS 1", t_toggle, False),
                contracts.SettingSlot(2, "SETTINGS 2", "SETTINGS 2", t_toggle, True),
                contracts.SettingSlot(3, "SETTINGS 3", "SETTINGS 3", t_value, "000"),
                contracts.SettingSlot(
                    4,
                    "SETTINGS 4",
                    "SETTINGS 4",
                    t_drop,
                    "Option A",
                    options=["Option A", "Option B", "Option C"],
                ),
                contracts.SettingSlot(5, "SETTINGS 5", "SETTINGS 5", t_toggle, False),
                contracts.SettingSlot(6, "SETTINGS 6", "SETTINGS 6", t_toggle, False),
                contracts.SettingSlot(7, "SETTINGS 7", "SETTINGS 7", t_toggle, False),
                contracts.SettingSlot(8, "SETTINGS 8", "SETTINGS 8", t_toggle, False),
            ]
        else:
            self._slots = list(slots)
        self.update_calls: list[tuple[int, Any]] = []

    def list_settings(self) -> list[Any]:
        return list(self._slots)

    def update_setting(self, slot_index: int, value: bool | str | int | float) -> Any:
        self.update_calls.append((slot_index, value))
        for idx, slot in enumerate(self._slots):
            if slot.slot_index == slot_index:
                updated = self._c.SettingSlot(
                    slot.slot_index,
                    slot.key,
                    slot.label,
                    slot.control_type,
                    value,
                    list(slot.options),
                )
                self._slots[idx] = updated
                return updated
        raise KeyError(f"Unknown setting slot_index: {slot_index}")


class FakeSessionCommandHandler:
    """Spy SessionCommandPort implementation."""

    def __init__(self) -> None:
        self.save_calls: list[tuple[Any | None, Any]] = []
        self.record_calls: list[tuple[bool, Any | None]] = []
        self.save_result: tuple[bool, str] = (True, "Snapshot saved")
        self.record_result: tuple[bool, str] = (True, "Recording updated")

    def save_snapshot(self, patient: Any | None, vitals: Any) -> tuple[bool, str]:
        self.save_calls.append((patient, vitals))
        return self.save_result

    def toggle_recording(self, active: bool, patient: Any | None) -> tuple[bool, str]:
        self.record_calls.append((active, patient))
        return self.record_result


@dataclass
class AppHarness:
    """Container returned by ``make_app`` / ``harness`` fixtures."""

    window: Any
    qapp: Any
    vital_port: FakeVitalDataPort
    patient_store: FakePatientStore
    settings_store: FakeSettingsStore
    command_handler: FakeSessionCommandHandler
    contracts: SimpleNamespace


# ---------------------------------------------------------------------------
# Session QApplication & Harness Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp() -> Any:
    """Pure-PyQt6 session QApplication with offscreen + 1:1 DPI scaling guards."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(["vitalsense5-e2e"])
    return app


@pytest.fixture
def make_app(qapp: Any) -> Callable[..., AppHarness]:
    """Factory fixture creating an isolated MainWindow with injected test doubles."""
    created_windows: list[Any] = []
    created_ports: list[FakeVitalDataPort] = []

    def _factory(
        *,
        patients: list[Any] | None = None,
        settings: list[Any] | None = None,
        kiosk: bool = False,
        active_patient_id: str | None = None,
        patient_count: int | None = None,
    ) -> AppHarness:
        contracts = load_contracts()
        main_mod = load_main_module()

        if patients is None and patient_count is not None:
            patients = [
                contracts.PatientRecord(
                    f"p-{idx}",
                    f"Patient Number {idx}",
                    25 + (idx % 50),
                    160 + (idx % 25),
                    55 + (idx % 35),
                )
                for idx in range(1, patient_count + 1)
            ]

        vital_port = FakeVitalDataPort(contracts)
        patient_store = FakePatientStore(
            contracts, patients=patients, active_id=active_patient_id
        )
        settings_store = FakeSettingsStore(contracts, slots=settings)
        command_handler = FakeSessionCommandHandler()

        win = main_mod.create_app(
            vital_port=vital_port,
            patient_store=patient_store,
            settings_store=settings_store,
            command_handler=command_handler,
            kiosk=kiosk,
        )
        win.show()
        qapp.processEvents()
        pump_events(60)
        created_windows.append(win)
        created_ports.append(vital_port)
        return AppHarness(
            window=win,
            qapp=qapp,
            vital_port=vital_port,
            patient_store=patient_store,
            settings_store=settings_store,
            command_handler=command_handler,
            contracts=contracts,
        )

    yield _factory

    for win in created_windows:
        try:
            win.close()
            win.deleteLater()
        except RuntimeError:
            pass
    for port in created_ports:
        port.stop()
    for top in list(qapp.topLevelWidgets()):
        try:
            top.close()
            top.deleteLater()
        except RuntimeError:
            pass
    qapp.processEvents()


@pytest.fixture
def harness(make_app: Callable[..., AppHarness]) -> AppHarness:
    """Default 3-patient windowed AppHarness."""
    return make_app()


# ---------------------------------------------------------------------------
# Opaque-Box Event Loop, Lookup, Touch, Keyboard, and Pixel Helpers
# ---------------------------------------------------------------------------


def pump_events(ms: int = 60) -> None:
    """Process Qt events and timers using QTest.qWait."""
    from PyQt6.QtTest import QTest

    QTest.qWait(ms)


def wait_until(
    predicate: Callable[[], Any],
    timeout_ms: int = 2000,
    step_ms: int = 20,
    description: str = "condition",
) -> Any:
    """Poll Qt event loop until ``predicate()`` returns truthy or raise TimeoutError."""
    from PyQt6.QtTest import QTest

    elapsed = 0
    while elapsed <= timeout_ms:
        result = predicate()
        if result:
            return result
        QTest.qWait(step_ms)
        elapsed += step_ms
    raise TimeoutError(f"Timed out after {timeout_ms}ms waiting for {description}")


def find_widget(root: Any, object_name: str) -> Any:
    """Find child QWidget by documented ``objectName`` or raise AssertionError."""
    from PyQt6.QtWidgets import QWidget

    widget = root.findChild(QWidget, object_name)
    if widget is None:
        names = [w.objectName() for w in root.findChildren(QWidget) if w.objectName()]
        raise AssertionError(
            f"Widget with objectName={object_name!r} not found under {root.objectName()!r}. "
            f"Available named widgets: {names}"
        )
    return widget


def find_overlay(harness_or_window: Any, object_name: str, require_visible: bool = False) -> Any | None:
    """Locate a modal/overlay by objectName inside MainWindow or top-level QDialogs."""
    from PyQt6.QtWidgets import QApplication, QWidget

    window = harness_or_window.window if hasattr(harness_or_window, "window") else harness_or_window
    candidates: list[Any] = []
    child = window.findChild(QWidget, object_name)
    if child is not None:
        candidates.append(child)
    app = QApplication.instance()
    if app is not None:
        for top in app.topLevelWidgets():
            if top.objectName() == object_name:
                candidates.append(top)
            nested = top.findChild(QWidget, object_name)
            if nested is not None and nested not in candidates:
                candidates.append(nested)

    if not candidates:
        return None
    if require_visible:
        for cand in candidates:
            if cand.isVisible():
                return cand
        return None
    for cand in candidates:
        if cand.isVisible():
            return cand
    return candidates[0]


def find_modal_card(modal_widget: Any, expected_w: int, expected_h: int) -> Any:
    """Return the visible modal card widget, handling either direct card or full-screen scrim wrapper."""
    from PyQt6.QtWidgets import QWidget

    if modal_widget.width() < 1200 and modal_widget.height() < 680:
        return modal_widget

    best: Any = modal_widget
    best_score = 10**9
    for child in modal_widget.findChildren(QWidget):
        if not child.isVisible():
            continue
        w, h = child.width(), child.height()
        if w >= 1200 and h >= 680:
            continue
        if w < 200 or h < 120:
            continue
        score = abs(w - expected_w) + abs(h - expected_h)
        if score < best_score:
            best_score = score
            best = child
    return best


def widget_rect_in_window(widget: Any, window: Any) -> Any:
    """Map ``widget`` geometry into ``window`` coordinate space."""
    from PyQt6.QtCore import QPoint, QRect

    top_left = widget.mapTo(window, QPoint(0, 0))
    return QRect(top_left, widget.size())


def click_widget(widget: Any, pos: Any = None, wait_ms: int = 35) -> None:
    """Click a visible enabled widget at its center (routing to childAt like real touch)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    assert widget.isVisible(), f"Cannot click hidden widget {widget.objectName()!r}"
    assert widget.isEnabled(), f"Cannot click disabled widget {widget.objectName()!r}"
    local_pos = pos if pos is not None else widget.rect().center()
    target = widget.childAt(local_pos) or widget
    target_pos = target.mapFrom(widget, local_pos) if target is not widget else local_pos
    QTest.mouseClick(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target_pos)
    QApplication.processEvents()
    QTest.qWait(wait_ms)


def press_and_hold(widget: Any, pos: Any = None) -> None:
    """Send mousePress without release to inspect pressed visual state."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    assert widget.isVisible(), f"Cannot press hidden widget {widget.objectName()!r}"
    local_pos = pos if pos is not None else widget.rect().center()
    target = widget.childAt(local_pos) or widget
    target_pos = target.mapFrom(widget, local_pos) if target is not widget else local_pos
    QTest.mousePress(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target_pos)
    QApplication.processEvents()
    QTest.qWait(20)


def release_widget(widget: Any, pos: Any = None, wait_ms: int = 35) -> None:
    """Send mouseRelease corresponding to press_and_hold."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    local_pos = pos if pos is not None else widget.rect().center()
    target = widget.childAt(local_pos) or widget
    target_pos = target.mapFrom(widget, local_pos) if target is not widget else local_pos
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target_pos)
    QApplication.processEvents()
    QTest.qWait(wait_ms)


def touch_drag(
    scroll_area: Any,
    dy_px: int,
    start_ratio: tuple[float, float] = (0.5, 0.7),
    steps: int = 12,
    step_ms: int = 12,
    settle_ms: int = 100,
) -> None:
    """Simulate a finger vertical drag gesture on ``scroll_area.viewport()``."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    vp = scroll_area.viewport()
    start_vp = QPoint(
        max(4, min(vp.width() - 4, int(vp.width() * start_ratio[0]))),
        max(4, min(vp.height() - 4, int(vp.height() * start_ratio[1]))),
    )
    target = vp.childAt(start_vp) or vp
    QTest.mousePress(
        target,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        target.mapFrom(vp, start_vp),
    )
    QApplication.processEvents()

    for step in range(1, steps + 1):
        cur_vp = QPoint(start_vp.x(), start_vp.y() + int(round(dy_px * step / steps)))
        QTest.mouseMove(target, target.mapFrom(vp, cur_vp))
        QApplication.processEvents()
        QTest.qWait(step_ms)

    end_vp = QPoint(start_vp.x(), start_vp.y() + dy_px)
    QTest.mouseRelease(
        target,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        target.mapFrom(vp, end_vp),
    )
    QApplication.processEvents()
    QTest.qWait(settle_ms)


def visible_texts(widget: Any) -> list[str]:
    """Collect visible text from a widget and its visible label/button/input descendants."""
    from PyQt6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit

    texts: list[str] = []
    if callable(getattr(widget, "text", None)) and widget.isVisible():
        txt = widget.text().strip()
        if txt:
            texts.append(txt)

    for child in widget.findChildren((QLabel, QAbstractButton, QLineEdit, QComboBox)):
        if not child.isVisible():
            continue
        if isinstance(child, QComboBox):
            txt = child.currentText().strip()
        elif callable(getattr(child, "text", None)):
            txt = child.text().strip()
        else:
            txt = ""
        if txt and txt not in texts:
            texts.append(txt)
    return texts


def joined_text(widget: Any) -> str:
    """Return space-joined visible texts of ``widget``."""
    return " ".join(visible_texts(widget))


def find_line_edit(widget: Any) -> Any:
    """Return ``widget`` if it is a QLineEdit, else its QLineEdit child."""
    from PyQt6.QtWidgets import QLineEdit

    if isinstance(widget, QLineEdit):
        return widget
    child = widget.findChild(QLineEdit)
    assert child is not None, f"No QLineEdit found inside {widget.objectName()!r}"
    return child


def focus_input_field(field_widget: Any) -> None:
    """Click a form input field (or its inner QLineEdit) to focus it and trigger virtual keyboard."""
    from PyQt6.QtWidgets import QLineEdit

    target = field_widget if isinstance(field_widget, QLineEdit) else (field_widget.findChild(QLineEdit) or field_widget)
    click_widget(target)
    pump_events(60)


def keyboard_mode(kb: Any) -> str:
    """Detect whether VirtualKeyboardOverlay is currently in 'qwerty' or 'numpad' mode."""
    from PyQt6.QtWidgets import QAbstractButton, QWidget

    prop = kb.property("mode")
    if isinstance(prop, str) and prop.lower() in ("qwerty", "numpad"):
        return prop.lower()

    labels: list[str] = []
    for child in kb.findChildren((QAbstractButton, QWidget)):
        if not child.isVisible():
            continue
        if callable(getattr(child, "text", None)):
            txt = child.text().strip().upper()
            if txt:
                labels.append(txt)
    alpha_hits = sum(1 for ch in ("Q", "W", "E", "A", "S", "Z") if ch in labels)
    digit_hits = sum(1 for ch in ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9") if ch in labels)
    if alpha_hits >= 3:
        return "qwerty"
    if digit_hits >= 5:
        return "numpad"
    return "unknown"


_KEY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "BACKSPACE": ("BACKSPACE", "BKSP", "DEL", "DELETE", "⌫", "<-", "←"),
    "SHIFT": ("SHIFT", "⇧", "CAPS", "CAP", "↑"),
    "SPACE": ("SPACE", "SPACEBAR", "␣", " "),
    "DONE": ("DONE", "OK", "ENTER", "HIDE", "CLOSE", "✓", "↵", "CONFIRM"),
    "CLEAR": ("CLEAR", "CLR", "C"),
}


def find_keyboard_key(kb: Any, key_label: str) -> Any:
    """Locate a visible key button inside ``VirtualKeyboardOverlay`` by label or synonym."""
    from PyQt6.QtWidgets import QAbstractButton, QWidget

    upper = key_label.upper()
    candidates_norm = _KEY_SYNONYMS.get(upper, (upper,))

    widgets = [
        w
        for w in kb.findChildren(QAbstractButton)
        if w.isVisible()
    ]
    if not widgets:
        widgets = [
            w
            for w in kb.findChildren(QWidget)
            if w.isVisible() and callable(getattr(w, "text", None))
        ]

    # Exact match pass
    for btn in widgets:
        txt = btn.text().strip().upper()
        acc = btn.accessibleName().strip().upper() if btn.accessibleName() else ""
        if key_label == " " and (btn.text() == " " or txt == "SPACE" or txt == "SPACEBAR" or txt == "␣"):
            return btn
        if txt in candidates_norm or acc in candidates_norm:
            return btn

    # Fallback: wide bottom space button when looking for SPACE / " "
    if upper in ("SPACE", " "):
        wide_empty = [
            btn for btn in widgets
            if not btn.text().strip() and btn.width() >= 120
        ]
        if wide_empty:
            return wide_empty[0]

    available = [btn.text() for btn in widgets]
    raise AssertionError(f"Keyboard key {key_label!r} not found. Visible keys: {available}")


def tap_keyboard_key(kb: Any, key_label: str) -> None:
    """Click a key on the visible virtual keyboard."""
    btn = find_keyboard_key(kb, key_label)
    click_widget(btn, wait_ms=25)


def type_via_keyboard(harness: AppHarness, text: str, *, press_done: bool = False) -> None:
    """Type text character-by-character using the active VirtualKeyboardOverlay."""
    kb = find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None and kb.isVisible(), "virtual_keyboard_overlay is not visible"

    for ch in text:
        if ch == " ":
            tap_keyboard_key(kb, "SPACE")
            continue
        if ch.isalpha() and ch.isupper():
            # Check if keyboard keys are currently lowercase; if so, press SHIFT
            try:
                sample_btn = find_keyboard_key(kb, ch)
                if sample_btn.text().strip() != ch:
                    tap_keyboard_key(kb, "SHIFT")
            except AssertionError:
                tap_keyboard_key(kb, "SHIFT")
            tap_keyboard_key(kb, ch)
        elif ch.isalpha() and ch.islower():
            try:
                sample_btn = find_keyboard_key(kb, ch)
                if sample_btn.text().strip() == ch.upper():
                    tap_keyboard_key(kb, "SHIFT")
            except AssertionError:
                pass
            tap_keyboard_key(kb, ch)
        else:
            tap_keyboard_key(kb, ch)

    if press_done:
        kb_now = find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
        if kb_now is not None and kb_now.isVisible():
            tap_keyboard_key(kb_now, "DONE")


def clear_input_via_keyboard(harness: AppHarness, field_widget: Any, max_chars: int = 32) -> None:
    """Clear an input field using VirtualKeyboardOverlay BACKSPACE key."""
    focus_input_field(field_widget)
    kb = find_overlay(harness, "virtual_keyboard_overlay", require_visible=True)
    assert kb is not None and kb.isVisible(), "virtual_keyboard_overlay did not open"
    edit = find_line_edit(field_widget)
    for _ in range(max_chars):
        if not edit.text():
            break
        tap_keyboard_key(kb, "BACKSPACE")


def find_patient_cards(patient_screen: Any) -> list[Any]:
    """Return ordered list of visible patient card widgets inside ``patient_scroll_area``."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QWidget

    scroll_area = find_widget(patient_screen, "patient_scroll_area")
    container = scroll_area.widget()
    if container is None:
        return []

    cards: list[Any] = []
    layout = container.layout()
    if layout is not None:
        for idx in range(layout.count()):
            item = layout.itemAt(idx)
            w = item.widget() if item is not None else None
            if w is not None and w.width() >= 400 and w.height() >= 50:
                cards.append(w)

    if not cards:
        for child in container.children():
            if isinstance(child, QWidget) and child.width() >= 400 and child.height() >= 50:
                cards.append(child)

    cards.sort(key=lambda c: c.mapTo(container, QPoint(0, 0)).y())
    return cards


def scroll_into_view_via_drag(scroll_area: Any, target_widget: Any, max_drags: int = 15) -> None:
    """Drag-scroll ``scroll_area`` until ``target_widget`` center is inside viewport."""
    from PyQt6.QtCore import QPoint

    vp = scroll_area.viewport()
    for _ in range(max_drags):
        pos_in_vp = target_widget.mapTo(vp, target_widget.rect().center())
        if 8 <= pos_in_vp.y() <= vp.height() - 8:
            return
        dy = -140 if pos_in_vp.y() > vp.height() - 8 else 140
        before = scroll_area.verticalScrollBar().value()
        touch_drag(scroll_area, dy_px=dy, start_ratio=(0.5, 0.5))
        after = scroll_area.verticalScrollBar().value()
        if after == before:
            break


def find_settings_row_control(row_widget: Any) -> Any:
    """Find the interactive control widget on the right half of a Settings row."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QAbstractButton, QComboBox, QLineEdit, QWidget

    for cls in (QComboBox, QLineEdit, QAbstractButton):
        matches = [c for c in row_widget.findChildren(cls) if c.isVisible()]
        if matches:
            matches.sort(key=lambda c: c.mapTo(row_widget, QPoint(0, 0)).x(), reverse=True)
            return matches[0]

    candidates = [
        c
        for c in row_widget.findChildren(QWidget)
        if c.isVisible() and c.mapTo(row_widget, QPoint(0, 0)).x() >= row_widget.width() * 0.45
    ]
    assert candidates, f"No interactive control found in {row_widget.objectName()!r}"
    candidates.sort(key=lambda c: c.mapTo(row_widget, QPoint(0, 0)).x(), reverse=True)
    return candidates[0]


def select_settings_dropdown(harness: AppHarness, row_widget: Any, option_text: str) -> None:
    """Select an option from SETTINGS 4 dropdown control via UI events."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QAbstractButton, QAbstractItemView, QApplication, QComboBox, QMenu, QWidget

    ctrl = find_settings_row_control(row_widget)
    click_widget(ctrl)
    pump_events(60)

    # 1. Check any newly opened popup / menu / list view
    for top in QApplication.topLevelWidgets():
        if not top.isVisible() or top is harness.window:
            continue
        if isinstance(top, QMenu):
            for act in top.actions():
                if option_text.lower() in act.text().lower():
                    rect = top.actionGeometry(act)
                    QTest.mouseClick(top, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
                    pump_events(50)
                    return
        for btn in top.findChildren(QAbstractButton):
            if btn.isVisible() and option_text.lower() in btn.text().lower():
                click_widget(btn)
                return
        for view in top.findChildren(QAbstractItemView):
            if view.isVisible():
                model = view.model()
                for row in range(model.rowCount()):
                    idx = model.index(row, 0)
                    if option_text.lower() in str(idx.data()).lower():
                        vrect = view.visualRect(idx)
                        QTest.mouseClick(
                            view.viewport(),
                            Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier,
                            vrect.center(),
                        )
                        pump_events(50)
                        return

    # 2. Check inside window overlays (custom dropdown popup)
    for btn in harness.window.findChildren(QAbstractButton):
        if btn is ctrl:
            continue
        if btn.isVisible() and option_text.lower() == btn.text().strip().lower():
            click_widget(btn)
            return

    # 3. Fallback for native QComboBox under offscreen QPA where popup view isn't popped out
    if isinstance(ctrl, QComboBox):
        idx = ctrl.findText(option_text)
        assert idx >= 0, f"Option {option_text!r} not found in QComboBox"
        ctrl.setCurrentIndex(idx)
        ctrl.activated.emit(idx)
        ctrl.textActivated.emit(option_text)
        pump_events(50)
        return

    raise AssertionError(f"Could not select dropdown option {option_text!r} in {row_widget.objectName()!r}")


# ---------------------------------------------------------------------------
# Color & Image Inspection Helpers
# ---------------------------------------------------------------------------


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert '#RRGGBB' to (r, g, b)."""
    clean = hex_color.lstrip("#")
    return int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16)


def rgb_distance(rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int]) -> float:
    """Euclidean RGB color distance."""
    return math.sqrt(
        (rgb_a[0] - rgb_b[0]) ** 2
        + (rgb_a[1] - rgb_b[1]) ** 2
        + (rgb_a[2] - rgb_b[2]) ** 2
    )


def grab_image(widget: Any) -> Any:
    """Grab a QWidget as ARGB32 QImage."""
    from PyQt6.QtGui import QImage

    return widget.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)


def count_color_pixels(
    img: Any,
    target_hex: str,
    *,
    rect: Any = None,
    tolerance: int = 18,
    stride: int = 2,
) -> int:
    """Count sampled pixels within Euclidean RGB distance ``tolerance`` of ``target_hex``."""
    tr, tg, tb = hex_to_rgb(target_hex)
    x0 = 0 if rect is None else max(0, rect.left())
    y0 = 0 if rect is None else max(0, rect.top())
    x1 = img.width() if rect is None else min(img.width(), rect.right() + 1)
    y1 = img.height() if rect is None else min(img.height(), rect.bottom() + 1)

    tol_sq = tolerance * tolerance
    count = 0
    for y in range(y0, y1, stride):
        for x in range(x0, x1, stride):
            px = img.pixel(x, y)
            r = (px >> 16) & 0xFF
            g = (px >> 8) & 0xFF
            b = px & 0xFF
            dist_sq = (r - tr) ** 2 + (g - tg) ** 2 + (b - tb) ** 2
            if dist_sq <= tol_sq:
                count += 1
    return count


def region_has_color(
    widget: Any,
    target_hex: str,
    *,
    rect: Any = None,
    tolerance: int = 18,
    stride: int = 2,
    min_pixels: int = 5,
) -> bool:
    """Return True if ``widget`` screenshot contains at least ``min_pixels`` matching ``target_hex``."""
    img = grab_image(widget)
    return count_color_pixels(img, target_hex, rect=rect, tolerance=tolerance, stride=stride) >= min_pixels


def images_differ(img_a: Any, img_b: Any, *, stride: int = 2, min_changed: int = 10) -> bool:
    """Return True if two same-sized QImages differ by at least ``min_changed`` sampled pixels."""
    if img_a.size() != img_b.size():
        return True
    changed = 0
    for y in range(0, img_a.height(), stride):
        for x in range(0, img_a.width(), stride):
            if img_a.pixel(x, y) != img_b.pixel(x, y):
                changed += 1
                if changed >= min_changed:
                    return True
    return False
