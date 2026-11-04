#pragma once
#include <Arduino.h>

// ADT7310 on SPI, mode 3. Power-up default is 13-bit continuous conversion,
// so 25 C reads 0x0C80 (bring-up plan p5, row 8).
void adtBegin();
uint16_t adtReadRaw();  // 16-bit temperature word, bits 15..3 hold the value
uint8_t adtReadId();
