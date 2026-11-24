"""Production UART NDJSON + PPGEdgePipeline adapter implementing VitalDataPort."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime
import json
import logging
import math
import threading
import time
from typing import Any

import numpy as np

from vitalsense5.algorithms.core.edge_pipeline import PPGEdgePipeline
from vitalsense5.contracts import (
    AlarmLevel,
    CloudState,
    ConnectionState,
    DeviceStatus,
    Gender,
    PatientRecord,
    PatientStorePort,
    SensorState,
    VitalSnapshot,
    WaveformBatch,
)

from vitalsense5.adapters.mock_vital_adapter import (
    VITAL_ALARM_KEYS,
    compute_vital_alarms,
)

logger = logging.getLogger(__name__)


def patient_record_to_demographics(patient: PatientRecord | None) -> dict[str, float] | None:
    """Convert a PatientRecord into the demographic dict expected by BPEstimator."""
    if patient is None:
        return None
    return {
        "age": float(patient.age),
        "height": float(patient.height_cm),
        "weight": float(patient.weight_kg),
        "gender": 1.0 if patient.gender == Gender.MALE else 0.0,
    }


class _RedACNormalizer:
    """Streaming DC-removal and adaptive amplitude normalizer for 18-bit Red PPG display."""

    def __init__(self, sample_rate_hz: float = 200.0) -> None:
        self._alpha_dc = 2.0 / (max(1.0, sample_rate_hz) * 1.0 + 1.0)  # ~1s EMA
        self._window = deque(maxlen=max(20, int(round(sample_rate_hz * 2.0))))
        self._dc: float | None = None

    def reset(self) -> None:
        self._dc = None
        self._window.clear()

    def push(self, raw_r: float) -> float:
        if self._dc is None:
            self._dc = raw_r
            return 0.0
        self._dc += self._alpha_dc * (raw_r - self._dc)
        ac = raw_r - self._dc
        self._window.append(abs(ac))
        peak = max(self._window) if self._window else 0.0
        if peak < 1e-6:
            return 0.0
        normalized = (ac / peak) * 0.85
        return max(-1.0, min(1.0, float(normalized)))


class SerialVitalAdapter:
    """Thread-safe UART1 NDJSON reader + PPGEdgePipeline adapter implementing VitalDataPort.

    Protocol (460800 baud 8N1 NDJSON from ESP32-S3):
    - ``"type": "s"`` (200 Hz): ``{"type":"s","seq":...,"ts":...,"r":...,"ir":...,"src":...,"f":1}``
      - ``ir`` feeds ``PPGEdgePipeline`` (60s / 12,000-sample window) for RR, PRV, and BP.
      - ``r`` is AC-normalized for ``PPGCanvasWidget`` via ``pop_waveform_samples()``.
    - ``"type": "t"`` (1 Hz): ``{"type":"t","up":...,"src":...,"clip":...,"ob":...,"f":...,"v":...,"i":...,"soc":...,"chg":...,"drp":...}``
      - Updates battery voltage/SoC/charging, active sensor source, and heartbeat.
    - ``spo2_percent`` and ``pi_percent`` are intentionally left as ``None``.
    """

    def __init__(
        self,
        *,
        port: str = "/dev/ttyAMA0",
        baudrate: int = 460800,
        sample_rate_hz: float = 200.0,
        window_seconds: float = 60.0,
        inference_interval_s: float = 5.0,
        heartbeat_timeout_s: float = 2.0,
        patient_store: PatientStorePort | None = None,
        pipeline: PPGEdgePipeline | None = None,
        serial_factory: Callable[..., Any] | None = None,
        use_pure_python: bool = True,
    ) -> None:
        if isinstance(sample_rate_hz, bool) or sample_rate_hz <= 0.0 or not math.isfinite(sample_rate_hz):
            raise ValueError(f"sample_rate_hz must be positive finite, got {sample_rate_hz!r}")
        if isinstance(baudrate, bool) or baudrate <= 0:
            raise ValueError(f"baudrate must be positive, got {baudrate!r}")

        self._port = str(port)
        self._baudrate = int(baudrate)
        self._sample_rate_hz = float(sample_rate_hz)
        self._window_samples = max(int(round(self._sample_rate_hz * 5.0)), int(round(self._sample_rate_hz * window_seconds)))
        self._inference_interval_s = max(0.5, float(inference_interval_s))
        self._heartbeat_timeout_s = max(0.5, float(heartbeat_timeout_s))
        self._patient_store = patient_store
        self._serial_factory = serial_factory

        self._pipeline = (
            pipeline
            if pipeline is not None
            else PPGEdgePipeline(fs=self._sample_rate_hz, use_pure_python=use_pure_python)
        )

        self._lock = threading.Lock()
        self._running = False
        self._reader_thread: threading.Thread | None = None
        self._inference_thread: threading.Thread | None = None
        self._serial_conn: Any = None

        self._ir_buffer: deque[float] = deque(maxlen=self._window_samples)
        self._waveform_queue: deque[float] = deque(maxlen=max(200, int(round(self._sample_rate_hz * 10.0))))
        self._red_normalizer = _RedACNormalizer(sample_rate_hz=self._sample_rate_hz)

        self._last_packet_time: float | None = None
        self._uart_state = ConnectionState.DISCONNECTED
        self._esp32_state = ConnectionState.DISCONNECTED
        self._sensor_state = SensorState.CALIBRATING
        self._cloud_state = CloudState.OFFLINE
        self._battery_percent = 0
        self._battery_voltage = 0.0
        self._is_charging = False
        self._active_source = "none"
        self._status_message = "Waiting for ESP32-S3 UART"
        self._finger_off_streak = 0
        self._finger_off_threshold = max(1, int(round(self._sample_rate_hz * 0.25)))  # >250ms

        self._latest_vitals = self._empty_vitals()

    @staticmethod
    def _empty_vitals() -> VitalSnapshot:
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

    def start(self) -> None:
        """Start background UART reader and physiological inference threads."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._uart_state = ConnectionState.RECONNECTING
            self._esp32_state = ConnectionState.RECONNECTING
            self._status_message = f"Connecting to {self._port}"

        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="vitalsense5-uart-reader",
            daemon=True,
        )
        self._inference_thread = threading.Thread(
            target=self._inference_loop,
            name="vitalsense5-pipeline-worker",
            daemon=True,
        )
        self._reader_thread.start()
        self._inference_thread.start()

    def stop(self) -> None:
        """Stop background threads and close the serial port."""
        with self._lock:
            self._running = False
            conn = self._serial_conn
            self._serial_conn = None

        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.5)
        if self._inference_thread is not None and self._inference_thread.is_alive():
            self._inference_thread.join(timeout=1.5)

    def _open_serial(self) -> Any:
        if self._serial_factory is not None:
            return self._serial_factory(self._port, self._baudrate, timeout=0.5)
        import serial  # type: ignore[import-untyped]

        return serial.Serial(self._port, self._baudrate, timeout=0.5)

    def _reader_loop(self) -> None:
        while self._running:
            conn = None
            try:
                conn = self._open_serial()
                with self._lock:
                    if not self._running:
                        try:
                            conn.close()
                        except Exception:
                            pass
                        break
                    self._serial_conn = conn
                    self._status_message = f"Listening on {self._port}"
                if hasattr(conn, "reset_input_buffer"):
                    conn.reset_input_buffer()

                while self._running:
                    raw_line = conn.readline()
                    if not raw_line:
                        continue
                    if isinstance(raw_line, (bytes, bytearray)):
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                    else:
                        line = str(raw_line).strip()
                    if line:
                        self.ingest_ndjson_line(line)
            except Exception as exc:
                logger.warning("SerialVitalAdapter read error on %s: %s", self._port, exc)
                with self._lock:
                    self._serial_conn = None
                    self._uart_state = ConnectionState.RECONNECTING
                    self._esp32_state = ConnectionState.RECONNECTING
                    self._status_message = f"UART reconnecting ({self._port})"
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                time.sleep(0.5)

    def _inference_loop(self) -> None:
        try:
            self._pipeline.warmup()
        except Exception as exc:
            logger.warning("PPGEdgePipeline warmup failed: %s", exc)

        last_run = 0.0
        while self._running:
            now = time.monotonic()
            if now - last_run >= self._inference_interval_s:
                try:
                    if self.run_inference_once():
                        last_run = time.monotonic()
                except Exception as exc:
                    logger.warning("SerialVitalAdapter inference error: %s", exc)
            time.sleep(0.25)

    def run_inference_once(self) -> bool:
        """Execute one PPGEdgePipeline cycle if a full IR window is available."""
        with self._lock:
            if len(self._ir_buffer) < self._window_samples:
                return False
            if self._sensor_state == SensorState.FINGER_OFF:
                return False
            ir_window = np.array(self._ir_buffer, dtype=np.float64)

        demographics = self._read_active_demographics()
        result = self._pipeline.process_window(
            ir_window,
            fs=self._sample_rate_hz,
            demographics=demographics,
        )
        self._apply_pipeline_result(result)
        return True

    def _read_active_demographics(self) -> dict[str, float] | None:
        if self._patient_store is None:
            return None
        try:
            patient = self._patient_store.get_active_patient()
        except Exception as exc:
            logger.warning("Failed to fetch active patient demographics: %s", exc)
            return None
        return patient_record_to_demographics(patient)

    def _apply_pipeline_result(self, result: dict[str, Any]) -> None:
        with self._lock:
            if self._sensor_state == SensorState.FINGER_OFF:
                return

            if not result.get("is_valid", False):
                status = str(result.get("status", ""))
                if "SQI_REJECTED" in status:
                    self._sensor_state = SensorState.POOR_SIGNAL
                return

            self._sensor_state = SensorState.OK
            rr_dict = result.get("rr", {})
            prv_dict = result.get("prv", {})
            bp_dict = result.get("bp", {})

            prv_rmssd = (
                round(float(prv_dict["rmssd"]), 1)
                if prv_dict.get("is_valid") and math.isfinite(float(prv_dict.get("rmssd", 0.0)))
                else None
            )
            rr_brpm = (
                round(float(rr_dict["rr_bpm"]), 1)
                if rr_dict.get("is_valid") and math.isfinite(float(rr_dict.get("rr_bpm", 0.0)))
                else None
            )
            bp_sys = (
                int(round(float(bp_dict["sbp_mmHg"])))
                if bp_dict.get("is_valid") and math.isfinite(float(bp_dict.get("sbp_mmHg", 0.0)))
                else None
            )
            bp_dia = (
                int(round(float(bp_dict["dbp_mmHg"])))
                if bp_dict.get("is_valid") and math.isfinite(float(bp_dict.get("dbp_mmHg", 0.0)))
                else None
            )
            mean_ppi = float(prv_dict.get("mean_ppi", 0.0)) if prv_dict.get("is_valid") else 0.0
            bpm = int(round(60000.0 / mean_ppi)) if mean_ppi > 0.0 and math.isfinite(mean_ppi) else None

            alarms = compute_vital_alarms(
                prv_rmssd_ms=prv_rmssd,
                rr_brpm=rr_brpm,
                pi_percent=None,
                spo2_percent=None,
                bp_sys_mmhg=bp_sys,
                bp_dia_mmhg=bp_dia,
            )
            self._latest_vitals = VitalSnapshot(
                prv_rmssd_ms=prv_rmssd,
                rr_brpm=rr_brpm,
                pi_percent=None,
                spo2_percent=None,
                bp_sys_mmhg=bp_sys,
                bp_dia_mmhg=bp_dia,
                bpm=bpm,
                alarms=alarms,
                timestamp=datetime.now(),
            )

    def ingest_ndjson_line(self, line: str) -> None:
        """Parse and apply one NDJSON packet from ESP32-S3 UART1."""
        try:
            msg = json.loads(line)
        except (json.JSONDecodeError, TypeError, ValueError):
            return
        if not isinstance(msg, dict):
            return

        pkt_type = msg.get("type")
        now = time.monotonic()

        with self._lock:
            self._last_packet_time = now
            self._uart_state = ConnectionState.CONNECTED
            self._esp32_state = ConnectionState.CONNECTED

            if pkt_type == "s":
                self._handle_sample_packet(msg)
            elif pkt_type == "t":
                self._handle_telemetry_packet(msg)

    def _handle_sample_packet(self, msg: dict[str, Any]) -> None:
        try:
            raw_r = float(msg["r"])
            raw_ir = float(msg["ir"])
        except (KeyError, TypeError, ValueError):
            return
        if not (math.isfinite(raw_r) and math.isfinite(raw_ir)):
            return

        src = msg.get("src")
        if isinstance(src, str) and src:
            self._active_source = src
            self._status_message = f"Connected ({src})"

        try:
            finger_raw = msg.get("f", 1)
            finger = 1 if finger_raw is None else int(finger_raw)
        except (TypeError, ValueError):
            finger = 1
        if finger == 0:
            self._finger_off_streak += 1
            if self._finger_off_streak >= self._finger_off_threshold:
                self._set_finger_off_locked()
            return

        self._finger_off_streak = 0
        if self._sensor_state == SensorState.FINGER_OFF:
            self._sensor_state = SensorState.CALIBRATING

        self._ir_buffer.append(raw_ir)
        norm_r = self._red_normalizer.push(raw_r)
        self._waveform_queue.append(norm_r)

    def _handle_telemetry_packet(self, msg: dict[str, Any]) -> None:
        if "v" in msg:
            try:
                v = float(msg["v"])
                if math.isfinite(v):
                    self._battery_voltage = v
            except (TypeError, ValueError):
                pass
        if "soc" in msg:
            try:
                self._battery_percent = max(0, min(100, int(msg["soc"])))
            except (TypeError, ValueError):
                pass
        if "chg" in msg:
            try:
                self._is_charging = bool(int(msg["chg"]))
            except (TypeError, ValueError):
                pass
        src = msg.get("src")
        if isinstance(src, str) and src:
            self._active_source = src
            self._status_message = "No active sensor" if src == "none" else f"Connected ({src})"

        if "f" in msg:
            try:
                if int(msg["f"]) == 0:
                    self._set_finger_off_locked()
                elif self._sensor_state == SensorState.FINGER_OFF:
                    self._finger_off_streak = 0
                    self._sensor_state = SensorState.CALIBRATING
            except (TypeError, ValueError):
                pass

    def _set_finger_off_locked(self) -> None:
        self._sensor_state = SensorState.FINGER_OFF
        self._ir_buffer.clear()
        self._waveform_queue.clear()
        self._red_normalizer.reset()
        self._latest_vitals = self._empty_vitals()

    def _is_heartbeat_timed_out_locked(self) -> bool:
        if self._last_packet_time is None:
            return False
        return (time.monotonic() - self._last_packet_time) > self._heartbeat_timeout_s

    def latest_vitals(self) -> VitalSnapshot:
        with self._lock:
            if (
                self._is_heartbeat_timed_out_locked()
                or self._uart_state == ConnectionState.DISCONNECTED
                or self._sensor_state == SensorState.FINGER_OFF
            ):
                return self._empty_vitals()
            return self._latest_vitals

    def pop_waveform_samples(self) -> WaveformBatch:
        with self._lock:
            if (
                self._is_heartbeat_timed_out_locked()
                or self._sensor_state == SensorState.FINGER_OFF
                or not self._waveform_queue
            ):
                return WaveformBatch(
                    samples=[],
                    sample_rate_hz=self._sample_rate_hz,
                    timestamp=datetime.now(),
                )
            samples = list(self._waveform_queue)
            self._waveform_queue.clear()
            return WaveformBatch(
                samples=samples,
                sample_rate_hz=self._sample_rate_hz,
                timestamp=datetime.now(),
            )

    def device_status(self) -> DeviceStatus:
        with self._lock:
            uart_state = self._uart_state
            esp32_state = self._esp32_state
            status_msg = self._status_message
            if self._is_heartbeat_timed_out_locked():
                uart_state = ConnectionState.DISCONNECTED
                esp32_state = ConnectionState.DISCONNECTED
                status_msg = "UART / ESP32 heartbeat timeout"

            return DeviceStatus(
                uart_state=uart_state,
                esp32_state=esp32_state,
                sensor_state=self._sensor_state,
                cloud_state=self._cloud_state,
                battery_percent=self._battery_percent,
                battery_voltage=self._battery_voltage,
                is_charging=self._is_charging,
                recording_active=False,
                recording_elapsed_s=0,
                status_message=status_msg,
            )


__all__ = ["SerialVitalAdapter", "patient_record_to_demographics"]
