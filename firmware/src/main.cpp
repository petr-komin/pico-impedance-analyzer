#include <Arduino.h>
#include <Wire.h>
#include <ADS1115_WE.h>
#include <cstdarg>
#include "AD9851.h"
#include "protocol.h"

// AD9851 pins (SPI bit-bang) — Waveshare RP2040-Zero
#define DDS_DATA_PIN   8
#define DDS_CLK_PIN    9
#define DDS_FQ_UD_PIN 10
#define DDS_RESET_PIN 11

// ADS1115 — Wire/I2C0 defaultne pouziva GP4 (SDA) + GP5 (SCL) na Pico
#define ADS_ADDR  0x48

// Prepinani referencniho rezistoru (rele, one-hot — vzdy sepnuto jen jedno)
#define RANGE0_PIN 12   // Rref rozsah 0
#define RANGE1_PIN 13   // Rref rozsah 1
#define RANGE2_PIN 14   // Rref rozsah 2

AD9851 dds(DDS_DATA_PIN, DDS_CLK_PIN, DDS_FQ_UD_PIN, DDS_RESET_PIN);
ADS1115_WE adc(ADS_ADDR);

static uint32_t   currentFreq = 1000000UL;
static ADS1115_RANGE adsGain  = ADS1115_RANGE_2048;
static uint8_t    currentRange = 0;

void setRange(uint8_t r) {
    if (r > 2) return;
    currentRange = r;
    digitalWrite(RANGE0_PIN, r == 0 ? HIGH : LOW);
    digitalWrite(RANGE1_PIN, r == 1 ? HIGH : LOW);
    digitalWrite(RANGE2_PIN, r == 2 ? HIGH : LOW);
}

// snprintf helper — mbed Arduino nema Serial.printf()
static void serialPrintf(const char *fmt, ...) {
    char buf[128];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    Serial.print(buf);
}

void setupADC() {
    if (!adc.init()) {
        Serial.println("{\"error\":\"ADS1115 not found\"}");
    }
    adc.setVoltageRange_mV(adsGain);
    adc.setConvRate(ADS1115_128_SPS);
    adc.setMeasureMode(ADS1115_SINGLE);
}

float readChannel(ADS1115_MUX ch) {
    adc.setCompareChannels(ch);
    adc.startSingleMeasurement();
    while (adc.isBusy()) delayMicroseconds(100);
    return adc.getResult_V();
}

void measure(float &vmag, float &vref, float &vphs) {
    vmag = readChannel(ADS1115_COMP_3_GND); // A3 = VMAG
    vref = readChannel(ADS1115_COMP_2_GND); // A2 = VREF
    vphs = readChannel(ADS1115_COMP_1_GND); // A1 = VPHS
}

void i2cScan() {
    Serial.print("{\"i2c_scan\":[");
    bool first = true;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            if (!first) Serial.print(",");
            Serial.print(addr);
            first = false;
        }
    }
    Serial.println("]}");
}

void handleCommand(const char *line) {
    char cmd[16];
    sscanf(line, "%15s", cmd);

    if (strcmp(cmd, "FREQ") == 0) {
        uint32_t f = 0;
        sscanf(line, "FREQ %lu", &f);
        if (f > 0 && f <= 70000000UL) {
            currentFreq = f;
            dds.setFrequency(currentFreq);
        }
        serialPrintf("{\"ok\":true,\"freq\":%lu}\n", currentFreq);

    } else if (strcmp(cmd, "MEASURE") == 0) {
        float vmag, vref, vphs;
        measure(vmag, vref, vphs);
        serialPrintf("{\"freq\":%lu,\"vmag\":%.4f,\"vref\":%.4f,\"vphs\":%.4f}\n",
                     currentFreq, vmag, vref, vphs);

    } else if (strcmp(cmd, "SWEEP") == 0) {
        uint32_t fStart, fStop, steps, dwell;
        if (sscanf(line, "SWEEP %lu %lu %lu %lu", &fStart, &fStop, &steps, &dwell) != 4) {
            Serial.println("{\"error\":\"SWEEP usage: SWEEP start stop steps dwell_ms\"}");
            return;
        }
        serialPrintf("{\"sweep_start\":true,\"steps\":%lu}\n", steps);
        for (uint32_t i = 0; i <= steps; i++) {
            uint32_t f = fStart + (uint32_t)((uint64_t)(fStop - fStart) * i / steps);
            dds.setFrequency(f);
            delay(dwell);
            float vmag, vref, vphs;
            measure(vmag, vref, vphs);
            serialPrintf("{\"i\":%lu,\"freq\":%lu,\"vmag\":%.4f,\"vref\":%.4f,\"vphs\":%.4f}\n",
                         i, f, vmag, vref, vphs);
        }
        currentFreq = fStop;
        Serial.println("{\"sweep_done\":true}");

    } else if (strcmp(cmd, "GAIN") == 0) {
        int g = 2;
        sscanf(line, "GAIN %d", &g);
        const ADS1115_RANGE gains[] = {
            ADS1115_RANGE_6144, ADS1115_RANGE_4096, ADS1115_RANGE_2048,
            ADS1115_RANGE_1024, ADS1115_RANGE_0512, ADS1115_RANGE_0256
        };
        if (g >= 0 && g <= 5) {
            adsGain = gains[g];
            adc.setVoltageRange_mV(adsGain);
        }
        serialPrintf("{\"ok\":true,\"gain\":%d}\n", g);

    } else if (strcmp(cmd, "RANGE") == 0) {
        int r = 0;
        sscanf(line, "RANGE %d", &r);
        setRange((uint8_t)r);
        serialPrintf("{\"ok\":true,\"range\":%u}\n", currentRange);

    } else if (strcmp(cmd, "SCAN") == 0) {
        i2cScan();

    } else if (strcmp(cmd, "PING") == 0) {
        Serial.println("{\"pong\":true}");

    } else {
        serialPrintf("{\"error\":\"unknown command: %s\"}\n", cmd);
    }
}

void setup() {
    Serial.begin(115200);
    pinMode(RANGE0_PIN, OUTPUT);
    pinMode(RANGE1_PIN, OUTPUT);
    pinMode(RANGE2_PIN, OUTPUT);
    setRange(0);
    Wire.begin(); // I2C0: GP4=SDA, GP5=SCL (mbed default pro Pico)
    i2cScan();
    dds.begin();
    dds.setFrequency(currentFreq);
    setupADC();
    Serial.println("{\"ready\":true,\"device\":\"pico-impedance-analyzer\"}");
}

static char rxBuf[128];
static uint8_t rxPos = 0;

void loop() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (rxPos > 0) {
                rxBuf[rxPos] = '\0';
                handleCommand(rxBuf);
                rxPos = 0;
            }
        } else if (rxPos < sizeof(rxBuf) - 1) {
            rxBuf[rxPos++] = c;
        }
    }
}
