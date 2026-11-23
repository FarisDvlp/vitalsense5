# VitalSense5
Real time ICU-Monitor style monitoring for vital sign based on Photoplethysmography

## Hardware Configuration:

Main Processing Unit: Raspberry PI 5 (2GB)

Main Display: Waveshare 7 Inch LCD - Touchscreen 1280x720 (H) 

Main MCU: ESP-32 S3

Main Sensor: MAX30102 PPG Sensor

Battery Sensor: INA219 Bi-Current Sensor

Battery: 2S2P 18650 Li-Ion Battery (8.4V 7000mAh)

## Communication

MCU -> Raspberry PI 5 via UART using JSON to read DATA

MAX30102 and INA219 -> MCU via I2C

## Systems Architecture

### Edge Device
PPG->ESP32-S3
FreeRTOS Dual Core (Core 1: I2C Polling + FIFO Drain Core 2: UART Streaming)

### Edge Processing
ESP32-S3->Raspberry Pi 5 (Kiosk Mode) UART Protocol

### Full Stack Framework Python
Backend(SciPy PYSerial Numpy)
Database(SQLite)
FrontEnd(PYQT6)
Cloud Database (undecided)

## Output
- Pulse Rate Variability (PRV)
- Respiratory Rate (RR)
- Perfusion Index (PI)
- Oxygen Blood Saturation (SpO2)
- Blood Pressure (BP) Systolic and Diastolic
- PPG Waveform

## Output Algorithm
All the output for this algorithm will be based on mathematics relation and machine learning model all trained on python.

