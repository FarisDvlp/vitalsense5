/**
 * @file config.h
 * @brief Pin definitions, I2C rates, MAX30102 200 Hz register constants,
 *        INA219 2S2P battery thresholds, and FreeRTOS task tuning for
 *        VitalSense5 on Waveshare ESP32-S3-Zero (ESP32-S3FH4R2).
 */

#ifndef VITALSENSE5_CONFIG_H
#define VITALSENSE5_CONFIG_H

#include <stdint.h>

namespace vs5 {
namespace config {

// ============================================================================
// 1. Hardware Pin Assignments (Waveshare ESP32-S3-Zero)
// ============================================================================

// I2C Bus 0 (Wire): On-Board MAX30102 (0x57) + High-Side INA219 (0x40)
constexpr int PIN_I2C0_SDA = 1;
constexpr int PIN_I2C0_SCL = 2;
constexpr uint32_t I2C0_FREQ_HZ = 400000UL;

// I2C Bus 1 (Wire1): External Finger Clip MAX30102 (0x57)
constexpr int PIN_I2C1_SDA = 3;
constexpr int PIN_I2C1_SCL = 4;
constexpr uint32_t I2C1_FREQ_HZ = 400000UL;
constexpr uint32_t I2C1_FALLBACK_FREQ_HZ = 100000UL;

// I2C Timeout & Bus Recovery
constexpr uint16_t I2C_TIMEOUT_MS = 20;
constexpr uint8_t  I2C_MAX_CONSECUTIVE_FAILURES = 3;
constexpr uint8_t  I2C_RECOVERY_CLOCK_PULSES = 9;

// UART1 (Serial1) <-> Raspberry Pi 5 (/dev/ttyAMA0, GPIO 14/15)
#ifndef VS5_UART1_TX_PIN
constexpr int PIN_UART1_TX = 43;
#else
constexpr int PIN_UART1_TX = VS5_UART1_TX_PIN;
#endif

#ifndef VS5_UART1_RX_PIN
constexpr int PIN_UART1_RX = 44;
#else
constexpr int PIN_UART1_RX = VS5_UART1_RX_PIN;
#endif

constexpr uint32_t UART1_BAUD = 460800UL;
constexpr uint32_t USB_DEBUG_BAUD = 115200UL;

// Onboard WS2812 RGB Diagnostic LED
constexpr int PIN_WS2812_RGB = 21;
constexpr uint8_t WS2812_NUM_PIXELS = 1;
constexpr uint8_t WS2812_BRIGHTNESS = 32; // Low brightness to avoid thermal/optical bleed

// ============================================================================
// 2. FreeRTOS Dual-Core Task & Queue Configuration
// ============================================================================

// Core 0 = PRO_CPU (UART TX/RX), Core 1 = APP_CPU (Deterministic I2C Acquisition)
constexpr int CORE_UART_COMMS = 0;
constexpr int CORE_SENSOR_ACQ = 1;

constexpr uint32_t TASK_STACK_SENSOR_ACQ = 8192;
constexpr uint32_t TASK_STACK_UART_COMMS = 8192;

constexpr uint8_t TASK_PRIO_SENSOR_ACQ = 3;
constexpr uint8_t TASK_PRIO_UART_COMMS = 2;

// 2 ms polling cadence (500 Hz) for draining 200 Hz FIFO without jitter
constexpr uint32_t SENSOR_POLL_PERIOD_MS = 2;
// 500 ms hot-plug probe interval on I2C Bus 1 when Finger Clip is disconnected
constexpr uint32_t CLIP_PROBE_INTERVAL_MS = 500;
// 200 ms INA219 polling interval (5-sample moving average -> 1 Hz output)
constexpr uint32_t INA219_POLL_INTERVAL_MS = 200;
// 1000 ms telemetry ("type":"t") emission interval
constexpr uint32_t TELEMETRY_INTERVAL_MS = 1000;

// Queue depths
constexpr size_t PPG_SAMPLE_QUEUE_DEPTH = 128; // 640 ms buffer at 200 Hz
constexpr size_t CMD_QUEUE_DEPTH = 8;

// Task Watchdog Timer timeout (3 seconds)
constexpr uint32_t TWDT_TIMEOUT_S = 3;

// ============================================================================
// 3. MAX30102 Register Map & Native 200 Hz (800 SPS / 4x Ave) Configuration
// ============================================================================

constexpr uint8_t MAX30102_I2C_ADDR = 0x57;
constexpr uint8_t MAX30102_EXPECTED_PART_ID = 0x15;

// MAX30102 Register Addresses
constexpr uint8_t REG_INT_STATUS_1 = 0x00;
constexpr uint8_t REG_INT_STATUS_2 = 0x01;
constexpr uint8_t REG_INT_ENABLE_1 = 0x02;
constexpr uint8_t REG_INT_ENABLE_2 = 0x03;
constexpr uint8_t REG_FIFO_WR_PTR  = 0x04;
constexpr uint8_t REG_OVF_COUNTER  = 0x05;
constexpr uint8_t REG_FIFO_RD_PTR  = 0x06;
constexpr uint8_t REG_FIFO_DATA    = 0x07;
constexpr uint8_t REG_FIFO_CONFIG  = 0x08;
constexpr uint8_t REG_MODE_CONFIG  = 0x09;
constexpr uint8_t REG_SPO2_CONFIG  = 0x0A;
constexpr uint8_t REG_LED1_PA      = 0x0C; // Red LED (660 nm)
constexpr uint8_t REG_LED2_PA      = 0x0D; // IR LED  (880 nm)
constexpr uint8_t REG_MULTI_LED_1  = 0x11;
constexpr uint8_t REG_MULTI_LED_2  = 0x12;
constexpr uint8_t REG_REV_ID       = 0xFE;
constexpr uint8_t REG_PART_ID      = 0xFF;

// INT_STATUS_1 bit masks
constexpr uint8_t BIT_PWR_RDY = 0x01; // Bit 0: Power-ready / brownout reset flag

// MODE_CONFIG bit masks & modes
constexpr uint8_t BIT_MODE_SHDN  = 0x80; // Bit 7: Hardware shutdown (LEDs off, <1 uA)
constexpr uint8_t BIT_MODE_RESET = 0x40; // Bit 6: Soft reset
constexpr uint8_t VAL_MODE_SPO2  = 0x03; // Mode 011: SpO2 (Red + IR)

// FIFO_CONFIG (0x08) = 0x5F:
//   SMP_AVE [7:5] = 010 (4 samples averaged)
//   FIFO_ROLLOVER_EN [4] = 1 (rollover enabled)
//   FIFO_A_FULL [3:0] = 0xF (17 samples watermark)
constexpr uint8_t VAL_FIFO_CONFIG_200HZ = 0x5F;

// SPO2_CONFIG (0x0A) = 0xEF:
//   Bit 7 = 1 (matches SparkFun setup convention; reserved/high)
//   SPO2_ADC_RGE [6:5] = 11 (16384 nA full scale)
//   SPO2_SR [4:2] = 100 (800 SPS raw -> 800 / 4 = 200 Hz effective FIFO output)
//   LED_PW [1:0] = 11 (411 us pulse width = 18-bit ADC resolution)
// Note: Masking bits [6:0] yields 0x6F; writing 0xEF or 0x6F sets identical [6:0] fields.
constexpr uint8_t VAL_SPO2_CONFIG_200HZ = 0x6F;

// Default LED Pulse Amplitudes (0x24 = 36 -> ~7.2 mA)
constexpr uint8_t DEFAULT_LED_RED_PA = 0x24;
constexpr uint8_t DEFAULT_LED_IR_PA  = 0x24;

// 18-bit ADC mask & Finger Detection Thresholds
constexpr uint32_t MAX30102_18BIT_MASK = 0x03FFFFUL;
constexpr uint32_t DEFAULT_IR_FINGER_THRESHOLD = 50000UL;
constexpr uint32_t MIN_IR_FINGER_THRESHOLD     = 10000UL;
constexpr uint32_t MAX_IR_FINGER_THRESHOLD     = 200000UL;
constexpr uint32_t MAX30102_SATURATION_COUNT   = 260000UL;

// Maximum FIFO depth per read burst
constexpr uint8_t MAX30102_FIFO_DEPTH = 32;

// ============================================================================
// 4. INA219 Power Monitor & 2S2P 18650 (8.4V 7000mAh) Battery Constants
// ============================================================================

constexpr uint8_t INA219_I2C_ADDR = 0x40;
constexpr size_t  INA219_FILTER_WINDOW = 5; // 5 * 200 ms = 1.0 s moving average

// Polarity multiplier for shunt current (+1.0f if discharging > 0 and charging < 0,
// -1.0f if wired in reverse).
#ifndef INA219_CHARGE_CURRENT_SIGN
constexpr float INA219_CURRENT_SIGN = 1.0f;
#else
constexpr float INA219_CURRENT_SIGN = static_cast<float>(INA219_CHARGE_CURRENT_SIGN);
#endif

// Charging threshold & hysteresis (net current flowing into battery: current_ma < -50 mA)
constexpr float CHARGE_DETECT_ENTER_MA = -50.0f;
constexpr float CHARGE_DETECT_EXIT_MA  = -20.0f;

// 2S2P internal pack resistance estimate for open-circuit voltage compensation:
// V_ocv = V_bus + (I_discharge_mA / 1000.0) * R_PACK_INTERNAL_OHM
constexpr float R_PACK_INTERNAL_OHM = 0.08f;

// Default fallback battery telemetry when INA219 is offline
constexpr float   DEFAULT_BATTERY_VOLTAGE_V = 0.0f;
constexpr uint8_t DEFAULT_BATTERY_PERCENT   = 0;

} // namespace config
} // namespace vs5

#endif // VITALSENSE5_CONFIG_H
