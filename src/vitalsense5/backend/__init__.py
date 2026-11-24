"""Hardware and ML backend adapters for VitalSense5."""

from __future__ import annotations

from .serial_vital_adapter import (
    SerialVitalAdapter,
    patient_record_to_demographics,
)

__all__ = ["SerialVitalAdapter", "patient_record_to_demographics"]
