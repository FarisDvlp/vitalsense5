/**
 * @file uart_comms.cpp
 * @brief Core 0 (PRO_CPU) UART1 460800-baud NDJSON transmitter (200 Hz "s" frames via
 *        zero-heap snprintf, 1 Hz "t" heartbeat telemetry) and non-blocking ArduinoJson
 *        downstream command parser.
 */

#include "uart_comms.h"

#include <ArduinoJson.h>
#include <stdio.h>
#include <string.h>

#ifdef ARDUINO
#include <esp_task_wdt.h>
#endif

namespace vs5 {

#ifdef ARDUINO
// Extern inter-core synchronization primitives defined in main.cpp
extern QueueHandle_t        g_ppgSampleQueue;
extern QueueHandle_t        g_cmdQueue;
extern SemaphoreHandle_t    g_powerHealthMutex;
extern PowerHealthTelemetry g_powerHealthState;

static volatile bool s_immediateTelemetryRequested = false;

void requestImmediateTelemetry() {
    s_immediateTelemetryRequested = true;
}
#endif // ARDUINO

bool parseDownstreamCommandJson(
    const char* json_line,
    FirmwareCommand* out_cmd,
    char* ack_buf,
    size_t ack_buf_size
) {
    if (out_cmd == nullptr || ack_buf == nullptr || ack_buf_size == 0) {
        return false;
    }
    memset(out_cmd, 0, sizeof(FirmwareCommand));
    out_cmd->type = CommandType::NONE;
    out_cmd->mode_policy = SensorModePolicy::AUTO;
    out_cmd->led_red_pa = config::DEFAULT_LED_RED_PA;
    out_cmd->led_ir_pa = config::DEFAULT_LED_IR_PA;
    out_cmd->ir_threshold = config::DEFAULT_IR_FINGER_THRESHOLD;

    if (json_line == nullptr || json_line[0] == '\0') {
        snprintf(ack_buf, ack_buf_size, "{\"type\":\"err\",\"cmd\":\"unknown\",\"ok\":0,\"err\":\"empty_line\"}\n");
        return false;
    }

    JsonDocument doc;
    const DeserializationError err = deserializeJson(doc, json_line);
    if (err) {
        snprintf(ack_buf, ack_buf_size, "{\"type\":\"err\",\"cmd\":\"unknown\",\"ok\":0,\"err\":\"invalid_json\"}\n");
        return false;
    }

    const char* cmd_str = doc["cmd"] | static_cast<const char*>(nullptr);
    if (cmd_str == nullptr || cmd_str[0] == '\0') {
        snprintf(ack_buf, ack_buf_size, "{\"type\":\"err\",\"cmd\":\"unknown\",\"ok\":0,\"err\":\"missing_cmd\"}\n");
        return false;
    }

    // 1. set_sensor_mode: {"cmd":"set_sensor_mode","mode":"auto"|"clip"|"onboard"}
    if (strcmp(cmd_str, "set_sensor_mode") == 0) {
        const char* mode_str = doc["mode"] | static_cast<const char*>(nullptr);
        SensorModePolicy policy = SensorModePolicy::AUTO;
        if (!parseSensorModePolicy(mode_str, &policy)) {
            snprintf(
                ack_buf,
                ack_buf_size,
                "{\"type\":\"err\",\"cmd\":\"set_sensor_mode\",\"ok\":0,\"err\":\"invalid_mode\"}\n"
            );
            return false;
        }
        out_cmd->type = CommandType::SET_SENSOR_MODE;
        out_cmd->mode_policy = policy;
        snprintf(
            ack_buf,
            ack_buf_size,
            "{\"type\":\"ack\",\"cmd\":\"set_sensor_mode\",\"mode\":\"%s\",\"ok\":1}\n",
            sensorModePolicyToString(policy)
        );
        return true;
    }

    // 2. set_led_current: {"cmd":"set_led_current","red":36,"ir":36}
    if (strcmp(cmd_str, "set_led_current") == 0) {
        if (!doc["red"].is<int>() || !doc["ir"].is<int>()) {
            snprintf(
                ack_buf,
                ack_buf_size,
                "{\"type\":\"err\",\"cmd\":\"set_led_current\",\"ok\":0,\"err\":\"missing_red_or_ir\"}\n"
            );
            return false;
        }
        const int red_val = doc["red"].as<int>();
        const int ir_val  = doc["ir"].as<int>();
        if (red_val < 0 || red_val > 255 || ir_val < 0 || ir_val > 255) {
            snprintf(
                ack_buf,
                ack_buf_size,
                "{\"type\":\"err\",\"cmd\":\"set_led_current\",\"ok\":0,\"err\":\"out_of_range\"}\n"
            );
            return false;
        }
        out_cmd->type = CommandType::SET_LED_CURRENT;
        out_cmd->led_red_pa = static_cast<uint8_t>(red_val);
        out_cmd->led_ir_pa  = static_cast<uint8_t>(ir_val);
        snprintf(
            ack_buf,
            ack_buf_size,
            "{\"type\":\"ack\",\"cmd\":\"set_led_current\",\"red\":%d,\"ir\":%d,\"ok\":1}\n",
            red_val,
            ir_val
        );
        return true;
    }

    // 3. set_ir_threshold: {"cmd":"set_ir_threshold","threshold":50000}
    if (strcmp(cmd_str, "set_ir_threshold") == 0) {
        if (!doc["threshold"].is<uint32_t>() && !doc["threshold"].is<int>()) {
            snprintf(
                ack_buf,
                ack_buf_size,
                "{\"type\":\"err\",\"cmd\":\"set_ir_threshold\",\"ok\":0,\"err\":\"missing_threshold\"}\n"
            );
            return false;
        }
        const long thresh_val = doc["threshold"].as<long>();
        if (thresh_val < static_cast<long>(config::MIN_IR_FINGER_THRESHOLD) ||
            thresh_val > static_cast<long>(config::MAX_IR_FINGER_THRESHOLD)) {
            snprintf(
                ack_buf,
                ack_buf_size,
                "{\"type\":\"err\",\"cmd\":\"set_ir_threshold\",\"ok\":0,\"err\":\"out_of_range\"}\n"
            );
            return false;
        }
        out_cmd->type = CommandType::SET_IR_THRESHOLD;
        out_cmd->ir_threshold = static_cast<uint32_t>(thresh_val);
        snprintf(
            ack_buf,
            ack_buf_size,
            "{\"type\":\"ack\",\"cmd\":\"set_ir_threshold\",\"threshold\":%lu,\"ok\":1}\n",
            static_cast<unsigned long>(out_cmd->ir_threshold)
        );
        return true;
    }

    // 4. reset_sensor: {"cmd":"reset_sensor"}
    if (strcmp(cmd_str, "reset_sensor") == 0) {
        out_cmd->type = CommandType::RESET_SENSOR;
        snprintf(ack_buf, ack_buf_size, "{\"type\":\"ack\",\"cmd\":\"reset_sensor\",\"ok\":1}\n");
        return true;
    }

    // 5. get_status: {"cmd":"get_status"}
    if (strcmp(cmd_str, "get_status") == 0) {
        out_cmd->type = CommandType::GET_STATUS;
        snprintf(ack_buf, ack_buf_size, "{\"type\":\"ack\",\"cmd\":\"get_status\",\"ok\":1}\n");
        return true;
    }

    snprintf(ack_buf, ack_buf_size, "{\"type\":\"err\",\"cmd\":\"unknown\",\"ok\":0,\"err\":\"unknown_cmd\"}\n");
    return false;
}

#ifdef ARDUINO

void initUart1Comms() {
    // Increase UART1 TX/RX hardware ring buffers before begin() so bursts never stall Core 0
    Serial1.setRxBufferSize(1024);
    Serial1.setTxBufferSize(2048);
    Serial1.begin(
        config::UART1_BAUD,
        SERIAL_8N1,
        config::PIN_UART1_RX,
        config::PIN_UART1_TX
    );
}

static void emitTelemetryPacketNow() {
    PowerHealthTelemetry snapshot{};
    if (g_powerHealthMutex != nullptr &&
        xSemaphoreTake(g_powerHealthMutex, pdMS_TO_TICKS(5)) == pdTRUE) {
        snapshot = g_powerHealthState;
        xSemaphoreGive(g_powerHealthMutex);
    }

    char line_buf[192];
    const int len = formatTelemetryNdjson(line_buf, sizeof(line_buf), snapshot);
    if (len > 0) {
        Serial1.write(reinterpret_cast<const uint8_t*>(line_buf), static_cast<size_t>(len));
    }
}

void taskUartCommsEntry(void* pvParameters) {
    (void)pvParameters;

    // Subscribe Core 0 UART task to Task Watchdog Timer
    esp_task_wdt_add(NULL);

    char   sample_line_buf[128];
    char   rx_line_buf[256];
    size_t rx_pos      = 0;
    bool   rx_overflow = false;

    uint32_t last_telemetry_ms = millis();

    for (;;) {
        esp_task_wdt_reset();

        // 1. Pop up to 16 queued 200 Hz PPG samples per cycle (blocks up to 5 ms on first read)
        PpgSampleFrame frame{};
        if (xQueueReceive(g_ppgSampleQueue, &frame, pdMS_TO_TICKS(5)) == pdTRUE) {
            int len = formatSampleNdjson(sample_line_buf, sizeof(sample_line_buf), frame);
            if (len > 0) {
                Serial1.write(reinterpret_cast<const uint8_t*>(sample_line_buf), static_cast<size_t>(len));
            }

            // Drain any additional samples currently ready without blocking
            for (uint8_t burst = 0; burst < 15; ++burst) {
                if (xQueueReceive(g_ppgSampleQueue, &frame, 0) != pdTRUE) {
                    break;
                }
                len = formatSampleNdjson(sample_line_buf, sizeof(sample_line_buf), frame);
                if (len > 0) {
                    Serial1.write(reinterpret_cast<const uint8_t*>(sample_line_buf), static_cast<size_t>(len));
                }
            }
        }

        // 2. Non-blocking UART1 RX line reader for downstream RPi 5 commands
        while (Serial1.available() > 0) {
            const int ch = Serial1.read();
            if (ch < 0) {
                break;
            }
            if (ch == '\r') {
                continue;
            }
            if (ch == '\n') {
                if (rx_overflow) {
                    Serial1.print("{\"type\":\"err\",\"cmd\":\"unknown\",\"ok\":0,\"err\":\"line_too_long\"}\n");
                    rx_overflow = false;
                    rx_pos = 0;
                    continue;
                }
                rx_line_buf[rx_pos] = '\0';
                if (rx_pos > 0) {
                    FirmwareCommand cmd{};
                    char ack_buf[160];
                    const bool valid = parseDownstreamCommandJson(
                        rx_line_buf,
                        &cmd,
                        ack_buf,
                        sizeof(ack_buf)
                    );
                    Serial1.print(ack_buf);

                    if (valid) {
                        if (cmd.type == CommandType::GET_STATUS) {
                            s_immediateTelemetryRequested = true;
                        } else if (g_cmdQueue != nullptr) {
                            xQueueSend(g_cmdQueue, &cmd, 0);
                        }
                    }
                }
                rx_pos = 0;
            } else if (!rx_overflow) {
                if (rx_pos + 1 < sizeof(rx_line_buf)) {
                    rx_line_buf[rx_pos++] = static_cast<char>(ch);
                } else {
                    // Line buffer overflow protection: discard until next '\n' and report error
                    rx_overflow = true;
                    rx_pos = 0;
                }
            }
        }

        // 3. Emit 1 Hz telemetry ("type":"t") heartbeat or immediate status response
        const uint32_t now_ms = millis();
        if (s_immediateTelemetryRequested ||
            (now_ms - last_telemetry_ms) >= config::TELEMETRY_INTERVAL_MS) {
            s_immediateTelemetryRequested = false;
            last_telemetry_ms = now_ms;
            emitTelemetryPacketNow();
        }
    }
}

#endif // ARDUINO

} // namespace vs5
