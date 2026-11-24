"""
Pulse Rate Variability (PRV) Estimation & ECG-HRV Benchmarking Package.

Exports:
- pan_tompkins_qrs: Pan-Tompkins ECG QRS detector for Lead II at 200 Hz (and 125 Hz)
- PRVEstimator: Standalone zero-training edge PRV inference class
"""

from __future__ import annotations

from .pan_tompkins import pan_tompkins_qrs
from .prv_estimator import PRVEstimator

__all__ = ["pan_tompkins_qrs", "PRVEstimator"]
