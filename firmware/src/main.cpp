/**
 * @file main.cpp
 * @brief VitalSense5 ESP32-S3-Zero Dual-Core FreeRTOS Firmware Entrypoint.
 *        - Core 1 (APP_CPU, Priority 3): Deterministic 2 ms (500 Hz) I2C acquisition task
 *          draining the active MAX30102 FIFO at 200 Hz (800 SPS / 4x average, 18-bit),
 *          managing Bus 1 Finger Clip hot-plug switching (<50 ms handover), polling
 *          INA219 2S2P battery telemetry every 200 ms, and driving the GPIO 21 WS2812 LED.
 *        - Core 0 (PRO_CPU, Priority 2): UART1 (460800 8N1, GPIO 43/44) NDJSON streamer
 *          and downstream command parser.
 */

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <esp_task_wdt.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include "config.h"
#include "power_monitor.h"
#include "protocol_types.h"
#include "sensor_manager.h"
#include "uart_comms.h"

namespace vs5 {

// Inter-core FreeRTOS queues and synchronization primitives
QueueHandle_t        g_ppgSampleQueue   = nullptr;
QueueHandle_t        g_cmdQueue         = nullptr;
SemaphoreHandle_t    g_powerHealthMutex = nullptr;
PowerHealthTelemetry g_powerHealthState{};

static SensorManager     s_sensorManager;
static PowerMonitor      s_powerMonitor;
static Adafruit_NeoPixel s_statusLed(
    config::WS2812_NUM_PIXELS,
    config::PIN_WS2812_RGB,
    NEO_GRB + NEO_KHZ800
);

static TaskHandle_t s_taskSensorAcqHandle = nullptr;
static TaskHandle_t s_taskUartCommsHandle = nullptr;

/**
 * @brief Update the onboard WS2812 RGB diagnostic LED (GPIO 21) per Section 9 of firmware.md:
 *        - Solid Cyan:   Active streaming from Finger Clip (Bus 1) with finger detected
 *        - Solid Green:  Active streaming from On-Board sensor (Bus 0) with finger detected
 *        - Dim Amber:    Sensor active, waiting for finger (finger == 0)
 *        - Flashing Red: Both MAX30102 sensors unreachable on Bus 0 and Bus 1
 */
static void updateDiagnosticLed(uint32_t now_ms, SensorSource source, uint8_t finger) {
    uint32_t color = 0;
    if (source == SensorSource::NONE) {
        // Flashing Red (2 Hz) when both sensors are faulted/unreachable
        const bool flash_on = ((now_ms / 250U) % 2U) == 0U;
        color = flash_on ? s_statusLed.Color(255, 0, 0) : s_statusLed.Color(0, 0, 0);
    } else if (finger == 0U) {
        // Dim Amber breathing when waiting for finger
        const uint32_t phase = (now_ms / 16U) % 120U;
        const uint8_t level = static_cast<uint8_t>((phase <= 60U) ? (20U + phase * 2U) : (20U + (120U - phase) * 2U));
        color = s_statusLed.Color(level, level / 2U, 0);
    } else if (source == SensorSource::CLIP) {
        // Solid Cyan for Finger Clip active + finger detected
        color = s_statusLed.Color(0, 200, 255);
    } else {
        // Solid Green for On-Board sensor active + finger detected
        color = s_statusLed.Color(0, 220, 40);
    }
    s_statusLed.setPixelColor(0, color);
    s_statusLed.show();
}

/**
 * @brief Core 1 (APP_CPU) High-Priority Sensor Acquisition Task.
 */
static void taskSensorAcquisitionEntry(void* pvParameters) {
    (void)pvParameters;

    // Subscribe Core 1 acquisition task to Task Watchdog Timer
    esp_task_wdt_add(NULL);

    // Initialize Dual I2C buses, MAX30102 sensors (Bus 0 & Bus 1), and INA219 (Bus 0)
    s_sensorManager.begin(&Wire, &Wire1);
    s_powerMonitor.begin(&Wire);

    TickType_t last_wake_tick = xTaskGetTickCount();
    const TickType_t poll_period_ticks = pdMS_TO_TICKS(config::SENSOR_POLL_PERIOD_MS);

    uint32_t last_ina219_poll_ms = millis();
    uint32_t last_led_update_ms  = millis();
    uint32_t cumulative_drops    = 0;

    PpgSampleFrame fifo_burst[config::MAX30102_FIFO_DEPTH];

    for (;;) {
        esp_task_wdt_reset();

        const uint32_t now_ms = millis();

        // 1. Process any pending downstream commands from Core 0
        FirmwareCommand cmd{};
        while (g_cmdQueue != nullptr && xQueueReceive(g_cmdQueue, &cmd, 0) == pdTRUE) {
            s_sensorManager.applyCommand(cmd, now_ms);
        }

        // 2. Drain active MAX30102 FIFO at 200 Hz (0..N samples per 2 ms tick)
        const size_t drained = s_sensorManager.drainActiveFifo(
            fifo_burst,
            config::MAX30102_FIFO_DEPTH,
            now_ms
        );
        for (size_t i = 0; i < drained; ++i) {
            if (xQueueSend(g_ppgSampleQueue, &fifo_burst[i], 0) != pdTRUE) {
                ++cumulative_drops;
            }
        }

        // 3. Periodic 500 ms hot-plug probe on I2C Bus 1 & sensor priority arbitration
        s_sensorManager.checkHotPlugAndArbitrate(now_ms);

        // 4. Periodic 200 ms (5 Hz) INA219 battery voltage & current polling
        //    and atomic update of shared PowerHealthTelemetry
        if ((now_ms - last_ina219_poll_ms) >= config::INA219_POLL_INTERVAL_MS) {
            last_ina219_poll_ms = now_ms;
            s_powerMonitor.pollSample();

            PowerHealthTelemetry next_state{};
            next_state.uptime_s    = now_ms / 1000UL;
            next_state.queue_drops = cumulative_drops;
            s_powerMonitor.populateTelemetry(&next_state);
            s_sensorManager.populateTelemetry(&next_state);

            if (g_powerHealthMutex != nullptr &&
                xSemaphoreTake(g_powerHealthMutex, pdMS_TO_TICKS(2)) == pdTRUE) {
                g_powerHealthState = next_state;
                xSemaphoreGive(g_powerHealthMutex);
            }
        }

        // 5. Update onboard WS2812 RGB status LED at ~20 Hz (every 50 ms)
        if ((now_ms - last_led_update_ms) >= 50UL) {
            last_led_update_ms = now_ms;
            updateDiagnosticLed(
                now_ms,
                s_sensorManager.activeSource(),
                s_sensorManager.lastFingerState()
            );
        }

        // Deterministic 2 ms cadence
        vTaskDelayUntil(&last_wake_tick, poll_period_ticks);
    }
}

} // namespace vs5

void setup() {
    // 1. USB CDC Debug Console (flashing & diagnostic logs)
    Serial.begin(vs5::config::USB_DEBUG_BAUD);

    // 2. Initialize WS2812 RGB LED to Blue pulse during boot
    vs5::s_statusLed.begin();
    vs5::s_statusLed.setBrightness(vs5::config::WS2812_BRIGHTNESS);
    vs5::s_statusLed.setPixelColor(0, vs5::s_statusLed.Color(0, 40, 255));
    vs5::s_statusLed.show();

    // 3. Initialize Hardware UART1 (460800 8N1 on TX=GPIO43, RX=GPIO44) for Raspberry Pi 5 link
    vs5::initUart1Comms();

    // 4. Create inter-core FreeRTOS queues and telemetry mutex
    vs5::g_ppgSampleQueue = xQueueCreate(
        vs5::config::PPG_SAMPLE_QUEUE_DEPTH,
        sizeof(vs5::PpgSampleFrame)
    );
    vs5::g_cmdQueue = xQueueCreate(
        vs5::config::CMD_QUEUE_DEPTH,
        sizeof(vs5::FirmwareCommand)
    );
    vs5::g_powerHealthMutex = xSemaphoreCreateMutex();

    // 5. Configure 3-second ESP32 Task Watchdog Timer
    esp_task_wdt_init(vs5::config::TWDT_TIMEOUT_S, true);

    // 6. Launch Core 1 (APP_CPU) Sensor Acquisition Task (Priority 3)
    xTaskCreatePinnedToCore(
        vs5::taskSensorAcquisitionEntry,
        "TaskSensorAcquisition",
        vs5::config::TASK_STACK_SENSOR_ACQ,
        nullptr,
        vs5::config::TASK_PRIO_SENSOR_ACQ,
        &vs5::s_taskSensorAcqHandle,
        vs5::config::CORE_SENSOR_ACQ
    );

    // 7. Launch Core 0 (PRO_CPU) UART Communications Task (Priority 2)
    xTaskCreatePinnedToCore(
        vs5::taskUartCommsEntry,
        "TaskUartComms",
        vs5::config::TASK_STACK_UART_COMMS,
        nullptr,
        vs5::config::TASK_PRIO_UART_COMMS,
        &vs5::s_taskUartCommsHandle,
        vs5::config::CORE_UART_COMMS
    );
}

void loop() {
    // Arduino loopTask is unused; yield indefinitely to FreeRTOS worker tasks
    vTaskDelay(pdMS_TO_TICKS(1000));
}
