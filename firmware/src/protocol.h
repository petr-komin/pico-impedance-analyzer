#pragma once
// Serial protocol (115200 baud, newline-terminated ASCII commands)
//
// ADC wiring: A3=VMAG, A2=VREF, A1=VPHS  (AD8302)
//
// PC -> RP2040:
//   PING
//   FREQ <hz>
//   MEASURE
//   SWEEP <start_hz> <stop_hz> <steps> <dwell_ms>
//   GAIN <0..5>   (0=±6144mV, 1=±4096mV, 2=±2048mV, 3=±1024mV, 4=±512mV, 5=±256mV)
//   RANGE <0..2>  (prepne relé referencniho rezistoru Rref)
//
// RP2040 -> PC:  newline-terminated JSON objects
//   {"freq":<hz>,"vmag":<V>,"vref":<V>,"vphs":<V>}  — MEASURE / sweep point
