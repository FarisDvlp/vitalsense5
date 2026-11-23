/**
 * @file protocol_types.h
 * @brief Inter-core data structures (PpgSampleFrame, PowerHealthTelemetry,
 *        FirmwareCommand, CommandAck) and NDJSON serialization helpers for
 *        the VitalSense5 ESP32-S3 <-> Raspberry Pi 5 UART protocol.
 */

#ifndef VITALSENSE5_PROTOCOL_TYPES_H
#define VITALSENSE5_PROTOCOL_TYPES_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "config.h"

namespace vs5 {

/**
 * @brief Active or selected PPG sensor source identifier.
 */
enum class SensorSource : uint8_t {
    ONBOARD = 0, // I2C Bus 0 (Wire, GPIO 1/2)
    CLIP    = 1, // I2C Bus 1 (Wire1, GPIO 3/4)
    NONE    = 2  // Both sensors unreachable / faulted
};

/**
 * @brief Sensor selection policy configurable via UART "set_sensor_mode".
 */
enum class SensorModePolicy : uint8_t {
    AUTO    = 0, // Default: Finger Clip priority on Bus 1, seamless fallback to On-Board on Bus 0
    CLIP    = 1, // Force Finger Clip (Bus 1) only; On-Board shut down
    ONBOARD = 2  // Force On-Board (Bus 0) only; Finger Clip shut down
};

/**
 * @brief Downstream command types sent from Raspberry Pi 5 to ESP32-S3 over UART1.
 */
enum class CommandType : uint8_t {
    NONE             = 0,
    SET_SENSOR_MODE  = 1, // {"cmd":"set_sensor_mode","mode":"auto"|"clip"|"onboard"}
    SET_LED_CURRENT  = 2, // {"cmd":"set_led_current","red":0..255,"ir":0..255}
    SET_IR_THRESHOLD = 3, // {"cmd":"set_ir_threshold","threshold":10000..200000}
    RESET_SENSOR     = 4, // {"cmd":"reset_sensor"}
    GET_STATUS       = 5  // {"cmd":"get_status"}
};

/**
 * @brief 200 Hz PPG sample frame posted from Core 1 -> Core 0 via xPpgSampleQueue.
 */
struct PpgSampleFrame {
    uint32_t seq;          // Monotonically increasing sample counter (0, 1, 2, ...)
    uint32_t timestamp_ms; // MCU millisecond timestamp
    uint32_t red;          // 18-bit MAX30102 Red ADC count (0..262143)
    uint32_t ir;           // 18-bit MAX30102 IR ADC count  (0..262143)
    uint8_t  source;       // 0 = ONBOARD ("onboard"), 1 = CLIP ("clip")
    uint8_t  finger;       // 1 if finger detected (ir >= threshold && ir < saturation), else 0
};

/**
 * @brief 1 Hz power and sensor health telemetry shared between Core 1 and Core 0.
 */
struct PowerHealthTelemetry {
    uint32_t uptime_s;          // MCU uptime in seconds
    float    battery_voltage_v; // Filtered 2S2P battery bus voltage (6.00V .. 8.40V)
    float    current_ma;        // Filtered battery current in mA (+ discharging, - charging)
    uint8_t  battery_percent;   // 0 .. 100% derived from 2S Li-Ion piecewise OCV curve
    bool     is_charging;       // true when net charging current flows into 2S2P pack
    bool     ina219_ok;         // true if INA219 (0x40 on Bus 0) responds
    bool     onboard_present;   // true if On-Board MAX30102 (0x57 on Bus 0) responds
    bool     clip_present;      // true if Finger Clip MAX30102 (0x57 on Bus 1) responds
    uint8_t  active_source;     // 0 = ONBOARD, 1 = CLIP, 2 = NONE
    uint8_t  finger_detected;   // 1 = finger present on active sensor, 0 = finger off
    uint32_t queue_drops;       // Cumulative dropped PPG frames if UART queue ever fills
};

/**
 * @brief Parsed command forwarded from Core 0 UART RX parser to Core 1 via xCmdQueue.
 */
struct FirmwareCommand {
    CommandType      type;
    SensorModePolicy mode_policy;
    uint8_t          led_red_pa;
    uint8_t          led_ir_pa;
    uint32_t         ir_threshold;
};

/**
 * @brief Convert SensorSource / numeric source code to protocol string ("clip", "onboard", "none").
 */
inline const char* sensorSourceToString(uint8_t source) {
    switch (static_cast<SensorSource>(source)) {
        case SensorSource::ONBOARD:
            return "onboard";
        case SensorSource::CLIP:
            return "clip";
        default:
            return "none";
    }
}

/**
 * @brief Convert SensorModePolicy to protocol string ("auto", "clip", "onboard").
 */
inline const char* sensorModePolicyToString(SensorModePolicy policy) {
    switch (policy) {
        case SensorModePolicy::AUTO:
            return "auto";
        case SensorModePolicy::CLIP:
            return "clip";
        case SensorModePolicy::ONBOARD:
            return "onboard";
        default:
            return "auto";
    }
}

/**
 * @brief Parse mode string ("auto", "clip", "onboard") into SensorModePolicy.
 * @return true if valid mode string, false otherwise.
 */
inline bool parseSensorModePolicy(const char* mode_str, SensorModePolicy* out_policy) {
    if (mode_str == nullptr || out_policy == nullptr) {
        return false;
    }
    if (strcmp(mode_str, "auto") == 0) {
        *out_policy = SensorModePolicy::AUTO;
        return true;
    }
    if (strcmp(mode_str, "clip") == 0) {
        *out_policy = SensorModePolicy::CLIP;
        return true;
    }
    if (strcmp(mode_str, "onboard") == 0) {
        *out_policy = SensorModePolicy::ONBOARD;
        return true;
    }
    return false;
}

/**
 * @brief Evaluate fast hardware finger-presence gate for an 18-bit IR sample.
 *        Returns 1 when ir >= ir_threshold and ir < MAX30102_SATURATION_COUNT, else 0.
 */
inline uint8_t evaluateFingerGate(uint32_t ir_count, uint32_t ir_threshold) {
    if (ir_count >= ir_threshold && ir_count < config::MAX30102_SATURATION_COUNT) {
        return 1U;
    }
    return 0U;
}

/**
 * @brief Format a 200 Hz PPG sample frame ("type":"s") as a newline-terminated NDJSON string
 *        using zero-heap stack snprintf.
 * @return Number of bytes written (excluding null terminator), or <= 0 on truncation/error.
 */
inline int formatSampleNdjson(char* buf, size_t buf_size, const PpgSampleFrame& sample) {
    if (buf == nullptr || buf_size == 0) {
        return 0;
    }
    const char* src_str = (sample.source == static_cast<uint8_t>(SensorSource::CLIP))
                              ? "clip"
                              : "onboard";
    const int written = snprintf(
        buf,
        buf_size,
        "{\"type\":\"s\",\"seq\":%lu,\"ts\":%lu,\"r\":%lu,\"ir\":%lu,\"src\":\"%s\",\"f\":%u}\n",
        static_cast<unsigned long>(sample.seq),
        static_cast<unsigned long>(sample.timestamp_ms),
        static_cast<unsigned long>(sample.red),
        static_cast<unsigned long>(sample.ir),
        src_str,
        static_cast<unsigned int>(sample.finger ? 1U : 0U)
    );
    if (written < 0 || static_cast<size_t>(written) >= buf_size) {
        return 0;
    }
    return written;
}

/**
 * @brief Format a 1 Hz device & battery telemetry frame ("type":"t") as a newline-terminated
 *        NDJSON string using zero-heap stack snprintf.
 * @return Number of bytes written (excluding null terminator), or <= 0 on truncation/error.
 */
inline int formatTelemetryNdjson(char* buf, size_t buf_size, const PowerHealthTelemetry& t) {
    if (buf == nullptr || buf_size == 0) {
        return 0;
    }
    const char* src_str = sensorSourceToString(t.active_source);
    const int written = snprintf(
        buf,
        buf_size,
        "{\"type\":\"t\",\"up\":%lu,\"src\":\"%s\",\"clip\":%u,\"ob\":%u,\"f\":%u,"
        "\"v\":%.2f,\"i\":%.1f,\"soc\":%u,\"chg\":%u,\"drp\":%lu}\n",
        static_cast<unsigned long>(t.uptime_s),
        src_str,
        static_cast<unsigned int>(t.clip_present ? 1U : 0U),
        static_cast<unsigned int>(t.onboard_present ? 1U : 0U),
        static_cast<unsigned int>(t.finger_detected ? 1U : 0U),
        static_cast<double>(t.battery_voltage_v),
        static_cast<double>(t.current_ma),
        static_cast<unsigned int>(t.battery_percent),
        static_cast<unsigned int>(t.is_charging ? 1U : 0U),
        static_cast<unsigned long>(t.queue_drops)
    );
    if (written < 0 || static_cast<size_t>(written) >= buf_size) {
        return 0;
    }
    return written;
}

} // namespace vs5

#endif // VITALSENSE5_PROTOCOL_TYPES_H
