/**
 * @file test_firmware_logic.cpp
 * @brief Native host C++ unit & adversarial edge-case test suite for the VitalSense5
 *        ESP32-S3 firmware protocol serialization, 2S2P 18650 (8.4V 7000mAh) piecewise
 *        SoC lookup, INA219 5-sample filter & charging hysteresis, fast hardware
 *        finger detection gate, dual-MAX30102 priority arbitration state machine,
 *        and ArduinoJson downstream UART command parser.
 *
 * Compiled on host with g++ -std=c++17 -Wall -Wextra -Werror
 * (including ArduinoJson v7 header from PlatformIO libdeps).
 */

#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <ArduinoJson.h>

#include "config.h"
#include "power_monitor.h"
#include "protocol_types.h"
#include "sensor_manager.h"
#include "uart_comms.h"

namespace vs5 {

// Embed the pure C++ command parser implementation directly when building native tests
// (since ARDUINO is not defined on host, uart_comms.cpp's parseDownstreamCommandJson
// compiles identically on host and MCU).
} // namespace vs5

#include "../src/uart_comms.cpp"

using namespace vs5;

static int g_tests_passed = 0;

#define RUN_TEST(fn)                                      \
    do {                                                  \
        printf("  [TEST] %-52s ... ", #fn);               \
        fn();                                             \
        printf("PASS\n");                                 \
        ++g_tests_passed;                                 \
    } while (0)

// ============================================================================
// 1. Register & Configuration Constants Verification (FW-GAP-01..12)
// ============================================================================
static void test_config_constants_and_register_values() {
    // Pins per Section 3 of firmware.md
    assert(config::PIN_I2C0_SDA == 1);
    assert(config::PIN_I2C0_SCL == 2);
    assert(config::PIN_I2C1_SDA == 3);
    assert(config::PIN_I2C1_SCL == 4);
    assert(config::PIN_UART1_TX == 43);
    assert(config::PIN_UART1_RX == 44);
    assert(config::PIN_WS2812_RGB == 21);

    // Baud rate & I2C clocks
    assert(config::UART1_BAUD == 460800UL);
    assert(config::I2C0_FREQ_HZ == 400000UL);
    assert(config::I2C1_FREQ_HZ == 400000UL);
    assert(config::I2C_TIMEOUT_MS == 20);

    // FreeRTOS Core 0 / Core 1 assignment & queue sizes
    assert(config::CORE_UART_COMMS == 0);
    assert(config::CORE_SENSOR_ACQ == 1);
    assert(config::PPG_SAMPLE_QUEUE_DEPTH == 128);
    assert(config::CMD_QUEUE_DEPTH == 8);
    assert(config::SENSOR_POLL_PERIOD_MS == 2);
    assert(config::CLIP_PROBE_INTERVAL_MS == 500);
    assert(config::INA219_POLL_INTERVAL_MS == 200);
    assert(config::TELEMETRY_INTERVAL_MS == 1000);
    assert(config::TWDT_TIMEOUT_S == 3);

    // MAX30102 registers for native 200 Hz (800 SPS / 4x FIFO averaging, 18-bit)
    assert(config::MAX30102_I2C_ADDR == 0x57);
    assert(config::MAX30102_EXPECTED_PART_ID == 0x15);
    assert(config::VAL_FIFO_CONFIG_200HZ == 0x5F);
    assert((config::VAL_SPO2_CONFIG_200HZ & 0x6F) == 0x6F);
    assert(config::VAL_MODE_SPO2 == 0x03);
    assert(config::DEFAULT_LED_RED_PA == 0x24);
    assert(config::DEFAULT_LED_IR_PA == 0x24);
    assert(config::DEFAULT_IR_FINGER_THRESHOLD == 50000UL);
    assert(config::MAX30102_18BIT_MASK == 0x03FFFFUL);
}

// ============================================================================
// 2. Fast Hardware Finger Gate & Boundary Tests (FW-GAP-09)
// ============================================================================
static void test_finger_presence_gate_boundaries() {
    const uint32_t thresh = config::DEFAULT_IR_FINGER_THRESHOLD; // 50000

    assert(evaluateFingerGate(0, thresh) == 0);
    assert(evaluateFingerGate(49999, thresh) == 0);
    assert(evaluateFingerGate(50000, thresh) == 1);
    assert(evaluateFingerGate(124910, thresh) == 1);
    assert(evaluateFingerGate(259999, thresh) == 1);
    // Saturated ADC counts (>= 260000 on 18-bit 0..262143 scale) must gate finger = 0
    assert(evaluateFingerGate(260000, thresh) == 0);
    assert(evaluateFingerGate(262143, thresh) == 0);
}

// ============================================================================
// 3. Dual-MAX30102 Priority State Machine Arbitration (FW-GAP-05)
// ============================================================================
static void test_dual_sensor_priority_arbitration() {
    // AUTO mode: Finger Clip (Bus 1) takes priority over On-Board (Bus 0)
    assert(selectActiveSensorSource(SensorModePolicy::AUTO, true, true) == SensorSource::CLIP);
    assert(selectActiveSensorSource(SensorModePolicy::AUTO, true, false) == SensorSource::CLIP);
    // Seamless fallback to On-Board when Clip is unplugged
    assert(selectActiveSensorSource(SensorModePolicy::AUTO, false, true) == SensorSource::ONBOARD);
    // Fault state when neither sensor responds
    assert(selectActiveSensorSource(SensorModePolicy::AUTO, false, false) == SensorSource::NONE);

    // Forced CLIP mode
    assert(selectActiveSensorSource(SensorModePolicy::CLIP, true, true) == SensorSource::CLIP);
    assert(selectActiveSensorSource(SensorModePolicy::CLIP, false, true) == SensorSource::NONE);

    // Forced ONBOARD mode (Clip ignored/shut down even if plugged in)
    assert(selectActiveSensorSource(SensorModePolicy::ONBOARD, true, true) == SensorSource::ONBOARD);
    assert(selectActiveSensorSource(SensorModePolicy::ONBOARD, true, false) == SensorSource::NONE);

    // Hardware 32-sample FIFO pointer wrap-around & burst decoding
    assert(computeMax30102FifoAvailable(0, 0, 0) == 0);
    assert(computeMax30102FifoAvailable(5, 2, 0) == 3);
    // Wrap-around across 32-entry ring (e.g. rd_ptr = 30, wr_ptr = 4 -> 6 samples)
    assert(computeMax30102FifoAvailable(4, 30, 0) == 6);
    // Overflow counter > 0 must report full 32-sample FIFO depth
    assert(computeMax30102FifoAvailable(12, 12, 1) == 32);

    // 18-bit MSB-first FIFO sample decode (Red = 118420 = 0x01CE94, IR = 124910 = 0x01E7EE)
    // With upper reserved bits [23:18] polluted to verify 0x03FFFF masking:
    const uint8_t valid_raw[6] = {
        static_cast<uint8_t>(0xC0U | 0x01U), 0xCEU, 0x94U,
        static_cast<uint8_t>(0xFCU | 0x01U), 0xE7U, 0xEEU
    };
    uint32_t dec_red = 0;
    uint32_t dec_ir  = 0;
    assert(decodeMax30102FifoSample(valid_raw, &dec_red, &dec_ir) == true);
    assert(dec_red == 118420UL);
    assert(dec_ir  == 124910UL);

    // Severed cable pull-up dropout (all 0xFF bytes) must be rejected as invalid
    const uint8_t dropout_raw[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
    assert(decodeMax30102FifoSample(dropout_raw, &dec_red, &dec_ir) == false);
}

// ============================================================================
// 4. 2S2P 18650 (6.0V - 8.4V) Piecewise SoC Lookup & OCV Compensation (FW-GAP-07)
// ============================================================================
static void test_2s2p_soc_piecewise_interpolation_and_boundaries() {
    // Exact anchor points from Section 7.2 table
    assert(interpolate2SLiIonSoc(8.55f) == 100);
    assert(interpolate2SLiIonSoc(8.40f) == 100);
    assert(interpolate2SLiIonSoc(8.20f) == 90);
    assert(interpolate2SLiIonSoc(8.00f) == 80);
    assert(interpolate2SLiIonSoc(7.80f) == 70);
    assert(interpolate2SLiIonSoc(7.64f) == 60);
    assert(interpolate2SLiIonSoc(7.50f) == 50);
    assert(interpolate2SLiIonSoc(7.38f) == 40);
    assert(interpolate2SLiIonSoc(7.26f) == 30);
    assert(interpolate2SLiIonSoc(7.10f) == 20);
    assert(interpolate2SLiIonSoc(6.80f) == 10);
    assert(interpolate2SLiIonSoc(6.00f) == 0);
    assert(interpolate2SLiIonSoc(5.20f) == 0);
    assert(interpolate2SLiIonSoc(-1.0f) == 0);
    assert(interpolate2SLiIonSoc(NAN) == 0);
    assert(interpolate2SLiIonSoc(INFINITY) == 0);

    // Midpoint interpolations
    // Halfway between 8.00V (80%) and 8.20V (90%) -> 8.10V = 85%
    assert(interpolate2SLiIonSoc(8.10f) == 85);
    // Halfway between 7.26V (30%) and 7.38V (40%) -> 7.32V = 35%
    assert(interpolate2SLiIonSoc(7.32f) == 35);
    // Monotonicity check across 5.80V .. 8.60V in 10 mV steps
    uint8_t prev_soc = 0;
    for (int mv = 5800; mv <= 8600; mv += 10) {
        const float v = static_cast<float>(mv) / 1000.0f;
        const uint8_t soc = interpolate2SLiIonSoc(v);
        assert(soc >= prev_soc);
        assert(soc <= 100);
        prev_soc = soc;
    }

    // Internal resistance compensation check:
    // At 7.92V under 1000 mA (1.0 A) discharge with R_internal = 0.08 Ohm:
    // V_ocv = 7.92 + 1.0 * 0.08 = 8.00V -> 80% SoC
    const float v_ocv = computeCompensatedOcv(7.92f, 1000.0f);
    assert(fabsf(v_ocv - 8.00f) < 1e-4f);
    assert(interpolate2SLiIonSoc(v_ocv) == 80);
}

// ============================================================================
// 5. INA219 5-Sample Moving Average & Charging Hysteresis
// ============================================================================
static void test_power_filter_moving_average_and_charging_hysteresis() {
    PowerFilterState filter;
    assert(filter.sampleCount() == 0);
    assert(filter.isCharging() == false);

    // Feed 5 discharging samples around 8.10V, +400 mA
    filter.pushSample(8.08f, 390.0f);
    filter.pushSample(8.09f, 395.0f);
    filter.pushSample(8.10f, 400.0f);
    filter.pushSample(8.11f, 405.0f);
    filter.pushSample(8.12f, 410.0f);

    assert(filter.sampleCount() == 5);
    assert(fabsf(filter.filteredVoltageV() - 8.10f) < 1e-3f);
    assert(fabsf(filter.filteredCurrentMa() - 400.0f) < 1e-3f);
    assert(filter.isCharging() == false);
    assert(filter.batteryPercent() >= 85 && filter.batteryPercent() <= 88);

    // Non-finite samples must be ignored without corrupting the window
    filter.pushSample(NAN, 500.0f);
    filter.pushSample(8.10f, INFINITY);
    assert(fabsf(filter.filteredVoltageV() - 8.10f) < 1e-3f);

    // Charging hysteresis test:
    // Enters charging only when current < -50.0 mA
    assert(evaluateChargingHysteresis(-35.0f, false) == false);
    assert(evaluateChargingHysteresis(-50.0f, false) == false);
    assert(evaluateChargingHysteresis(-50.1f, false) == true);
    // Once charging, stays true until current rises above -20.0 mA
    assert(evaluateChargingHysteresis(-45.0f, true) == true);
    assert(evaluateChargingHysteresis(-25.0f, true) == true);
    assert(evaluateChargingHysteresis(-20.0f, true) == true);
    assert(evaluateChargingHysteresis(-19.9f, true) == false);
    assert(evaluateChargingHysteresis(100.0f, true) == false);
}

// ============================================================================
// 6. 200 Hz Sample ("s") & 1 Hz Telemetry ("t") NDJSON Formatting (FW-GAP-08)
// ============================================================================
static void test_ndjson_sample_and_telemetry_formatting() {
    PpgSampleFrame sample{};
    sample.seq = 10482;
    sample.timestamp_ms = 52410;
    sample.red = 118420;
    sample.ir = 124910;
    sample.source = static_cast<uint8_t>(SensorSource::CLIP);
    sample.finger = 1;

    char buf[128];
    const int s_len = formatSampleNdjson(buf, sizeof(buf), sample);
    assert(s_len > 0);
    assert(buf[s_len - 1] == '\n');

    const char* expected_s =
        "{\"type\":\"s\",\"seq\":10482,\"ts\":52410,\"r\":118420,\"ir\":124910,\"src\":\"clip\",\"f\":1}\n";
    assert(strcmp(buf, expected_s) == 0);

    // Verify bandwidth budget: single 200 Hz line must be well under 90 bytes
    assert(s_len < 90);

    // Verify buffer-too-small safety
    char tiny[16];
    assert(formatSampleNdjson(tiny, sizeof(tiny), sample) == 0);
    assert(formatSampleNdjson(nullptr, 100, sample) == 0);

    // Verify 1 Hz telemetry ("t") frame formatting matches Section 8.2 of firmware.md
    PowerHealthTelemetry telem{};
    telem.uptime_s = 342;
    telem.active_source = static_cast<uint8_t>(SensorSource::CLIP);
    telem.clip_present = true;
    telem.onboard_present = true;
    telem.finger_detected = 1;
    telem.battery_voltage_v = 8.18f;
    telem.current_ma = 412.5f;
    telem.battery_percent = 89;
    telem.is_charging = false;
    telem.queue_drops = 0;

    char t_buf[192];
    const int t_len = formatTelemetryNdjson(t_buf, sizeof(t_buf), telem);
    assert(t_len > 0);
    assert(t_buf[t_len - 1] == '\n');

    const char* expected_t =
        "{\"type\":\"t\",\"up\":342,\"src\":\"clip\",\"clip\":1,\"ob\":1,\"f\":1,"
        "\"v\":8.18,\"i\":412.5,\"soc\":89,\"chg\":0,\"drp\":0}\n";
    assert(strcmp(t_buf, expected_t) == 0);
}

// ============================================================================
// 7. Downstream UART Command Parser & Adversarial Inputs (FW-GAP-10)
// ============================================================================
static void test_downstream_command_parser_valid_and_invalid() {
    FirmwareCommand cmd{};
    char ack[192];

    // 1. Valid set_sensor_mode ("auto", "clip", "onboard")
    assert(parseDownstreamCommandJson(
        "{\"cmd\":\"set_sensor_mode\",\"mode\":\"auto\"}",
        &cmd,
        ack,
        sizeof(ack)
    ) == true);
    assert(cmd.type == CommandType::SET_SENSOR_MODE);
    assert(cmd.mode_policy == SensorModePolicy::AUTO);
    assert(strcmp(ack, "{\"type\":\"ack\",\"cmd\":\"set_sensor_mode\",\"mode\":\"auto\",\"ok\":1}\n") == 0);

    assert(parseDownstreamCommandJson(
        "{\"cmd\":\"set_sensor_mode\",\"mode\":\"onboard\"}",
        &cmd,
        ack,
        sizeof(ack)
    ) == true);
    assert(cmd.mode_policy == SensorModePolicy::ONBOARD);

    // Invalid sensor mode
    assert(parseDownstreamCommandJson(
        "{\"cmd\":\"set_sensor_mode\",\"mode\":\"invalid_bus\"}",
        &cmd,
        ack,
        sizeof(ack)
    ) == false);
    assert(strstr(ack, "\"type\":\"err\"") != nullptr);

    // 2. Valid set_led_current
    assert(parseDownstreamCommandJson(
        "{\"cmd\":\"set_led_current\",\"red\":36,\"ir\":48}",
        &cmd,
        ack,
        sizeof(ack)
    ) == true);
    assert(cmd.type == CommandType::SET_LED_CURRENT);
    assert(cmd.led_red_pa == 36);
    assert(cmd.led_ir_pa == 48);
    assert(strcmp(ack, "{\"type\":\"ack\",\"cmd\":\"set_led_current\",\"red\":36,\"ir\":48,\"ok\":1}\n") == 0);

    // Out-of-range LED current (> 255 or < 0)
    assert(parseDownstreamCommandJson(
        "{\"cmd\":\"set_led_current\",\"red\":300,\"ir\":36}",
        &cmd,
        ack,
        sizeof(ack)
    ) == false);
    assert(strstr(ack, "\"err\":\"out_of_range\"") != nullptr);

    // 3. Valid set_ir_threshold
    assert(parseDownstreamCommandJson(
        "{\"cmd\":\"set_ir_threshold\",\"threshold\":65000}",
        &cmd,
        ack,
        sizeof(ack)
    ) == true);
    assert(cmd.type == CommandType::SET_IR_THRESHOLD);
    assert(cmd.ir_threshold == 65000UL);

    // Out-of-range IR threshold (< 10000 or > 200000)
    assert(parseDownstreamCommandJson(
        "{\"cmd\":\"set_ir_threshold\",\"threshold\":500}",
        &cmd,
        ack,
        sizeof(ack)
    ) == false);
    assert(strstr(ack, "\"err\":\"out_of_range\"") != nullptr);

    // 4. Valid reset_sensor & get_status
    assert(parseDownstreamCommandJson("{\"cmd\":\"reset_sensor\"}", &cmd, ack, sizeof(ack)) == true);
    assert(cmd.type == CommandType::RESET_SENSOR);

    assert(parseDownstreamCommandJson("{\"cmd\":\"get_status\"}", &cmd, ack, sizeof(ack)) == true);
    assert(cmd.type == CommandType::GET_STATUS);

    // 5. Malformed JSON, empty line, and unknown command
    assert(parseDownstreamCommandJson("", &cmd, ack, sizeof(ack)) == false);
    assert(strstr(ack, "\"err\":\"empty_line\"") != nullptr);

    assert(parseDownstreamCommandJson("{malformed json", &cmd, ack, sizeof(ack)) == false);
    assert(strstr(ack, "\"err\":\"invalid_json\"") != nullptr);

    assert(parseDownstreamCommandJson("{\"cmd\":\"self_destruct\"}", &cmd, ack, sizeof(ack)) == false);
    assert(strstr(ack, "\"err\":\"unknown_cmd\"") != nullptr);
}

int main() {
    printf("=== VitalSense5 ESP32-S3 Firmware Native Logic & Protocol Tests ===\n");
    RUN_TEST(test_config_constants_and_register_values);
    RUN_TEST(test_finger_presence_gate_boundaries);
    RUN_TEST(test_dual_sensor_priority_arbitration);
    RUN_TEST(test_2s2p_soc_piecewise_interpolation_and_boundaries);
    RUN_TEST(test_power_filter_moving_average_and_charging_hysteresis);
    RUN_TEST(test_ndjson_sample_and_telemetry_formatting);
    RUN_TEST(test_downstream_command_parser_valid_and_invalid);
    printf("=== All %d native firmware test suites PASSED ===\n", g_tests_passed);
    return 0;
}
