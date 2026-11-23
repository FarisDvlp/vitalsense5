"""Standalone PC mock adapters implementing VitalSense5 contracts."""

from __future__ import annotations

from .memory_stores import (
    PATIENT_BOUNDS,
    InMemoryPatientStore,
    InMemorySettingsStore,
    MockSessionCommandHandler,
    SavedSnapshotRecord,
    validate_patient_fields,
)
from .mock_vital_adapter import (
    SIMULATION_PROFILES,
    VITAL_ALARM_KEYS,
    MockVitalDataAdapter,
    compute_vital_alarms,
    synthesize_ppg_sample,
)

__all__ = [
    "InMemoryPatientStore",
    "InMemorySettingsStore",
    "MockSessionCommandHandler",
    "MockVitalDataAdapter",
    "PATIENT_BOUNDS",
    "SIMULATION_PROFILES",
    "SavedSnapshotRecord",
    "VITAL_ALARM_KEYS",
    "compute_vital_alarms",
    "synthesize_ppg_sample",
    "validate_patient_fields",
]
