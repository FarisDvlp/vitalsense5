#!/usr/bin/env python3
"""
app_integration_example.py
Minimal Working Example (MWE) demonstrating how to initialize and run the
PPG Multi-Parameter Estimation Pipeline (RR, PRV, BP) in a Python application.

Usage:
    python -m vitalsense5.algorithms.app_integration_example
"""
import time
import numpy as np

from vitalsense5.algorithms import PPGEdgePipeline


def generate_synthetic_ppg(duration_sec: float = 60.0, fs: float = 200.0) -> np.ndarray:
    """Generate an anatomically realistic 60s PPG pulse train with respiration modulation."""
    n_samples = int(round(duration_sec * fs))
    period = int(round(fs * 0.8))  # ~75 bpm
    t_beat = np.linspace(0.0, 1.0, period, endpoint=False)
    
    # Gaussian mixture pulse: systolic crest + dicrotic notch / diastolic wave
    beat = np.exp(-0.5 * ((t_beat - 0.20) / 0.05) ** 2) + 0.35 * np.exp(-0.5 * ((t_beat - 0.45) / 0.08) ** 2)
    beat = (beat - beat.min()) / (beat.max() - beat.min())
    
    # Tile beats across the 60s window
    n_tiles = n_samples // period + 2
    raw = np.tile(beat, n_tiles)[:n_samples]
    
    # Add subtle respiration baseline modulation (~15 bpm = 0.25 Hz)
    t = np.linspace(0.0, duration_sec, n_samples, endpoint=False)
    resp = 0.08 * np.sin(2 * np.pi * 0.25 * t)
    
    # Scale to realistic ADC readings with positive skewness and valid perfusion index (~2.5%)
    ac_signal = (raw + resp) * 250.0
    dc_level = 10000.0  # PI = AC / DC * 100% ≈ 2.5%
    return ac_signal + dc_level


def main():
    print("=" * 70)
    print("  PPG Physiological Monitoring Pipeline - Software Integration Demo")
    print("=" * 70)

    # 1. Initialize Pipeline
    print("[1/4] Initializing PPGEdgePipeline (fs=200.0 Hz, pure-Python mode)...")
    t0 = time.perf_counter()
    pipeline = PPGEdgePipeline(fs=200.0, use_pure_python=True)
    init_time_ms = (time.perf_counter() - t0) * 1000.0
    print(f"      Pipeline initialized in {init_time_ms:.1f} ms.")

    # 2. Warm up caches
    print("[2/4] Executing warm-up cycle...")
    t0 = time.perf_counter()
    warmup_res = pipeline.warmup(duration_sec=60.0)
    warmup_time_ms = (time.perf_counter() - t0) * 1000.0
    print(f"      Warm-up completed in {warmup_time_ms:.1f} ms (Inference: {warmup_res['total_latency_ms']:.1f} ms).")

    # 3. Simulate receiving 60s buffer (12,000 samples @ 200 Hz)
    print("[3/4] Simulating 60s window ingestion from sensor...")
    raw_ppg = generate_synthetic_ppg(duration_sec=60.0, fs=200.0)
    print(f"      Buffer shape: {raw_ppg.shape} ({len(raw_ppg)/200.0:.0f} seconds).")

    # 4. Process window (with optional patient demographics)
    print("[4/4] Executing inference across RR, PRV, and BP models...")
    demographics = {"age": 45.0, "height": 170.0, "weight": 70.0, "gender": 1.0}
    telemetry = pipeline.process_window(raw_ppg, demographics=demographics)

    print("\n" + "-" * 70)
    print(f"  RESULTS (Total Pipeline Latency: {telemetry['total_latency_ms']:.2f} ms)")
    print("-" * 70)
    print(f"  Window Valid    : {telemetry['is_valid']} ({telemetry['status']})")
    
    sqi = telemetry["sqi"]
    print(f"  Signal Quality  : PI={sqi['perfusion_index']:.2f}%, Skew={sqi['skewness']:.2f}, RelPower={sqi['relative_power']:.2f}")

    if telemetry["is_valid"]:
        rr = telemetry["rr"]
        prv = telemetry["prv"]
        bp = telemetry["bp"]

        print(f"  Respiratory Rate: {rr['rr_bpm']:.1f} breaths/min (Confidence: {rr['confidence']:.2f})")
        print(f"  Heart Rate (PPI): {60000.0 / prv['mean_ppi']:.1f} bpm (RMSSD: {prv['rmssd']:.1f} ms, LF/HF: {prv['lf_hf_ratio']:.2f})")
        print(f"  Blood Pressure  : {bp['sbp_mmHg']:.1f} / {bp['dbp_mmHg']:.1f} mmHg (MAP: {bp['map_mmHg']:.1f} mmHg)")
    else:
        print(f"  [ALERT] Window rejected by SQI early gate. Status: {telemetry['status']}")

    print("=" * 70)
    print("Demo execution finished successfully!\n")


if __name__ == "__main__":
    main()
