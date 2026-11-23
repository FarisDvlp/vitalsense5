/**
 * @file uart_comms.h
 * @brief Core 0 UART1 (460800 8N1, TX=GPIO43, RX=GPIO44) NDJSON streamer and
 *        downstream Raspberry Pi 5 command parser.
 */

#ifndef VITALSENSE5_UART_COMMS_H
#define VITALSENSE5_UART_COMMS_H

#include <stddef.h>
#include <stdint.h>

#include "config.h"
#include "protocol_types.h"

#ifdef ARDUINO
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#endif

namespace vs5 {

/**
 * @brief Parse a single newline-stripped JSON command line from Raspberry Pi 5
 *        into a FirmwareCommand and format the corresponding "ack" or "err"
 *        NDJSON response line into ack_buf.
 * @return true if the command is valid and should be executed, false on error.
 */
bool parseDownstreamCommandJson(
    const char* json_line,
    FirmwareCommand* out_cmd,
    char* ack_buf,
    size_t ack_buf_size
);

#ifdef ARDUINO
/**
 * @brief Initialize UART1 (Serial1) on GPIO 43 (TX) and GPIO 44 (RX) at 460800 baud.
 */
void initUart1Comms();

/**
 * @brief Core 0 FreeRTOS task entrypoint: drains 200 Hz PpgSampleFrame queue,
 *        emits 1 Hz PowerHealthTelemetry ("type":"t") frames, and parses incoming
 *        UART1 JSON commands non-blockingly.
 */
void taskUartCommsEntry(void* pvParameters);

/**
 * @brief Trigger an immediate out-of-band "type":"t" telemetry packet on Core 0
 *        (used when "get_status" command is received).
 */
void requestImmediateTelemetry();

#endif // ARDUINO

} // namespace vs5

#endif // VITALSENSE5_UART_COMMS_H
