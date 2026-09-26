#include "settings.h"

#include <Preferences.h>

namespace settings {

namespace {
// The touch calibration maps into screen coordinates, so it belongs to one display rotation. The
// key names the rotation: a calibration taken at another rotation is ignored rather than misused.
constexpr const char *TOUCH_KEY = "touch_r3";
Settings g = {true, 20, 20, {false, false, 0, 0, 0, 0}};
constexpr const char *NVS_NS = "nvd";
}  // namespace

void begin() {
  Preferences p;
  p.begin(NVS_NS, false);  // read-write: creates the namespace on first boot instead of logging NOT_FOUND
  g.bootSafe = p.getBool("boot_safe", g.bootSafe);
  g.pulseMs = p.getUShort("pulse_ms", g.pulseMs);
  g.gapMs = p.getUShort("gap_ms", g.gapMs);
  if (p.isKey(TOUCH_KEY) && p.getBytesLength(TOUCH_KEY) == sizeof(TouchCal))
    p.getBytes(TOUCH_KEY, &g.touch, sizeof(TouchCal));
  p.end();
}

Settings &get() { return g; }

bool save() {
  Preferences p;
  if (!p.begin(NVS_NS, false)) return false;
  bool ok = p.putBool("boot_safe", g.bootSafe) > 0;
  ok &= p.putUShort("pulse_ms", g.pulseMs) > 0;
  ok &= p.putUShort("gap_ms", g.gapMs) > 0;
  ok &= p.putBytes(TOUCH_KEY, &g.touch, sizeof(TouchCal)) == sizeof(TouchCal);
  p.end();
  return ok;
}

}  // namespace settings
