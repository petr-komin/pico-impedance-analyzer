# Pico Impedance Analyzer

Impedance analyzer / frequency response measurement system based on the Waveshare RP2040-Zero microcontroller, AD9851 DDS signal generator, ADS1115 ADC and AD8302 RF/IF magnitude+phase detector.

## What it does

- Sweeps a signal across a user-defined frequency range (1 Hz – 70 MHz)
- Measures the response via the AD8302 (magnitude 0–60 dB, phase 0–180°), referenced to VREF for ratiometric accuracy
- Computes complex impedance, capacitance / inductance and Q / D from a series-Rref fixture
- Up to 3 reference-resistor ranges, switched by reed relays
- SOL (short / open / load) calibration per range removes fixture and relay parasitics
- Streams results over USB serial to a desktop application with live magnitude / phase plots

Intended use cases: frequency response of filters/amplifiers, L/C/Q meter, antenna analyzer.

## Hardware

| Component | Role |
|-----------|------|
| [Waveshare RP2040-Zero](https://www.waveshare.com/rp2040-zero.htm) | Microcontroller |
| AD9851 | DDS signal generator (up to 70 MHz, 180 MHz master clock) |
| ADS1115 | 16-bit I²C ADC (reads VMAG, VREF, VPHS from AD8302) |
| AD8302 | RF/IF magnitude and phase detector |
| 3× reed relay + FET driver | Selects the reference resistor range |

### Pin assignment

| Signal | RP2040 GPIO |
|--------|-------------|
| I²C SDA (ADS1115) | GP4 |
| I²C SCL (ADS1115) | GP5 |
| DDS DATA | GP8 |
| DDS W_CLK | GP9 |
| DDS FQ_UD | GP10 |
| DDS RESET | GP11 |
| Range relay 0 (Rref #1) | GP12 |
| Range relay 1 (Rref #2) | GP13 |
| Range relay 2 (Rref #3) | GP14 |

ADS1115 ADDR pin → GND (I²C address `0x48`).

### ADC channel mapping (AD8302 → ADS1115)

| ADS1115 input | AD8302 signal |
|---------------|---------------|
| A3 | VMAG (magnitude) |
| A2 | VREF (reference, ~1.8 V) |
| A1 | VPHS (phase) |

VREF is digitised too, so dB and phase are computed ratiometrically
(`VMAG/VREF`, `VPHS/VREF`) and are immune to supply drift.

### Range switching (reed relays)

The reference resistor `Rref` of the measurement fixture is selected by **three
reed relays, one per range, one-hot** (exactly one closed at a time). The relay
coils are driven by GP12 / GP13 / GP14:

- **Active = logic HIGH** turns the relay ON.
- Each GPIO drives a **small N-channel logic-level MOSFET** (e.g. 2N7002 /
  BSS138) as a low-side switch — the RP2040 pin cannot source the coil current
  directly.
- A **flyback diode** (1N4148) sits anti-parallel across each relay coil.

```
            5V ──[ relay coil ]──┬───────── drain
                                 │
                       1N4148 ───┤  (cathode to the 5V side of the coil)
                                 │
   GP12/13/14 ──[ 1k ]── gate ───┤  N-MOSFET (2N7002 / BSS138)
                          source ─┴──────── GND
```

On boot the firmware drives all relay pins LOW and selects range 0.

#### Reed coil winding (bare reed switches)

For bare reed switches (no coil), wind your own. Pull-in depends on
**ampere-turns (N·I)**, not turns alone. With **Ø0.1 mm enamelled copper**
(~2.2 Ω/m, ~0.024 Ω/turn over the glass body) driven from **5 V**, full voltage
over-drives the switch, so limit the current with a series resistor:

| Turns N | Coil R | Series R | Coil current | ≈ ampere-turns |
|---------|--------|----------|--------------|----------------|
| 500  | 12 Ω | 56 Ω  | 70 mA   | ~35 AT |
| **1000** | **24 Ω** | **120 Ω** | **35 mA** | **~35 AT** |
| 2000 | 48 Ω | 240 Ω | 17.5 mA | ~35 AT |

Recommended: **~1000 turns + 120 Ω** in series (½ W). This reliably trips a
~20 AT reed switch. Centre the glass capsule inside the coil; if it does not
click, lower the series resistor (more current = more ampere-turns). The series
resistor goes between 5 V and the coil; the MOSFET switches the low side.

### Measurement fixture (impedance / L / C / Q)

A voltage divider with a series reference resistor turns the device into an
impedance meter:

```
   DDS ─►[buffer]──┬───[ Rref ]───┬─── DUT ─── GND
                 node A          node B
                 (INPA)          (INPB)
```

The AD8302 measures `|V_A / V_B|` and the phase between the nodes, from which the
software derives `Z = Rref · H / (1 - H)` and then C, L, ESR and Q (`|X|/ESR`)
or D (`1/Q`). Inductive vs. capacitive is chosen manually (L/C mode) because the
AD8302 reports only `|phase|`.

- **Ranges:** pick `Rref` close to the DUT's `|Z|` for best sensitivity. Default
  values **51 / 510 / 5111 Ω** (configurable in the app), switched by the relays.
- **Calibration:** per range, measure SOL standards — **SHORT (0 Ω)**,
  **OPEN (∞)**, **LOAD (known R)** — over the same sweep. A bilinear correction
  then removes the fixture, relay and AD8302 input parasitics. Stored in
  `calibration.json`; range/Rref settings live in `config.json` (both git-ignored).
- **Q accuracy:** reliable to Q ≈ 20–30; above ~50 the phase sits within <1° of
  90° and the AD8302 phase resolution dominates. For high-Q coils use a
  resonance method instead.

## Repository layout

```
firmware/       PlatformIO project (Arduino / mbed framework)
  src/          Full firmware (DDS + ADC + relays + serial protocol)
  src_diag/     Diagnostic sketch — I²C scan + ADC readout
  platformio.ini

desktop/        Python desktop application
  main.py       Entry point
  core/
    device.py       Serial communication with the firmware
    measurement.py  Sweep data model, AD8302 voltage → dB / degree
    calibration.py  Ranges + SOL calibration + Z / L / C / Q computation
  ui/
    main_window.py  PySide6 GUI: Measurement + Calibration tabs, live plots
    freq_widget.py  Frequency input widget
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
| `MEASURE` | Single measurement → `{"freq":…,"vmag":…,"vref":…,"vphs":…}` |
| `SWEEP <start> <stop> <steps> <dwell_ms>` | Frequency sweep, one JSON line per point |
| `GAIN <0-5>` | ADS1115 PGA range (0=±6.1V … 5=±0.26V) |
| `RANGE <0-2>` | Select reference-resistor range (closes the matching relay, active HIGH) → `{"ok":true,"range":N}` |

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
