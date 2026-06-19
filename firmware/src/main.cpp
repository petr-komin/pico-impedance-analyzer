#include <Arduino.h>
#include <Wire.h>
#include <ADS1115_WE.h>
#include "AD9851.h"
#include "protocol.h"

// AD9851 pins (SPI bit-bang)
#define DDS_DATA_PIN  19
#define DDS_CLK_PIN   18
#define DDS_FQ_UD_PIN 17
#define DDS_RESET_PIN 16

// ADS1115
#define ADS_ADDR  0x48
#define ADS_SDA   4
#define ADS_SCL   5

AD9851 dds(DDS_DATA_PIN, DDS_CLK_PIN, DDS_FQ_UD_PIN, DDS_RESET_PIN);
ADS1115_WE adc(ADS_ADDR);

static uint32_t currentFreq = 1000000UL;
static uint8_t  adsGain = ADS1115_RANGE_2048; // ±2.048 V

void setupADC() {
    // Wire already initialised in setup() before i2cScan()
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

// Returns magnitude voltage (VMAG) and phase voltage (VPHS) from AD8302
void measure(float &vmag, float &vphs) {
    vmag = readChannel(ADS1115_COMP_0_GND); // A0 = VMAG
    vphs = readChannel(ADS1115_COMP_1_GND); // A1 = VPHS
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
        Serial.printf("{\"ok\":true,\"freq\":%lu}\n", currentFreq);

    } else if (strcmp(cmd, "MEASURE") == 0) {
        float vmag, vphs;
        measure(vmag, vphs);
        Serial.printf("{\"freq\":%lu,\"vmag\":%.4f,\"vphs\":%.4f}\n",
                      currentFreq, vmag, vphs);

    } else if (strcmp(cmd, "SWEEP") == 0) {
        // SWEEP <start_hz> <stop_hz> <steps> <dwell_ms>
        uint32_t fStart, fStop, steps;
        uint32_t dwell;
        if (sscanf(line, "SWEEP %lu %lu %lu %lu", &fStart, &fStop, &steps, &dwell) != 4) {
            Serial.println("{\"error\":\"SWEEP usage: SWEEP start stop steps dwell_ms\"}");
            return;
        }
        Serial.printf("{\"sweep_start\":true,\"steps\":%lu}\n", steps);
        for (uint32_t i = 0; i <= steps; i++) {
            uint32_t f = fStart + (uint32_t)((uint64_t)(fStop - fStart) * i / steps);
            dds.setFrequency(f);
            delay(dwell);
            float vmag, vphs;
            measure(vmag, vphs);
            Serial.printf("{\"i\":%lu,\"freq\":%lu,\"vmag\":%.4f,\"vphs\":%.4f}\n",
                          i, f, vmag, vphs);
        }
        currentFreq = fStop;
        Serial.println("{\"sweep_done\":true}");

    } else if (strcmp(cmd, "GAIN") == 0) {
        // GAIN <0..5>  maps to ADS1115 ranges: 6144/4096/2048/1024/512/256 mV
        int g = 2;
        sscanf(line, "GAIN %d", &g);
        const uint8_t gains[] = {
            ADS1115_RANGE_6144, ADS1115_RANGE_4096, ADS1115_RANGE_2048,
            ADS1115_RANGE_1024, ADS1115_RANGE_512,  ADS1115_RANGE_256
        };
        if (g >= 0 && g <= 5) {
            adsGain = gains[g];
            adc.setVoltageRange_mV(adsGain);
        }
        Serial.printf("{\"ok\":true,\"gain\":%d}\n", g);

    } else if (strcmp(cmd, "SCAN") == 0) {
        i2cScan();

    } else if (strcmp(cmd, "PING") == 0) {
        Serial.println("{\"pong\":true}");

    } else {
        Serial.printf("{\"error\":\"unknown command: %s\"}\n", cmd);
    }
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

void setup() {
    Serial.begin(115200);
    Wire.setSDA(ADS_SDA);
    Wire.setSCL(ADS_SCL);
    Wire.begin();
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
