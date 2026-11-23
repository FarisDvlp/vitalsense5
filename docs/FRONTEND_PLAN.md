# VitalSense5 — Frontend Software Architecture & Integration Plan

**Target Platform:** Raspberry Pi 5 (2GB), Waveshare 7-inch Capacitive Touchscreen (`1280x720`, Kiosk Mode)  
**UI Framework:** `PyQt6` (`>=6.10`) with bundled `JetBrains Mono` typography  
**Design Source:** `VitalSense-5` Figma (`dN8Zi4OHyd8No80Dm4dkca`) & [`project.md`](../project.md)

---

## 1. Purpose & System Context

VitalSense5 is a real-time, ICU-monitor style vital sign monitor based on Photoplethysmography (PPG). The system splits responsibilities cleanly between edge firmware (`ESP32-S3`), Python signal processing/ML & persistence (`Raspberry Pi 5` backend/database), and the `PyQt6` touchscreen interface (`VitalSense5` frontend).

```text
+-----------------------+      I2C      +----------------------------------+
| MAX30102 PPG Sensor   | ------------> | ESP32-S3 (FreeRTOS Dual Core)    |
| INA219 Current Sensor | ------------> | Core 1: I2C + FIFO Drain         |
+-----------------------+               | Core 2: UART JSON Streaming      |
                                        +----------------------------------+
                                                         |
                                                    UART (JSON)
                                                         v
+--------------------------------------------------------------------------+
| Raspberry Pi 5 (2GB) — Teammate-Owned Backend & Persistence              |
|  - PySerial UART reader & packet parser                                  |
|  - SciPy / NumPy signal conditioning + Python ML models                  |
|    (PRV RMSSD, RR, PI, SpO2, BP SYS/DIA, BPM, PPG waveform)              |
|  - SQLite local storage & Cloud Database sync                            |
+--------------------------------------------------------------------------+
                     ||
                     ||  Typed Frontend Contracts (src/vitalsense5/contracts/)
                     \/  VitalDataPort | PatientStorePort | SettingsPort | SessionCommandPort
+--------------------------------------------------------------------------+
| Raspberry Pi 5 (2GB) — VitalSense5 PyQt6 Frontend (THIS REPOSITORY)      |
|  - 1280x720 Kiosk / Windowed Shell (Waveshare 7" Touchscreen)            |
|  - MainScreen, PatientScreen, SettingsModal, NewPatientDialog            |
|  - TouchScrollArea + Built-in QWERTY/Numpad VirtualKeyboardOverlay       |
|  - Standalone PC Mock Adapters (src/vitalsense5/adapters/)               |
+--------------------------------------------------------------------------+
```

### Strict Scope Exclusion Matrix

| Concern | Frontend (`vitalsense5`) | Teammate-Owned Layer |
|---|---|---|
| `1280x720` `PyQt6` layout, Figma styling, pressed states | **Owned** | Excluded |
| Bundled `JetBrains Mono` fonts & SVG Tiny 1.2 icons | **Owned** | Excluded |
| PPG `QPainter` grid & ring-buffered waveform rendering | **Owned** | Excluded |
| On-screen QWERTY/Numpad keyboard & touch drag scrolling | **Owned** | Excluded |
| Typed DTOs (`models.py`), `Protocol` ports (`ports.py`), PC mocks (`adapters/`) | **Owned** | Implements production ports |
| `PySerial` UART JSON framing, port discovery, reconnect logic | Excluded | **Backend / Firmware** |
| `SciPy`/`NumPy` DSP filtering, peak detection, ML vital estimation | Excluded | **Backend / Algorithm** |
| `SQLite` schema/queries & Cloud DB client/sync | Excluded | **Database** |
| `ESP32-S3` FreeRTOS tasks, `MAX30102`/`INA219` I2C drivers | Excluded | **Firmware** |

---

## 2. Package & Module Architecture (`src/vitalsense5/`)

The `src` layout isolates presentation, contracts, and mock adapters into six focused modules:

1. **`src/vitalsense5/theme/`** *(Foundation — Milestone M1)*
   - `tokens.py`: Immutable `COLORS`, `RADII`, `BORDERS`, `LAYOUT`, `TYPOGRAPHY` dataclasses matching exact Figma hex/px values, plus `clamp_pill_radius(figma_radius, min_dim_px)` to prevent Qt QSS square-corner fallback.
   - `fonts.py`: `load_bundled_fonts()` registering all 6 `assets/fonts/JetBrainsMono-*.ttf` weights via `QFontDatabase.addApplicationFont()`, asset path helpers (`VITALSENSE5_ASSETS_DIR` overrideable), and `jetbrains_mono_font()` / `font_from_token()`.
   - `styles.py`: Pure QSS builders (`app_base_qss`, `action_button_qss`, `modal_card_qss`, `modal_scrim_qss`, `input_pill_qss`, `patient_card_qss`, `scrollbar_qss`, `settings_pill_qss`, `vital_accent_bar_qss`).

2. **`src/vitalsense5/contracts/`** *(Boundaries — Milestone M2)*
   - `models.py`: Pure Python enums (`ConnectionState`, `CloudState`, `SensorState`, `AlarmLevel`, `SettingControlType`) and immutable dataclasses (`VitalSnapshot`, `WaveformBatch`, `DeviceStatus`, `PatientRecord`, `SettingSlot`). Zero Qt widget imports so backend teammates can import DTOs in headless services or tests.
   - `ports.py`: `typing.Protocol` interfaces (`VitalDataPort`, `PatientStorePort`, `SettingsPort`, `SessionCommandPort`, and optional `SimulationControlPort`).

3. **`src/vitalsense5/adapters/`** *(PC Testing Mocks — Milestone M2)*
   - `MockVitalDataAdapter`: Generates realistic synthetic PPG waveforms (systolic peak + dicrotic notch) and updating `PRV`, `RR`, `PI`, `SpO2`, `BP`, `BPM`, battery, and connectivity states. Supports simulation profiles (`normal`, `warning`, `critical`, `finger_off`, `uart_disconnected`, `low_battery`, `cloud_offline`) via `SimulationControlPort`.
   - `InMemoryPatientStore`, `InMemorySettingsStore`, `MockSessionCommandHandler`: In-memory implementations supporting patient CRUD, the 8 `SETTINGS 1`–`SETTINGS 8` generic slots, snapshot saving, and recording state transitions.

4. **`src/vitalsense5/widgets/`** *(Reusable UI & Touch Components — Milestone M3)*
   - `StatusHeaderBar`: Top bar (`VS5` logo, screen title or active patient name, clock, cloud status icon, UART/ESP32 status, battery % + `QPainter` dynamic battery icon).
   - `VitalColumnWidget`: Reusable vital readout column with `5px` colored accent bar, `48px` header, optional sublabel (`RMSSD`), `96px`/`64px` value, units, `--` stale/disconnect masking, `WARNING`/`CRITICAL` alarm highlight, and optional `BPM` sub-readout.
   - `PPGCanvasWidget`: `1124x250` `#E4E4E4` canvas, `5px` `#D2D2D2` border, `2px` `#C9C9C9` grid (`34px` V / `41.766px` H), `2px` `#313131` ring-buffered trace, and sensor/disconnect overlays (`FINGER_OFF`, `POOR_SIGNAL`, `CALIBRATING`, `DISCONNECTED`).
   - `ActionButton`: `212x51` `r=10px` button supporting `#D9D9D9` -> `#3F3F3F` (`#D9D9D9` text) pressed state plus `#FF7F7F` (`danger`) and `#90FF93` (`success`) variants.
   - `TouchScrollArea`: `QScrollArea` with mouse/touch drag scrolling (`TOUCH_DRAG_THRESHOLD_PX = 8`) so finger swipes scroll smoothly without accidental clicks.
   - `VirtualKeyboardOverlay`: Built-in QWERTY + Numpad touch overlay emitting key/backspace/done events and reporting occupied height for modal upward repositioning.

5. **`src/vitalsense5/screens/`** *(Screen Orchestration — Milestone M4)*
   - `MainScreen`: Header + 5 vital columns + `PPGCanvasWidget` + bottom action bar (`PATIENT`, `SETTINGS`, `SAVE`, `RECORD` with active recording timer/badge + non-blocking toast).
   - `PatientScreen`: Header (with compact connection badge) + `TouchScrollArea` of `1166x71` patient cards (`#226DAA` selected border) + `BACK`, `EDIT PATIENT`, `NEW PATIENT`.
   - `SettingsModal`: `669x383` modal over translucent scrim (`rgba(0,0,0,102)`), `TouchScrollArea` with `SETTINGS 1`–`SETTINGS 8` placeholder rows (6 toggles, `VALUE000` numpad pill, `LIST` dropdown popover), `2px` dividers, and `btn_settings_close`.
   - `NewPatientDialog`: `875x231` modal supporting Create & Edit modes (`Name`, `Age`, `Height`, `Weight` pill inputs, inline validation, `CANCEL`, `SAVE`) with automatic upward shift when the virtual keyboard opens.
   - `MainWindow`: Top-level `1280x720` shell hosting `QStackedWidget` (`MainScreen` <-> `PatientScreen`), modal scrim/overlays, `VirtualKeyboardOverlay`, `QTimer` polling loop, and `F11` kiosk toggle.

6. **`src/vitalsense5/main.py`** *(Entrypoint — Milestone M4)*
   - `create_app(vital_port=None, patient_store=None, settings_store=None, command_handler=None, kiosk=False) -> MainWindow`
   - `main(argv=None) -> int` supporting `--windowed`, `--kiosk`, `--mock`, and `--tick-ms N` (default `33`).

### Architectural Invariants
- **No simulation or hardware math in widgets:** `widgets/` and `screens/` strictly render DTO snapshots and emit user actions to `contracts/` ports.
- **No Qt imports in `contracts/`:** `contracts/models.py` and `contracts/ports.py` remain pure Python so backend and database engineers can implement and test adapters without a GUI dependency.
- **Single-threaded Qt GUI updates:** External background threads never mutate `QWidget`s directly; `MainWindow` pulls thread-safe snapshots on the GUI thread via `QTimer`.

---

## 3. Visual Design System & `1280x720` Screen / Widget Architecture

### Design Tokens Summary (`src/vitalsense5/theme/tokens.py`)

| Token Group | Exact Values | Usage |
|---|---|---|
| **Canvases & Cards** | `#EDEDED` screen, `#D9D9D9` card/modal/button, `#FDFDFD` input, `#F0F0F0` Settings pill, `rgba(0,0,0,102)` scrim | Backgrounds, cards, modals |
| **Pressed States** | `#3F3F3F` fill / `#D9D9D9` text (default); `#E05E5E` (danger); `#6CE670` (success) | Tactile touchscreen press feedback |
| **PPG Waveform Grid** | `#E4E4E4` fill, `5px #D2D2D2` border, `2px #C9C9C9` grid (`34px` V / `41.766px` H), `2px #313131` trace | Live waveform area (`1124x250`) |
| **Vital Accents (`5px`)** | PRV `#CD5656`, RR `#E98D62`, PI `#B369D3`, SpO2 `#64C25E`, BP `#4E54A7` | `h=166px` (`166.5` Figma) vertical column bars |
| **Brand & Semantic** | `#226DAA` selection/logo blue, `#1EB5D7` logo cyan, `#FF7F7F` record/cancel, `#90FF93` save/ON, `#FF6161` OFF/critical, `#E98D62` warning/low battery, `#B9FF7F`/`#59C461` battery, `#0F172A` cloud online, `#919191` placeholder/offline | Brand, semantic controls, clinical status |
| **Radii (Qt Clamped)** | Action btn `10px`, Patient card `14px`, Modal `15px`, Input pill `47->29px`, Settings pill `19->15px`, Scrollbars `16->14px` / `10->6px` | `clamp_pill_radius()` prevents Qt square fallback |
| **Typography** | `JetBrains Mono` weights `200` (`ExtraLight`), `300` (`Light`), `400`, `500`, `600`, `700` (`Bold`); sizes `96/64/48/36/32/24/20/16px`; `PI` tracking `-3.84px` | Bundled `.ttf` files loaded via `QFontDatabase` |

### `1280x720` Screen & Modal Hierarchy

```text
MainWindow (objectName="main_window", 1280x720 fixed or fullscreen kiosk)
├── QStackedWidget
│   ├── MainScreen (objectName="main_screen")
│   │   ├── StatusHeaderBar (y=24..116: vs5_logo, lbl_active_patient, lbl_datetime, cloud icon, lbl_uart_status, lbl_battery_pct, battery icon)
│   │   ├── Vital Columns Row (y=133..323: vital_prv, vital_rr, vital_pi, vital_spo2, vital_bp)
│   │   ├── PPGCanvasWidget (objectName="ppg_canvas", 80,348 1124x250)
│   │   └── Bottom Bar (y=628: btn_patient, btn_settings, btn_save, btn_record [212x51])
│   └── PatientScreen (objectName="patient_screen")
│       ├── StatusHeaderBar (VS5 logo, "Patient List" 32px Bold, clock, cloud, compact connection badge, battery)
│       ├── TouchScrollArea (objectName="patient_scroll_area", y=134..610, 1166x71 cards, 28px scrollbar)
│       └── Bottom Bar (y=628: btn_back, btn_edit_patient, btn_new_patient [212x51])
├── Modal Backdrop Scrim (rgba(0,0,0,102))
│   ├── SettingsModal (objectName="settings_modal", 669x383, settings_scroll_area, settings_row_1..8, btn_settings_close)
│   └── NewPatientDialog (objectName="new_patient_dialog", 875x231, input_patient_name/age/height/weight, btn_patient_cancel, btn_patient_save)
├── Toast Banner (non-blocking save/validation/recording feedback)
└── VirtualKeyboardOverlay (objectName="virtual_keyboard_overlay", bottom-docked QWERTY / Numpad)
```

### Stable Qt `objectName` Reference

| Component | `objectName` | Notes |
|---|---|---|
| Top-level window | `main_window` | Fixed `1280x720` windowed or fullscreen kiosk |
| Main monitor screen | `main_screen` | Contains `vital_prv`, `vital_rr`, `vital_pi`, `vital_spo2`, `vital_bp`, `ppg_canvas` |
| Main screen header labels | `lbl_active_patient`, `lbl_datetime`, `lbl_uart_status`, `lbl_battery_pct` | Updated on `QTimer` tick |
| Main screen buttons | `btn_patient`, `btn_settings`, `btn_save`, `btn_record` | `212x51`, `r=10px` |
| Patient list screen | `patient_screen` | Contains `patient_scroll_area`, `btn_back`, `btn_edit_patient`, `btn_new_patient` |
| Settings modal | `settings_modal` | Contains `settings_scroll_area`, `settings_row_1`..`settings_row_8`, `btn_settings_close` |
| New/Edit patient modal | `new_patient_dialog` | Contains `input_patient_name`, `input_patient_age`, `input_patient_height`, `input_patient_weight`, `btn_patient_cancel`, `btn_patient_save` |
| Virtual keyboard | `virtual_keyboard_overlay` | Exposes active mode (`qwerty` / `numpad`) and key buttons |

---

## 4. Raspberry Pi 5 (2GB) & Waveshare 7" `1280x720` Kiosk Ergonomics

1. **Minimum Touch Target Discipline (`>=44px`)**
   - Bottom action buttons (`51px`), patient cards (`71px`), and patient modal input pills (`59px`) naturally satisfy the `44px` minimum.
   - `SettingsModal` rows (`48px` tall) wrap `31px`-tall toggles and pills inside `>=44px` vertical touch hitboxes, and list/modal scrolling relies on whole-viewport touch drag rather than narrow `13px`/`28px` scrollbar thumbs.

2. **Touch Drag-vs-Tap Discrimination (`TouchScrollArea`)**
   - Tracks pointer press position; movement `< 8px` (`LAYOUT.TOUCH_DRAG_THRESHOLD_PX`) on release is treated as a tap (selecting a patient card or toggling a setting), whereas movement `>= 8px` scrolls the viewport smoothly without triggering child click actions.

3. **In-App `VirtualKeyboardOverlay` & Modal Upward Repositioning**
   - **QWERTY mode** activates automatically when `input_patient_name` receives focus (letters, digits, space, shift, backspace, `DONE`).
   - **Numpad mode** activates automatically when `input_patient_age`, `input_patient_height`, `input_patient_weight`, or `SETTINGS 3` (`VALUE000`) receives focus (digits `0–9`, optional `.`, backspace, `DONE`).
   - **Collision avoidance at `1280x720`:** The keyboard docks at the bottom (`y ≈ 430..720`, height `~290px`). While visible, `NewPatientDialog` (`h=231`) or `SettingsModal` (`h=383`) shifts upward toward the top safe zone (`y ≈ 36..120`) so every input pill and `CANCEL`/`SAVE` remains 100% visible and tappable.

4. **Low-RAM (`2GB`) PPG Rendering & Kiosk Mode**
   - `PPGCanvasWidget` avoids heavyweight `QtWebEngine` or `Matplotlib` dependencies, using a bounded `collections.deque` ring buffer rendered directly with `QPainter` (`2px` `#313131` stroke) at `~30 FPS` (`--tick-ms 33`).
   - `--windowed` enforces `setFixedSize(1280, 720)` for deterministic desktop verification; `--kiosk` applies `Qt.WindowType.FramelessWindowHint` + `showFullScreen()`, toggleable via `F11`.
   - For Raspberry Pi OS deployment, launch with `QT_QPA_PLATFORM=wayland` (or `xcb` on X11); hover-only visual states are omitted in favor of crisp `:pressed` / `[pressed="true"]` feedback.

---

## 5. Teammate Integration Boundaries & Contract Ports

### DTOs (`src/vitalsense5/contracts/models.py`)

- **Enums:**
  - `ConnectionState`: `CONNECTED`, `DISCONNECTED`, `RECONNECTING`
  - `CloudState`: `ONLINE`, `OFFLINE`, `SYNCING`, `ERROR`
  - `SensorState`: `OK`, `FINGER_OFF`, `POOR_SIGNAL`, `CALIBRATING`
  - `AlarmLevel`: `NORMAL`, `WARNING`, `CRITICAL`
  - `SettingControlType`: `TOGGLE`, `VALUE`, `DROPDOWN`
- **Dataclasses:**
  - `VitalSnapshot(prv_rmssd_ms, rr_brpm, pi_percent, spo2_percent, bp_sys_mmhg, bp_dia_mmhg, bpm=None, alarms={}, timestamp=...)` — nullable numeric fields allow `--` rendering during disconnect/calibration.
  - `WaveformBatch(samples: list[float], sample_rate_hz: float, timestamp: datetime)`
  - `DeviceStatus(uart_state, esp32_state, sensor_state, cloud_state, battery_percent, battery_voltage, is_charging, recording_active, recording_elapsed_s, status_message="")`
  - `PatientRecord(patient_id: str, name: str, age: int, height_cm: int, weight_kg: int)`
  - `SettingSlot(slot_index: int, key: str, label: str, control_type: SettingControlType, value: bool | str | int | float, options: list[str] = ...)`

### Port Protocols (`src/vitalsense5/contracts/ports.py`)

- **`VitalDataPort`**:
  - `start() -> None`
  - `stop() -> None`
  - `latest_vitals() -> VitalSnapshot`
  - `pop_waveform_samples() -> WaveformBatch`
  - `device_status() -> DeviceStatus`
  - *Design Note (`SimulationControlPort` separation):* Test-profile switching (`set_simulation_profile(profile: str)`) is defined on a separate optional `SimulationControlPort` protocol (implemented by `MockVitalDataAdapter`) rather than required on `VitalDataPort`, so teammate production UART/ML adapters do not have to implement mock simulation methods.
- **`PatientStorePort`**: `list_patients()`, `get_active_patient()`, `set_active_patient(patient_id)`, `create_patient(name, age, height_cm, weight_kg)`, `update_patient(patient_id, name, age, height_cm, weight_kg)`.
- **`SettingsPort`**: `list_settings() -> list[SettingSlot]`, `update_setting(slot_index: int, value: bool | str) -> SettingSlot`.
- **`SessionCommandPort`**: `save_snapshot(patient, vitals) -> tuple[bool, str]`, `toggle_recording(active, patient) -> tuple[bool, str]`.

### Thread-Safety & Integration Recipe

Teammate `PySerial` / `SciPy` / `SQLite` threads should push computed results into thread-safe buffers (`threading.Lock` or `queue.Queue`) and return immediately from `latest_vitals()`, `pop_waveform_samples()`, and `device_status()`. `MainWindow` polls these methods on the Qt GUI thread (`QTimer`, `33ms` default).

```python
import sys
from PyQt6.QtWidgets import QApplication
from vitalsense5.main import create_app

# Teammate-owned production implementations of contracts/ports.py:
# from my_backend import SerialVitalAdapter, SqlitePatientStore, SqliteSettingsStore, SessionService

def run_production() -> int:
    app = QApplication(sys.argv)
    window = create_app(
        vital_port=SerialVitalAdapter(port="/dev/ttyAMA0", baudrate=115200),
        patient_store=SqlitePatientStore("vitalsense5.db"),
        settings_store=SqliteSettingsStore("vitalsense5.db"),
        command_handler=SessionService("vitalsense5.db"),
        kiosk=True,
    )
    window.show()
    return app.exec()
```
