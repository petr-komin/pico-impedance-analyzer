# Pico Impedance Analyzer

Impedance analyzer / frequency response measurement system based on the Waveshare RP2040-Zero microcontroller, AD9851 DDS signal generator, ADS1115 ADC and AD8302 RF/IF magnitude+phase detector.

## What it does

- Sweeps a signal across a user-defined frequency range (1 Hz – 70 MHz)
- Measures the response via the AD8302 (magnitude 0–60 dB, phase 0–180°)
- Streams results over USB serial to a desktop application
- Desktop app plots magnitude and phase vs. frequency in real time

Intended use cases: frequency response of filters/amplifiers, RLC meter, antenna analyzer.

## Hardware

| Component | Role |
|-----------|------|
| [Waveshare RP2040-Zero](https://www.waveshare.com/rp2040-zero.htm) | Microcontroller |
| AD9851 | DDS signal generator (up to 70 MHz, 180 MHz master clock) |
| ADS1115 | 16-bit I²C ADC (reads VMAG and VPHS from AD8302) |
| AD8302 | RF/IF magnitude and phase detector |

### Pin assignment

| Signal | RP2040 GPIO |
|--------|-------------|
| I²C SDA (ADS1115) | GP4 |
| I²C SCL (ADS1115) | GP5 |
| DDS DATA | GP8 |
| DDS W_CLK | GP9 |
| DDS FQ_UD | GP10 |
| DDS RESET | GP11 |

ADS1115 ADDR pin → GND (I²C address `0x48`).

## Repository layout

```
firmware/       PlatformIO project (Arduino / mbed framework)
  src/          Full firmware (DDS + ADC + serial protocol)
  src_diag/     Diagnostic sketch — I²C scan + ADC readout
  platformio.ini

desktop/        Python desktop application
  main.py       Entry point
  core/
    device.py   Serial communication with the firmware
    measurement.py  AD8302 voltage → dB / degree conversion
  ui/
    main_window.py  PySide6 GUI with live pyqtgraph plots
  requirements.txt
```

## Firmware

### Requirements

- [PlatformIO](https://platformio.org/)
- Platform: `raspberrypi`, board: `pico`, framework: `arduino`

### Build & upload

```bash
cd firmware

# Diagnostic first — verify I²C and ADC wiring
pio run -e diagnostic --target upload
pio device monitor          # send 's' to rescan I²C, 'r' to read ADC

# Full firmware
pio run -e main --target upload
```

### Serial protocol

The firmware communicates at **115200 baud** with newline-terminated ASCII commands. Responses are JSON objects.

| Command | Description |
|---------|-------------|
| `PING` | Connectivity check → `{"pong":true}` |
| `SCAN` | I²C bus scan → `{"i2c_scan":[72]}` |
| `FREQ <hz>` | Set DDS frequency |
| `MEASURE` | Single measurement → `{"freq":…,"vmag":…,"vphs":…}` |
| `SWEEP <start> <stop> <steps> <dwell_ms>` | Frequency sweep, one JSON line per point |
| `GAIN <0-5>` | ADS1115 PGA range (0=±6.1V … 5=±0.26V) |

## Desktop application

### Requirements

- Python 3.11+
- Works on Linux, Windows, macOS

```bash
cd desktop
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Dependencies

| Package | Purpose |
|---------|---------|
| PySide6 | GUI framework |
| pyqtgraph | Real-time plotting |
| pyserial | USB serial communication |
| numpy | Data arrays for sweep results |

## License

MIT
