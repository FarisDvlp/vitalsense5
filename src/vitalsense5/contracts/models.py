"""Immutable domain models and enums for VitalSense5 frontend-backend contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ConnectionState(Enum):
    """UART / ESP32-S3 transport connection state."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


class CloudState(Enum):
    """Cloud database synchronization state."""

    ONLINE = "online"
    OFFLINE = "offline"
    SYNCING = "syncing"
    ERROR = "error"


class SensorState(Enum):
    """MAX30102 optical PPG sensor signal state."""

    OK = "ok"
    FINGER_OFF = "finger_off"
    POOR_SIGNAL = "poor_signal"
    CALIBRATING = "calibrating"


class AlarmLevel(Enum):
    """Clinical alarm severity level for vital sign columns."""

    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


class SettingControlType(Enum):
    """Supported control types for generic Settings modal slots."""

    TOGGLE = "toggle"
    VALUE = "value"
    DROPDOWN = "dropdown"


class Gender(Enum):
    """Patient biological sex / gender selection."""

    MALE = "Male"
    FEMALE = "Female"


@dataclass(frozen=True)
class VitalSnapshot:
    """Latest vital sign measurements and per-parameter alarm states."""

    prv_rmssd_ms: float | None = None
    rr_brpm: float | None = None
    pi_percent: float | None = None
    spo2_percent: float | None = None
    bp_sys_mmhg: int | None = None
    bp_dia_mmhg: int | None = None
    bpm: int | None = None
    alarms: dict[str, AlarmLevel] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class WaveformBatch:
    """Batch of normalized PPG waveform samples from the signal pipeline."""

    samples: list[float] = field(default_factory=list)
    sample_rate_hz: float = 125.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class DeviceStatus:
    """Hardware, connectivity, power, and recording telemetry."""

    uart_state: ConnectionState = ConnectionState.CONNECTED
    esp32_state: ConnectionState = ConnectionState.CONNECTED
    sensor_state: SensorState = SensorState.OK
    cloud_state: CloudState = CloudState.ONLINE
    battery_percent: int = 95
    battery_voltage: float = 8.2
    is_charging: bool = False
    recording_active: bool = False
    recording_elapsed_s: int = 0
    status_message: str = ""


@dataclass(frozen=True)
class PatientRecord:
    """Patient demographic record displayed and edited in the frontend."""

    patient_id: str
    name: str
    age: int
    height_cm: int
    weight_kg: int
    gender: Gender = Gender.MALE


@dataclass(frozen=True)
class SettingSlot:
    """Configuration slot rendered in the Settings modal."""

    slot_index: int
    key: str
    label: str
    control_type: SettingControlType
    value: bool | str | int | float
    options: list[str] = field(default_factory=list)


__all__ = [
    "AlarmLevel",
    "CloudState",
    "ConnectionState",
    "DeviceStatus",
    "Gender",
    "PatientRecord",
    "SensorState",
    "SettingControlType",
    "SettingSlot",
    "VitalSnapshot",
    "WaveformBatch",
]
