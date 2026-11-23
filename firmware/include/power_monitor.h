/**
 * @file power_monitor.h
 * @brief INA219 high-side bidirectional power monitor (I2C Bus 0, 0x40),
 *        5-sample (1.0 s) moving-average filter, charging hysteresis, and
 *        2S2P 18650 (6.0V - 8.4V, 7000mAh) piecewise voltage-to-SoC lookup.
 */

#ifndef VITALSENSE5_POWER_MONITOR_H
#define VITALSENSE5_POWER_MONITOR_H

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "config.h"
#include "protocol_types.h"

#ifdef ARDUINO
#include <Wire.h>
#include <Adafruit_INA219.h>
#endif

namespace vs5 {

/**
 * @brief Anchor point for the 2S Li-Ion open-circuit voltage (V_ocv) to SoC (%) curve.
 */
struct SocAnchorPoint {
    float   voltage_v;
    uint8_t soc_percent;
};

/**
 * @brief 11-point piecewise 2S2P 18650 Li-Ion open-circuit voltage to SoC table
 *        specified in Section 7.2 of firmware.md.
 */
static constexpr SocAnchorPoint k2SLiIonSocTable[] = {
    {8.40f, 100},
    {8.20f,  90},
    {8.00f,  80},
    {7.80f,  70},
    {7.64f,  60},
    {7.50f,  50},
    {7.38f,  40},
    {7.26f,  30},
    {7.10f,  20},
    {6.80f,  10},
    {6.00f,   0}
};

static constexpr size_t k2SLiIonSocTableSize =
    sizeof(k2SLiIonSocTable) / sizeof(k2SLiIonSocTable[0]);

/**
 * @brief Compute internal-resistance-compensated open-circuit voltage (V_ocv)
 *        for the 2S2P battery pack:
 *        V_ocv = V_bus + I_discharge_A * R_pack_internal
 *        (Works for both discharge I > 0 and charge I < 0).
 */
inline float computeCompensatedOcv(float bus_voltage_v, float current_ma) {
    if (!isfinite(bus_voltage_v) || bus_voltage_v <= 0.0f) {
        return 0.0f;
    }
    const float current_a = isfinite(current_ma) ? (current_ma / 1000.0f) : 0.0f;
    return bus_voltage_v + (current_a * config::R_PACK_INTERNAL_OHM);
}

/**
 * @brief Piecewise linear interpolation of 2S2P Li-Ion state of charge (0..100%)
 *        from open-circuit voltage V_ocv.
 */
inline uint8_t interpolate2SLiIonSoc(float v_ocv) {
    if (!isfinite(v_ocv) || v_ocv <= k2SLiIonSocTable[k2SLiIonSocTableSize - 1].voltage_v) {
        return 0;
    }
    if (v_ocv >= k2SLiIonSocTable[0].voltage_v) {
        return 100;
    }

    for (size_t i = 0; i + 1 < k2SLiIonSocTableSize; ++i) {
        const float v_high = k2SLiIonSocTable[i].voltage_v;
        const float v_low  = k2SLiIonSocTable[i + 1].voltage_v;
        if (v_ocv <= v_high && v_ocv >= v_low) {
            const float s_high = static_cast<float>(k2SLiIonSocTable[i].soc_percent);
            const float s_low  = static_cast<float>(k2SLiIonSocTable[i + 1].soc_percent);
            const float span   = v_high - v_low;
            if (span <= 1e-5f) {
                return k2SLiIonSocTable[i].soc_percent;
            }
            const float ratio = (v_ocv - v_low) / span;
            const float soc_f = s_low + ratio * (s_high - s_low);
            const int soc_rounded = static_cast<int>(soc_f + 0.5f);
            if (soc_rounded < 0) return 0;
            if (soc_rounded > 100) return 100;
            return static_cast<uint8_t>(soc_rounded);
        }
    }
    return 0;
}

/**
 * @brief Evaluate charging state with hysteresis to prevent oscillation near cutoff:
 *        - Enters charging when current_ma < -50.0 mA (CHARGE_DETECT_ENTER_MA)
 *        - Exits charging when current_ma > -20.0 mA (CHARGE_DETECT_EXIT_MA)
 */
inline bool evaluateChargingHysteresis(float filtered_current_ma, bool previously_charging) {
    if (!isfinite(filtered_current_ma)) {
        return false;
    }
    if (previously_charging) {
        return filtered_current_ma <= config::CHARGE_DETECT_EXIT_MA;
    }
    return filtered_current_ma < config::CHARGE_DETECT_ENTER_MA;
}

/**
 * @brief 5-sample moving average filter and state tracker for INA219 readings.
 */
class PowerFilterState {
public:
    PowerFilterState() {
        reset();
    }

    void reset() {
        for (size_t i = 0; i < config::INA219_FILTER_WINDOW; ++i) {
            voltage_ring_[i] = 0.0f;
            current_ring_[i] = 0.0f;
        }
        head_ = 0;
        count_ = 0;
        filtered_voltage_v_ = config::DEFAULT_BATTERY_VOLTAGE_V;
        filtered_current_ma_ = 0.0f;
        battery_percent_ = config::DEFAULT_BATTERY_PERCENT;
        is_charging_ = false;
    }

    void pushSample(float bus_voltage_v, float raw_current_ma) {
        if (!isfinite(bus_voltage_v) || !isfinite(raw_current_ma)) {
            return;
        }
        const float signed_current_ma = raw_current_ma * config::INA219_CURRENT_SIGN;

        voltage_ring_[head_] = bus_voltage_v;
        current_ring_[head_] = signed_current_ma;
        head_ = (head_ + 1) % config::INA219_FILTER_WINDOW;
        if (count_ < config::INA219_FILTER_WINDOW) {
            ++count_;
        }

        float v_sum = 0.0f;
        float i_sum = 0.0f;
        for (size_t i = 0; i < count_; ++i) {
            v_sum += voltage_ring_[i];
            i_sum += current_ring_[i];
        }
        filtered_voltage_v_  = v_sum / static_cast<float>(count_);
        filtered_current_ma_ = i_sum / static_cast<float>(count_);

        const float v_ocv = computeCompensatedOcv(filtered_voltage_v_, filtered_current_ma_);
        battery_percent_  = interpolate2SLiIonSoc(v_ocv);
        is_charging_      = evaluateChargingHysteresis(filtered_current_ma_, is_charging_);
    }

    float   filteredVoltageV()  const { return filtered_voltage_v_; }
    float   filteredCurrentMa() const { return filtered_current_ma_; }
    uint8_t batteryPercent()    const { return battery_percent_; }
    bool    isCharging()        const { return is_charging_; }
    size_t  sampleCount()       const { return count_; }

private:
    float   voltage_ring_[config::INA219_FILTER_WINDOW];
    float   current_ring_[config::INA219_FILTER_WINDOW];
    size_t  head_;
    size_t  count_;
    float   filtered_voltage_v_;
    float   filtered_current_ma_;
    uint8_t battery_percent_;
    bool    is_charging_;
};

#ifdef ARDUINO
/**
 * @brief Hardware INA219 manager living on Core 1 (I2C Bus 0, 0x40).
 */
class PowerMonitor {
public:
    PowerMonitor();

    /**
     * @brief Initialize INA219 on I2C Bus 0 (0x40) with 16V, 320mV (PG=/8, up to 3.2A) calibration.
     */
    bool begin(TwoWire* wire = &Wire);

    /**
     * @brief Poll a new voltage & current reading (called every 200 ms on Core 1).
     */
    bool pollSample();

    /**
     * @brief Populate battery/power fields inside PowerHealthTelemetry.
     */
    void populateTelemetry(PowerHealthTelemetry* out_telemetry) const;

    bool isHealthy() const { return ina219_ok_; }

private:
    bool probeIna219_() const;
    bool configureIna219_16V_320mV_();

    TwoWire*         wire_;
    Adafruit_INA219  ina219_;
    PowerFilterState filter_;
    bool             ina219_ok_;
};
#endif // ARDUINO

} // namespace vs5

#endif // VITALSENSE5_POWER_MONITOR_H
