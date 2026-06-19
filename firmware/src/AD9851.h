#pragma once
#include <Arduino.h>

// AD9851 master clock — adjust if your board uses different crystal/PLL
#define AD9851_CLOCK_HZ 180000000UL

class AD9851 {
public:
    AD9851(uint8_t dataPin, uint8_t clkPin, uint8_t fqUdPin, uint8_t resetPin)
        : _data(dataPin), _clk(clkPin), _fqud(fqUdPin), _rst(resetPin) {}

    void begin() {
        pinMode(_data, OUTPUT);
        pinMode(_clk,  OUTPUT);
        pinMode(_fqud, OUTPUT);
        pinMode(_rst,  OUTPUT);
        reset();
        // Switch to serial load mode: pulse W_CLK then FQ_UD
        pulse(_clk);
        pulse(_fqud);
    }

    void reset() {
        digitalWrite(_rst, HIGH);
        delayMicroseconds(5);
        digitalWrite(_rst, LOW);
    }

    // freq in Hz, phase 0–31 (5 bits, each step = 11.25°)
    void setFrequency(uint32_t freq, uint8_t phase = 0) {
        uint32_t ftw = (uint32_t)(((uint64_t)freq << 32) / AD9851_CLOCK_HZ);
        sendByte(ftw & 0xFF);
        sendByte((ftw >> 8) & 0xFF);
        sendByte((ftw >> 16) & 0xFF);
        sendByte((ftw >> 24) & 0xFF);
        sendByte((phase & 0x1F) << 3); // control word: REFCLK x6 off, phase bits
        pulse(_fqud);
    }

private:
    uint8_t _data, _clk, _fqud, _rst;

    void pulse(uint8_t pin) {
        digitalWrite(pin, HIGH);
        delayMicroseconds(1);
        digitalWrite(pin, LOW);
        delayMicroseconds(1);
    }

    void sendByte(uint8_t b) {
        for (uint8_t i = 0; i < 8; i++) {
            digitalWrite(_data, (b >> i) & 1);
            pulse(_clk);
        }
    }
};
