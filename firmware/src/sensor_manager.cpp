/**
 * @file sensor_manager.cpp
 * @brief Implementation of Dual-MAX30102 hot-plug switching, 9-clock I2C bus recovery,
 *        native 200 Hz (800 SPS / 4x FIFO average, 18-bit) register configuration,
 *        and deterministic FIFO draining on ESP32-S3 Core 1.
 */

#include "sensor_manager.h"

#ifdef ARDUINO
#include <Arduino.h>

namespace vs5 {

SensorManager::SensorManager()
    : bus0_(&Wire),
      bus1_(&Wire1),
      mode_policy_(SensorModePolicy::AUTO),
      active_source_(SensorSource::NONE),
      onboard_present_(false),
      clip_present_(false),
      onboard_configured_(false),
      clip_configured_(false),
      bus0_fail_count_(0),
      bus1_fail_count_(0),
      last_probe_ms_(0),
      led_red_pa_(config::DEFAULT_LED_RED_PA),
      led_ir_pa_(config::DEFAULT_LED_IR_PA),
      ir_threshold_(config::DEFAULT_IR_FINGER_THRESHOLD),
      sample_seq_(0),
      last_finger_detected_(0) {}

void SensorManager::recoverI2cBus(int sda_pin, int scl_pin) {
    pinMode(sda_pin, INPUT_PULLUP);
    pinMode(scl_pin, OUTPUT);
    digitalWrite(scl_pin, HIGH);
    delayMicroseconds(10);

    // If a slave device is holding SDA low mid-byte, clock SCL up to 9 times
    // at ~100 kHz until SDA releases high.
    for (uint8_t i = 0; i < config::I2C_RECOVERY_CLOCK_PULSES; ++i) {
        if (digitalRead(sda_pin) == HIGH) {
            break;
        }
        digitalWrite(scl_pin, LOW);
        delayMicroseconds(5);
        digitalWrite(scl_pin, HIGH);
        delayMicroseconds(5);
    }

    // Generate manual I2C STOP condition (SDA LOW -> HIGH while SCL is HIGH)
    pinMode(sda_pin, OUTPUT);
    digitalWrite(sda_pin, LOW);
    delayMicroseconds(5);
    digitalWrite(scl_pin, HIGH);
    delayMicroseconds(5);
    digitalWrite(sda_pin, HIGH);
    delayMicroseconds(5);
    pinMode(sda_pin, INPUT_PULLUP);
}

void SensorManager::begin(TwoWire* bus0, TwoWire* bus1) {
    bus0_ = (bus0 != nullptr) ? bus0 : &Wire;
    bus1_ = (bus1 != nullptr) ? bus1 : &Wire1;

    // Unstick both I2C buses before initializing hardware peripherals
    recoverI2cBus(config::PIN_I2C0_SDA, config::PIN_I2C0_SCL);
    recoverI2cBus(config::PIN_I2C1_SDA, config::PIN_I2C1_SCL);

    bus0_->begin(config::PIN_I2C0_SDA, config::PIN_I2C0_SCL, config::I2C0_FREQ_HZ);
    bus0_->setTimeOut(config::I2C_TIMEOUT_MS);

    bus1_->begin(config::PIN_I2C1_SDA, config::PIN_I2C1_SCL, config::I2C1_FREQ_HZ);
    bus1_->setTimeOut(config::I2C_TIMEOUT_MS);

    onboard_present_ = probeMax30102_(bus0_);
    clip_present_    = probeMax30102_(bus1_);

    if (onboard_present_) {
        onboard_configured_ = configureMax30102For200Hz_(bus0_);
    }
    if (clip_present_) {
        clip_configured_ = configureMax30102For200Hz_(bus1_);
    }

    const SensorSource initial_target = selectActiveSensorSource(
        mode_policy_,
        clip_present_ && clip_configured_,
        onboard_present_ && onboard_configured_
    );
    transitionToSource_(initial_target);
    last_probe_ms_ = millis();
}

bool SensorManager::writeRegister_(TwoWire* bus, uint8_t reg, uint8_t value) const {
    if (bus == nullptr) {
        return false;
    }
    bus->beginTransmission(config::MAX30102_I2C_ADDR);
    bus->write(reg);
    bus->write(value);
    return (bus->endTransmission() == 0);
}

bool SensorManager::readRegister_(TwoWire* bus, uint8_t reg, uint8_t* out_value) const {
    if (bus == nullptr || out_value == nullptr) {
        return false;
    }
    bus->beginTransmission(config::MAX30102_I2C_ADDR);
    bus->write(reg);
    if (bus->endTransmission(false) != 0) {
        return false;
    }
    const size_t received = bus->requestFrom(
        static_cast<uint8_t>(config::MAX30102_I2C_ADDR),
        static_cast<uint8_t>(1),
        static_cast<uint8_t>(true)
    );
    if (received != 1 || !bus->available()) {
        return false;
    }
    *out_value = static_cast<uint8_t>(bus->read());
    return true;
}

bool SensorManager::probeMax30102_(TwoWire* bus) const {
    if (bus == nullptr) {
        return false;
    }
    bus->beginTransmission(config::MAX30102_I2C_ADDR);
    if (bus->endTransmission() != 0) {
        return false;
    }
    uint8_t part_id = 0;
    if (!readRegister_(bus, config::REG_PART_ID, &part_id)) {
        return false;
    }
    return (part_id == config::MAX30102_EXPECTED_PART_ID);
}

bool SensorManager::readFifoBurst_(TwoWire* bus, uint8_t* out_buf, size_t num_bytes) const {
    if (bus == nullptr || out_buf == nullptr || num_bytes == 0) {
        return false;
    }
    bus->beginTransmission(config::MAX30102_I2C_ADDR);
    bus->write(config::REG_FIFO_DATA);
    if (bus->endTransmission(false) != 0) {
        return false;
    }

    // Read in chunks up to 60 bytes (10 x 6-byte Red+IR samples, safely within ESP32 Wire 128-byte buffer)
    size_t offset = 0;
    while (offset < num_bytes) {
        size_t chunk = num_bytes - offset;
        if (chunk > 60U) {
            chunk = 60U;
        }
        const size_t received = bus->requestFrom(
            static_cast<uint8_t>(config::MAX30102_I2C_ADDR),
            static_cast<uint8_t>(chunk),
            static_cast<uint8_t>((offset + chunk) >= num_bytes)
        );
        if (received != chunk) {
            return false;
        }
        for (size_t i = 0; i < chunk; ++i) {
            if (!bus->available()) {
                return false;
            }
            out_buf[offset + i] = static_cast<uint8_t>(bus->read());
        }
        offset += chunk;
    }
    return true;
}

bool SensorManager::configureMax30102For200Hz_(TwoWire* bus) {
    if (bus == nullptr) {
        return false;
    }

    if (!probeMax30102_(bus)) {
        return false;
    }

    // Issue soft reset (MODE_CONFIG bit 6 = 0x40) and wait for reset bit to self-clear
    if (!writeRegister_(bus, config::REG_MODE_CONFIG, config::BIT_MODE_RESET)) {
        return false;
    }
    const uint32_t reset_start_ms = millis();
    bool reset_cleared = false;
    while ((millis() - reset_start_ms) < 50UL) {
        uint8_t mode_reg = 0xFFU;
        if (!readRegister_(bus, config::REG_MODE_CONFIG, &mode_reg)) {
            return false;
        }
        if ((mode_reg & config::BIT_MODE_RESET) == 0U) {
            reset_cleared = true;
            break;
        }
        delay(1);
    }
    if (!reset_cleared) {
        return false;
    }

    // Explicitly enforce exact register values from Section 5.1 of firmware.md:
    // FIFO_CONFIG (0x08) = 0x5F (SMP_AVE=4, FIFO_ROLLOVER_EN=1, FIFO_A_FULL=0x0F)
    // MODE_CONFIG (0x09) = 0x03 (SpO2 mode: Red + IR)
    // SPO2_CONFIG (0x0A) = 0x6F (ADC_RGE=16384nA, SR=800 SPS, PW=411us 18-bit)
    if (!writeRegister_(bus, config::REG_FIFO_CONFIG, config::VAL_FIFO_CONFIG_200HZ)) {
        return false;
    }
    if (!writeRegister_(bus, config::REG_MODE_CONFIG, config::VAL_MODE_SPO2)) {
        return false;
    }
    if (!writeRegister_(bus, config::REG_SPO2_CONFIG, config::VAL_SPO2_CONFIG_200HZ)) {
        return false;
    }
    if (!writeRegister_(bus, config::REG_LED1_PA, led_red_pa_)) {
        return false;
    }
    if (!writeRegister_(bus, config::REG_LED2_PA, led_ir_pa_)) {
        return false;
    }

    // Clear FIFO write/overflow/read pointers and read INT_STATUS_1 to clear PWR_RDY
    if (!writeRegister_(bus, config::REG_FIFO_WR_PTR, 0x00)) {
        return false;
    }
    if (!writeRegister_(bus, config::REG_OVF_COUNTER, 0x00)) {
        return false;
    }
    if (!writeRegister_(bus, config::REG_FIFO_RD_PTR, 0x00)) {
        return false;
    }
    uint8_t int_status = 0;
    if (!readRegister_(bus, config::REG_INT_STATUS_1, &int_status)) {
        return false;
    }

    return true;
}

bool SensorManager::setSensorShutdown_(TwoWire* bus, bool shutdown) {
    if (bus == nullptr) {
        return false;
    }
    uint8_t mode_val = config::VAL_MODE_SPO2;
    if (shutdown) {
        mode_val |= config::BIT_MODE_SHDN;
    }
    if (!writeRegister_(bus, config::REG_MODE_CONFIG, mode_val)) {
        return false;
    }
    if (!shutdown) {
        // Reset FIFO pointers when waking from hardware shutdown so stale samples are discarded
        writeRegister_(bus, config::REG_FIFO_WR_PTR, 0x00);
        writeRegister_(bus, config::REG_OVF_COUNTER, 0x00);
        writeRegister_(bus, config::REG_FIFO_RD_PTR, 0x00);
    }
    return true;
}

bool SensorManager::checkAndClearBrownout_(TwoWire* bus) {
    uint8_t int_status = 0;
    if (!readRegister_(bus, config::REG_INT_STATUS_1, &int_status)) {
        return false;
    }
    // If PWR_RDY (bit 0) is set, the sensor experienced a power-on reset or brownout
    // and reverted to its default halted state. Re-apply the 200 Hz configuration immediately.
    if ((int_status & config::BIT_PWR_RDY) != 0U) {
        return configureMax30102For200Hz_(bus);
    }
    return true;
}

void SensorManager::transitionToSource_(SensorSource target_source) {
    if (target_source == active_source_) {
        return;
    }

    if (target_source == SensorSource::CLIP) {
        // Shut down On-Board sensor on Bus 0 (SHDN = 1, LEDs OFF)
        if (onboard_present_) {
            setSensorShutdown_(bus0_, true);
        }
        // Wake or configure Finger Clip sensor on Bus 1
        if (!clip_configured_) {
            clip_configured_ = configureMax30102For200Hz_(bus1_);
        } else {
            setSensorShutdown_(bus1_, false);
        }
        active_source_ = clip_configured_ ? SensorSource::CLIP : SensorSource::NONE;
    } else if (target_source == SensorSource::ONBOARD) {
        // Shut down Finger Clip sensor on Bus 1 if reachable
        if (clip_present_) {
            setSensorShutdown_(bus1_, true);
        }
        // Wake or configure On-Board sensor on Bus 0
        if (!onboard_configured_) {
            onboard_configured_ = configureMax30102For200Hz_(bus0_);
        } else {
            setSensorShutdown_(bus0_, false);
        }
        active_source_ = onboard_configured_ ? SensorSource::ONBOARD : SensorSource::NONE;
    } else {
        if (clip_present_) {
            setSensorShutdown_(bus1_, true);
        }
        if (onboard_present_) {
            setSensorShutdown_(bus0_, true);
        }
        active_source_ = SensorSource::NONE;
        last_finger_detected_ = 0;
    }
}

void SensorManager::handleActiveBusFailure_() {
    if (active_source_ == SensorSource::CLIP) {
        ++bus1_fail_count_;
        if (bus1_fail_count_ >= config::I2C_MAX_CONSECUTIVE_FAILURES) {
            clip_present_ = false;
            clip_configured_ = false;
            bus1_fail_count_ = 0;

            // Recover Bus 1 in case SDA was pulled low during cable disconnect
            recoverI2cBus(config::PIN_I2C1_SDA, config::PIN_I2C1_SCL);
            bus1_->begin(config::PIN_I2C1_SDA, config::PIN_I2C1_SCL, config::I2C1_FREQ_HZ);
            bus1_->setTimeOut(config::I2C_TIMEOUT_MS);

            // Immediate seamless failover to On-Board sensor (<50 ms)
            if (!onboard_present_) {
                onboard_present_ = probeMax30102_(bus0_);
            }
            const SensorSource fallback = selectActiveSensorSource(
                mode_policy_,
                false,
                onboard_present_
            );
            transitionToSource_(fallback);
        }
    } else if (active_source_ == SensorSource::ONBOARD) {
        ++bus0_fail_count_;
        if (bus0_fail_count_ >= config::I2C_MAX_CONSECUTIVE_FAILURES) {
            onboard_present_ = false;
            onboard_configured_ = false;
            bus0_fail_count_ = 0;

            recoverI2cBus(config::PIN_I2C0_SDA, config::PIN_I2C0_SCL);
            bus0_->begin(config::PIN_I2C0_SDA, config::PIN_I2C0_SCL, config::I2C0_FREQ_HZ);
            bus0_->setTimeOut(config::I2C_TIMEOUT_MS);

            const SensorSource fallback = selectActiveSensorSource(
                mode_policy_,
                clip_present_,
                false
            );
            transitionToSource_(fallback);
        }
    }
}

void SensorManager::checkHotPlugAndArbitrate(uint32_t now_ms) {
    if ((now_ms - last_probe_ms_) < config::CLIP_PROBE_INTERVAL_MS) {
        return;
    }
    last_probe_ms_ = now_ms;

    // 1. Probe Bus 1 (Finger Clip) if not currently active
    if (active_source_ != SensorSource::CLIP) {
        const bool bus1_ack = probeMax30102_(bus1_);
        if (bus1_ack && !clip_present_) {
            clip_present_ = true;
            clip_configured_ = configureMax30102For200Hz_(bus1_);
            bus1_fail_count_ = 0;
        } else if (!bus1_ack) {
            clip_present_ = false;
            clip_configured_ = false;
        }
    }

    // 2. Probe Bus 0 (On-Board) if not currently active
    if (active_source_ != SensorSource::ONBOARD) {
        const bool bus0_ack = probeMax30102_(bus0_);
        if (bus0_ack && !onboard_present_) {
            onboard_present_ = true;
            onboard_configured_ = configureMax30102For200Hz_(bus0_);
            bus0_fail_count_ = 0;
            // Keep On-Board shut down if Clip is active
            if (active_source_ == SensorSource::CLIP) {
                setSensorShutdown_(bus0_, true);
            }
        } else if (!bus0_ack) {
            onboard_present_ = false;
            onboard_configured_ = false;
        }
    }

    // 3. Arbitrate desired active sensor according to mode policy
    const SensorSource desired = selectActiveSensorSource(
        mode_policy_,
        clip_present_ && clip_configured_,
        onboard_present_ && onboard_configured_
    );
    if (desired != active_source_) {
        transitionToSource_(desired);
    }
}

size_t SensorManager::drainActiveFifo(
    PpgSampleFrame* out_frames,
    size_t max_frames,
    uint32_t now_ms
) {
    if (out_frames == nullptr || max_frames == 0 || active_source_ == SensorSource::NONE) {
        return 0;
    }

    TwoWire* active_bus = (active_source_ == SensorSource::CLIP) ? bus1_ : bus0_;
    const uint8_t src_code = static_cast<uint8_t>(active_source_);

    // Verify the active sensor is still responding and check PWR_RDY brownout flag
    if (!checkAndClearBrownout_(active_bus)) {
        handleActiveBusFailure_();
        return 0;
    }

    // Read FIFO_WR_PTR (0x04), OVF_COUNTER (0x05), and FIFO_RD_PTR (0x06) with error checking
    uint8_t wr_ptr  = 0;
    uint8_t ovf_cnt = 0;
    uint8_t rd_ptr  = 0;
    if (!readRegister_(active_bus, config::REG_FIFO_WR_PTR, &wr_ptr) ||
        !readRegister_(active_bus, config::REG_OVF_COUNTER, &ovf_cnt) ||
        !readRegister_(active_bus, config::REG_FIFO_RD_PTR, &rd_ptr)) {
        handleActiveBusFailure_();
        return 0;
    }

    const uint8_t available_samples = computeMax30102FifoAvailable(wr_ptr, rd_ptr, ovf_cnt);
    if (available_samples == 0U) {
        // Sensor responded cleanly; reset consecutive failure counter
        if (active_source_ == SensorSource::CLIP) {
            bus1_fail_count_ = 0;
        } else {
            bus0_fail_count_ = 0;
        }
        return 0;
    }

    size_t samples_to_read = available_samples;
    if (samples_to_read > max_frames) {
        samples_to_read = max_frames;
    }
    if (samples_to_read > config::MAX30102_FIFO_DEPTH) {
        samples_to_read = config::MAX30102_FIFO_DEPTH;
    }

    // Each SpO2 sample is 6 bytes (3 bytes Red MSB-first, 3 bytes IR MSB-first)
    uint8_t raw_fifo_bytes[config::MAX30102_FIFO_DEPTH * 6];
    if (!readFifoBurst_(active_bus, raw_fifo_bytes, samples_to_read * 6U)) {
        handleActiveBusFailure_();
        return 0;
    }

    size_t count = 0;
    for (size_t i = 0; i < samples_to_read; ++i) {
        uint32_t raw_red = 0;
        uint32_t raw_ir  = 0;
        if (!decodeMax30102FifoSample(&raw_fifo_bytes[i * 6U], &raw_red, &raw_ir)) {
            handleActiveBusFailure_();
            return count;
        }

        const uint8_t finger = evaluateFingerGate(raw_ir, ir_threshold_);
        last_finger_detected_ = finger;

        PpgSampleFrame& frame = out_frames[count];
        frame.seq          = sample_seq_++;
        frame.timestamp_ms = now_ms;
        frame.red          = raw_red;
        frame.ir           = raw_ir;
        frame.source       = src_code;
        frame.finger       = finger;
        ++count;
    }

    // Reset consecutive failure counter on clean FIFO read
    if (active_source_ == SensorSource::CLIP) {
        bus1_fail_count_ = 0;
    } else {
        bus0_fail_count_ = 0;
    }

    return count;
}

bool SensorManager::applyCommand(const FirmwareCommand& cmd, uint32_t now_ms) {
    (void)now_ms;
    switch (cmd.type) {
        case CommandType::SET_SENSOR_MODE: {
            mode_policy_ = cmd.mode_policy;
            const SensorSource desired = selectActiveSensorSource(
                mode_policy_,
                clip_present_ && clip_configured_,
                onboard_present_ && onboard_configured_
            );
            transitionToSource_(desired);
            return true;
        }
        case CommandType::SET_LED_CURRENT: {
            led_red_pa_ = cmd.led_red_pa;
            led_ir_pa_  = cmd.led_ir_pa;
            bool ok = true;
            if (onboard_present_) {
                ok = ok && writeRegister_(bus0_, config::REG_LED1_PA, led_red_pa_);
                ok = ok && writeRegister_(bus0_, config::REG_LED2_PA, led_ir_pa_);
            }
            if (clip_present_) {
                ok = ok && writeRegister_(bus1_, config::REG_LED1_PA, led_red_pa_);
                ok = ok && writeRegister_(bus1_, config::REG_LED2_PA, led_ir_pa_);
            }
            return ok;
        }
        case CommandType::SET_IR_THRESHOLD: {
            if (cmd.ir_threshold < config::MIN_IR_FINGER_THRESHOLD ||
                cmd.ir_threshold > config::MAX_IR_FINGER_THRESHOLD) {
                return false;
            }
            ir_threshold_ = cmd.ir_threshold;
            return true;
        }
        case CommandType::RESET_SENSOR: {
            if (active_source_ == SensorSource::CLIP) {
                clip_configured_ = configureMax30102For200Hz_(bus1_);
                return clip_configured_;
            }
            if (active_source_ == SensorSource::ONBOARD) {
                onboard_configured_ = configureMax30102For200Hz_(bus0_);
                return onboard_configured_;
            }
            return false;
        }
        default:
            return false;
    }
}

void SensorManager::populateTelemetry(PowerHealthTelemetry* out_telemetry) const {
    if (out_telemetry == nullptr) {
        return;
    }
    out_telemetry->onboard_present = onboard_present_;
    out_telemetry->clip_present    = clip_present_;
    out_telemetry->active_source   = static_cast<uint8_t>(active_source_);
    out_telemetry->finger_detected = (active_source_ != SensorSource::NONE)
                                         ? last_finger_detected_
                                         : 0U;
}

} // namespace vs5

#endif // ARDUINO
