# VitalSense5 — ESP32-S3 Firmware Architecture & Implementation Specification

**Target MCU:** Waveshare ESP32-S3-Zero Mini Development Board (`ESP32-S3FH4R2`, Dual-Core Xtensa LX7 @ 240 MHz, 4 MB Flash, 2 MB Quad PSRAM)  
**Build System & Framework:** PlatformIO (`espressif32`, `framework = arduino`) in [`firmware/`](firmware/)  
**Host Target:** Raspberry Pi 5 (2 GB) running the VitalSense5 Python Backend (`PySerial` + `SciPy`/`NumPy` + `PyQt6` Kiosk UI)  
**Related Documents:** [`project.md`](project.md) · [`docs/FRONTEND_PLAN.md`](docs/FRONTEND_PLAN.md) · [`docs/DESIGN_GAP_REPORT.md`](docs/DESIGN_GAP_REPORT.md) · [`src/vitalsense5/contracts/models.py`](src/vitalsense5/contracts/models.py)

---

## 1. Firmware Audit & Resolved Plan Gaps

An audit of the initial `firmware.md` draft against hardware datasheets (`ESP32-S3`, `MAX30102`, `INA219`, `TP5100`) and the VitalSense5 frontend/backend contracts ([`models.py`](src/vitalsense5/contracts/models.py)) identified **12 technical gaps**, all resolved in this specification:

| Gap ID | Original Gap in `firmware.md` | Resolution in Updated Specification |
|---|---|---|
| **FW-GAP-01** | **Non-native 125 Hz MAX30102 rate:** The MAX30102 hardware ADC only supports `50, 100, 200, 400, 800, 1000, 1600, 3200` SPS with `1, 2, 4, 8, 16, 32` FIFO averaging. | **Standardized on native 200 Hz effective output rate** (`800 SPS` raw ADC rate with `SMP_AVE = 4` hardware FIFO averaging, yielding 200 averaged samples/sec with 6 dB lower optical shot noise). |
| **FW-GAP-02** | **FreeRTOS core numbering mismatch:** Specified "Core 1" and "Core 2", whereas ESP32-S3 FreeRTOS cores are **0-indexed (`Core 0` and `Core 1`)**. | **Core 1 (`APP_CPU`)** is dedicated to deterministic I2C polling, FIFO draining, hot-plug detection, and INA219 telemetry; **Core 0 (`PRO_CPU`)** handles UART TX streaming and RX command parsing. |
| **FW-GAP-03** | **Unspecified inter-core data transfer & memory safety:** No mechanism defined between the I2C producer core and UART consumer core. | Lock-free **FreeRTOS Queue (`xQueueCreate(128, sizeof(PpgSampleFrame))`)** for 200 Hz PPG samples (`640 ms` buffer headroom) plus atomic mutex-protected `PowerHealthTelemetry` struct for 1 Hz status frames. |
| **FW-GAP-04** | **Missing UART physical pins, baud rate & framing:** Did not specify USB CDC vs hardware UART, GPIO pins, or baud rate needed for JSON streaming. | **Hardware `UART1`** on dedicated GPIOs (`TX = GPIO 43`, `RX = GPIO 44`, configurable fallback `GPIO 5`/`GPIO 6`) wired to Raspberry Pi 5 `GPIO 14/15` (`/dev/ttyAMA0`) at **`460800` baud** (`8N1`) using **Newline-Delimited JSON (NDJSON)**. USB-C (`USB CDC`) remains dedicated to flashing and debug logs. |
| **FW-GAP-05** | **I2C address collision & hot-plug switching undefined:** Both MAX30102 sensors share fixed I2C address `0x57`. Switching behavior when plugging/unplugging the finger clip was unspecified. | Dual hardware I2C controllers (`Wire` on Bus 0, `Wire1` on Bus 1). **Periodic 500 ms Bus 1 probe (`0x57`) + continuous ACK monitoring:** when the Finger Clip responds on Bus 1, the On-Board sensor on Bus 0 is placed in hardware shutdown (`SHDN = 1`, LEDs off); if Bus 1 disconnects/NACKs, the On-Board sensor wakes and resumes seamlessly within `<50 ms`. |
| **FW-GAP-06** | **Unspecified MAX30102 optical & ADC registers:** ADC full-scale range, LED pulse width/resolution, and LED currents were missing. | `16384 nA` ADC range, `411 µs` pulse width (**full 18-bit ADC resolution**), `SpO2 Mode (0x03)` (Red + IR), `FIFO_A_FULL = 0x0F`, and default LED currents (`Red = 0x24` / `7.2 mA`, `IR = 0x24` / `7.2 mA`, adjustable at runtime via UART command). |
| **FW-GAP-07** | **Missing INA219 power-path topology & 2S2P SoC math:** No voltage-to-percentage curve or charging detection for the `8.4 V 7000 mAh` battery + `TP5100` charger + `12 V PD Trigger`. | **High-side bidirectional shunt (`0.1 Ω`) on the 2S2P battery pack output** (`I2C 0x40` on Bus 0). Positive vs negative shunt current determines `is_charging` vs discharging, paired with a **piecewise 2S Li-Ion open-circuit/load-compensated SoC curve (`6.0 V = 0%` to `8.4 V = 100%`)**. |
| **FW-GAP-08** | **Undefined JSON schema & frontend contract mapping:** [`models.py`](src/vitalsense5/contracts/models.py) requires `SensorState`, `ConnectionState`, `battery_percent`, `battery_voltage`, `is_charging`, and `WaveformBatch`. | Defined two compact NDJSON packet types: **`"s"` (200 Hz PPG sample line)** formatted via zero-heap `snprintf` and **`"t"` (1 Hz status/battery/heartbeat line)** plus **`"ack"` / `"err"`** command responses. |
| **FW-GAP-09** | **Unclear MCU vs RPi 5 responsibility for `SensorState`:** Whether finger-off and signal quality are computed on ESP32-S3 or in Python. | **Hybrid split:** ESP32-S3 emits raw 18-bit Red & IR counts, active sensor source (`"clip"` vs `"onboard"`), and an immediate hardware `finger` boolean (`IR > 50,000` counts); Raspberry Pi 5 Python backend computes full SQI (`ok`, `poor_signal`, `calibrating`) and ML vital signs. |
| **FW-GAP-10** | **No downstream control channel from RPi 5 (`SettingsModal`):** [`DESIGN_GAP_REPORT.md`](docs/DESIGN_GAP_REPORT.md) (`GAP-01`) notes 8 Settings slots on the UI without firmware hooks. | **Lightweight bidirectional UART RX command parser** on Core 0 accepting newline-terminated JSON commands (`set_sensor_mode`, `set_led_current`, `set_ir_threshold`, `reset_sensor`, `get_status`). |
| **FW-GAP-11** | **Missing fault recovery & watchdog strategy:** Long-Finger-Clip cables on I2C Bus 1 can pick up EMI or lock SDA low mid-transaction. | Hardware I2C timeout (`50 ms`), 9-clock SCL bus-recovery sequence on stuck SDA, automatic sensor re-initialization on power-ready (`PWR_RDY`) brownout flag, and 3-second ESP32 Task Watchdog Timer (`TWDT`). |
| **FW-GAP-12** | **Missing PlatformIO project blueprint:** No directory layout, board definition, build flags, or library dependencies. | Standardized [`firmware/platformio.ini`](#10-platformio-project-structure--configuration) configuration targeting `esp32-s3-devkitc-1` (`ESP32-S3FH4R2`) with pinned libraries (`SparkFun MAX3010x`, `Adafruit INA219`, `ArduinoJson`). |

---

## 2. Hardware Configuration & Power Architecture

### 2.1 Bill of Materials (Edge Subsystem)

| Component | Part / Specification | Role in VitalSense5 |
|---|---|---|
| **Main MCU** | **ESP32-S3-Zero Mini Dev Board** (`ESP32-S3FH4R2`) | Dual-core 240 MHz edge controller draining dual I2C buses and streaming 200 Hz NDJSON telemetry over UART1. |
| **Primary PPG (Optional Priority)** | **MAX30102 (Finger Clip)** | External finger-clip optical pulse oximeter & heart-rate sensor connected via shielded 4-wire cable (`VCC`, `GND`, `SDA1`, `SCL1`). |
| **Fallback PPG (Always Wired)** | **MAX30102 (On-Board)** | Chassis-mounted optical PPG sensor on `I2C Bus 0`; active whenever the Finger Clip is unplugged. |
| **Battery Monitor** | **INA219 Bi-Directional Current/Power Monitor** | Measures high-side 2S2P battery bus voltage (`0–26 V`) and bidirectional charge/discharge current across a `0.1 Ω` (`R100`) shunt. |
| **Battery Pack** | **2S2P 18650 Li-Ion Battery Pack** (`7.4 V` nominal, `8.4 V` max, `7000 mAh`) | Provides untethered portable power for the Raspberry Pi 5, Waveshare 7" LCD, and ESP32-S3 subsystem. |
| **Charger IC** | **TP5100 2S Step-Down Li-Ion Charger** (`8.4 V` CC/CV) | Charges the 2S2P pack from the 12 V USB-C PD input (configured with `SET` jumper shorted for 2S `8.4 V` mode). |
| **External Power Input** | **USB-C PD Trigger Module (`12 V` Fixed)** | Negotiates 12 V DC from a USB-C PD power adapter to supply the TP5100 2S charger with sufficient headroom (`>= 11 V` required for 8.4 V 2S charging). |

### 2.2 Power Path Topology

```text
+--------------------+     12V DC     +------------------------+
| USB-C PD Brick     | -------------> | TP5100 Charger (2S)    |
| + 12V PD Trigger   |                | V_chg = 8.4V, I_max=2A |
+--------------------+                +-----------+------------+
                                                  |
                                                  +-------------------+
                                                  |                   |
                                         (Charge: I < 0)     (Discharge: I > 0)
                                                  |                   v
+--------------------+   I2C Bus 0    +-----------v------------+      +----------------------------+
| ESP32-S3-Zero      | <------------- | INA219 (0x40, HighSide)| ---> | 5V Buck Converter (>=5A)   |
| (3.3V Regulated)   |                | 0.1 Ohm Shunt (R100)   |      | -> Raspberry Pi 5 (2GB)    |
+--------------------+                +-----------+------------+      | -> Waveshare 7" Touch LCD  |
                                                  |                   | -> ESP32-S3 5V / 3.3V Rail |
                                      +-----------+------------+      +----------------------------+
                                      | 2S2P 18650 Li-Ion Pack |
                                      | 6.0V (0%) .. 8.4V(100%)|
                                      +------------------------+
```

> **Electrical Safety Note (MAX30102 Board Pull-Ups):** Many commercial MAX30102 breakout modules (e.g., green MH-ET LIVE boards) tie internal I2C pull-ups to an onboard `1.8 V` regulator rather than `3.3 V`. Verify that both MAX30102 boards have their I2C pull-up jumper/resistors referenced to **`3.3 V`** (matching the ESP32-S3 GPIO logic level) and include `4.7 kΩ` pull-ups on `Bus 0` and `2.2 kΩ–4.7 kΩ` pull-ups on `Bus 1` (for Finger Clip cable capacitance).

---

## 3. Pin Wiring & Peripheral Allocation

The Waveshare **ESP32-S3-Zero** exposes `GPIO 1`–`GPIO 13`, `GPIO 21` (onboard WS2812 RGB LED), and `GPIO 43` (`TX`) / `GPIO 44` (`RX`).

| Peripheral / Interface | ESP32-S3 Pin | Signal | Target Connection | Bus / Address / Speed |
|---|---|---|---|---|
| **I2C Bus 0 (`Wire`)** | `GPIO 1` | `I2C0_SDA` | MAX30102 (On-Board) `SDA` + INA219 `SDA` | `400 kHz` Fast Mode |
| **I2C Bus 0 (`Wire`)** | `GPIO 2` | `I2C0_SCL` | MAX30102 (On-Board) `SCL` + INA219 `SCL` | MAX30102: `0x57` · INA219: `0x40` |
| **I2C Bus 1 (`Wire1`)** | `GPIO 3` | `I2C1_SDA` | MAX30102 (Finger Clip) `SDA` (via connector) | `400 kHz` (`100 kHz` fallback if cable > 0.5 m) |
| **I2C Bus 1 (`Wire1`)** | `GPIO 4` | `I2C1_SCL` | MAX30102 (Finger Clip) `SCL` (via connector) | MAX30102: `0x57` |
| **UART1 (`Serial1`)** | `GPIO 43` *(or `GPIO 5`)* | `UART1_TX` | Raspberry Pi 5 `GPIO 15` (`UART0_RXD`, Pin 10) | `460800` baud, `8N1`, `3.3 V` TTL |
| **UART1 (`Serial1`)** | `GPIO 44` *(or `GPIO 6`)* | `UART1_RX` | Raspberry Pi 5 `GPIO 14` (`UART0_TXD`, Pin 8) | `460800` baud, `8N1`, `3.3 V` TTL |
| **Common Ground** | `GND` | `GND` | Raspberry Pi 5 `GND` (Pin 6 / Pin 9) + Sensor `GND` | Shared signal reference |
| **Status RGB LED** | `GPIO 21` | `WS2812` | Onboard ESP32-S3-Zero Addressable RGB LED | Visual diagnostic state (Boot / Clip / Onboard / Fault) |
| **USB Debug (`Serial`)** | `GPIO 19 / 20` | `USB D- / D+` | USB-C Connector (Hardware CDC) | Flashing & `115200` debug console |

---

## 4. Dual-Core FreeRTOS Architecture

ESP32-S3 runs symmetric multiprocessing (SMP) FreeRTOS across **Core 0 (`PRO_CPU`)** and **Core 1 (`APP_CPU`)**. To guarantee zero jitter on the 200 Hz optical sampling timeline while serializing NDJSON strings over UART:

```text
+======================================================================================+
|                           ESP32-S3 FreeRTOS Dual-Core MCU                            |
|                                                                                      |
|  CORE 1 (APP_CPU) — Priority 3                   CORE 0 (PRO_CPU) — Priority 2       |
|  [TaskSensorAcquisition]                         [TaskUartComms]                     |
|  - Periodic 2 ms tick (500 Hz loop)              - Blocks on PPG Sample Queue        |
|  - Drains active MAX30102 hardware FIFO          - Formats 200 Hz "s" NDJSON lines   |
|  - Hot-plug detection (Bus 1 every 500 ms)         using stack snprintf()            |
|  - Shuts down inactive sensor (SHDN=1)           - Emits 1 Hz "t" Telemetry NDJSON   |
|  - Polls INA219 on Bus 0 every 200 ms              (INA219 SoC + active sensor + seq)|
|    (5-sample moving average -> 1 Hz state)       - Non-blocking UART1 RX parser for  |
|        |                        |                  RPi 5 downstream JSON commands    |
|        | 200 Hz PpgSampleFrame  | 1 Hz Atomic              ^                         |
|        v                        v                          |                         |
|  [xPpgSampleQueue (128 items)] [g_powerHealthMutex]        | [xCmdQueue (8 items)]   |
+=================|==============================|===========|=========================+
                  +------------------------------+-----------+
                                                 |
                                       UART1 (460800 8N1)
                                       TX=GPIO43, RX=GPIO44
                                                 v
                            Raspberry Pi 5 (/dev/ttyAMA0 Python Backend)
```

### 4.1 Task Specification & Core Affinity

| Task Name | Core ID | Priority | Stack Size | Wake / Cadence | Responsibilities |
|---|---|---|---|---|---|
| `TaskSensorAcquisition` | **Core 1** (`1`) | `3` (High) | `8192 B` | `vTaskDelayUntil` (`2 ms` tick) | Drains active MAX30102 FIFO at 200 Hz, manages Bus 1 Finger Clip hot-plug preemption (`500 ms` probe), shuts down unused sensor, polls INA219 every `200 ms`, feeds Task WDT. |
| `TaskUartComms` | **Core 0** (`0`) | `2` (Medium) | `8192 B` | Event-driven (`xQueueReceive`, `10 ms` timeout) | Pops `PpgSampleFrame` structs and transmits 200 Hz `"s"` NDJSON lines; transmits 1 Hz `"t"` telemetry line; parses incoming `\n`-delimited JSON commands from RPi 5 and posts to `xCmdQueue`. |

### 4.2 Inter-Core Data Structures

```cpp
// Posted from Core 1 -> Core 0 at 200 Hz via xPpgSampleQueue (depth = 128 frames = 640 ms buffer)
struct PpgSampleFrame {
    uint32_t seq;          // Monotonically increasing sample counter (wraps at 2^32)
    uint32_t timestamp_ms; // esp_timer_get_time() / 1000
    uint32_t red;          // 18-bit MAX30102 Red ADC count (0..262143)
    uint32_t ir;           // 18-bit MAX30102 IR ADC count  (0..262143)
    uint8_t  source;       // 0 = ONBOARD (Bus 0), 1 = CLIP (Bus 1)
    uint8_t  finger;       // 1 if ir >= ir_finger_threshold (default 50000), else 0
};

// Updated on Core 1 (every 200 ms, averaged over 5 readings) and read on Core 0 at 1 Hz
struct PowerHealthTelemetry {
    uint32_t uptime_s;
    float    battery_voltage_v; // INA219 load/bus voltage (6.00V .. 8.40V)
    float    current_ma;        // INA219 shunt current (negative = charging, positive = discharging)
    uint8_t  battery_percent;   // 0 .. 100% derived from 2S Li-Ion piecewise lookup
    bool     is_charging;       // true when current_ma < -50.0 mA (net charge flowing into pack)
    bool     ina219_ok;         // true if INA219 I2C0 0x40 responds
    bool     onboard_present;   // true if MAX30102 on Bus 0 responds
    bool     clip_present;      // true if MAX30102 on Bus 1 responds
    uint8_t  active_source;     // 0 = ONBOARD, 1 = CLIP, 2 = NONE/FAULT
    uint8_t  finger_detected;   // 1 = finger present on active sensor, 0 = finger off
    uint32_t queue_drops;       // Total dropped PPG samples if UART ever stalls
};
```

---

## 5. MAX30102 Sampling Configuration (Native 200 Hz)

### 5.1 Optimal Register Configuration for 200 Hz Output

Rather than running the MAX30102 ADC at raw 200 SPS with no averaging (`SMP_AVE = 1`), the firmware configures the internal ADC to sample at **800 SPS** with **4x hardware FIFO averaging (`SMP_AVE = 4`)** (or `400 SPS` with `2x` averaging). Using `800 SPS / 4 = 200 Hz`:
- Reduces uncorrelated optical shot noise and ambient 50/60 Hz flicker by **50% (6 dB SNR improvement)** inside the sensor's hardware accumulator before data ever crosses the I2C bus.
- Keeps I2C bus traffic strictly at **200 samples/second** (`6 bytes` per Red+IR sample = `1,200 bytes/s`, taking `< 3%` of a 400 kHz I2C bus).

| Register | Address | Value | Setting & Technical Rationale |
|---|---|---|---|
| **FIFO Configuration (`FIFO_CONFIG`)** | `0x08` | `0x5F` | `SMP_AVE = 010` (**4 samples averaged**), `FIFO_ROLLOVER_EN = 1` (auto-rollover on full), `FIFO_A_FULL = 0xF` (interrupt/watermark at 17 samples). |
| **Mode Configuration (`MODE_CONFIG`)** | `0x09` | `0x03` | **SpO2 Mode (`011`)**: Activates both **Red (`660 nm`)** and **IR (`880 nm`)** LED channels required for SpO2, PI, PRV, RR, and BP estimation. |
| **SpO2 Configuration (`SPO2_CONFIG`)** | `0x0A` | `0xEF` | `SPO2_ADC_RGE = 11` (**`16384 nA` full scale** to prevent ambient/strong-pulse clipping), `SPO2_SR = 100` (**`800 SPS`** -> `800 / 4 = 200 Hz` net FIFO output), `LED_PW = 11` (**`411 µs` pulse width = full 18-bit ADC resolution**). *(Note: With `411 µs` dual-LED pulse width, the MAX30102 datasheet table permits up to `1000 SPS` in SpO2 mode, so `800 SPS` with `4x` averaging operates at full 18-bit resolution).* |
| **LED1 Pulse Amplitude (`LED1_PA`, Red)** | `0x0C` | `0x24` | **`~7.2 mA`** initial Red LED current (`0x00`–`0xFF` maps to `0.0`–`51.0 mA`). Runtime adjustable via UART command. |
| **LED2 Pulse Amplitude (`LED2_PA`, IR)** | `0x0D` | `0x24` | **`~7.2 mA`** initial IR LED current. Matched initial drive simplifies AC/DC ratio (`R`) baseline calibration. |

### 5.2 FIFO Draining Strategy on Core 1

1. Every `2 ms`, `TaskSensorAcquisition` calls `sensor.check()` on the currently active MAX30102 instance, reading `FIFO_WR_PTR (0x04)`, `OVF_COUNTER (0x05)`, and `FIFO_RD_PTR (0x06)`.
2. At `200 Hz` (`1 sample` every `5.0 ms`), `sensor.check()` typically finds `0` or `1` new sample per `2 ms` poll (or bursts of up to `32` samples in the hardware FIFO if a Bus 1 hot-plug probe briefly took a few milliseconds).
3. Each 6-byte FIFO entry (`3 bytes Red`, `3 bytes IR`) is masked with `& 0x03FFFF` (18-bit unsigned integer `0..262143`), tagged with sequence number `seq` and `timestamp_ms`, checked against the fast finger-presence threshold (`ir >= 50000`), and pushed into `xPpgSampleQueue`.

### 5.3 Finger Presence & Hybrid `SensorState` Mapping

Following the agreed hybrid architecture:
- **On the ESP32-S3:** The firmware evaluates a fast hardware finger-presence gate on every sample:
  - `finger = 1` when `ir >= ir_threshold` (default `50,000` counts on the 18-bit `0..262143` scale; adjustable via command) and `ir < 260,000` (not saturated).
  - `finger = 0` when `ir < 50,000` (sensor open to air / finger removed).
- **On the Raspberry Pi 5 (Python Backend):**
  - If `finger == 0` for `> 250 ms` (`50` consecutive samples), the backend sets `DeviceStatus.sensor_state = SensorState.FINGER_OFF` and clears active waveforms/vitals to `--`.
  - When `finger` transitions from `0 -> 1`, the backend sets `SensorState.CALIBRATING` for the initial settling window (`~2–3 seconds`), then evaluates perfusion index (`AC/DC`) and spectral kurtosis/SNR to report either `SensorState.OK` or `SensorState.POOR_SIGNAL`.

---

## 6. Dual-MAX30102 Hot-Plug & Priority Switching State Machine

Both MAX30102 sensors have a fixed hardware I2C slave address of `0x57`:
- **On-Board MAX30102** is permanently wired to **I2C Bus 0 (`Wire`, `SDA = GPIO 1`, `SCL = GPIO 2`)**.
- **Finger Clip MAX30102** is pluggable on **I2C Bus 1 (`Wire1`, `SDA = GPIO 3`, `SCL = GPIO 4`)**.

### 6.1 State Machine Rules (`AUTO` Priority Mode — Default)

```text
                    +-------------------------------------------+
                    |               BOOT / INIT                 |
                    |  Init Wire (GPIO 1,2) & Wire1 (GPIO 3,4)  |
                    +---------------------+---------------------+
                                          |
                          Probe Bus 1 (0x57, PartID == 0x15)
                                  /               \
                        [ACK & ID=0x15]       [NACK / Timeout]
                                /                   \
                               v                     v
        +------------------------------+     +------------------------------+
        |     STATE: CLIP_ACTIVE       |     |    STATE: ONBOARD_ACTIVE     |
        | - Bus 1 MAX30102: Wake & Run |     | - Bus 0 MAX30102: Wake & Run |
        | - Bus 0 MAX30102: SHDN = 1   |     | - Bus 1 probed every 500 ms  |
        |   (LEDs OFF, 0.7 uA standby) |     |   (1-byte addr ping < 50 us) |
        +--------------+---------------+     +--------------+---------------+
                       |                                    |
         [3 consecutive Bus 1 I2C NACKs       [Bus 1 responds ACK + PartID 0x15]
          or PWR_RDY brownout detected]                     |
                       |                                    |
                       +-----------------> <----------------+
                                 Seamless Handover (<50 ms)
```

1. **When Finger Clip is Connected (`CLIP_ACTIVE`):**
   - The On-Board MAX30102 on Bus 0 is placed into hardware shutdown by setting `MODE_CONFIG (0x09)` bit 7 (`SHDN = 1`), turning off its Red/IR LEDs completely (`< 1 µA` current draw, zero optical crosstalk).
   - Core 1 drains the Finger Clip MAX30102 on Bus 1 at 200 Hz and tags all outgoing samples with `"src":"clip"` (`source = 1`).
   - If the Finger Clip is unplugged mid-stream (detected immediately by `3` consecutive I2C NACKs or a `0xFF`/`0x00` FIFO read failure on Bus 1), Core 1 wakes the On-Board MAX30102 (`SHDN = 0`), resets its FIFO pointers (`0x04..0x06 = 0x00`), and transitions to `ONBOARD_ACTIVE` within `< 50 ms`.
2. **When Finger Clip is Disconnected (`ONBOARD_ACTIVE`):**
   - Core 1 drains the On-Board MAX30102 on Bus 0 at 200 Hz and tags all outgoing samples with `"src":"onboard"` (`source = 0`).
   - Every `500 ms` (between 200 Hz FIFO reads), Core 1 performs a fast non-blocking address probe on Bus 1 (`Wire1.beginTransmission(0x57); Wire1.endTransmission()`).
   - If Bus 1 ACKs and its `PART_ID (0xFF)` register reads `0x15`, Core 1 initializes the Finger Clip registers (`200 Hz`, `18-bit`), asserts `SHDN = 1` on the On-Board sensor, and switches to `CLIP_ACTIVE`.
3. **Hot-Plug Re-Initialization Guard:**
   - Because plugging in the Finger Clip causes a power-on reset on the remote sensor, the firmware always reads `INT_STATUS_1 (0x00)` bit 0 (`PWR_RDY`) on the active sensor. If `PWR_RDY == 1` is ever observed (indicating an intermittent cable brownout), the firmware immediately re-applies the 200 Hz register configuration so the sensor never reverts to its power-on default halted state.

---

## 7. INA219 Power & 2S2P Battery Telemetry (`8.4 V 7000 mAh`)

### 7.1 High-Side Bidirectional Sensing on I2C Bus 0 (`0x40`)

The INA219 is wired on the **high side of the 2S2P battery pack output** (between the battery positive terminal and the junction leading to the TP5100 charger output and the 5 V system buck converter):
- **Bus Voltage Range:** `16 V` FSR (`PG = /2`, `±80 mV` shunt range across `R_shunt = 0.1 Ω`, max measurable current `±800 mA` at `/2` gain or `±3.2 A` at `PG = /8` `±320 mV` range — configure **`16V, 320mV (PG=/8)`** to support up to `3.2 A` charging/discharging without clipping).
- **Sampling & Filtering:** Core 1 reads `getBusVoltage_V()` and `getCurrent_mA()` every `200 ms` (`5 Hz`) and maintains a **5-sample moving average (`1.0 s` window)** to reject transient current spikes from Raspberry Pi 5 CPU bursts.
- **Charging Detection (`is_charging`):**
  - When the 12 V PD adapter is plugged in and the TP5100 is actively charging the 2S2P pack, net current flows **into** the battery (`I_shunt < -50.0 mA`, depending on `VIN+`/`VIN-` orientation; configurable sign polarity macro `INA219_CHARGE_CURRENT_SIGN`).
  - Hysteresis of `±30 mA` prevents `is_charging` from toggling near full charge cutoff.

### 7.2 2S2P 18650 (`6.0 V`–`8.4 V`) Piecewise Voltage-to-SoC Lookup Table

A 2S Li-Ion pack (`2 × 3.0 V..4.2 V` cells in series) has a non-linear discharge plateau around `7.2 V–7.6 V`. A simple linear formula (`(V - 6.0) / 2.4`) distorts mid-range percentages by up to `18%`. The firmware uses internal-resistance compensation (`V_ocv = V_bus + I_discharge_A * R_pack_internal`, where `R_pack_internal ≈ 0.08 Ω` for 2S2P) followed by piecewise linear interpolation across 11 anchor points:

| `V_ocv` (2S Pack) | Per-Cell Equivalent | `battery_percent` (`SoC`) | UI Battery Indicator State ([`GAP-13`](docs/DESIGN_GAP_REPORT.md)) |
|---|---|---|---|
| `>= 8.40 V` | `4.20 V` | **`100%`** | Green (`#59C461` / `#B9FF7F`) |
| `8.20 V` | `4.10 V` | **`90%`** | Green |
| `8.00 V` | `4.00 V` | **`80%`** | Green |
| `7.80 V` | `3.90 V` | **`70%`** | Green |
| `7.64 V` | `3.82 V` | **`60%`** | Green |
| `7.50 V` | `3.75 V` | **`50%`** | Green |
| `7.38 V` | `3.69 V` | **`40%`** | Green |
| `7.26 V` | `3.63 V` | **`30%`** | Green |
| `7.10 V` | `3.55 V` | **`20%`** | **Warning Amber (`#E98D62`, `<= 20%`)** |
| `6.80 V` | `3.40 V` | **`10%`** | **Critical Red (`#FF6161`, `<= 10%`)** |
| `<= 6.00 V` | `3.00 V` | **`0%`** | Critical / Safe Shutdown Threshold |

---

## 8. Bidirectional UART NDJSON Protocol Specification

### 8.1 Physical Link & Framing

- **Interface:** Hardware `UART1` (`TX = GPIO 43`, `RX = GPIO 44`) <-> Raspberry Pi 5 `/dev/ttyAMA0` (`GPIO 14/15`).
- **Serial Parameters:** **`460800` baud**, `8` data bits, `No` parity, `1` stop bit (`8N1`), no hardware flow control.
- **Framing:** **Newline-Delimited JSON (NDJSON)** — every message in either direction is a single compact JSON object terminated by `\n` (`0x0A`).
- **Bandwidth Budget at 200 Hz:**
  - `200 lines/s` × `~68 bytes/line` = **`13,600 bytes/s` (`136 kbps`)**.
  - At `460800` baud (`46,080 bytes/s` capacity), the 200 Hz per-sample NDJSON stream uses only **`29.5%` of link capacity**, leaving `> 70%` headroom. (At `115200` baud, 200 Hz per-sample JSON would exceed the `11,520 bytes/s` wire limit and drop samples—hence **`460800` baud is mandatory**).

### 8.2 Upstream Messages (ESP32-S3 -> Raspberry Pi 5)

#### 1. High-Rate PPG Sample Frame (`"type": "s"`, 200 Hz)
Formatted on Core 0 using stack-allocated `snprintf()` (zero heap allocation, `< 25 µs` formatting time):

```json
{"type":"s","seq":10482,"ts":52410,"r":118420,"ir":124910,"src":"clip","f":1}
```

| Field | Type | Description |
|---|---|---|
| `type` | `string` | Always `"s"` (PPG sample packet). |
| `seq` | `uint32` | Monotonic sample sequence counter (`0, 1, 2, ...`). Allows Python backend to detect exact sample loss if `seq != prev_seq + 1`. |
| `ts` | `uint32` | MCU millisecond timestamp (`millis()`). |
| `r` | `uint32` | Raw 18-bit MAX30102 Red channel ADC count (`0..262143`). |
| `ir` | `uint32` | Raw 18-bit MAX30102 Infrared channel ADC count (`0..262143`). |
| `src` | `string` | Active PPG sensor source: `"clip"` (Bus 1 Finger Clip) or `"onboard"` (Bus 0 On-Board). |
| `f` | `int` | Fast hardware finger-presence flag: `1` = finger detected (`ir >= threshold`), `0` = finger off. |

#### 2. Device & Battery Telemetry Heartbeat Frame (`"type": "t"`, 1 Hz)
Emitted once every `1000 ms` on Core 0 (even if both PPG sensors are faulted, serving as the ESP32-S3 liveness heartbeat for [`GAP-11`](docs/DESIGN_GAP_REPORT.md)):

```json
{"type":"t","up":342,"src":"clip","clip":1,"ob":1,"f":1,"v":8.18,"i":412.5,"soc":89,"chg":0,"drp":0}
```

| Field | Type | Maps to `DeviceStatus` ([`models.py`](src/vitalsense5/contracts/models.py)) | Description |
|---|---|---|---|
| `type` | `string` | — | Always `"t"` (1 Hz telemetry & heartbeat packet). |
| `up` | `uint32` | `esp32_state = CONNECTED` | ESP32-S3 uptime in seconds. If no `"s"` or `"t"` frame arrives on RPi 5 within `2.0 s`, backend marks `uart_state` / `esp32_state = DISCONNECTED`. |
| `src` | `string` | `status_message` | Active sensor: `"clip"`, `"onboard"`, or `"none"`. |
| `clip` | `int` | — | `1` if Finger Clip MAX30102 on Bus 1 is connected and healthy, else `0`. |
| `ob` | `int` | — | `1` if On-Board MAX30102 on Bus 0 is connected and healthy, else `0`. |
| `f` | `int` | `sensor_state` (`FINGER_OFF` when `0`) | Current finger detection state on the active sensor (`1` or `0`). |
| `v` | `float` | `battery_voltage` | Filtered 2S2P battery voltage in Volts (e.g. `8.18`). |
| `i` | `float` | — | Filtered battery current in `mA` (positive = discharging, negative = charging). |
| `soc` | `int` | `battery_percent` | Computed 2S2P battery percentage (`0..100`). |
| `chg` | `int` | `is_charging` (`bool(chg)`) | `1` if battery is actively charging via TP5100, `0` if discharging/idle. |
| `drp` | `uint32` | — | Cumulative count of dropped queue samples (diagnostic health counter; `0` under normal operation). |

#### 3. Command Acknowledgement / Error Frame (`"type": "ack"` / `"err"`, On-Demand)

```json
{"type":"ack","cmd":"set_sensor_mode","mode":"auto","ok":1}
```

### 8.3 Downstream Commands (Raspberry Pi 5 -> ESP32-S3)

Core 0 reads incoming bytes from `Serial1` non-blockingly into a 256-byte line buffer. When `\n` is received, it parses the JSON command via `ArduinoJson` and forwards a `FirmwareCommand` struct to Core 1 via `xCmdQueue`:

| Command (`"cmd"`) | Example Payload from RPi 5 | Firmware Action |
|---|---|---|
| `set_sensor_mode` | `{"cmd":"set_sensor_mode","mode":"auto"}` | Sets sensor selection policy: `"auto"` (default: Clip priority with On-Board fallback), `"clip"` (force Bus 1 only), or `"onboard"` (force Bus 0 only, shut down Clip). |
| `set_led_current` | `{"cmd":"set_led_current","red":36,"ir":36}` | Updates MAX30102 `LED1_PA` (`0x0C`) and `LED2_PA` (`0x0D`) registers (`0..255`, where `36 = 0x24 ≈ 7.2 mA`). |
| `set_ir_threshold` | `{"cmd":"set_ir_threshold","threshold":50000}` | Updates the fast hardware `finger` detection IR DC threshold (`10000..200000`). |
| `reset_sensor` | `{"cmd":"reset_sensor"}` | Issues a soft reset (`MODE_CONFIG = 0x40`) to the active MAX30102 and re-initializes 200 Hz sampling. |
| `get_status` | `{"cmd":"get_status"}` | Immediately triggers an out-of-band `"type":"t"` telemetry packet. |

---

## 9. Fault Tolerance, Bus Recovery & Diagnostics

1. **I2C Bus Hang Recovery (9-Clock Pulse Clear):**
   - External Finger Clip cables (`Bus 1`) are susceptible to transient disconnects while a slave holds `SDA` low.
   - Before calling `Wire1.begin(3, 4, 400000)` (or upon 3 consecutive I2C timeouts), the firmware configures `SCL` as `OUTPUT` and `SDA` as `INPUT_PULLUP`, toggles `SCL` up to 9 times at `100 kHz` until `SDA` releases high, generates a manual `STOP` condition, and re-initializes the hardware I2C peripheral.
   - Both `Wire.setTimeOut(20)` and `Wire1.setTimeOut(20)` are configured to `20 ms` so a severed Finger Clip cable never blocks Core 1 indefinitely.
2. **Task Watchdog Timer (TWDT):**
   - Configured with a `3000 ms` timeout watching both `TaskSensorAcquisition` (Core 1) and `TaskUartComms` (Core 0).
3. **Onboard WS2812 RGB Diagnostic LED (`GPIO 21`):**
   - **Blue pulse:** Booting / initializing I2C buses.
   - **Solid Cyan:** Active streaming from **Finger Clip (`Bus 1`)** with finger detected.
   - **Solid Green:** Active streaming from **On-Board sensor (`Bus 0`)** with finger detected.
   - **Dim Amber breathing:** Sensor active, waiting for finger (`finger == 0`).
   - **Flashing Red:** Both MAX30102 sensors unreachable on `Bus 0` and `Bus 1`.

---

## 10. PlatformIO Project Structure & Configuration

The firmware resides in [`firmware/`](firmware/) inside this repository so firmware, Python backend contracts, and UI specifications stay version-controlled together.

### 10.1 Directory Layout

```text
VitalSense5/
├── firmware.md                       # This specification document
├── firmware/
│   ├── platformio.ini                # PlatformIO build, board & library configuration
│   ├── include/
│   │   ├── config.h                  # Pin definitions, I2C rates, 200 Hz register constants
│   │   ├── protocol_types.h          # PpgSampleFrame, PowerHealthTelemetry, FirmwareCommand
│   │   ├── sensor_manager.h          # Dual-MAX30102 hot-plug & FIFO drain controller
│   │   ├── power_monitor.h           # INA219 filter & 2S2P piecewise SoC lookup
│   │   └── uart_comms.h              # Core 0 UART1 NDJSON streamer & command parser API
│   └── src/
│       ├── main.cpp                  # FreeRTOS queue init & xTaskCreatePinnedToCore(Core 0/1)
│       ├── sensor_manager.cpp        # Core 1 I2C0/I2C1 management & 9-clock bus recovery
│       ├── power_monitor.cpp         # Core 1 INA219 polling & SoC interpolation
│       └── uart_comms.cpp            # Core 0 200 Hz snprintf NDJSON TX & ArduinoJson RX
```

### 10.2 Reference `firmware/platformio.ini`

```ini
[env:esp32-s3-zero]
platform = espressif32 @ ^6.9.0
board = esp32-s3-devkitc-1
framework = arduino

; Waveshare ESP32-S3-Zero (ESP32-S3FH4R2: 4MB Flash, 2MB Quad PSRAM)
board_build.mcu = esp32s3
board_build.f_cpu = 240000000L
board_upload.flash_size = 4MB
board_build.arduino.memory_type = qio_qspi

; USB-C native CDC for flashing & debug logs; UART1 (GPIO 43/44) for RPi 5 data link
build_flags =
    -D ARDUINO_USB_MODE=1
    -D ARDUINO_USB_CDC_ON_BOOT=1
    -D CORE_DEBUG_LEVEL=1
    -Wall
    -Wextra

monitor_speed = 115200

lib_deps =
    sparkfun/SparkFun MAX3010x Pulse and Proximity Sensor Library @ ^1.1.2
    adafruit/Adafruit INA219 @ ^1.2.3
    bblanchon/ArduinoJson @ ^7.2.0
    adafruit/Adafruit NeoPixel @ ^1.12.3
```

---

## 11. Cross-Document Alignment Checklist (Backend & Frontend)

To ensure seamless end-to-end integration across the ESP32-S3 firmware, Raspberry Pi 5 Python backend, and PyQt6 UI:

1. **Sample Rate Update (`125.0 Hz` -> `200.0 Hz`):**
   - The firmware streams at **native `200.0 Hz`** (`800 SPS` / `4x` FIFO average).
   - When implementing the production `SerialVitalAdapter` ([`docs/FRONTEND_PLAN.md`](docs/FRONTEND_PLAN.md#L216)), initialize `WaveformBatch(samples=..., sample_rate_hz=200.0)` and open `/dev/ttyAMA0` at `baudrate=460800`.
2. **Heartbeat & Disconnect Timeout (`GAP-11`):**
   - The Python UART reader must monitor incoming `"s"` (`200 Hz`) and `"t"` (`1 Hz`) frames. If `> 2.0 seconds` elapse without a valid NDJSON line, `DeviceStatus.uart_state` and `DeviceStatus.esp32_state` transition to `ConnectionState.DISCONNECTED`.
3. **Finger-Off & Calibration Gating (`GAP-12`):**
   - When `"f": 0` is reported in `"s"` / `"t"` packets, the Python backend sets `DeviceStatus.sensor_state = SensorState.FINGER_OFF` so `PPGCanvasWidget` displays the finger-off banner and masks stale vitals with `"--"`.
