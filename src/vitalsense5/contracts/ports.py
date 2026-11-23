"""Runtime-checkable Protocol ports separating VitalSense5 UI from backend/DB."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    DeviceStatus,
    PatientRecord,
    SettingSlot,
    VitalSnapshot,
    WaveformBatch,
)


@runtime_checkable
class VitalDataPort(Protocol):
    """Stream and telemetry port implemented by mock or UART/ML backend adapters."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def latest_vitals(self) -> VitalSnapshot: ...

    def pop_waveform_samples(self) -> WaveformBatch: ...

    def device_status(self) -> DeviceStatus: ...


@runtime_checkable
class SimulationControlPort(Protocol):
    """Optional test/demo profile switcher kept separate from production VitalDataPort."""

    def set_simulation_profile(self, profile: str) -> None: ...


@runtime_checkable
class PatientStorePort(Protocol):
    """Persistence port for listing, selecting, creating, and updating patients."""

    def list_patients(self) -> list[PatientRecord]: ...

    def get_active_patient(self) -> PatientRecord | None: ...

    def set_active_patient(self, patient_id: str) -> PatientRecord: ...

    def create_patient(
        self,
        name: str,
        age: int,
        height_cm: int,
        weight_kg: int,
    ) -> PatientRecord: ...

    def update_patient(
        self,
        patient_id: str,
        name: str,
        age: int,
        height_cm: int,
        weight_kg: int,
    ) -> PatientRecord: ...


@runtime_checkable
class SettingsPort(Protocol):
    """Configuration port backing the generic SETTINGS 1..8 modal slots."""

    def list_settings(self) -> list[SettingSlot]: ...

    def update_setting(self, slot_index: int, value: bool | str) -> SettingSlot: ...


@runtime_checkable
class SessionCommandPort(Protocol):
    """Command port for explicit SAVE snapshot and RECORD session actions."""

    def save_snapshot(
        self,
        patient: PatientRecord | None,
        vitals: VitalSnapshot,
    ) -> tuple[bool, str]: ...

    def toggle_recording(
        self,
        active: bool,
        patient: PatientRecord | None,
    ) -> tuple[bool, str]: ...


__all__ = [
    "PatientStorePort",
    "SessionCommandPort",
    "SettingsPort",
    "SimulationControlPort",
    "VitalDataPort",
]
