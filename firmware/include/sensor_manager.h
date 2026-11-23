/**
 * @file sensor_manager.h
 * @brief Dual-MAX30102 hot-plug priority state machine (Bus 1 Finger Clip priority
 *        with <50 ms seamless fallback to Bus 0 On-Board sensor), native 200 Hz
 *        (800 SPS / 4x FIFO average, 18-bit) register configuration, PWR_RDY
 *        brownout recovery, and 9-clock I2C bus unstick routine.
 */

#ifndef VITALSENSE5_SENSOR_MANAGER_H
#define VITALSENSE5_SENSOR_MANAGER_H

#include <stddef.h>
#include <stdint.h>

#include "config.h"
#include "protocol_types.h"

#ifdef ARDUINO
#include <Wire.h>
#endif

namespace vs5 {

/**
 * @brief Pure state-machine arbitration logic for selecting the active MAX30102
 *        sensor given current mode policy and Bus 0 / Bus 1 sensor presence.
 */
inline SensorSource selectActiveSensorSource(
    SensorModePolicy policy,
    bool clip_healthy,
    bool onboard_healthy
) {
    switch (policy) {
        case SensorModePolicy::CLIP:
            return clip_healthy ? SensorSource::CLIP : SensorSource::NONE;
        case SensorModePolicy::ONBOARD:
            return onboard_healthy ? SensorSource::ONBOARD : SensorSource::NONE;
        case SensorModePolicy::AUTO:
        default:
            if (clip_healthy) {
                return SensorSource::CLIP;
            }
            if (onboard_healthy) {
                return SensorSource::ONBOARD;
            }
            return SensorSource::NONE;
    }
}

/**
 * @brief Calculate the number of unread samples in the 32-deep MAX30102 hardware FIFO
 *        given the 5-bit write and read pointers (0..31).
 */
inline uint8_t computeMax30102FifoAvailable(uint8_t wr_ptr, uint8_t rd_ptr, uint8_t ovf_cnt) {
    if (ovf_cnt > 0) {
        return config::MAX30102_FIFO_DEPTH;
    }
    const uint8_t w = wr_ptr & 0x1FU;
    const uint8_t r = rd_ptr & 0x1FU;
    if (w == r) {
        return 0U;
    }
    if (w > r) {
        return static_cast<uint8_t>(w - r);
    }
    return static_cast<uint8_t>((config::MAX30102_FIFO_DEPTH - r) + w);
}

/**
 * @brief Decode a 6-byte MAX30102 SpO2 FIFO entry (3 bytes Red MSB-first, 3 bytes IR MSB-first)
 *        into 18-bit unsigned ADC counts (0..262143) and reject invalid all-1s bus dropout bytes.
 * @return true if entry is valid, false if bus pull-up dropout (0xFFFFFF) is detected.
 */
inline bool decodeMax30102FifoSample(
    const uint8_t raw_6bytes[6],
    uint32_t* out_red,
    uint32_t* out_ir
) {
    if (raw_6bytes == nullptr || out_red == nullptr || out_ir == nullptr) {
        return false;
    }
    const uint32_t red_24 = (static_cast<uint32_t>(raw_6bytes[0]) << 16) |
                            (static_cast<uint32_t>(raw_6bytes[1]) << 8)  |
                            static_cast<uint32_t>(raw_6bytes[2]);
    const uint32_t ir_24  = (static_cast<uint32_t>(raw_6bytes[3]) << 16) |
                            (static_cast<uint32_t>(raw_6bytes[4]) << 8)  |
                            static_cast<uint32_t>(raw_6bytes[5]);
    if (red_24 == 0xFFFFFFUL && ir_24 == 0xFFFFFFUL) {
        return false;
    }
    *out_red = red_24 & config::MAX30102_18BIT_MASK;
    *out_ir  = ir_24  & config::MAX30102_18BIT_MASK;
    return true;
}

#ifdef ARDUINO
/**
 * @brief Core 1 Dual-MAX30102 acquisition and hot-plug manager.
 */
class SensorManager {
public:
    SensorManager();

    /**
     * @brief Initialize I2C Bus 0 (Wire) and I2C Bus 1 (Wire1) with 9-clock bus clear,
     *        probe both MAX30102 sensors, and activate the highest-priority sensor.
     */
    void begin(TwoWire* bus0 = &Wire, TwoWire* bus1 = &Wire1);

    /**
     * @brief Periodic 500 ms hot-plug probe and health check on I2C Bus 1 / Bus 0.
     *        Handles seamless switchover and shuts down the inactive sensor (SHDN = 1).
     */
    void checkHotPlugAndArbitrate(uint32_t now_ms);

    /**
     * @brief Drain available 200 Hz (18-bit Red + IR) samples from the active MAX30102
     *        hardware FIFO into caller-supplied buffer.
     * @param out_frames Array of PpgSampleFrame structs (capacity >= max_frames).
     * @param max_frames Maximum frames to pop in this tick (e.g. 32).
     * @param now_ms     Current millisecond timestamp.
     * @return Number of new PpgSampleFrame entries written to out_frames.
     */
    size_t drainActiveFifo(PpgSampleFrame* out_frames, size_t max_frames, uint32_t now_ms);

    /**
     * @brief Execute a runtime command from Raspberry Pi 5 (set_sensor_mode,
     *        set_led_current, set_ir_threshold, reset_sensor).
     * @return true if command succeeded.
     */
    bool applyCommand(const FirmwareCommand& cmd, uint32_t now_ms);

    /**
     * @brief Populate sensor-related fields of PowerHealthTelemetry.
     */
    void populateTelemetry(PowerHealthTelemetry* out_telemetry) const;

    /**
     * @brief Manually recover a stuck I2C bus by toggling SCL up to 9 clock pulses
     *        until SDA releases high, followed by a STOP condition.
     */
    static void recoverI2cBus(int sda_pin, int scl_pin);

    SensorSource     activeSource()    const { return active_source_; }
    SensorModePolicy modePolicy()      const { return mode_policy_; }
    bool             isClipPresent()   const { return clip_present_; }
    bool             isOnboardPresent() const { return onboard_present_; }
    uint8_t          lastFingerState() const { return last_finger_detected_; }
    uint32_t         irThreshold()     const { return ir_threshold_; }
    uint8_t          ledRedPa()        const { return led_red_pa_; }
    uint8_t          ledIrPa()         const { return led_ir_pa_; }

private:
    bool probeMax30102_(TwoWire* bus) const;
    bool configureMax30102For200Hz_(TwoWire* bus);
    bool setSensorShutdown_(TwoWire* bus, bool shutdown);
    bool checkAndClearBrownout_(TwoWire* bus);
    bool writeRegister_(TwoWire* bus, uint8_t reg, uint8_t value) const;
    bool readRegister_(TwoWire* bus, uint8_t reg, uint8_t* out_value) const;
    bool readFifoBurst_(TwoWire* bus, uint8_t* out_buf, size_t num_bytes) const;
    void transitionToSource_(SensorSource target_source);
    void handleActiveBusFailure_();

    TwoWire*         bus0_;
    TwoWire*         bus1_;

    SensorModePolicy mode_policy_;
    SensorSource     active_source_;
    bool             onboard_present_;
    bool             clip_present_;
    bool             onboard_configured_;
    bool             clip_configured_;

    uint8_t          bus0_fail_count_;
    uint8_t          bus1_fail_count_;
    uint32_t         last_probe_ms_;

    uint8_t          led_red_pa_;
    uint8_t          led_ir_pa_;
    uint32_t         ir_threshold_;
    uint32_t         sample_seq_;
    uint8_t          last_finger_detected_;
};
#endif // ARDUINO

} // namespace vs5

#endif // VITALSENSE5_SENSOR_MANAGER_H
