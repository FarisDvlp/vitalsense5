"""Unit tests for vitalsense5.algorithms, SerialVitalAdapter, and main.py serial/mock wiring."""

from __future__ import annotations

import json
import math
import time

import numpy as np
import pytest

from vitalsense5.adapters import (
    InMemoryPatientStore,
    MockVitalDataAdapter,
)
from vitalsense5.backend import (
    SerialVitalAdapter,
    patient_record_to_demographics,
)
from vitalsense5.algorithms import (
    BPEstimator,
    EdgePPGMonitor,
    PPGEdgePipeline,
    PRVEstimator,
    RREstimator,
)
from vitalsense5.contracts import (
    ConnectionState,
    Gender,
    PatientRecord,
    SensorState,
    VitalDataPort,
)
from vitalsense5.main import _resolve_vital_adapter


def _synthetic_ppg(duration_sec: float = 60.0, fs: float = 200.0) -> np.ndarray:
    n_samples = int(round(duration_sec * fs))
    period = int(round(fs * 0.8))  # 75 bpm
    t_beat = np.linspace(0.0, 1.0, period, endpoint=False)
    beat = np.exp(-0.5 * ((t_beat - 0.20) / 0.05) ** 2) + 0.35 * np.exp(
        -0.5 * ((t_beat - 0.45) / 0.08) ** 2
    )
    beat = (beat - beat.min()) / (beat.max() - beat.min())
    raw = np.tile(beat, n_samples // period + 2)[:n_samples]
    t = np.linspace(0.0, duration_sec, n_samples, endpoint=False)
    resp = 0.08 * np.sin(2.0 * math.pi * 0.25 * t)
    return (raw + resp) * 250.0 + 10000.0


def test_algorithms_package_imports_and_pipeline_demographics() -> None:
    assert EdgePPGMonitor is PPGEdgePipeline
    pipeline = PPGEdgePipeline(fs=200.0, use_pure_python=True)
    assert isinstance(pipeline.rr_estimator, RREstimator)
    assert isinstance(pipeline.prv_estimator, PRVEstimator)
    assert isinstance(pipeline.bp_estimator, BPEstimator)

    ppg = _synthetic_ppg(duration_sec=60.0, fs=200.0)
    res_no_demo = pipeline.process_window(ppg, fs=200.0)
    assert res_no_demo["is_valid"] is True
    assert res_no_demo["status"] == "VALID"
    assert res_no_demo["rr"]["is_valid"] is True
    assert res_no_demo["prv"]["is_valid"] is True
    assert res_no_demo["bp"]["is_valid"] is True

    res_demo = pipeline.process_window(
        ppg,
        fs=200.0,
        demographics={"age": 62.0, "height": 175.0, "weight": 82.0, "gender": 1.0},
    )
    assert res_demo["is_valid"] is True
    assert res_demo["bp"]["is_valid"] is True
    assert 70.0 <= res_demo["bp"]["sbp_mmHg"] <= 195.0
    assert 45.0 <= res_demo["bp"]["dbp_mmHg"] <= 125.0


def test_pipeline_rejects_edge_cases() -> None:
    pipeline = PPGEdgePipeline(fs=200.0, use_pure_python=True)
    assert pipeline.process_window(None)["is_valid"] is False  # type: ignore[arg-type]
    assert pipeline.process_window(np.array([], dtype=np.float64))["is_valid"] is False
    assert pipeline.process_window(np.full(12000, 1000.0))["status"] == "INVALID_FLATLINE"
    short_non_flat = np.sin(np.linspace(0.0, 10.0, 100))
    assert pipeline.process_window(short_non_flat)["status"].startswith("INVALID_SHORT_BUFFER")
    bad = _synthetic_ppg(10.0, 200.0)
    bad[10] = float("nan")
    assert pipeline.process_window(bad)["status"].startswith("INVALID_NON_FINITE")


def test_patient_record_to_demographics_mapping() -> None:
    assert patient_record_to_demographics(None) is None
    male = PatientRecord(
        patient_id="p1",
        name="Budi",
        age=52,
        height_cm=172,
        weight_kg=74,
        gender=Gender.MALE,
    )
    female = PatientRecord(
        patient_id="p2",
        name="Siti",
        age=41,
        height_cm=160,
        weight_kg=56,
        gender=Gender.FEMALE,
    )
    assert patient_record_to_demographics(male) == {
        "age": 52.0,
        "height": 172.0,
        "weight": 74.0,
        "gender": 1.0,
    }
    assert patient_record_to_demographics(female) == {
        "age": 41.0,
        "height": 160.0,
        "weight": 56.0,
        "gender": 0.0,
    }


def test_serial_adapter_ndjson_channels_spo2_pi_and_demographics() -> None:
    store = InMemoryPatientStore()
    active = store.get_active_patient()
    assert active is not None

    captured_demographics: list[dict[str, float] | None] = []

    class _SpyPipeline(PPGEdgePipeline):
        def process_window(self, ppg_buffer, fs=None, demographics=None):
            captured_demographics.append(demographics)
            return super().process_window(ppg_buffer, fs=fs, demographics=demographics)

    adapter = SerialVitalAdapter(
        port="/dev/ttyAMA0",
        baudrate=460800,
        sample_rate_hz=200.0,
        window_seconds=60.0,
        patient_store=store,
        pipeline=_SpyPipeline(fs=200.0, use_pure_python=True),
    )
    assert isinstance(adapter, VitalDataPort)

    # Telemetry packet updates battery and connection status
    adapter.ingest_ndjson_line(
        json.dumps(
            {
                "type": "t",
                "up": 10,
                "src": "clip",
                "clip": 1,
                "ob": 1,
                "f": 1,
                "v": 8.12,
                "i": 320.0,
                "soc": 86,
                "chg": 1,
                "drp": 0,
            }
        )
    )
    status = adapter.device_status()
    assert status.uart_state == ConnectionState.CONNECTED
    assert status.esp32_state == ConnectionState.CONNECTED
    assert status.battery_percent == 86
    assert status.battery_voltage == pytest.approx(8.12)
    assert status.is_charging is True
    assert "clip" in status.status_message

    # Feed 60s @ 200 Hz (12000 samples): IR is pulsatile, Red is distinct so we verify Red drives display
    ir_sig = _synthetic_ppg(duration_sec=60.0, fs=200.0)
    for idx, ir_val in enumerate(ir_sig):
        r_val = 90000.0 + 400.0 * math.sin(2.0 * math.pi * 1.2 * (idx / 200.0))
        adapter.ingest_ndjson_line(
            json.dumps(
                {
                    "type": "s",
                    "seq": idx,
                    "ts": idx * 5,
                    "r": int(round(r_val)),
                    "ir": int(round(ir_val)),
                    "src": "clip",
                    "f": 1,
                }
            )
        )

    batch = adapter.pop_waveform_samples()
    assert batch.sample_rate_hz == 200.0
    assert len(batch.samples) == 2000  # 10s display queue maxlen @ 200 Hz
    assert all(-1.0 <= s <= 1.0 for s in batch.samples)
    assert max(batch.samples) > 0.2
    assert min(batch.samples) < -0.2

    # Run inference and verify demographics forwarded & SpO2/PI remain None
    assert adapter.run_inference_once() is True
    assert len(captured_demographics) == 1
    assert captured_demographics[0] == patient_record_to_demographics(active)

    vitals = adapter.latest_vitals()
    assert vitals.spo2_percent is None
    assert vitals.pi_percent is None
    assert vitals.rr_brpm is not None
    assert vitals.prv_rmssd_ms is not None
    assert vitals.bp_sys_mmhg is not None
    assert vitals.bp_dia_mmhg is not None
    assert vitals.bpm is not None


def test_serial_adapter_finger_off_and_heartbeat_timeout() -> None:
    adapter = SerialVitalAdapter(
        sample_rate_hz=200.0,
        window_seconds=10.0,
        heartbeat_timeout_s=0.5,
    )
    adapter.ingest_ndjson_line('{"type":"s","seq":1,"ts":5,"r":90000,"ir":120000,"src":"onboard","f":1}')
    assert adapter.device_status().uart_state == ConnectionState.CONNECTED

    # Telemetry f=0 triggers FINGER_OFF and clears waveform queue
    adapter.ingest_ndjson_line('{"type":"t","up":12,"src":"onboard","f":0,"v":7.9,"soc":75,"chg":0}')
    assert adapter.device_status().sensor_state == SensorState.FINGER_OFF
    assert adapter.pop_waveform_samples().samples == []
    assert adapter.latest_vitals().bp_sys_mmhg is None

    # Malformed JSON is ignored safely
    adapter.ingest_ndjson_line("{not-valid-json")

    # Wait past heartbeat timeout -> DISCONNECTED
    time.sleep(0.6)
    status = adapter.device_status()
    assert status.uart_state == ConnectionState.DISCONNECTED
    assert status.esp32_state == ConnectionState.DISCONNECTED


def test_resolve_vital_adapter_falls_back_to_mock_when_port_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryPatientStore()
    monkeypatch.delenv("VITALSENSE5_SERIAL", raising=False)
    adapter = _resolve_vital_adapter(
        patient_store=store,
        use_serial=True,
        serial_port="/nonexistent/ttyAMA0_missing",
    )
    assert isinstance(adapter, MockVitalDataAdapter)

    adapter_default = _resolve_vital_adapter(
        patient_store=store,
        use_serial=None,
        serial_port="/nonexistent/ttyAMA0_missing",
    )
    assert isinstance(adapter_default, MockVitalDataAdapter)


def test_serial_adapter_background_threads_and_malformed_finger_field() -> None:
    ir_sig = _synthetic_ppg(duration_sec=60.0, fs=200.0)
    lines: list[bytes] = [
        b'{"type":"t","up":1,"src":"clip","f":1,"v":8.1,"soc":90,"chg":0}\n',
        b'{"type":"s","seq":0,"ts":0,"r":90000,"ir":10000,"src":"clip","f":null}\n',
        b'{"type":"s","seq":1,"ts":5,"r":90010,"ir":10010,"src":"clip","f":"bad"}\n',
    ]
    for idx, ir_val in enumerate(ir_sig, start=2):
        r_val = 90000.0 + 400.0 * math.sin(2.0 * math.pi * 1.2 * (idx / 200.0))
        lines.append(
            (
                json.dumps(
                    {
                        "type": "s",
                        "seq": idx,
                        "ts": idx * 5,
                        "r": int(round(r_val)),
                        "ir": int(round(ir_val)),
                        "src": "clip",
                        "f": 1,
                    }
                )
                + "\n"
            ).encode("utf-8")
        )

    class _FakeSerial:
        def __init__(self) -> None:
            self._idx = 0
            self.closed = False

        def reset_input_buffer(self) -> None:
            return None

        def readline(self) -> bytes:
            if self.closed:
                return b""
            if self._idx < len(lines):
                line = lines[self._idx]
                self._idx += 1
                return line
            time.sleep(0.1)
            return b'{"type":"t","up":2,"src":"clip","f":1,"v":8.1,"soc":90,"chg":0}\n'

        def close(self) -> None:
            self.closed = True

    created: list[_FakeSerial] = []

    def _factory(port: str, baudrate: int, timeout: float = 0.5) -> _FakeSerial:
        conn = _FakeSerial()
        created.append(conn)
        return conn

    adapter = SerialVitalAdapter(
        sample_rate_hz=200.0,
        window_seconds=60.0,
        inference_interval_s=0.5,
        heartbeat_timeout_s=2.0,
        serial_factory=_factory,
    )
    adapter.start()
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            vitals = adapter.latest_vitals()
            if vitals.rr_brpm is not None and vitals.bp_sys_mmhg is not None:
                break
            time.sleep(0.05)
        status = adapter.device_status()
        assert status.uart_state == ConnectionState.CONNECTED
        assert status.battery_percent == 90
        vitals = adapter.latest_vitals()
        assert vitals.rr_brpm is not None
        assert vitals.bp_sys_mmhg is not None
        assert vitals.spo2_percent is None
        assert vitals.pi_percent is None
        batch = adapter.pop_waveform_samples()
        assert len(batch.samples) > 0
    finally:
        adapter.stop()

    assert len(created) == 1
    assert created[0].closed is True
