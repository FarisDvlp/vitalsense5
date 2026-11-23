# VitalSense5 — Frontend Application & Integration Architecture

PyQt6 real-time ICU-monitor style frontend for **VitalSense5** (`1280x720` Waveshare 7-inch LCD touchscreen on Raspberry Pi 5), implementing the `VitalSense-5` Figma design with clean integration contracts for teammate-owned backend, signal-processing, database, and ESP32-S3 firmware modules.

> **System Reference:** See [`project.md`](project.md) for the hardware architecture (`Raspberry PI 5 (2GB)`, `Waveshare 7 Inch LCD - Touchscreen 1280x720 (H)`, `ESP-32 S3`, `MAX30102`, `INA219`, `2S2P 18650 8.4V 7000mAh`) and end-to-end stack.

---

## Documentation Index

| Document | Purpose |
|---|---|
| [`docs/FRONTEND_PLAN.md`](docs/FRONTEND_PLAN.md) | Scoped frontend architecture, `1280x720` screen/widget design, RPi 5 kiosk & touchscreen ergonomics, and teammate adapter integration contracts. |
| [`docs/DESIGN_GAP_REPORT.md`](docs/DESIGN_GAP_REPORT.md) | Exhaustive gap audit (`GAP-01`–`GAP-26`) comparing the `VitalSense-5` Figma design against `project.md` and product requirements, with frontend mitigations and open team decisions. |
| [`firmware.md`](firmware.md) | ESP32-S3-Zero dual-core FreeRTOS firmware specification (`200 Hz` MAX30102 dual-bus hot-plug, INA219 2S2P SoC, `460800` baud NDJSON protocol) & PlatformIO implementation in [`firmware/`](firmware/). |
| [`project.md`](project.md) | Read-only hardware, communication, and algorithm specification for the full VitalSense5 project. |

---

## Scope & Teammate Integration Boundaries

This repository contains **only the frontend presentation layer, UI state management, touchscreen input/ergonomics, typed integration contracts, and standalone PC mock adapters**.

### Included (Frontend Scope)
- `1280x720` `PyQt6` UI matching the `VitalSense-5` Figma screens (`Main Screen`, `Patient Screen`, `Settings` modal with `SETTINGS 1`–`SETTINGS 8` placeholder slots, `New Patient Pop Up` / Edit mode, pressed button states, and `VS5` logo).
- Bundled `JetBrains Mono` typography (`assets/fonts/`) and SVG Tiny 1.2 compatible vector icons (`assets/icons/`).
- Touchscreen-friendly drag scrolling (`>=8px` drag-vs-tap threshold) and in-app QWERTY / Numpad virtual keyboard overlay.
- Typed Python `Protocol` ports and DTOs (`src/vitalsense5/contracts/`) plus swappable PC mock adapters (`src/vitalsense5/adapters/`).

### Excluded (Teammate-Owned Plugins)
- **Backend & Signal Processing:** `PySerial` UART JSON reader, `SciPy`/`NumPy` PPG filtering, peak detection, and ML inference (`PRV`, `RR`, `PI`, `SpO2`, `BP`).
- **Database & Cloud Sync:** Local `SQLite` persistence and Cloud DB synchronization (`undecided` in `project.md`).
- **Edge Firmware:** `ESP32-S3` FreeRTOS dual-core I2C polling (`MAX30102`, `INA219`) and UART JSON streaming.

Teammates plug production implementations into the frontend without editing any widget or screen via `create_app(...)` in `src/vitalsense5/main.py` (see [`docs/FRONTEND_PLAN.md`](docs/FRONTEND_PLAN.md#5-teammate-integration-boundaries--contract-ports)):

```python
window = create_app(
    vital_port=real_uart_vital_adapter,
    patient_store=sqlite_patient_store,
    settings_store=sqlite_settings_store,
    command_handler=real_session_command_handler,
    kiosk=True,
)
```

---

## Repository Layout

```text
VitalSense5/
├── project.md                              # Existing hardware/system spec (read-only)
├── README.md                               # Project overview, setup, run/test commands
├── pyproject.toml                          # Python package config & pytest settings
├── requirements.txt                        # Runtime & dev dependencies
├── docs/
│   ├── FRONTEND_PLAN.md                    # Frontend architecture & integration plan
│   └── DESIGN_GAP_REPORT.md                # Figma vs project.md design & functionality gaps
├── assets/
│   ├── fonts/                              # Bundled JetBrainsMono-*.ttf (6 weights)
│   └── icons/                              # vs5_logo.svg, cloud.svg, battery.svg, dropdown_arrow.svg
├── src/
│   └── vitalsense5/
│       ├── __init__.py                     # Package marker & version
│       ├── theme/                          # Palette, typography, font loader, QSS helpers
│       ├── contracts/                      # DTOs & abstract integration ports
│       ├── adapters/                       # MockVitalDataAdapter & in-memory stores
│       ├── widgets/                        # Header, VitalColumn, PPGCanvas, ActionButton, TouchScroll, VirtualKeyboard
│       ├── screens/                        # MainScreen, PatientScreen, SettingsModal, NewPatientDialog, MainWindow
│       └── main.py                         # CLI & create_app() entrypoint
└── tests/
    ├── unit/                               # Per-milestone unit & integration tests
    └── e2e/                                # Requirement-driven E2E suite + 1280x720 screenshot rubric
```

---

## Local Windows Setup, Run & Test Commands

> **IMPORTANT — Windows Python Interpreter Warning:**  
> Always invoke **`python`** (e.g., Python 3.14.x with `PyQt6`, `Pillow`, and `pytest` installed) or `py -3.14` — **do NOT use bare `py`**. On Windows environments with Python 3.14t installed, bare `py` defaults to free-threaded `python3.14t.exe`, which lacks `PyQt6` and raises `ModuleNotFoundError: No module named 'PyQt6'`.

### 1. Install Dependencies & Asset Path Resolution

```powershell
python -m pip install -r requirements.txt
# Optional editable install (requires setuptools; or run from repo root with PYTHONPATH=src):
python -m pip install -e . --no-build-isolation
```

`assets/` resides at the repository root (`VitalSense5/assets/`). Running from the repository root (`PYTHONPATH=src`, `pytest`, or an editable `pip install -e .`) resolves `assets/` automatically. If the package is installed non-editably outside the repository tree, set `VITALSENSE5_ASSETS_DIR` to the absolute path of `assets/` before launching.

### 2. Run Modes (Desktop Pre-Deployment Testing)

```powershell
# Default 1280x720 fixed windowed mode with simulated PPG & vital signs:
$env:PYTHONPATH = "src"
python -m vitalsense5 --windowed --mock

# Fullscreen kiosk preview (press F11 to toggle windowed/fullscreen):
python -m vitalsense5 --kiosk --mock

# Custom UI / mock stream tick interval (ms, default 33):
python -m vitalsense5 --windowed --tick-ms 33
```

### 3. Run Tests

```powershell
# Run M1 theme & asset unit tests in headless offscreen mode (PowerShell):
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest tests/unit/test_theme_and_assets.py -v

# Run all unit tests:
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest tests/unit -v

# Run full test suite:
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest
```

---

## Raspberry Pi 5 Kiosk Deployment Notes

> *Note: The commands below are target-hardware deployment notes derived from `project.md` (`Raspberry PI 5 (2GB)`, `Waveshare 7 Inch LCD - Touchscreen 1280x720 (H)`) and have not been executed on physical RPi 5 hardware from the Windows dev environment.*

1. **No System Font Installation Required:** `vitalsense5.theme.load_bundled_fonts()` registers all 6 `JetBrainsMono-*.ttf` weights directly from `assets/fonts/` via `QFontDatabase.addApplicationFont()`.
2. **Display Server Selection:** On Raspberry Pi OS Bookworm/Trixie, run under Wayland (`QT_QPA_PLATFORM=wayland`) or X11 (`QT_QPA_PLATFORM=xcb`) matching the active compositor (`labwc`/`wayfire` or `Xorg`).
3. **Kiosk Launch Command:**
   ```bash
   QT_QPA_PLATFORM=wayland python3 -m vitalsense5 --kiosk
   ```
   Press `F11` when a commissioning keyboard is attached to toggle between fullscreen kiosk and `1280x720` windowed mode.
4. **Touchscreen Calibration & Ergonomics:** Ensure the Waveshare 7" `1280x720` capacitive touch input is mapped to the HDMI output at native `1280x720` scaling (`1:1`). Built-in drag scrolling (`>=8px` threshold) and the on-screen QWERTY/Numpad overlay operate without an external mouse or keyboard.
