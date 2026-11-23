"""In-memory patient, settings, and session command adapters for PC testing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import threading

from vitalsense5.contracts import (
    Gender,
    PatientRecord,
    SettingControlType,
    SettingSlot,
    VitalSnapshot,
)

PATIENT_BOUNDS: dict[str, tuple[int, int]] = {
    "age": (1, 120),
    "height_cm": (30, 250),
    "weight_kg": (1, 300),
}


def validate_patient_fields(
    name: str,
    age: int,
    height_cm: int,
    weight_kg: int,
    gender: Gender | str = Gender.MALE,
) -> tuple[str, int, int, int, Gender]:
    """Validate and normalize patient fields against clinical bounds."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Patient name must be a non-empty string")
    cleaned_name = name.strip()

    validated_ints: dict[str, int] = {}
    for field_name, raw_value in (
        ("age", age),
        ("height_cm", height_cm),
        ("weight_kg", weight_kg),
    ):
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise ValueError(f"{field_name} must be an integer, got {raw_value!r}")
        low, high = PATIENT_BOUNDS[field_name]
        if raw_value < low or raw_value > high:
            raise ValueError(f"{field_name} must be between {low} and {high}, got {raw_value}")
        validated_ints[field_name] = raw_value

    if isinstance(gender, Gender):
        valid_gender = gender
    elif isinstance(gender, str):
        norm = gender.strip().lower()
        if norm == "male":
            valid_gender = Gender.MALE
        elif norm == "female":
            valid_gender = Gender.FEMALE
        else:
            raise ValueError(f"gender must be 'Male' or 'Female', got {gender!r}")
    else:
        raise ValueError(f"gender must be Gender or str, got {gender!r}")

    return (
        cleaned_name,
        validated_ints["age"],
        validated_ints["height_cm"],
        validated_ints["weight_kg"],
        valid_gender,
    )


def _default_patients() -> list[PatientRecord]:
    return [
        PatientRecord("p-1", "Patient Number 1", 34, 170, 68, Gender.MALE),
        PatientRecord("p-2", "Patient Number 2", 42, 165, 60, Gender.FEMALE),
        PatientRecord("p-3", "Patient Number 3", 28, 175, 72, Gender.MALE),
        PatientRecord("p-4", "Patient Number 4", 51, 168, 74, Gender.FEMALE),
        PatientRecord("p-5", "Patient Number 5", 39, 172, 66, Gender.MALE),
        PatientRecord("p-6", "Patient Number 6", 46, 160, 58, Gender.FEMALE),
        PatientRecord("p-7", "Patient Number 7", 63, 174, 79, Gender.MALE),
        PatientRecord("p-8", "Patient Number 8", 24, 178, 70, Gender.FEMALE),
    ]


def _default_settings() -> list[SettingSlot]:
    return [
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
        SettingSlot(5, "SETTINGS 5", "SETTINGS 5", SettingControlType.TOGGLE, False),
        SettingSlot(6, "SETTINGS 6", "SETTINGS 6", SettingControlType.TOGGLE, False),
        SettingSlot(7, "SETTINGS 7", "SETTINGS 7", SettingControlType.TOGGLE, False),
        SettingSlot(8, "SETTINGS 8", "SETTINGS 8", SettingControlType.TOGGLE, False),
    ]


def _copy_setting_slot(slot: SettingSlot) -> SettingSlot:
    return SettingSlot(
        slot.slot_index,
        slot.key,
        slot.label,
        slot.control_type,
        slot.value,
        list(slot.options),
    )


class InMemoryPatientStore:
    """Thread-safe in-memory PatientStorePort implementation for standalone testing."""

    def __init__(
        self,
        patients: list[PatientRecord] | None = None,
        active_patient_id: str | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._patients: list[PatientRecord] = (
            _default_patients() if patients is None else list(patients)
        )
        known_ids = {p.patient_id for p in self._patients}
        if active_patient_id is not None:
            if active_patient_id not in known_ids:
                raise KeyError(f"Unknown active_patient_id: {active_patient_id!r}")
            self._active_id: str | None = active_patient_id
        elif self._patients:
            self._active_id = self._patients[0].patient_id
        else:
            self._active_id = None
        self._next_seq = len(self._patients) + 1

    def list_patients(self) -> list[PatientRecord]:
        """Return a snapshot list of all stored patients."""
        with self._lock:
            return list(self._patients)

    def get_active_patient(self) -> PatientRecord | None:
        """Return the currently active patient, or None when empty."""
        with self._lock:
            for patient in self._patients:
                if patient.patient_id == self._active_id:
                    return patient
            return None

    def set_active_patient(self, patient_id: str) -> PatientRecord:
        """Select the active patient by ID, raising KeyError if unknown."""
        with self._lock:
            for patient in self._patients:
                if patient.patient_id == patient_id:
                    self._active_id = patient_id
                    return patient
            raise KeyError(f"Unknown patient_id: {patient_id!r}")

    def create_patient(
        self,
        name: str,
        age: int,
        height_cm: int,
        weight_kg: int,
        gender: Gender | str = Gender.MALE,
    ) -> PatientRecord:
        """Validate, store, and auto-activate a new patient record."""
        cleaned_name, valid_age, valid_height, valid_weight, valid_gender = (
            validate_patient_fields(name, age, height_cm, weight_kg, gender)
        )
        with self._lock:
            existing_ids = {p.patient_id for p in self._patients}
            while f"p-{self._next_seq}" in existing_ids:
                self._next_seq += 1
            patient_id = f"p-{self._next_seq}"
            self._next_seq += 1

            record = PatientRecord(
                patient_id,
                cleaned_name,
                valid_age,
                valid_height,
                valid_weight,
                valid_gender,
            )
            self._patients.append(record)
            self._active_id = patient_id
            return record

    def update_patient(
        self,
        patient_id: str,
        name: str,
        age: int,
        height_cm: int,
        weight_kg: int,
        gender: Gender | str = Gender.MALE,
    ) -> PatientRecord:
        """Validate and update an existing patient record, raising KeyError if unknown."""
        with self._lock:
            target_idx: int | None = None
            for idx, patient in enumerate(self._patients):
                if patient.patient_id == patient_id:
                    target_idx = idx
                    break
            if target_idx is None:
                raise KeyError(f"Unknown patient_id: {patient_id!r}")

            cleaned_name, valid_age, valid_height, valid_weight, valid_gender = (
                validate_patient_fields(name, age, height_cm, weight_kg, gender)
            )
            updated = PatientRecord(
                patient_id,
                cleaned_name,
                valid_age,
                valid_height,
                valid_weight,
                valid_gender,
            )
            self._patients[target_idx] = updated
            return updated

    def delete_patient(self, patient_id: str) -> None:
        """Delete a patient record by ID, falling back active patient if needed."""
        with self._lock:
            target_idx: int | None = None
            for idx, patient in enumerate(self._patients):
                if patient.patient_id == patient_id:
                    target_idx = idx
                    break
            if target_idx is None:
                raise KeyError(f"Unknown patient_id: {patient_id!r}")

            self._patients.pop(target_idx)
            if self._active_id == patient_id:
                self._active_id = self._patients[0].patient_id if self._patients else None


class InMemorySettingsStore:
    """Thread-safe in-memory SettingsPort pre-seeded with Figma SETTINGS 1..8 slots."""

    def __init__(self, slots: list[SettingSlot] | None = None) -> None:
        self._lock = threading.Lock()
        raw_slots = _default_settings() if slots is None else list(slots)
        self._slots: list[SettingSlot] = [_copy_setting_slot(slot) for slot in raw_slots]

    def list_settings(self) -> list[SettingSlot]:
        """Return defensive copies of all setting slots."""
        with self._lock:
            return [_copy_setting_slot(slot) for slot in self._slots]

    def update_setting(
        self,
        slot_index: int,
        value: bool | str | int | float,
    ) -> SettingSlot:
        """Validate and update a setting slot by slot_index."""
        if isinstance(slot_index, bool) or not isinstance(slot_index, int):
            raise KeyError(f"Unknown setting slot_index: {slot_index!r}")
        with self._lock:
            for idx, slot in enumerate(self._slots):
                if slot.slot_index != slot_index:
                    continue

                validated_value: bool | str | int | float
                if slot.control_type == SettingControlType.TOGGLE:
                    if not isinstance(value, bool):
                        raise ValueError(
                            f"Slot {slot_index} expects bool for TOGGLE, got {type(value).__name__}"
                        )
                    validated_value = value
                elif slot.control_type == SettingControlType.VALUE:
                    if isinstance(value, bool):
                        raise ValueError(
                            f"Slot {slot_index} expects str/int/float for VALUE, got bool"
                        )
                    if isinstance(value, str):
                        stripped = value.strip()
                        if not stripped:
                            raise ValueError(f"Slot {slot_index} VALUE must not be empty")
                        validated_value = stripped
                    elif isinstance(value, int):
                        validated_value = value
                    elif isinstance(value, float):
                        if not math.isfinite(value):
                            raise ValueError(f"Slot {slot_index} float value must be finite")
                        validated_value = value
                    else:
                        raise ValueError(
                            f"Slot {slot_index} expects str/int/float for VALUE, got {type(value).__name__}"
                        )
                elif slot.control_type == SettingControlType.DROPDOWN:
                    if not isinstance(value, str):
                        raise ValueError(
                            f"Slot {slot_index} expects str for DROPDOWN, got {type(value).__name__}"
                        )
                    if slot.options and value not in slot.options:
                        raise ValueError(
                            f"Slot {slot_index} option {value!r} not in allowed options {slot.options!r}"
                        )
                    validated_value = value
                else:
                    raise ValueError(f"Unsupported control type {slot.control_type!r}")

                updated = SettingSlot(
                    slot.slot_index,
                    slot.key,
                    slot.label,
                    slot.control_type,
                    validated_value,
                    list(slot.options),
                )
                self._slots[idx] = updated
                return _copy_setting_slot(updated)

            raise KeyError(f"Unknown setting slot_index: {slot_index!r}")


@dataclass(frozen=True)
class SavedSnapshotRecord:
    """Recorded snapshot entry stored by MockSessionCommandHandler."""

    patient: PatientRecord | None
    vitals: VitalSnapshot
    saved_at: datetime


class MockSessionCommandHandler:
    """Thread-safe SessionCommandPort capturing SAVE and RECORD actions in memory."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshots: list[SavedSnapshotRecord] = []
        self._recording_active: bool = False
        self._recording_patient: PatientRecord | None = None
        self._recording_events: list[tuple[bool, PatientRecord | None, datetime]] = []

    @property
    def is_recording(self) -> bool:
        """Return whether recording is currently active."""
        with self._lock:
            return self._recording_active

    @property
    def recording_patient(self) -> PatientRecord | None:
        """Return the patient associated with the active recording session, if any."""
        with self._lock:
            return self._recording_patient

    def list_saved_snapshots(self) -> list[SavedSnapshotRecord]:
        """Return a copy of all saved snapshot records."""
        with self._lock:
            return list(self._snapshots)

    def list_recording_events(self) -> list[tuple[bool, PatientRecord | None, datetime]]:
        """Return a copy of all recording toggle events."""
        with self._lock:
            return list(self._recording_events)

    def save_snapshot(
        self,
        patient: PatientRecord | None,
        vitals: VitalSnapshot,
    ) -> tuple[bool, str]:
        """Store a snapshot in memory and return a user-facing status tuple."""
        with self._lock:
            self._snapshots.append(
                SavedSnapshotRecord(
                    patient=patient,
                    vitals=vitals,
                    saved_at=datetime.now(),
                )
            )
        if patient is not None:
            return True, f"Snapshot saved for {patient.name}"
        return True, "Snapshot saved (no active patient)"

    def toggle_recording(
        self,
        active: bool,
        patient: PatientRecord | None,
    ) -> tuple[bool, str]:
        """Update recording state and return a user-facing status tuple."""
        target_active = bool(active)
        with self._lock:
            self._recording_active = target_active
            self._recording_patient = patient if target_active else None
            self._recording_events.append((target_active, patient, datetime.now()))

        if target_active:
            if patient is not None:
                return True, f"Recording started for {patient.name}"
            return True, "Recording started"
        return True, "Recording stopped"


__all__ = [
    "InMemoryPatientStore",
    "InMemorySettingsStore",
    "MockSessionCommandHandler",
    "PATIENT_BOUNDS",
    "SavedSnapshotRecord",
    "validate_patient_fields",
]
