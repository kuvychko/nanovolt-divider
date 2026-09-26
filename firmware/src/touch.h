// XPT2046 resistive touch, bit-banged on its own pins (pins.h).
//
// It is bit-banged rather than put on an SPI host because the only free host (VSPI) is the SD
// card's, and the SD card's SCK is also I2C SCL. A few hundred microseconds per sample is plenty
// for buttons.
#pragma once
#include <stdint.h>

namespace touch {

void begin();
bool pressed();  // PENIRQ low
// Averaged raw 12-bit readings; false if the panel is not (firmly) pressed.
bool readRaw(int16_t &x, int16_t &y);
// Screen coordinates (landscape, 320 x 240) through the stored calibration, or a default one.
bool read(int16_t &sx, int16_t &sy);

}  // namespace touch
