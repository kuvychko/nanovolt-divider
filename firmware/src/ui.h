// Touchscreen front panel (320 x 240 landscape): status bar, output banner, range / polarity /
// factor / temperature readout, and five buttons. Redraws whenever the instrument state changes,
// whether the change came from a touch or from SCPI.
#pragma once
#include <Print.h>

namespace ui {

void begin();  // runs the touch calibration if the screen is held at boot
void loop();

void requestTouchCal();       // DIAG:TOUCh:CAL - runs on the next loop()
void invertDisplay(bool on);  // DIAG:DISP:INV - for identifying the panel variant
void printTouch(Print &out);  // DIAG:TOUCh? - raw and mapped coordinates of the current touch

}  // namespace ui
