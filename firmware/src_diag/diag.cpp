#include <Arduino.h>
#include <Wire.h>
#include <ADS1115_WE.h>

#define ADS_ADDR 0x48

ADS1115_WE adc(ADS_ADDR);

void i2cScan() {
    Serial.println("=== I2C scan ===");
    uint8_t found = 0;
    char buf[32];
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            snprintf(buf, sizeof(buf), "  0x%02X (%3d)", addr, addr);
            Serial.print(buf);
            if (addr == 0x48) Serial.print(" <- ADS1115 (ADDR=GND)");
            if (addr == 0x49) Serial.print(" <- ADS1115 (ADDR=VDD)");
            if (addr == 0x4A) Serial.print(" <- ADS1115 (ADDR=SDA)");
            if (addr == 0x4B) Serial.print(" <- ADS1115 (ADDR=SCL)");
            Serial.println();
            found++;
        }
    }
    if (found == 0) Serial.println("  Zadne zarizeni nenalezeno!");
    snprintf(buf, sizeof(buf), "  Celkem: %d zarizeni", found);
    Serial.println(buf);
    Serial.println("================");
}

void adcRead() {
    char buf[64];
    Serial.println("=== ADS1115 cteni (A0..A3 vs GND, range +-2.048V) ===");
    ADS1115_MUX channels[] = {
        ADS1115_COMP_0_GND, ADS1115_COMP_1_GND,
        ADS1115_COMP_2_GND, ADS1115_COMP_3_GND
    };
    for (int i = 0; i < 4; i++) {
        adc.setCompareChannels(channels[i]);
        adc.startSingleMeasurement();
        while (adc.isBusy()) delayMicroseconds(100);
        float v = adc.getResult_V();
        snprintf(buf, sizeof(buf), "  A%d: %+.4f V", i, v);
        Serial.println(buf);
    }
    Serial.println("=====================================================");
}

void setup() {
    Serial.begin(115200);
    delay(2000);

    Wire.begin();

    Serial.println("Pico Impedance Analyzer - DIAGNOSTIKA");
    Serial.println("Prikazy: s=I2C scan, r=cti ADC, Enter=opakuj ADC");
    Serial.println();

    i2cScan();

    if (adc.init()) {
        adc.setVoltageRange_mV(ADS1115_RANGE_2048);
        adc.setConvRate(ADS1115_128_SPS);
        adc.setMeasureMode(ADS1115_SINGLE);
        Serial.println("ADS1115 OK");
    } else {
        Serial.println("ADS1115 CHYBA - zkontroluj zapojeni");
    }
    Serial.println();
    adcRead();
}

void loop() {
    if (Serial.available()) {
        char c = Serial.read();
        if (c == 's' || c == 'S') {
            i2cScan();
        } else if (c == 'r' || c == 'R' || c == '\n' || c == '\r') {
            adcRead();
        }
    }
}
