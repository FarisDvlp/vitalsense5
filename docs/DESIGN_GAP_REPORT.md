# VitalSense5 — Design & Functionality Gap Report

**Audited Artifacts:**
- Figma File: `VitalSense-5` (`dN8Zi4OHyd8No80Dm4dkca`) — `Main Screen` (`1:2`), `Patient Screen` (`5:294`), `Settings` (`3:117`), `New Patient Pop Up` (`5:383`) & `(Example)` (`5:407`), `Button Pressed` (`5:403`), `Logo` (`5:3`) vs `Logo (FIX)` (`5:101`), plus exported `figma_assets/` SVGs.
- System & Product Requirements: [`project.md`](../project.md) (`Raspberry PI 5 (2GB)`, `Waveshare 7 Inch LCD 1280x720`, `ESP32-S3`, `MAX30102`, `INA219`, `2S2P 18650`, `SciPy`/`NumPy`/`PySerial`, `SQLite`, Cloud DB, `PyQt6` Kiosk) and project requirements `R1`–`R4`.

---

## 1. Executive Summary & Audit Scope

While the `VitalSense-5` Figma file establishes a clean visual baseline at `1280x720`, it depicts a static "happy-path" mockup rather than a complete ICU-style clinical monitor operating on a keyboard-less 7-inch touchscreen. This audit identifies **26 concrete gaps (`GAP-01` through `GAP-26`)** across 5 categories:

| Category | Gap IDs | Count | Highest Severity |
|---|---|---|---|
| **A. Undefined `Settings` Rows & Modal Lifecycle** | `GAP-01` – `GAP-03` | 3 | High |
| **B. Unspecified Button & Patient-Management Behaviors** | `GAP-04` – `GAP-10` | 7 | High |
| **C. Missing Hardware, Sensor, Connectivity & Alarm States** | `GAP-11` – `GAP-17` | 7 | Critical |
| **D. Figma Alignment, Typography & Asset Anomalies** | `GAP-18` – `GAP-22` | 5 | Medium |
| **E. Raspberry Pi 5 Touchscreen Ergonomics** | `GAP-23` – `GAP-26` | 4 | Critical |
| **Total** | **`GAP-01` – `GAP-26`** | **26** | **4 Critical** |

### Severity Legend
- **Critical:** Blocks safe clinical monitoring, hardware fault visibility, or core touchscreen usability in kiosk deployment.
- **High:** Causes dead/ambiguous UI controls, broken modal lifecycles, or inaccessible touch targets.
- **Medium:** Creates data-formatting, validation, or operational ambiguity during integration.
- **Low:** Minor visual inconsistency, duplicate Figma layers, or 1–2px coordinate jitter.

---

## 2. Category A — Undefined `Settings` Rows & Modal Lifecycle (`GAP-01`–`GAP-03`)

### `GAP-01` (High) — Generic `SETTINGS 1`–`SETTINGS 8` Placeholder Rows
- **Observation:** `Settings` (`3:117`) renders 8 placeholder rows (`SETTINGS 1`–`SETTINGS 8`): 6 ON/OFF toggles (`Rows 1, 2, 5, 6, 7, 8`), 1 underlined numeric value (`SETTINGS 3`: `VALUE000` at `504,100,128x31`), and 1 dropdown (`SETTINGS 4`: `LIST` at `504,150,128x31`), with zero mapping to `project.md` features (UART port/baud, PPG gain/filter, alarm thresholds, Cloud sync, kiosk exit).
- **Frontend Mitigation:** Keep the exact 8 generic `SETTINGS 1`–`SETTINGS 8` slots backed by `SettingsPort` (`SettingSlot` DTOs) so the UI renders dynamic labels, types, and options as soon as teammates populate real configuration rows.
- **Open Team Decision:** Backend, Firmware, and Product leads must assign concrete names, types, defaults, and persistence targets to `SETTINGS 1`–`SETTINGS 8`.

### `GAP-02` (High) — Missing `Settings` Modal Chrome (Close / Done / Scrim)
- **Observation:** The `Settings` frame (`3:117`, `669x383`) is a standalone card with **no title bar, no Close (`X`) or `DONE` button, no `SAVE`/`CANCEL` actions, and no backdrop scrim**. On a touchscreen kiosk without `Esc`, a user entering `Settings` would be trapped.
- **Frontend Mitigation:** Wrap `SettingsModal` in a translucent dark backdrop scrim (`rgba(0, 0, 0, 102)`), add a dedicated `btn_settings_close` (`DONE` / `X`) control (`>=44px` touch target), and optionally allow backdrop tap-to-close.
- **Open Team Decision:** Confirm whether setting changes apply immediately on interaction (current `SettingsPort.update_setting` design) or require explicit `APPLY`/`CANCEL` rollback.

### `GAP-03` (Medium) — Unspecified `LIST` Dropdown Popover & `VALUE000` Editing/Units
- **Observation:** `SETTINGS 4` (`LIST`, `504,150,128x31`) has no dropdown menu mockup, and `SETTINGS 3` (`VALUE000`, `504,100,128x31`) specifies neither allowed numeric ranges/units nor how text editing occurs.
- **Frontend Mitigation:** Render a touch-friendly popover list (`>=44px` item height) anchored to the `LIST` pill, and bind `VALUE000` taps to the built-in `VirtualKeyboardOverlay` in Numpad mode.
- **Open Team Decision:** Define valid dropdown options for `LIST` slots and min/max/decimal/unit rules for numeric `VALUE` slots.

---

## 3. Category B — Unspecified Button & Patient-Management Behaviors (`GAP-04`–`GAP-10`)

### `GAP-04` (High) — Unspecified `SAVE` Button Action & Feedback (`Main Screen`)
- **Observation:** `SAVE` (`3:104`, `779,628,212x51`) has no defined behavior—whether it writes a vital snapshot to `SQLite`, exports a report, or triggers cloud upload—and Figma provides no confirmation toast or error indicator.
- **Frontend Mitigation:** Delegate `SAVE` clicks to `SessionCommandPort.save_snapshot(patient, vitals)` and display a non-blocking status toast (`"Snapshot saved"` or adapter error message).
- **Open Team Decision:** Database/Backend team to define snapshot storage schema, whether `SAVE` triggers immediate cloud sync, and behavior when no active patient is selected.

### `GAP-05` (High) — Unspecified `RECORD` Toggle Semantics & Active State (`Main Screen`)
- **Observation:** `RECORD` (`3:98`, `1016,629,212x51`, `#FF7F7F`) gives no indication of toggle behavior, active recording visual state (elapsed `MM:SS` timer, recording indicator dot, `"STOP"`/`"REC"` label), or collision with `CANCEL` (`5:395`, also `#FF7F7F`).
- **Frontend Mitigation:** Delegate to `SessionCommandPort.toggle_recording(active, patient)`, update button label/indicator (`"REC MM:SS"` / `"STOP REC"`) while recording is active, and display status feedback.
- **Open Team Decision:** Define continuous PPG/vital logging format (`SQLite` vs binary/CSV), maximum session duration on 2GB RAM / SD storage, and auto-stop rules on disconnect.

### `GAP-06` (High) — Unspecified `EDIT PATIENT` Flow & Empty-Selection Guard (`Patient Screen`)
- **Observation:** `EDIT PATIENT` (`5:355`, `794,629,212x51`) has no target screen in Figma and no defined behavior if the patient list is empty or no card is selected.
- **Frontend Mitigation:** Open `NewPatientDialog` in `"Edit Patient"` mode pre-filled with the selected `PatientRecord`, and disable/guard `EDIT PATIENT` with feedback when no patient is selected.
- **Open Team Decision:** Confirm whether patient IDs are immutable after creation and whether editing updates historical SQLite records retroactively.

### `GAP-07` (Medium) — No Patient Deletion Affordance
- **Observation:** Neither `Patient Screen` (`5:294`) nor `New Patient Pop Up` (`5:383`) includes a `DELETE` button or confirmation dialog.
- **Frontend Mitigation:** Preserve the exact 3-button Figma footer (`BACK`, `EDIT PATIENT`, `NEW PATIENT`) without inventing unapproved destructive buttons; document the omission clearly.
- **Open Team Decision:** Clinical/Product leads to decide if on-device patient deletion (with confirmation modal and recording-history cascade rules) is required in v2.

### `GAP-08` (Medium) — Unspecified Patient Switching Timing & Mid-Recording Behavior
- **Observation:** Figma highlights Row 1 (`5:337`, `3px solid #226DAA`) without specifying whether tapping a card switches the active patient immediately or only upon pressing `BACK`, or what happens if `RECORD` is active.
- **Frontend Mitigation:** Tapping a patient card updates `PatientStorePort.set_active_patient()`, highlights the card (`3px solid #226DAA`), and updates `MainScreen`'s header; if `recording_active` is `True`, guard or warn before switching.
- **Open Team Decision:** Confirm clinical rule: block patient switch during active recording or auto-stop and save the prior session first.

### `GAP-09` (Medium) — Missing Input Validation & Unit Formatting (`New Patient Pop Up`)
- **Observation:** `New Patient Pop Up` (`5:383`) shows placeholders (`Name`, `Age`, `Height`, `Weight`), while `(Example)` (`5:407`) shows formatted strings (`"John Doe"`, `"36 Years Old"`, `"178 cm"`, `"70 Kg"`). No validation bounds, required-field indicators, or numeric-only rules exist.
- **Frontend Mitigation:** Store raw integers (`age`, `height_cm`, `weight_kg`) in `PatientRecord`, validate non-empty `Name` and sensible clinical bounds (`Age` 1–120, `Height` 30–250 cm, `Weight` 1–300 kg) with `#FF6161` invalid border + inline error message, and format units on display.
- **Open Team Decision:** Confirm pediatric vs adult min/max bounds for `Age`, `Height`, and `Weight`.

### `GAP-10` (Low-Medium) — Missing Pressed States for Colored Action Buttons
- **Observation:** `Button Pressed` (`5:403`) defines normal `#D9D9D9` -> pressed `#3F3F3F` (`#D9D9D9` text), leaving `#FF7F7F` (`RECORD`, `CANCEL`) and `#90FF93` (`SAVE`) without specified pressed colors.
- **Frontend Mitigation:** Define high-contrast darkened pressed variants in `theme/tokens.py` (`#FF7F7F` -> `#E05E5E`, `#90FF93` -> `#6CE670`) so all buttons provide clear tactile feedback on touchscreens.
- **Open Team Decision:** Design lead sign-off on colored button pressed hex tokens.

---

## 4. Category C — Missing Hardware, Sensor, Connectivity & Alarm States (`GAP-11`–`GAP-17`)

### `GAP-11` (Critical) — UART / ESP32-S3 Disconnect & Stale-Value Fallback
- **Observation:** `Main Screen` (`3:96`) displays only static `"Connected:  UART"` / `"Connected: ESP32"`; `Patient Screen` (`5:294`) omits connection status entirely; no `DISCONNECTED`, `RECONNECTING`, or stale-value `"--"` fallback exists.
- **Frontend Mitigation:** Model `ConnectionState` (`CONNECTED`, `DISCONNECTED`, `RECONNECTING`) in `DeviceStatus`, display `"--"` across vital columns and a disconnect banner on `PPGCanvasWidget` when UART/ESP32 is offline, and show a compact connection badge on `PatientScreen`.
- **Open Team Decision:** Backend/Firmware leads to specify UART JSON heartbeat interval and stale-data timeout (e.g., `>2.0s` without valid packet).

### `GAP-12` (Critical) — MAX30102 Finger-Off, Poor Signal & Calibrating States
- **Observation:** `project.md` relies on a `MAX30102` PPG sensor, yet Figma assumes a perpetual clean waveform (`Vector 39`, `3:93`) with no `FINGER_OFF`, motion-artifact (`POOR_SIGNAL`), or `CALIBRATING` states.
- **Frontend Mitigation:** Model `SensorState` (`OK`, `FINGER_OFF`, `POOR_SIGNAL`, `CALIBRATING`) in `DeviceStatus`, flatlining/pausing the PPG trace with an explicit overlay banner and masking unstable vitals with `"--"`.
- **Open Team Decision:** Algorithm/Firmware leads to define signal-quality index (SQI) and finger-detection thresholds emitted in UART JSON.

### `GAP-13` (High) — Dynamic INA219 2S2P 8.4V 7000mAh Battery Telemetry
- **Observation:** Figma (`3:97`, `3:106`, `5:333`, `5:334`) hardcodes `"95%"` and a static full-green battery icon (`main_battery.svg` also uses `<mask>`/`<use>`, which Qt SVG Tiny 1.2 drops). No low-battery (`<=20%`), critical (`<=10%`), charging, or INA219 fault states exist.
- **Frontend Mitigation:** Bundle clean SVG Tiny 1.2 `assets/icons/battery.svg` for static checks and render a dynamic `QPainter` battery icon in `StatusHeaderBar` reflecting `0–100%` fill height, amber `#E98D62` (`<=20%`), red `#FF6161` (`<=10%`), and charging indicator (`is_charging`).
- **Open Team Decision:** Firmware/Hardware leads to supply the 2S2P 18650 (8.4V) voltage-to-SoC lookup curve and safe auto-shutdown threshold.

### `GAP-14` (High) — Cloud Database Connectivity States (`undecided` in `project.md`)
- **Observation:** `Main Screen` (`3:107`) and `Patient Screen` (`5:380`) show a static solid `#0F172A` cloud icon (`cloud.svg`), lacking `ONLINE`, `OFFLINE`, `SYNCING`, or `ERROR` feedback.
- **Frontend Mitigation:** Model `CloudState` in `DeviceStatus` and tint/annotate the cloud status indicator (`#0F172A` online, `#919191` offline, `#226DAA` syncing, `#FF6161` error).
- **Open Team Decision:** Database lead to finalize Cloud DB technology (`project.md` line 37: `undecided`), sync cadence, and offline queue indicator requirements.

### `GAP-15` (Critical) — ICU-Monitor Abnormal Vital Threshold Alerts
- **Observation:** `project.md` line 2 specifies *"Real time ICU-Monitor style monitoring"*, yet Figma has zero abnormal vital alert states (no red/amber column highlight, no alarm banner, no audible/visual alarm mute or acknowledge button).
- **Frontend Mitigation:** Include `alarms: dict[str, AlarmLevel]` (`NORMAL`, `WARNING`, `CRITICAL`) in `VitalSnapshot`, visually emphasizing breached `VitalColumnWidget` borders/values in `#E98D62` (warning) or `#FF6161` (critical).
- **Open Team Decision:** Clinical/Algorithm leads to define adult/pediatric alarm thresholds for `PRV`, `RR`, `PI`, `SpO2`, `BP`, and `BPM`, plus audible buzzer/mute requirements.

### `GAP-16` (High) — Missing `BPM` (Heart Rate) Display
- **Observation:** Figma includes `PRV (RMSSD ms)` (`88,133`) alongside `RR`, `PI`, `SpO2`, and `BP`, but omits standard heart rate (`HR / BPM`).
- **Frontend Mitigation:** Include `bpm: int | None = None` in `VitalSnapshot` and reserve an unobtrusive secondary `BPM` sub-readout inside the `PRV` column (or header) without breaking the 5-column Figma grid.
- **Open Team Decision:** Product/Clinical leads to confirm whether `BPM` stays as a sub-readout under `PRV` or warrants a dedicated layout change in v2.

### `GAP-17` (Medium) — PPG Scale/Freeze Controls & RTC-less Raspberry Pi 5 Clock/Locale
- **Observation:** The `1124x250` PPG grid (`3:31`) omits timebase (`mm/s`), gain/amplitude scale, and waveform freeze/pause controls. Additionally, `"16/10 Sen 10:30"` (`3:94`) uses Indonesian weekday `"Sen"` (*Senin*), and Raspberry Pi 5 has no battery-backed RTC out of the box without NTP or an external RTC module.
- **Frontend Mitigation:** Use configurable rolling/sweep ring-buffer rendering in `PPGCanvasWidget`, display local system date/time cleanly (supporting configurable locale/format), and keep clock formatting decoupled from vital timestamps.
- **Open Team Decision:** Hardware/Backend leads to confirm PPG sample rate (`Hz`), sweep speed, and whether an external RTC module or offline fallback clock prompt is used on RPi 5.

---

## 5. Category D — Figma Alignment, Typography & Asset Anomalies (`GAP-18`–`GAP-22`)

### `GAP-18` (Low) — Duplicate `Logo` Layers & Superseded Logo Frame
- **Observation:** `Main Screen` (`1:2`) contains two stacked `Logo` instances (`5:53` and `5:295`) at `(31, 24)`, and the canvas retains an older `Logo` frame (`5:3`) alongside `Logo (FIX)` (`5:101`).
- **Frontend Mitigation:** Render `assets/icons/vs5_logo.svg` (copied from `Logo (FIX)` `5:101`) exactly once per header.
- **Open Team Decision:** None (resolved in frontend).

### `GAP-19` (Low) — Minor 1–2px Coordinate Jitter Across Figma Nodes
- **Observation:** Accent bars `Vector 34..38` sit at `y=138` vs `y=136`; `SAVE` sits at `y=628` while `RECORD` sits at `y=629`; `Patient Screen` date sits at `y=68` vs `y=66` on `Main Screen`; `BP` `mmHg` sits at `y=269` (SYS) vs `y=271` (DIA).
- **Frontend Mitigation:** Snap sibling elements to clean shared baselines in PyQt6 layouts (`y=138` accent bars, `y=628` bottom bar, `y=66` header date/time).
- **Open Team Decision:** None (resolved in frontend).

### `GAP-20` (Medium) — `PI` Value Format (`"03"` vs Decimal Clinical Values) & Column Width
- **Observation:** `PI` (`3:21`) displays zero-padded `"03"` (`96px` Light, `-3.84px` tracking), whereas clinical Perfusion Index is typically a decimal (`0.5%`, `3.2%`, `12.4%`). At `96px`, 4-character strings like `"12.4"` risk colliding with the `"%"` unit label.
- **Frontend Mitigation:** Format `PI` cleanly (e.g., `1` decimal place when `<10`, auto-adjusting font size or layout spacing when string length exceeds 2–3 characters) and test overflow in `test_widgets_and_touch.py`.
- **Open Team Decision:** Algorithm lead to confirm `PI` precision/format (`0.1` vs integer `%`).

### `GAP-21` (Low) — Patient Card Unit Inconsistency (`"Weight: XX"` vs `"70 Kg"`)
- **Observation:** `Patient Screen` card metadata (`5:354`) writes `"Age: XX Height: XXcm Weight: XX"` (omitting `"kg"`), while `New Patient Pop Up (Example)` (`5:416`) writes `"70 Kg"`.
- **Frontend Mitigation:** Normalize `PatientScreen` card metadata to `"Age: {age}  Height: {height_cm}cm  Weight: {weight_kg}kg"`.
- **Open Team Decision:** None unless imperial units are ever requested.

### `GAP-22` (Low) — `figma_assets/` SVG Export Quirks (`settings_polygon.svg`, `main_battery.svg`) & Qt QSS Radius Clamping
- **Observation:**
  1. `settings_polygon.svg` (`d="M6.06218 0L12.1244 10.5H0L6.06218 0Z"`) points **upward** in SVG Y-down coordinates because Figma rotated the node 180° in the frame.
  2. `main_battery.svg` uses `<mask>` + `<use>`, which Qt's SVG Tiny 1.2 `QSvgRenderer` ignores, dropping the `#59C461` border.
  3. Qt QSS disables `border-radius` completely (rendering square corners) whenever `border-radius > min(width, height) / 2` (impacting Figma's `47px` on `h=59px`, `19px` on `h=31px`, `16px` on `w=28px`, `10px` on `w=13px`).
- **Frontend Mitigation:** Authored clean SVG Tiny 1.2 assets (`assets/icons/dropdown_arrow.svg` pointing downward, `assets/icons/battery.svg` with dual-path border + fill and zero `<mask>`/`<use>`), and implemented `clamp_pill_radius()` in `src/vitalsense5/theme/tokens.py`.
- **Open Team Decision:** None (resolved in frontend).

---

## 6. Category E — Raspberry Pi 5 Touchscreen Ergonomics (`GAP-23`–`GAP-26`)

### `GAP-23` (High) — Sub-44px Touch Targets in `Settings` & Scrollbars
- **Observation:** `Settings` toggles (`84x31px`), `VALUE000`/`LIST` pills (`128x31px`), `Settings` scrollbar (`13px` wide), and `Patient Screen` scrollbar (`28px` wide) are all smaller than the `44x44px` minimum recommended finger touch target on a 7-inch `1280x720` display.
- **Frontend Mitigation:** Expand each `Settings` row's touch hitbox (`>=48px` tall) around the visual `31px` pill/toggle, use `>=44px` scrollbar handles, and enable whole-viewport touch drag scrolling.
- **Open Team Decision:** None (resolved in frontend).

### `GAP-24` (Critical) — Missing On-Screen Virtual Keyboard / Numpad & Modal Overlap
- **Observation:** Raspberry Pi 5 kiosk deployment (`project.md`) has no physical keyboard. Figma omits an on-screen keyboard/numpad, and `New Patient Pop Up` (`5:383`, centered vertically at `y=244..475`) would be obscured by a bottom-docked keyboard at `1280x720`.
- **Frontend Mitigation:** Implement `VirtualKeyboardOverlay` with automatic QWERTY (`Name`) and Numpad (`Age`, `Height`, `Weight`, `VALUE000`) switching, and shift active modals upward (`y ≈ 36..120`) whenever the keyboard is open.
- **Open Team Decision:** Confirm whether non-ASCII/accented patient names or special characters are needed in the QWERTY layout.

### `GAP-25` (High) — Missing Touch Drag Scrolling Behavior
- **Observation:** Both `Patient Screen` and `Settings` assume mouse-wheel or tiny scrollbar-thumb interaction (`28px` / `13px`), which is frustrating with fingers on a capacitive touchscreen.
- **Frontend Mitigation:** Implement `TouchScrollArea` with a `>=8px` drag threshold so finger swipes scroll smoothly without firing accidental tap/selection events.
- **Open Team Decision:** None (resolved in frontend).

### `GAP-26` (Medium) — Missing Kiosk Mode Toggle / Commissioning Exit & Hover States
- **Observation:** Figma has no desktop-vs-kiosk mode switch or commissioning exit mechanism, and hover-dependent styling fails on touchscreens.
- **Frontend Mitigation:** Support `--windowed` (`1280x720`) and `--kiosk` (fullscreen frameless) CLI flags plus `F11` toggle, and avoid hover-only states in QSS.
- **Open Team Decision:** Team lead to decide whether a long-press corner gesture or `SETTINGS` slot should also expose kiosk exit in production.

---

## 7. Summary Decision Matrix for Teammates

| Decision Area | Related Gaps | Owner | Frontend Placeholder / Current Behavior |
|---|---|---|---|
| `SETTINGS 1`–`SETTINGS 8` definitions & bounds | `GAP-01`, `GAP-03` | Backend / Firmware / Product | 8 generic slots via `SettingsPort` (`6` toggles, `VALUE000`, `LIST`) |
| `Settings` apply-immediately vs `APPLY`/`CANCEL` | `GAP-02` | Product / Backend | Immediate `SettingsPort.update_setting()` + `btn_settings_close` |
| `SAVE` snapshot & `RECORD` session persistence | `GAP-04`, `GAP-05` | Database / Backend | Delegated to `SessionCommandPort` + toast & recording timer |
| Patient edit/delete & mid-recording switch rules | `GAP-06`–`GAP-09` | Product / Database | Create/Edit modal + validation (`Name`, `Age`, `Height`, `Weight`); no delete UI |
| UART JSON schema, heartbeat & reconnect timeout | `GAP-11`, `GAP-17` | Firmware / Backend | `ConnectionState` + `"--"` fallback + `PPGCanvasWidget` overlay |
| `MAX30102` SQI / finger-off thresholds & `BPM` slot | `GAP-12`, `GAP-16` | Algorithm / Firmware | `SensorState` overlays + `bpm` field in `VitalSnapshot` |
| `INA219` 8.4V battery SoC curve & shutdown rule | `GAP-13` | Firmware / Hardware | Dynamic `QPainter` battery (`<=20%` warning, `<=10%` critical, charging) |
| Cloud DB technology, sync & retry queue | `GAP-14` | Database | `CloudState` (`ONLINE`, `OFFLINE`, `SYNCING`, `ERROR`) indicator |
| Clinical alarm thresholds & audible buzzer | `GAP-15` | Clinical / Algorithm | `AlarmLevel` (`NORMAL`, `WARNING`, `CRITICAL`) column highlighting |
| `PI` decimal precision & RPi 5 RTC/NTP strategy | `GAP-17`, `GAP-20` | Algorithm / Hardware | Clean decimal/int formatting + local system clock display |
