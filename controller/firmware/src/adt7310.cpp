#include "adt7310.h"

#include <SPI.h>

#include "pins.h"

static const SPISettings ADT_SPI(1000000, MSBFIRST, SPI_MODE3);

void adtBegin() {
  digitalWriteFast(ADT_CS, HIGH);
  pinMode(ADT_CS, OUTPUT);
  SPI.begin();
  // 32 ones resets the serial interface and the registers.
  SPI.beginTransaction(ADT_SPI);
  digitalWriteFast(ADT_CS, LOW);
  for (int i = 0; i < 4; i++) SPI.transfer(0xFF);
  digitalWriteFast(ADT_CS, HIGH);
  SPI.endTransaction();
  delayMicroseconds(600);
}

uint16_t adtReadRaw() {
  SPI.beginTransaction(ADT_SPI);
  digitalWriteFast(ADT_CS, LOW);
  SPI.transfer(0x50);  // read, register 0x02 (temperature value)
  uint16_t hi = SPI.transfer(0x00);
  uint16_t lo = SPI.transfer(0x00);
  digitalWriteFast(ADT_CS, HIGH);
  SPI.endTransaction();
  return (hi << 8) | lo;
}

uint8_t adtReadId() {
  SPI.beginTransaction(ADT_SPI);
  digitalWriteFast(ADT_CS, LOW);
  SPI.transfer(0x58);  // read, register 0x03 (ID)
  uint8_t id = SPI.transfer(0x00);
  digitalWriteFast(ADT_CS, HIGH);
  SPI.endTransaction();
  return id;
}
