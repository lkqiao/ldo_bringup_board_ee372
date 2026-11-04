#include "loads.h"

#include "pins.h"

static IntervalTimer pulseTimer;
static IntervalTimer mdTimer;

static volatile uint8_t mask = 0;
static volatile bool pulseRunning = false;
static volatile bool pulseLevel = false;
static volatile uint32_t pulseHighUs = 0;
static volatile uint32_t pulseLowUs = 0;
static float pulseFreq = 0;
static float pulseDutyCycle = 0;

static volatile bool mdsqRunning = false;
// MD defaults to 0 (low power). MD_SEL high turns Q6 on and holds MD at 0 V.
static constexpr bool MD_SEL_DEFAULT = HIGH;
static volatile bool mdSel = MD_SEL_DEFAULT;
static float mdsqFreq = 0;

static bool estop = false;
static const char *estopWhy = "";

static uint8_t stepState = 0;
static bool stepUp = true;
static uint32_t stepHold = 1000;
static uint32_t stepT0 = 0;

static void writeMask(uint8_t m) {
  for (uint8_t i = 0; i < 5; i++) digitalWriteFast(PIN_VG[i], (m >> i) & 1);
  mask = m;
}

static void writeMdSel(bool level) {
  digitalWriteFast(PIN_MD_SEL, level);
  mdSel = level;
}

// A PIT reload takes effect one period late, so the ISR loads the length of
// the level after the one it just set.
static void pulseIsr() {
  pulseLevel = !pulseLevel;
  digitalWriteFast(PIN_VG[0], pulseLevel);
  pulseTimer.update(pulseLevel ? pulseLowUs : pulseHighUs);
}

static void mdIsr() { writeMdSel(!mdSel); }

void loadsBegin() {
  for (uint8_t i = 0; i < 5; i++) {
    digitalWriteFast(PIN_VG[i], LOW);
    pinMode(PIN_VG[i], OUTPUT);
  }
  digitalWriteFast(PIN_MD_SEL, MD_SEL_DEFAULT);
  pinMode(PIN_MD_SEL, OUTPUT);
  writeMask(0);
  writeMdSel(MD_SEL_DEFAULT);
}

uint16_t loadTenths(uint8_t m) {
  uint16_t sum = 0;
  for (uint8_t i = 0; i < 5; i++)
    if ((m >> i) & 1) sum += LOAD_TENTHS_MA[i];
  return sum;
}

uint16_t activeLimitTenths() { return mdsqRunning ? LIMIT_MDSQ_TENTHS_MA : LIMIT_TENTHS_MA; }

static char err[96];

static const char *checkMask(uint8_t m) {
  if (m > 0x1F) return "mask must be 0 to 31";
  uint16_t sum = loadTenths(m);
  uint16_t lim = activeLimitTenths();
  if (sum > lim) {
    snprintf(err, sizeof(err), "loads sum to %u.%u mA, over the %u mA limit%s", sum / 10, sum % 10,
             lim / 10, mdsqRunning ? " during the MD square wave" : "");
    return err;
  }
  return nullptr;
}

const char *setMask(uint8_t m) {
  if (estop) return "e-stop latched, send RESET first";
  if (stepState) return "wait for the step sequence to finish";
  if (pulseRunning) return "stop the VG0 pulse first";
  if (const char *e = checkMask(m)) return e;
  writeMask(m);
  return nullptr;
}

const char *stepStart(bool up, uint32_t holdMs) {
  if (estop) return "e-stop latched, send RESET first";
  if (stepState) return "step sequence already running";
  if (pulseRunning) return "stop the VG0 pulse first";
  if (holdMs < 50 || holdMs > 60000) return "hold must be 0.05 to 60 s";
  if (const char *e = checkMask(TG1 | TG0)) return e;
  stepUp = up;
  stepHold = holdMs;
  writeMask(0);
  writeMask(up ? TG1 : (TG1 | TG0));
  stepState = 1;
  stepT0 = millis();
  return nullptr;
}

void stepTick() {
  if (!stepState || millis() - stepT0 < stepHold) return;
  if (stepState == 1) {
    digitalWriteFast(PIN_VG[0], stepUp ? HIGH : LOW);  // the measured edge
    mask = stepUp ? (TG1 | TG0) : TG1;
    stepState = 2;
    stepT0 = millis();
  } else {
    writeMask(0);
    stepState = 0;
  }
}

uint8_t stepPhase() { return stepState; }
bool stepUpDir() { return stepUp; }
uint32_t stepHoldMs() { return stepHold; }

const char *pulseStart(float hz, float duty) {
  if (estop) return "e-stop latched, send RESET first";
  if (pulseRunning) return "VG0 pulse already running";
  if (stepState) return "wait for the step sequence to finish";
  if (mdsqRunning) return "stop the MD square wave first";
  if (mask != TG1) return "the VG0 pulse starts from 1 mA (TG1 only)";
  if (!(hz >= 0.1f && hz <= 1000.0f)) return "pulse frequency must be 0.1 to 1000 Hz";
  if (!(duty >= 5.0f && duty <= 95.0f)) return "pulse duty must be 5 to 95 %";
  if (const char *e = checkMask(TG1 | TG0)) return e;
  float period = 1e6f / hz;
  pulseHighUs = (uint32_t)(period * duty / 100.0f);
  pulseLowUs = (uint32_t)(period - pulseHighUs);
  pulseFreq = hz;
  pulseDutyCycle = duty;
  pulseLevel = false;
  digitalWriteFast(PIN_VG[0], LOW);
  pulseRunning = true;
  pulseTimer.begin(pulseIsr, pulseLowUs);
  pulseTimer.update(pulseHighUs);
  return nullptr;
}

const char *pulseStop() {
  if (!pulseRunning) return nullptr;
  pulseTimer.end();
  digitalWriteFast(PIN_VG[0], LOW);
  pulseRunning = false;
  pulseLevel = false;
  pulseFreq = 0;
  pulseDutyCycle = 0;
  return nullptr;
}

const char *setMd(int md) {
  if (md != 0 && md != 1) return "MD must be 0 or 1";
  if (mdsqRunning) return "stop the MD square wave first";
  writeMdSel(md == 0);  // MD = 1 (HP) is MD_SEL low
  return nullptr;
}

const char *mdsqStart(float hz) {
  if (estop) return "e-stop latched, send RESET first";
  if (mdsqRunning) return "MD square wave already running";
  if (pulseRunning) return "stop the VG0 pulse first";
  if (stepState) return "wait for the step sequence to finish";
  if (!(hz >= 0.1f && hz <= 1000.0f)) return "MD square wave must be 0.1 to 1000 Hz";
  uint16_t sum = loadTenths(mask);
  if (sum > LIMIT_MDSQ_TENTHS_MA) {
    snprintf(err, sizeof(err), "loads sum to %u.%u mA, the MD square wave needs 10 mA or less",
             sum / 10, sum % 10);
    return err;
  }
  mdsqFreq = hz;
  mdsqRunning = true;
  mdTimer.begin(mdIsr, 0.5e6f / hz);
  return nullptr;
}

const char *mdsqStop() {
  if (!mdsqRunning) return nullptr;
  mdTimer.end();
  mdsqRunning = false;
  mdsqFreq = 0;
  writeMdSel(MD_SEL_DEFAULT);
  return nullptr;
}

void safeState(const char *why) {
  stepState = 0;
  pulseStop();
  mdsqStop();
  writeMask(0);
  writeMdSel(MD_SEL_DEFAULT);
  if (!estop) estopWhy = why;
  estop = true;
}

void clearEstop() {
  estop = false;
  estopWhy = "";
}

uint8_t loadMask() { return mask; }
bool pulseOn() { return pulseRunning; }
float pulseHz() { return pulseFreq; }
float pulseDuty() { return pulseDutyCycle; }
bool mdsqOn() { return mdsqRunning; }
float mdsqHz() { return mdsqFreq; }
bool mdSelLevel() { return mdSel; }
bool estopLatched() { return estop; }
const char *estopReason() { return estopWhy; }
bool anythingActive() {
  return mask != 0 || pulseRunning || mdsqRunning || mdSel != MD_SEL_DEFAULT || stepState;
}
