/**
 * @file power_monitor.cpp
 * @brief INA219 high-side bidirectional power polling on ESP32-S3 Core 1 (I2C Bus 0, 0x40),
 *        5-sample (1.0 s) moving average filter, and 2S2P 18650 (8.4V 7000mAh) SoC calculation.
 */

#include "power_monitor.h"

#ifdef ARDUINO
#include <Arduino.h>

namespace vs5 {

PowerMonitor::PowerMonitor()
    : wire_(&Wire),
      ina219_(config::INA219_I2C_ADDR),
      filter_(),
      ina219_ok_(false) {}

bool PowerMonitor::probeIna219_() const {
    if (wire_ == nullptr) {
        return false;
    }
    wire_->beginTransmission(config::INA219_I2C_ADDR);
    return (wire_->endTransmission() == 0);
}

bool PowerMonitor::configureIna219_16V_320mV_() {
    if (wire_ == nullptr) {
        return false;
    }
    // 1. Initialize Adafruit_INA219 internal currentDivider_mA = 10 (100 uA/bit LSB)
    //    and CALIBRATION register (0x05) = 4096 (0x1000) for a 0.1 Ohm (R100) shunt.
    ina219_.setCalibration_32V_2A();

    // 2. Override CONFIG register (0x00) to set BRNG = 0 (16V Bus Voltage FSR)
    //    with PG = /8 (320mV Shunt Voltage FSR, up to +/-3.2A), 12-bit Bus & Shunt ADCs,
    //    and Continuous Shunt + Bus mode per Section 7.1 of firmware.md.
    const uint16_t config_16v_320mv =
        INA219_CONFIG_BVOLTAGERANGE_16V |
        INA219_CONFIG_GAIN_8_320MV |
        INA219_CONFIG_BADCRES_12BIT |
        INA219_CONFIG_SADCRES_12BIT_1S_532US |
        INA219_CONFIG_MODE_SANDBVOLT_CONTINUOUS;

    wire_->beginTransmission(config::INA219_I2C_ADDR);
    wire_->write(INA219_REG_CONFIG);
    wire_->write(static_cast<uint8_t>((config_16v_320mv >> 8) & 0xFFU));
    wire_->write(static_cast<uint8_t>(config_16v_320mv & 0xFFU));
    return (wire_->endTransmission() == 0);
}

bool PowerMonitor::begin(TwoWire* wire) {
    wire_ = (wire != nullptr) ? wire : &Wire;
    filter_.reset();

    if (!probeIna219_()) {
        ina219_ok_ = false;
        return false;
    }

    if (!ina219_.begin(wire_)) {
        ina219_ok_ = false;
        return false;
    }

    if (!configureIna219_16V_320mV_()) {
        ina219_ok_ = false;
        return false;
    }
    ina219_ok_ = true;

    // Seed initial filter sample immediately
    pollSample();
    return ina219_ok_;
}

bool PowerMonitor::pollSample() {
    if (!probeIna219_()) {
        ina219_ok_ = false;
        return false;
    }

    // Re-initialize calibration if INA219 was hot-reconnected
    if (!ina219_ok_) {
        if (!ina219_.begin(wire_) || !configureIna219_16V_320mV_()) {
            return false;
        }
        ina219_ok_ = true;
    }

    const float bus_v      = ina219_.getBusVoltage_V();
    if (!ina219_.success()) {
        ina219_ok_ = false;
        return false;
    }
    const float shunt_mv   = ina219_.getShuntVoltage_mV();
    if (!ina219_.success()) {
        ina219_ok_ = false;
        return false;
    }
    const float current_ma = ina219_.getCurrent_mA();
    if (!ina219_.success()) {
        ina219_ok_ = false;
        return false;
    }

    // Load/pack voltage = bus voltage + shunt drop
    const float pack_v = bus_v + (shunt_mv / 1000.0f);
    if (!isfinite(pack_v) || pack_v < 0.0f || pack_v > 16.0f) {
        return false;
    }

    filter_.pushSample(pack_v, current_ma);
    return true;
}

void PowerMonitor::populateTelemetry(PowerHealthTelemetry* out_telemetry) const {
    if (out_telemetry == nullptr) {
        return;
    }
    out_telemetry->ina219_ok         = ina219_ok_;
    out_telemetry->battery_voltage_v = filter_.filteredVoltageV();
    out_telemetry->current_ma        = filter_.filteredCurrentMa();
    out_telemetry->battery_percent   = filter_.batteryPercent();
    out_telemetry->is_charging       = filter_.isCharging();
}

} // namespace vs5

#endif // ARDUINO
