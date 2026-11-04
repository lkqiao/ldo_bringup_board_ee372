#pragma once
#include <Arduino.h>

// Pin map from the netlist of the EE372B bring-up board (U2, Teensy 4.1).

// Outputs. None of these reach a chip pin.
constexpr uint8_t PIN_VG[5] = {2, 3, 4, 5, 6};  // VG0..VG4 through R22..R26 to Q1..Q5 gates
constexpr uint8_t PIN_MD_SEL = 7;               // Q6 gate through J9; high pulls MD low
constexpr uint8_t ADT_CS = 10;              // ADT7310 CS

// SPI bus to the ADT7310, run by the SPI library.
constexpr uint8_t ADT_MOSI = 11;
constexpr uint8_t ADT_MISO = 12;
constexpr uint8_t ADT_SCK = 13;

// Read-only analog pins. Set to INPUT_DISABLE once in setup() and never changed.
constexpr uint8_t PIN_ISENSE_OUT = 15;  // A1, U4 output, current through R3
constexpr uint8_t PIN_ISENSE_IN = 16;   // A2, U3 output, current through R4
constexpr uint8_t PIN_VOUT_B = 17;      // A3, R48 to SHUNT_OUT_B (VOUT after R3)
constexpr uint8_t PIN_VOUT_LDO = 18;    // A4, R47 to SHUNT_OUT_A (VOUT_LDO)
constexpr uint8_t PIN_VDD_LDO = 19;     // A5, R46 to SHUNT_IN_B (VDD_LDO)
constexpr uint8_t PIN_VDD_A = 20;       // A6, R45 to SHUNT_IN_A (VDD at J1)
constexpr uint8_t PIN_MD = 23;          // A9, R51 to MD

constexpr uint8_t READ_PINS[7] = {PIN_ISENSE_OUT, PIN_ISENSE_IN, PIN_VOUT_B, PIN_VOUT_LDO,
                                  PIN_VDD_LDO,    PIN_VDD_A,     PIN_MD};
constexpr uint8_t DRIVEN_PINS[10] = {PIN_VG[0],  PIN_VG[1],    PIN_VG[2],    PIN_VG[3],   PIN_VG[4],
                                     PIN_MD_SEL, ADT_CS, ADT_MOSI, ADT_MISO, ADT_SCK};

constexpr bool pinsOverlap() {
  for (uint8_t r : READ_PINS)
    for (uint8_t d : DRIVEN_PINS)
      if (r == d) return true;
  return false;
}
static_assert(!pinsOverlap(), "a read pin is also a driven pin");
