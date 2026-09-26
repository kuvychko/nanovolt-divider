// TMP275 on the 1 ohm island (I2C 0x48): 12-bit, continuous conversion, polled once a second.
#pragma once

namespace tmp275 {

bool init();     // configures 12-bit; false if absent
void poll();     // reads when due; re-probes an absent sensor every 5 s
bool present();
bool valid();    // a reading has been taken and the sensor still answers
float celsius(); // last reading; NAN if !valid()

}  // namespace tmp275
