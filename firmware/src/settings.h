// Persistent instrument settings (NVS namespace "nvd"). Calibration lives separately (calibration.h).
#pragma once
#include <stdint.h>

namespace settings {

struct TouchCal {
  bool valid;
  bool swapXY;             // raw X channel runs along the screen's Y axis
  int16_t x0, x1, y0, y1;  // raw readings at screen x = 0 / 319 and y = 0 / 239
};

struct Settings {
  bool bootSafe;  // pulse the safe state at boot (spec rule 1). OFF only for first power-on.
  uint16_t pulseMs;
  uint16_t gapMs;
  TouchCal touch;
};

void begin();
Settings &get();
bool save();

}  // namespace settings
