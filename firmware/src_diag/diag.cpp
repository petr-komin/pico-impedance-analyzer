#include <Arduino.h>
#include <Wire.h>

// mbed Arduino: Wire = I2C0, defaultne GP4 (SDA) + GP5 (SCL) na Pico
// Wire.setSDA/setSCL ani Serial.printf() nejsou v mbed dostupne

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

    if (found == 0) {
        Serial.println("  Zadne zarizeni nenalezeno!");
    }
    snprintf(buf, sizeof(buf), "  Celkem: %d zarizeni", found);
    Serial.println(buf);
    Serial.println("================");
}

void setup() {
    Serial.begin(115200);
    delay(2000);

    Wire.begin();  // GP4=SDA, GP5=SCL jsou default pro I2C0 na Pico

    Serial.println("Pico Impedance Analyzer - DIAGNOSTIKA");
    Serial.println("I2C: SDA=GP4  SCL=GP5 (Wire/I2C0 default)");
    i2cScan();
}

void loop() {
    if (Serial.available()) {
        char c = Serial.read();
        if (c == 's' || c == 'S') {
            i2cScan();
        }
    }
    delay(5000);
    i2cScan();
}
