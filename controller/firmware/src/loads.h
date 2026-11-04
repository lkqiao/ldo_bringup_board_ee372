#pragma once
#include <Arduino.h>

// Nominal branch currents at VOUT = 1.0 V, in tenths of a mA (bring-up plan p5).
constexpr uint16_t LOAD_TENTHS_MA[5] = {187, 10, 150, 100, 50};
constexpr uint16_t LIMIT_TENTHS_MA = 200;       // plan p4, never above 20 mA
constexpr uint16_t LIMIT_MDSQ_TENTHS_MA = 100;  // plan p23, 10 mA during mode switching

constexpr uint8_t TG0 = 1 << 0;
constexpr uint8_t TG1 = 1 << 1;

void loadsBegin();
uint16_t loadTenths(uint8_t mask);
uint16_t activeLimitTenths();

// Each returns nullptr on success or an error message.
const char *setMask(uint8_t mask);
// Timed step sequence. Loads off, first level for holdMs, second level for
// holdMs, then loads off. Up is 1 -> 19.7 mA, down is 19.7 -> 1 mA. The
// level change between the two holds is a single edge on VG0.
const char *stepStart(bool up, uint32_t holdMs);
void stepTick();  // call from loop()
uint8_t stepPhase();  // 0 idle, 1 first hold, 2 second hold
bool stepUpDir();
uint32_t stepHoldMs();
const char *pulseStart(float hz, float duty);
const char *pulseStop();
const char *setMd(int md);
const char *mdsqStart(float hz);
const char *mdsqStop();

void safeState(const char *why);  // every output low, latch the e-stop
void clearEstop();

uint8_t loadMask();
bool pulseOn();
float pulseHz();
float pulseDuty();
bool mdsqOn();
float mdsqHz();
bool mdSelLevel();
bool estopLatched();
const char *estopReason();
bool anythingActive();
