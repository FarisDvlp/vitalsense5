"""Unit tests for VitalSense5 M2 contracts and mock/in-memory adapters (zero Qt)."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import datetime
import math
from pathlib import Path
import threading

import pytest

from vitalsense5.adapters import (
    PATIENT_BOUNDS,
    SIMULATION_PROFILES,
    VITAL_ALARM_KEYS,
    InMemoryPatientStore,
    InMemorySettingsStore,
    MockSessionCommandHandler,
    MockVitalDataAdapter,
    compute_vital_alarms,
    synthesize_ppg_sample,
)
from vitalsense5.contracts import (
    AlarmLevel,
    CloudState,
    ConnectionState,
    DeviceStatus,
    PatientRecord,
    PatientStorePort,
    SensorState,
    SessionCommandPort,
    SettingControlType,
    SettingSlot,
    SettingsPort,
    SimulationControlPort,
    VitalDataPort,
    VitalSnapshot,
    WaveformBatch,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_VITALSENSE = REPO_ROOT / "src" / "vitalsense5"


def _collect_imports(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0].lower())
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0].lower())
    return imported


def test_contracts_and_adapters_have_zero_forbidden_imports() -> None:
    forbidden = {
        "pyqt6",
        "pyside6",
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
    for subdir in ("contracts", "adapters"):
        target_dir = SRC_VITALSENSE / subdir
        py_files = sorted(target_dir.rglob("*.py"))
        assert py_files, f"No python files found in {target_dir}"
        for py_file in py_files:
            hits = _collect_imports(py_file) & forbidden
            assert not hits, f"Forbidden imports {hits} in {py_file}"


def test_protocol_conformance_and_simulation_port_separation() -> None:
    vital_adapter = MockVitalDataAdapter()
    patient_store = InMemoryPatientStore()
    settings_store = InMemorySettingsStore()
    command_handler = MockSessionCommandHandler()

    assert isinstance(vital_adapter, VitalDataPort)
    assert isinstance(vital_adapter, SimulationControlPort)
    assert isinstance(patient_store, PatientStorePort)
    assert isinstance(settings_store, SettingsPort)
    assert isinstance(command_handler, SessionCommandPort)

    class ProductionVitalStub:
        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def latest_vitals(self) -> VitalSnapshot:
            return VitalSnapshot()

        def pop_waveform_samples(self) -> WaveformBatch:
            return WaveformBatch()

        def device_status(self) -> DeviceStatus:
            return DeviceStatus()

    stub = ProductionVitalStub()
    assert isinstance(stub, VitalDataPort)
    assert not isinstance(stub, SimulationControlPort)


def test_enums_and_dto_positional_construction_and_immutability() -> None:
    assert {m.name for m in ConnectionState} == {"CONNECTED", "DISCONNECTED", "RECONNECTING"}
    assert {m.name for m in CloudState} == {"ONLINE", "OFFLINE", "SYNCING", "ERROR"}
    assert {m.name for m in SensorState} == {"OK", "FINGER_OFF", "POOR_SIGNAL", "CALIBRATING"}
    assert {m.name for m in AlarmLevel} == {"NORMAL", "WARNING", "CRITICAL"}
    assert {m.name for m in SettingControlType} == {"TOGGLE", "VALUE", "DROPDOWN"}

    patient = PatientRecord("p-1", "Patient Number 1", 34, 170, 68)
    assert patient.patient_id == "p-1"
    assert patient.name == "Patient Number 1"
    assert patient.age == 34
    assert patient.height_cm == 170
    assert patient.weight_kg == 68

    slot_default_opts = SettingSlot(1, "SETTINGS 1", "SETTINGS 1", SettingControlType.TOGGLE, False)
    slot_kw_opts = SettingSlot(
        4,
        "SETTINGS 4",
        "SETTINGS 4",
        SettingControlType.DROPDOWN,
        "Option A",
        options=["Option A", "Option B"],
    )
    slot_pos_opts = SettingSlot(
        4,
        "SETTINGS 4",
        "SETTINGS 4",
        SettingControlType.DROPDOWN,
        "Option B",
        ["Option A", "Option B"],
    )
    assert slot_default_opts.options == []
    assert slot_kw_opts.options == ["Option A", "Option B"]
    assert slot_pos_opts.value == "Option B"

    snapshot = VitalSnapshot()
    assert snapshot.prv_rmssd_ms is None
    assert snapshot.bpm is None
    assert snapshot.alarms == {}
    assert isinstance(snapshot.timestamp, datetime)

    batch = WaveformBatch()
    assert batch.samples == []
    assert batch.sample_rate_hz == 200.0
    assert isinstance(batch.timestamp, datetime)

    status = DeviceStatus()
    assert status.uart_state == ConnectionState.CONNECTED
    assert status.battery_percent == 95
    assert status.battery_voltage == 8.2

    with pytest.raises(FrozenInstanceError):
        patient.name = "Changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        slot_default_opts.value = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.bpm = 80  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        batch.sample_rate_hz = 250.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        status.battery_percent = 50  # type: ignore[misc]


def test_ppg_waveform_lifecycle_bounds_and_progression() -> None:
    adapter = MockVitalDataAdapter(sample_rate_hz=200.0)

    # Stopped initially -> no samples
    assert adapter.pop_waveform_samples().samples == []

    adapter.start()
    batches = [adapter.pop_waveform_samples() for _ in range(12)]
    all_samples = [sample for batch in batches for sample in batch.samples]

    assert all(batch.sample_rate_hz == 200.0 for batch in batches)
    assert all(len(batch.samples) >= 1 for batch in batches)
    assert all(-1.0 <= s <= 1.0 for s in all_samples)
    assert max(all_samples) > 0.3
    assert min(all_samples) < -0.3
    assert batches[0].samples != batches[1].samples

    adapter.stop()
    assert adapter.pop_waveform_samples().samples == []


def test_synthesize_ppg_sample_and_invalid_adapter_init() -> None:
    waveform = [synthesize_ppg_sample(i / 100.0) for i in range(100)]
    assert all(-1.0 <= s <= 1.0 for s in waveform)
    # Systolic peak near phase 0.22 must exceed dicrotic peak near phase 0.46
    assert synthesize_ppg_sample(0.22) > synthesize_ppg_sample(0.46) > synthesize_ppg_sample(0.85)

    with pytest.raises(ValueError):
        MockVitalDataAdapter(sample_rate_hz=0.0)
    with pytest.raises(ValueError):
        MockVitalDataAdapter(sample_rate_hz=math.nan)
    with pytest.raises(ValueError):
        MockVitalDataAdapter(initial_profile="invalid_profile")


def test_mock_vital_adapter_normal_ranges_and_alarms() -> None:
    adapter = MockVitalDataAdapter()
    adapter.start()
    vitals = adapter.latest_vitals()
    status = adapter.device_status()

    assert vitals.prv_rmssd_ms is not None and 45.0 <= vitals.prv_rmssd_ms <= 90.0
    assert vitals.rr_brpm is not None and 12.0 <= vitals.rr_brpm <= 20.0
    assert vitals.pi_percent is not None and 1.5 <= vitals.pi_percent <= 8.0
    assert vitals.spo2_percent is not None and 95.0 <= vitals.spo2_percent <= 100.0
    assert vitals.bp_sys_mmhg is not None and 90 <= vitals.bp_sys_mmhg <= 129
    assert vitals.bp_dia_mmhg is not None and 60 <= vitals.bp_dia_mmhg <= 84
    assert vitals.bpm is not None and 60 <= vitals.bpm <= 100

    assert set(vitals.alarms.keys()) == set(VITAL_ALARM_KEYS)
    assert all(level == AlarmLevel.NORMAL for level in vitals.alarms.values())
    assert status.uart_state == ConnectionState.CONNECTED
    assert status.esp32_state == ConnectionState.CONNECTED
    assert status.sensor_state == SensorState.OK
    assert status.cloud_state == CloudState.ONLINE


@pytest.mark.parametrize(
    "profile",
    [
        "normal",
        "warning",
        "critical",
        "alarm_critical",
        "finger_off",
        "poor_signal",
        "uart_disconnected",
        "low_battery",
        "cloud_offline",
    ],
)
def test_mock_vital_adapter_all_simulation_profiles(profile: str) -> None:
    assert profile in SIMULATION_PROFILES
    adapter = MockVitalDataAdapter()
    adapter.start()
    adapter.set_simulation_profile(profile)
    assert adapter.profile == profile

    vitals = adapter.latest_vitals()
    batch = adapter.pop_waveform_samples()
    status = adapter.device_status()

    assert set(vitals.alarms.keys()) == set(VITAL_ALARM_KEYS)

    if profile == "normal":
        assert all(v == AlarmLevel.NORMAL for v in vitals.alarms.values())
        assert len(batch.samples) > 0
    elif profile == "warning":
        assert AlarmLevel.WARNING in vitals.alarms.values()
        assert AlarmLevel.CRITICAL not in vitals.alarms.values()
        assert len(batch.samples) > 0
    elif profile in ("critical", "alarm_critical"):
        assert AlarmLevel.CRITICAL in vitals.alarms.values()
        assert vitals.spo2_percent is not None and vitals.spo2_percent < 90.0
        assert len(batch.samples) > 0
    elif profile == "finger_off":
        assert status.sensor_state == SensorState.FINGER_OFF
        assert batch.samples == []
        assert vitals.prv_rmssd_ms is None
        assert vitals.spo2_percent is None
        assert vitals.bp_sys_mmhg is None
        assert vitals.bpm is None
    elif profile == "poor_signal":
        assert status.sensor_state == SensorState.POOR_SIGNAL
        assert len(batch.samples) > 0
        assert all(-1.0 <= s <= 1.0 for s in batch.samples)
        assert vitals.spo2_percent is not None
    elif profile == "uart_disconnected":
        assert status.uart_state == ConnectionState.DISCONNECTED
        assert status.esp32_state == ConnectionState.DISCONNECTED
        assert batch.samples == []
        assert vitals.prv_rmssd_ms is None
        assert vitals.spo2_percent is None
        assert vitals.bp_dia_mmhg is None
    elif profile == "low_battery":
        assert status.battery_percent <= 20
        assert not status.is_charging
        assert len(batch.samples) > 0
    elif profile == "cloud_offline":
        assert status.cloud_state == CloudState.OFFLINE
        assert len(batch.samples) > 0


def test_mock_vital_adapter_invalid_profile_and_recording_flag() -> None:
    adapter = MockVitalDataAdapter()
    with pytest.raises(ValueError, match="Unknown simulation profile"):
        adapter.set_simulation_profile("does_not_exist")
    with pytest.raises(ValueError, match="Unknown simulation profile"):
        adapter.set_simulation_profile(["normal"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unknown simulation profile"):
        adapter.set_simulation_profile(123)  # type: ignore[arg-type]

    assert adapter.device_status().recording_active is False
    adapter.set_recording_state(True)
    assert adapter.device_status().recording_active is True
    adapter.set_recording_state(False)
    assert adapter.device_status().recording_active is False


def test_compute_vital_alarms_thresholds() -> None:
    alarms = compute_vital_alarms(
        prv_rmssd_ms=40.0,
        rr_brpm=16.0,
        pi_percent=0.4,
        spo2_percent=83.0,
        bp_sys_mmhg=135,
        bp_dia_mmhg=82,
    )
    assert alarms == {
        "PRV": AlarmLevel.WARNING,
        "RR": AlarmLevel.NORMAL,
        "PI": AlarmLevel.CRITICAL,
        "SpO2": AlarmLevel.CRITICAL,
        "BP": AlarmLevel.WARNING,
    }


@pytest.mark.parametrize("bad_val", [float("nan"), float("inf"), float("-inf")])
def test_compute_vital_alarms_non_finite_floats_are_warning(bad_val: float) -> None:
    alarms = compute_vital_alarms(
        prv_rmssd_ms=bad_val,
        rr_brpm=bad_val,
        pi_percent=bad_val,
        spo2_percent=bad_val,
        bp_sys_mmhg=120,
        bp_dia_mmhg=80,
    )
    assert alarms == {
        "PRV": AlarmLevel.WARNING,
        "RR": AlarmLevel.WARNING,
        "PI": AlarmLevel.WARNING,
        "SpO2": AlarmLevel.WARNING,
        "BP": AlarmLevel.NORMAL,
    }


def test_mock_vital_adapter_thread_safety() -> None:
    adapter = MockVitalDataAdapter()
    adapter.start()
    errors: list[Exception] = []

    def reader() -> None:
        try:
            for _ in range(50):
                _ = adapter.latest_vitals()
                batch = adapter.pop_waveform_samples()
                assert all(-1.0 <= s <= 1.0 for s in batch.samples)
                _ = adapter.device_status()
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    def switcher() -> None:
        try:
            for profile in ("normal", "warning", "critical", "finger_off", "poor_signal") * 10:
                adapter.set_simulation_profile(profile)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(3)] + [
        threading.Thread(target=switcher)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive()

    assert errors == []


def test_in_memory_patient_store_crud_selection_and_validation() -> None:
    store = InMemoryPatientStore()
    seeded = store.list_patients()
    assert len(seeded) == 8
    assert seeded[0].name == "Patient Number 1"
    assert seeded[-1].name == "Patient Number 8"
    active = store.get_active_patient()
    assert active is not None and active.patient_id == "p-1"

    selected = store.set_active_patient("p-3")
    assert selected.patient_id == "p-3"
    assert store.get_active_patient() == selected

    created = store.create_patient("  Budi Santoso  ", 1, 30, 1)
    assert created.name == "Budi Santoso"
    assert created.age == 1
    assert created.height_cm == 30
    assert created.weight_kg == 1
    assert store.get_active_patient() == created
    assert len(store.list_patients()) == 9

    updated = store.update_patient(created.patient_id, "Budi S.", 120, 250, 300)
    assert updated.patient_id == created.patient_id
    assert updated.name == "Budi S."
    assert (updated.age, updated.height_cm, updated.weight_kg) == (120, 250, 300)

    # Empty store support
    empty_store = InMemoryPatientStore(patients=[])
    assert empty_store.list_patients() == []
    assert empty_store.get_active_patient() is None
    first = empty_store.create_patient("First Patient", 30, 170, 65)
    assert empty_store.get_active_patient() == first

    with pytest.raises(KeyError):
        InMemoryPatientStore(active_patient_id="missing")
    with pytest.raises(KeyError):
        store.set_active_patient("unknown-id")
    with pytest.raises(KeyError):
        store.update_patient("unknown-id", "Valid Name", 30, 170, 65)


@pytest.mark.parametrize(
    ("name", "age", "height_cm", "weight_kg"),
    [
        ("", 30, 170, 65),
        ("   ", 30, 170, 65),
        ("Valid", PATIENT_BOUNDS["age"][0] - 1, 170, 65),
        ("Valid", PATIENT_BOUNDS["age"][1] + 1, 170, 65),
        ("Valid", 30, PATIENT_BOUNDS["height_cm"][0] - 1, 65),
        ("Valid", 30, PATIENT_BOUNDS["height_cm"][1] + 1, 65),
        ("Valid", 30, 170, PATIENT_BOUNDS["weight_kg"][0] - 1),
        ("Valid", 30, 170, PATIENT_BOUNDS["weight_kg"][1] + 1),
        ("Valid", True, 170, 65),  # type: ignore[arg-type]
    ],
)
def test_in_memory_patient_store_rejects_invalid_fields(
    name: str, age: int, height_cm: int, weight_kg: int
) -> None:
    store = InMemoryPatientStore()
    with pytest.raises(ValueError):
        store.create_patient(name, age, height_cm, weight_kg)
    with pytest.raises(ValueError):
        store.update_patient("p-1", name, age, height_cm, weight_kg)


def test_in_memory_settings_store_defaults_updates_and_errors() -> None:
    store = InMemorySettingsStore()
    slots = store.list_settings()
    assert len(slots) == 8
    assert [s.slot_index for s in slots] == list(range(1, 9))
    assert [s.key for s in slots] == [f"SETTINGS {i}" for i in range(1, 9)]

    assert slots[0].control_type == SettingControlType.TOGGLE and slots[0].value is False
    assert slots[1].control_type == SettingControlType.TOGGLE and slots[1].value is True
    assert slots[2].control_type == SettingControlType.VALUE and slots[2].value == "000"
    assert slots[3].control_type == SettingControlType.DROPDOWN
    assert slots[3].value == "Option A"
    assert slots[3].options == ["Option A", "Option B", "Option C"]
    for idx in range(4, 8):
        assert slots[idx].control_type == SettingControlType.TOGGLE and slots[idx].value is False

    # Mutating returned options list must not affect store state
    slots[3].options.append("Tampered")
    assert store.list_settings()[3].options == ["Option A", "Option B", "Option C"]

    updated_toggle = store.update_setting(1, True)
    assert updated_toggle.value is True
    updated_val = store.update_setting(3, " 125 ")
    assert updated_val.value == "125"
    updated_drop = store.update_setting(4, "Option C")
    assert updated_drop.value == "Option C"

    persisted = {s.slot_index: s for s in store.list_settings()}
    assert persisted[1].value is True
    assert persisted[3].value == "125"
    assert persisted[4].value == "Option C"

    with pytest.raises(KeyError):
        store.update_setting(0, True)
    with pytest.raises(KeyError):
        store.update_setting(9, True)
    with pytest.raises(KeyError):
        store.update_setting(True, True)
    with pytest.raises(KeyError):
        store.update_setting(False, True)
    with pytest.raises(KeyError):
        store.update_setting(1.0, True)  # type: ignore[arg-type]
    with pytest.raises(KeyError):
        store.update_setting("1", True)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        store.update_setting(1, "true")
    with pytest.raises(ValueError):
        store.update_setting(3, True)
    with pytest.raises(ValueError):
        store.update_setting(3, "   ")
    with pytest.raises(ValueError):
        store.update_setting(4, "Invalid Option")
    with pytest.raises(ValueError):
        store.update_setting(4, False)


def test_mock_session_command_handler_save_and_record() -> None:
    handler = MockSessionCommandHandler()
    patient = PatientRecord("p-1", "Patient Number 1", 34, 170, 68)
    vitals = VitalSnapshot(prv_rmssd_ms=68.0, spo2_percent=98.0, bpm=72)

    ok_save, msg_save = handler.save_snapshot(patient, vitals)
    assert ok_save is True
    assert "Patient Number 1" in msg_save

    ok_none, msg_none = handler.save_snapshot(None, vitals)
    assert ok_none is True
    assert msg_none
    assert len(handler.list_saved_snapshots()) == 2

    ok_start, msg_start = handler.toggle_recording(True, patient)
    assert ok_start is True
    assert "started" in msg_start.lower()
    assert handler.is_recording is True
    assert handler.recording_patient == patient

    ok_stop, msg_stop = handler.toggle_recording(False, patient)
    assert ok_stop is True
    assert "stopped" in msg_stop.lower()
    assert handler.is_recording is False
    assert handler.recording_patient is None
    assert len(handler.list_recording_events()) == 2


def test_in_memory_patient_store_explicit_active_id_and_seq_collision_skip() -> None:
    patients = [
        PatientRecord("p-2", "Second Patient", 40, 170, 68),
        PatientRecord("p-5", "Fifth Patient", 50, 175, 72),
    ]
    store = InMemoryPatientStore(patients=patients, active_patient_id="p-2")
    active = store.get_active_patient()
    assert active is not None and active.patient_id == "p-2"

    # _next_seq starts at len(patients)+1 == 3 -> skips nothing at 3, or if p-2/p-3 exist skips p-3
    store_collide = InMemoryPatientStore(
        patients=[
            PatientRecord("p-1", "One", 30, 170, 65),
            PatientRecord("p-3", "Three", 35, 172, 70),
        ]
    )
    created = store_collide.create_patient("Four", 28, 168, 60)
    assert created.patient_id == "p-4"
    assert store_collide.get_active_patient() == created


def test_in_memory_settings_store_numeric_and_invalid_value_types() -> None:
    store = InMemorySettingsStore()
    assert store.update_setting(3, 42).value == 42
    assert store.update_setting(3, 3.5).value == 3.5

    for bad_val in (float("nan"), float("inf"), float("-inf"), True, ["bad"]):
        with pytest.raises(ValueError):
            store.update_setting(3, bad_val)  # type: ignore[arg-type]


def test_in_memory_patient_store_gender_and_delete_fallback() -> None:
    from vitalsense5.contracts import Gender

    store = InMemoryPatientStore()
    created = store.create_patient("Amina", 27, 160, 54, gender=Gender.FEMALE)
    assert created.gender == Gender.FEMALE
    assert store.get_active_patient() == created

    updated = store.update_patient(created.patient_id, "Amina", 28, 161, 55, gender="Male")
    assert updated.gender == Gender.MALE

    with pytest.raises(ValueError):
        store.create_patient("Bad", 30, 170, 65, gender="Other")

    # Deleting active patient falls back to first remaining patient
    store.delete_patient(created.patient_id)
    assert store.get_active_patient() is not None
    assert store.get_active_patient().patient_id == "p-1"

    with pytest.raises(KeyError):
        store.delete_patient("p-nonexistent")

    # Deleting all patients leaves get_active_patient() == None
    for p in list(store.list_patients()):
        store.delete_patient(p.patient_id)
    assert store.list_patients() == []
    assert store.get_active_patient() is None
