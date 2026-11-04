#include <Arduino.h>

#include "adt7310.h"
#include "loads.h"
#include "pins.h"

#define FW_VERSION "ldo-ctrl 1.0"

constexpr uint32_t TELEMETRY_MS = 50;
constexpr uint32_t TEMP_MS = 250;
constexpr uint32_t WATCHDOG_MS = 2000;

// ADC sums over one telemetry frame, in READ_PINS order.
static uint32_t adcSum[7];
static uint32_t adcCount = 0;
static uint16_t tempRaw = 0;
static uint8_t adtId = 0;

static uint32_t lastTelemetry = 0;
static uint32_t lastTemp = 0;
static uint32_t lastRx = 0;

static char line[128];
static uint8_t lineLen = 0;

static void sampleAdc() {
  for (uint8_t i = 0; i < 7; i++) {
    // MD sits behind 100k, so a throwaway read lets the sample cap settle.
    if (READ_PINS[i] == PIN_MD) analogRead(PIN_MD);
    adcSum[i] += analogRead(READ_PINS[i]);
  }
  adcCount++;
}

static void sendTelemetry() {
  char buf[460];
  float n = adcCount ? (float)adcCount : 1.0f;
  int len = snprintf(buf, sizeof(buf),
                     "{\"tel\":1,\"ms\":%lu,\"adc\":[%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f],\"n\":%lu,"
                     "\"temp\":%u,\"vg\":%u,\"msel\":%d,\"pulse\":%d,\"phz\":%.3f,\"pduty\":%.1f,"
                     "\"mdsq\":%d,\"mhz\":%.3f,\"step\":%u,\"sup\":%d,\"shold\":%lu,\"lim\":%u,\"estop\":%d,"
                     "\"why\":\"%s\"}\n",
                     (unsigned long)millis(), adcSum[0] / n, adcSum[1] / n, adcSum[2] / n, adcSum[3] / n,
                     adcSum[4] / n, adcSum[5] / n, adcSum[6] / n, (unsigned long)adcCount, tempRaw,
                     loadMask(), mdSelLevel(), pulseOn(), pulseHz(), pulseDuty(), mdsqOn(), mdsqHz(), stepPhase(),
                     stepUpDir(), (unsigned long)stepHoldMs(), activeLimitTenths() / 10, estopLatched(),
                     estopReason());
  if (len > 0) Serial.write(buf, min(len, (int)sizeof(buf) - 1));
  for (auto &s : adcSum) s = 0;
  adcCount = 0;
}

static void reply(const char *id, const char *err) {
  if (err)
    Serial.printf("{\"ack\":%s,\"ok\":false,\"err\":\"%s\"}\n", id, err);
  else
    Serial.printf("{\"ack\":%s,\"ok\":true}\n", id);
}

static void handleLine(char *s) {
  char *id = strtok(s, " ");
  char *cmd = strtok(nullptr, " ");
  char *a1 = strtok(nullptr, " ");
  char *a2 = strtok(nullptr, " ");
  if (!id || !cmd) return;
  lastRx = millis();

  if (!strcmp(cmd, "HB")) return reply(id, nullptr);
  if (!strcmp(cmd, "INFO")) {
    Serial.printf("{\"ack\":%s,\"ok\":true,\"fw\":\"%s\",\"loads\":[%.1f,%.1f,%.1f,%.1f,%.1f],"
                  "\"lim\":%u,\"lim_mdsq\":%u,\"adt_id\":%u}\n",
                  id, FW_VERSION, LOAD_TENTHS_MA[0] / 10.0, LOAD_TENTHS_MA[1] / 10.0,
                  LOAD_TENTHS_MA[2] / 10.0, LOAD_TENTHS_MA[3] / 10.0, LOAD_TENTHS_MA[4] / 10.0,
                  LIMIT_TENTHS_MA / 10, LIMIT_MDSQ_TENTHS_MA / 10, adtId);
    return;
  }
  if (!strcmp(cmd, "ESTOP")) {
    safeState("e-stop");
    return reply(id, nullptr);
  }
  if (!strcmp(cmd, "RESET")) {
    clearEstop();
    return reply(id, nullptr);
  }
  if (!strcmp(cmd, "LOAD") && a1) return reply(id, setMask((uint8_t)atoi(a1)));
  if (!strcmp(cmd, "TG") && a1 && a2) {
    int n = atoi(a1);
    if (n < 0 || n > 4) return reply(id, "TG must be 0 to 4");
    uint8_t m = loadMask();
    m = atoi(a2) ? (m | (1 << n)) : (m & ~(1 << n));
    return reply(id, setMask(m));
  }
  if (!strcmp(cmd, "STEP") && a1) {
    uint32_t hold = a2 ? (uint32_t)atol(a2) : 1000;
    if (!strcmp(a1, "UP")) return reply(id, stepStart(true, hold));
    if (!strcmp(a1, "DOWN")) return reply(id, stepStart(false, hold));
  }
  if (!strcmp(cmd, "PULSE") && a1) {
    if (!strcmp(a1, "OFF")) return reply(id, pulseStop());
    return reply(id, pulseStart(atof(a1), a2 ? atof(a2) : 50.0f));
  }
  if (!strcmp(cmd, "MD") && a1) return reply(id, setMd(atoi(a1)));
  if (!strcmp(cmd, "MDSQ") && a1) {
    if (!strcmp(a1, "OFF")) return reply(id, mdsqStop());
    return reply(id, mdsqStart(atof(a1)));
  }
  reply(id, "unknown command");
}

static void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen) {
        line[lineLen] = 0;
        handleLine(line);
        lineLen = 0;
      }
    } else if (lineLen < sizeof(line) - 1) {
      line[lineLen++] = c;
    }
  }
}

static void watchdog() {
  if (!anythingActive()) return;
  if (!Serial.dtr())
    safeState("watchdog: USB port closed");
  else if (millis() - lastRx > WATCHDOG_MS)
    safeState("watchdog: no heartbeat for 2 s");
}

void setup() {
  loadsBegin();
  for (uint8_t p : READ_PINS) pinMode(p, INPUT_DISABLE);
  analogReadResolution(12);
  analogReadAveraging(8);
  Serial.begin(115200);
  adtBegin();
  adtId = adtReadId();
  lastRx = millis();
}

void loop() {
  readSerial();
  watchdog();
  stepTick();
  sampleAdc();
  uint32_t now = millis();
  if (now - lastTemp >= TEMP_MS) {
    lastTemp = now;
    tempRaw = adtReadRaw();
  }
  if (now - lastTelemetry >= TELEMETRY_MS) {
    lastTelemetry = now;
    if (Serial.dtr()) {
      sendTelemetry();
    } else {
      for (auto &s : adcSum) s = 0;
      adcCount = 0;
    }
  }
}
