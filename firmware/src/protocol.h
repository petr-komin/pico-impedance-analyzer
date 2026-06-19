#pragma once
// Serial protocol (115200 baud, newline-terminated ASCII commands)
//
// PC -> RP2040:
//   PING
//   FREQ <hz>
//   MEASURE
//   SWEEP <start_hz> <stop_hz> <steps> <dwell_ms>
//   GAIN <0..5>   (0=±6144mV, 1=±4096mV, 2=±2048mV, 3=±1024mV, 4=±512mV, 5=±256mV)
//
// RP2040 -> PC:  newline-terminated JSON objects
