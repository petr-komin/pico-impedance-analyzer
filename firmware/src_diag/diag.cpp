#include <Arduino.h>
#include <Wire.h>

#define SDA_PIN 4
#define SCL_PIN 5

void i2cScan() {
    Serial.println("=== I2C scan ===");
    uint8_t found = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.printf("  0x%02X (%3d)", addr, addr);
            // pojmenuj zname adresy
            if (addr == 0x48) Serial.print(" <- ADS1115 (ADDR=GND)");
            if (addr == 0x49) Serial.print(" <- ADS1115 (ADDR=VDD)");
            if (addr == 0x4A) Serial.print(" <- ADS1115 (ADDR=SDA)");
            if (addr == 0x4B) Serial.print(" <- ADS1115 (ADDR=SCL)");
            Serial.println();
            found++;
        }
    }
    if (found == 0) {
        Serial.println("  Zadne zarizeni nenalezeno!");
    }
    Serial.printf("  Celkem: %d zarizeni\n", found);
    Serial.println("================");
}

void setup() {
    Serial.begin(115200);
    delay(2000); // cas na otevreni terminalu

    Wire.setSDA(SDA_PIN);
    Wire.setSCL(SCL_PIN);
    Wire.begin();

    Serial.println("Pico Impedance Analyzer - DIAGNOSTIKA");
    Serial.printf("I2C: SDA=GP%d  SCL=GP%d\n", SDA_PIN, SCL_PIN);
    i2cScan();
}

void loop() {
    // opakuj scan kazdych 5 sekund, nebo kdyz pride 's' po serialu
    if (Serial.available()) {
        char c = Serial.read();
        if (c == 's' || c == 'S') {
            i2cScan();
        }
    }
    delay(5000);
    i2cScan();
}
