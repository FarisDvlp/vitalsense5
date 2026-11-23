"""Standalone PC mock vital-sign & PPG waveform adapter implementing VitalDataPort."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import threading
import time

from vitalsense5.contracts import (
    AlarmLevel,
    CloudState,
    ConnectionState,
    DeviceStatus,
    SensorState,
    VitalSnapshot,
    WaveformBatch,
)

VITAL_ALARM_KEYS: tuple[str, ...] = ("PRV", "RR", "PI", "SpO2", "BP")

SIMULATION_PROFILES: tuple[str, ...] = (
    "normal",
    "warning",
    "critical",
    "alarm_critical",
    "finger_off",
    "poor_signal",
    "uart_disconnected",
    "low_battery",
    "cloud_offline",
)


@dataclass(frozen=True)
class _ProfileSpec:
    uart_state: ConnectionState
    esp32_state: ConnectionState
    sensor_state: SensorState
    cloud_state: CloudState
    battery_percent: int
    battery_voltage: float
    is_charging: bool
    status_message: str
    has_signal: bool
    prv_base: float
    prv_amp: float
    rr_base: float
    rr_amp: float
    pi_base: float
    pi_amp: float
    spo2_base: float
    spo2_amp: float
    bp_sys_base: float
    bp_dia_base: float
    bpm_base: float
    noise_amp: float = 0.0


_PROFILE_SPECS: dict[str, _ProfileSpec] = {
    "normal": _ProfileSpec(
        uart_state=ConnectionState.CONNECTED,
        esp32_state=ConnectionState.CONNECTED,
        sensor_state=SensorState.OK,
        cloud_state=CloudState.ONLINE,
        battery_percent=95,
        battery_voltage=8.2,
        is_charging=False,
        status_message="Connected",
        has_signal=True,
        prv_base=68.0,
        prv_amp=3.0,
        rr_base=16.0,
        rr_amp=0.8,
        pi_base=3.0,
        pi_amp=0.2,
        spo2_base=98.0,
        spo2_amp=0.4,
        bp_sys_base=120.0,
        bp_dia_base=80.0,
        bpm_base=72.0,
    ),
    "warning": _ProfileSpec(
        uart_state=ConnectionState.CONNECTED,
        esp32_state=ConnectionState.CONNECTED,
        sensor_state=SensorState.OK,
        cloud_state=CloudState.ONLINE,
        battery_percent=92,
        battery_voltage=8.1,
        is_charging=False,
        status_message="Warning: abnormal vital signs",
        has_signal=True,
        prv_base=38.0,
        prv_amp=1.5,
        rr_base=23.0,
        rr_amp=0.8,
        pi_base=1.1,
        pi_amp=0.1,
        spo2_base=92.5,
        spo2_amp=0.5,
        bp_sys_base=142.0,
        bp_dia_base=90.0,
        bpm_base=108.0,
    ),
    "critical": _ProfileSpec(
        uart_state=ConnectionState.CONNECTED,
        esp32_state=ConnectionState.CONNECTED,
        sensor_state=SensorState.OK,
        cloud_state=CloudState.ONLINE,
        battery_percent=88,
        battery_voltage=8.0,
        is_charging=False,
        status_message="Critical: vital alarm threshold breached",
        has_signal=True,
        prv_base=20.0,
        prv_amp=1.0,
        rr_base=32.0,
        rr_amp=0.8,
        pi_base=0.3,
        pi_amp=0.05,
        spo2_base=84.0,
        spo2_amp=0.8,
        bp_sys_base=176.0,
        bp_dia_base=108.0,
        bpm_base=134.0,
    ),
    "alarm_critical": _ProfileSpec(
        uart_state=ConnectionState.CONNECTED,
        esp32_state=ConnectionState.CONNECTED,
        sensor_state=SensorState.OK,
        cloud_state=CloudState.ONLINE,
        battery_percent=88,
        battery_voltage=8.0,
        is_charging=False,
        status_message="Critical: vital alarm threshold breached",
        has_signal=True,
        prv_base=20.0,
        prv_amp=1.0,
        rr_base=32.0,
        rr_amp=0.8,
        pi_base=0.3,
        pi_amp=0.05,
        spo2_base=84.0,
        spo2_amp=0.8,
        bp_sys_base=176.0,
        bp_dia_base=108.0,
        bpm_base=134.0,
    ),
    "finger_off": _ProfileSpec(
        uart_state=ConnectionState.CONNECTED,
        esp32_state=ConnectionState.CONNECTED,
        sensor_state=SensorState.FINGER_OFF,
        cloud_state=CloudState.ONLINE,
        battery_percent=95,
        battery_voltage=8.2,
        is_charging=False,
        status_message="Sensor finger off",
        has_signal=False,
        prv_base=0.0,
        prv_amp=0.0,
        rr_base=0.0,
        rr_amp=0.0,
        pi_base=0.0,
        pi_amp=0.0,
        spo2_base=0.0,
        spo2_amp=0.0,
        bp_sys_base=0.0,
        bp_dia_base=0.0,
        bpm_base=0.0,
    ),
    "poor_signal": _ProfileSpec(
        uart_state=ConnectionState.CONNECTED,
        esp32_state=ConnectionState.CONNECTED,
        sensor_state=SensorState.POOR_SIGNAL,
        cloud_state=CloudState.ONLINE,
        battery_percent=94,
        battery_voltage=8.1,
        is_charging=False,
        status_message="Poor PPG signal quality",
        has_signal=True,
        prv_base=42.0,
        prv_amp=2.0,
        rr_base=19.0,
        rr_amp=0.8,
        pi_base=0.9,
        pi_amp=0.1,
        spo2_base=94.0,
        spo2_amp=0.5,
        bp_sys_base=126.0,
        bp_dia_base=82.0,
        bpm_base=78.0,
        noise_amp=0.28,
    ),
    "uart_disconnected": _ProfileSpec(
        uart_state=ConnectionState.DISCONNECTED,
        esp32_state=ConnectionState.DISCONNECTED,
        sensor_state=SensorState.OK,
        cloud_state=CloudState.ONLINE,
        battery_percent=95,
        battery_voltage=8.2,
        is_charging=False,
        status_message="UART / ESP32 disconnected",
        has_signal=False,
        prv_base=0.0,
        prv_amp=0.0,
        rr_base=0.0,
        rr_amp=0.0,
        pi_base=0.0,
        pi_amp=0.0,
        spo2_base=0.0,
        spo2_amp=0.0,
        bp_sys_base=0.0,
        bp_dia_base=0.0,
        bpm_base=0.0,
    ),
    "low_battery": _ProfileSpec(
        uart_state=ConnectionState.CONNECTED,
        esp32_state=ConnectionState.CONNECTED,
        sensor_state=SensorState.OK,
        cloud_state=CloudState.ONLINE,
        battery_percent=14,
        battery_voltage=6.7,
        is_charging=False,
        status_message="Low battery (14%)",
        has_signal=True,
        prv_base=68.0,
        prv_amp=3.0,
        rr_base=16.0,
        rr_amp=0.8,
        pi_base=3.0,
        pi_amp=0.2,
        spo2_base=98.0,
        spo2_amp=0.4,
        bp_sys_base=120.0,
        bp_dia_base=80.0,
        bpm_base=72.0,
    ),
    "cloud_offline": _ProfileSpec(
        uart_state=ConnectionState.CONNECTED,
        esp32_state=ConnectionState.CONNECTED,
        sensor_state=SensorState.OK,
        cloud_state=CloudState.OFFLINE,
        battery_percent=95,
        battery_voltage=8.2,
        is_charging=False,
        status_message="Cloud offline",
        has_signal=True,
        prv_base=68.0,
        prv_amp=3.0,
        rr_base=16.0,
        rr_amp=0.8,
        pi_base=3.0,
        pi_amp=0.2,
        spo2_base=98.0,
        spo2_amp=0.4,
        bp_sys_base=120.0,
        bp_dia_base=80.0,
        bpm_base=72.0,
    ),
}


def compute_vital_alarms(
    *,
    prv_rmssd_ms: float | None,
    rr_brpm: float | None,
    pi_percent: float | None,
    spo2_percent: float | None,
    bp_sys_mmhg: int | None,
    bp_dia_mmhg: int | None,
) -> dict[str, AlarmLevel]:
    """Compute clinical alarm levels for all 5 vital columns from physiological thresholds."""
    if prv_rmssd_ms is None:
        prv_alarm = AlarmLevel.NORMAL
    elif not math.isfinite(prv_rmssd_ms):
        prv_alarm = AlarmLevel.WARNING
    elif prv_rmssd_ms < 25.0 or prv_rmssd_ms > 160.0:
        prv_alarm = AlarmLevel.CRITICAL
    elif prv_rmssd_ms < 45.0 or prv_rmssd_ms > 120.0:
        prv_alarm = AlarmLevel.WARNING
    else:
        prv_alarm = AlarmLevel.NORMAL

    if rr_brpm is None:
        rr_alarm = AlarmLevel.NORMAL
    elif not math.isfinite(rr_brpm):
        rr_alarm = AlarmLevel.WARNING
    elif rr_brpm < 9.0 or rr_brpm > 28.0:
        rr_alarm = AlarmLevel.CRITICAL
    elif rr_brpm < 12.0 or rr_brpm > 20.0:
        rr_alarm = AlarmLevel.WARNING
    else:
        rr_alarm = AlarmLevel.NORMAL

    if pi_percent is None:
        pi_alarm = AlarmLevel.NORMAL
    elif not math.isfinite(pi_percent):
        pi_alarm = AlarmLevel.WARNING
    elif pi_percent < 0.5:
        pi_alarm = AlarmLevel.CRITICAL
    elif pi_percent < 1.5 or pi_percent > 12.0:
        pi_alarm = AlarmLevel.WARNING
    else:
        pi_alarm = AlarmLevel.NORMAL

    if spo2_percent is None:
        spo2_alarm = AlarmLevel.NORMAL
    elif not math.isfinite(spo2_percent):
        spo2_alarm = AlarmLevel.WARNING
    elif spo2_percent < 90.0:
        spo2_alarm = AlarmLevel.CRITICAL
    elif spo2_percent < 95.0:
        spo2_alarm = AlarmLevel.WARNING
    else:
        spo2_alarm = AlarmLevel.NORMAL

    if bp_sys_mmhg is None or bp_dia_mmhg is None:
        bp_alarm = AlarmLevel.NORMAL
    elif not math.isfinite(bp_sys_mmhg) or not math.isfinite(bp_dia_mmhg):
        bp_alarm = AlarmLevel.WARNING
    elif bp_sys_mmhg >= 160 or bp_dia_mmhg >= 100 or bp_sys_mmhg < 80 or bp_dia_mmhg < 50:
        bp_alarm = AlarmLevel.CRITICAL
    elif bp_sys_mmhg >= 130 or bp_dia_mmhg >= 85 or bp_sys_mmhg < 90 or bp_dia_mmhg < 60:
        bp_alarm = AlarmLevel.WARNING
    else:
        bp_alarm = AlarmLevel.NORMAL

    return {
        "PRV": prv_alarm,
        "RR": rr_alarm,
        "PI": pi_alarm,
        "SpO2": spo2_alarm,
        "BP": bp_alarm,
    }


def synthesize_ppg_sample(phase: float, *, noise_amp: float = 0.0, sample_index: int = 0) -> float:
    """Synthesize one centered PPG sample in [-1.0, 1.0] from cardiac phase [0.0, 1.0).

    Models a sharp systolic peak followed by a dicrotic notch / diastolic wave
    using pure-Python ``math.exp`` Gaussians.
    """
    p = phase % 1.0
    systolic = math.exp(-(((p - 0.22) / 0.075) ** 2))
    dicrotic = 0.42 * math.exp(-(((p - 0.46) / 0.11) ** 2))
    raw = systolic + dicrotic
    centered = raw * 1.65 - 0.72
    if noise_amp > 0.0:
        artifact = noise_amp * (
            0.6 * math.sin(2.0 * math.pi * (p * 5.0 + sample_index * 0.17))
            + 0.4 * math.cos(2.0 * math.pi * (p * 11.0 + sample_index * 0.31))
        )
        centered += artifact
    return max(-1.0, min(1.0, centered))


class MockVitalDataAdapter:
    """Thread-safe pure-Python simulator implementing VitalDataPort and SimulationControlPort."""

    def __init__(
        self,
        *,
        sample_rate_hz: float = 125.0,
        initial_profile: str = "normal",
    ) -> None:
        if isinstance(sample_rate_hz, bool) or sample_rate_hz <= 0.0 or not math.isfinite(sample_rate_hz):
            raise ValueError(f"sample_rate_hz must be a positive finite number, got {sample_rate_hz!r}")
        if not isinstance(initial_profile, str) or initial_profile not in _PROFILE_SPECS:
            raise ValueError(
                f"Unknown simulation profile {initial_profile!r}; expected one of {SIMULATION_PROFILES}"
            )
        self._lock = threading.Lock()
        self._sample_rate_hz = float(sample_rate_hz)
        self._profile = initial_profile
        self._running = False
        self._phase = 0.0
        self._sample_counter = 0
        now = time.monotonic()
        self._start_epoch = now
        self._last_pop_time = now
        self._recording_active = False
        self._recording_started_at: float | None = None

    @property
    def profile(self) -> str:
        """Return the currently selected simulation profile name."""
        with self._lock:
            return self._profile

    def start(self) -> None:
        """Start mock vital and waveform streaming."""
        with self._lock:
            now = time.monotonic()
            if not self._running:
                self._running = True
                self._last_pop_time = now

    def stop(self) -> None:
        """Stop mock streaming."""
        with self._lock:
            self._running = False

    def set_simulation_profile(self, profile: str) -> None:
        """Switch active simulation profile (SimulationControlPort)."""
        if not isinstance(profile, str) or profile not in _PROFILE_SPECS:
            raise ValueError(
                f"Unknown simulation profile {profile!r}; expected one of {SIMULATION_PROFILES}"
            )
        with self._lock:
            self._profile = profile

    def set_recording_state(self, active: bool) -> None:
        """Update mock recording indicator and elapsed timer state."""
        with self._lock:
            now = time.monotonic()
            if active and not self._recording_active:
                self._recording_active = True
                self._recording_started_at = now
            elif not active:
                self._recording_active = False
                self._recording_started_at = None

    def latest_vitals(self) -> VitalSnapshot:
        """Return the latest vital snapshot for the active simulation profile."""
        with self._lock:
            spec = _PROFILE_SPECS[self._profile]
            if not spec.has_signal:
                return VitalSnapshot(
                    prv_rmssd_ms=None,
                    rr_brpm=None,
                    pi_percent=None,
                    spo2_percent=None,
                    bp_sys_mmhg=None,
                    bp_dia_mmhg=None,
                    bpm=None,
                    alarms={key: AlarmLevel.NORMAL for key in VITAL_ALARM_KEYS},
                    timestamp=datetime.now(),
                )

            t = (time.monotonic() - self._start_epoch) if self._running else 0.0
            prv = round(spec.prv_base + spec.prv_amp * math.sin(0.35 * t), 1)
            rr = round(spec.rr_base + spec.rr_amp * math.sin(0.22 * t), 1)
            pi = round(spec.pi_base + spec.pi_amp * math.sin(0.30 * t), 1)
            spo2 = round(min(100.0, spec.spo2_base + spec.spo2_amp * math.sin(0.18 * t)), 1)
            bp_sys = round(spec.bp_sys_base + 2.0 * math.sin(0.25 * t))
            bp_dia = round(spec.bp_dia_base + 2.0 * math.sin(0.25 * t + 0.5))
            bpm = round(spec.bpm_base + 2.0 * math.sin(0.40 * t))

            alarms = compute_vital_alarms(
                prv_rmssd_ms=prv,
                rr_brpm=rr,
                pi_percent=pi,
                spo2_percent=spo2,
                bp_sys_mmhg=bp_sys,
                bp_dia_mmhg=bp_dia,
            )
            return VitalSnapshot(
                prv_rmssd_ms=prv,
                rr_brpm=rr,
                pi_percent=pi,
                spo2_percent=spo2,
                bp_sys_mmhg=bp_sys,
                bp_dia_mmhg=bp_dia,
                bpm=bpm,
                alarms=alarms,
                timestamp=datetime.now(),
            )

    def pop_waveform_samples(self) -> WaveformBatch:
        """Pop newly synthesized PPG samples since the previous call.

        Inter-call elapsed time ``dt`` is clamped to ``[0.032, 0.25]`` seconds
        so ~30 Hz UI polling tracks real time while tight unit-test loops
        still receive non-empty batches and long pauses avoid huge catch-up bursts.
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_pop_time
            self._last_pop_time = now

            spec = _PROFILE_SPECS[self._profile]
            if not self._running or not spec.has_signal:
                return WaveformBatch(
                    samples=[],
                    sample_rate_hz=self._sample_rate_hz,
                    timestamp=datetime.now(),
                )

            dt = max(0.032, min(0.25, elapsed))
            count = max(1, round(dt * self._sample_rate_hz))
            t = now - self._start_epoch
            bpm = spec.bpm_base + 2.0 * math.sin(0.40 * t)
            phase_step = (bpm / 60.0) / self._sample_rate_hz

            samples: list[float] = []
            for _ in range(count):
                samples.append(
                    synthesize_ppg_sample(
                        self._phase,
                        noise_amp=spec.noise_amp,
                        sample_index=self._sample_counter,
                    )
                )
                self._phase = (self._phase + phase_step) % 1.0
                self._sample_counter += 1

            return WaveformBatch(
                samples=samples,
                sample_rate_hz=self._sample_rate_hz,
                timestamp=datetime.now(),
            )

    def device_status(self) -> DeviceStatus:
        """Return current device connectivity, sensor, cloud, battery, and recording status."""
        with self._lock:
            spec = _PROFILE_SPECS[self._profile]
            elapsed_s = 0
            if self._recording_active and self._recording_started_at is not None:
                elapsed_s = max(0, int(time.monotonic() - self._recording_started_at))
            return DeviceStatus(
                uart_state=spec.uart_state,
                esp32_state=spec.esp32_state,
                sensor_state=spec.sensor_state,
                cloud_state=spec.cloud_state,
                battery_percent=spec.battery_percent,
                battery_voltage=spec.battery_voltage,
                is_charging=spec.is_charging,
                recording_active=self._recording_active,
                recording_elapsed_s=elapsed_s,
                status_message=spec.status_message,
            )


__all__ = [
    "MockVitalDataAdapter",
    "SIMULATION_PROFILES",
    "VITAL_ALARM_KEYS",
    "compute_vital_alarms",
    "synthesize_ppg_sample",
]
