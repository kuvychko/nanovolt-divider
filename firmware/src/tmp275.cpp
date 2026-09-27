#include "tmp275.h"

#include <Arduino.h>
#include <math.h>

#include "bus.h"
#include "pins.h"

namespace tmp275 {

namespace {

constexpr uint8_t REG_TEMP = 0x00;
constexpr uint8_t REG_CONFIG = 0x01;
constexpr uint8_t CONFIG_12BIT = 0x60;  // R1:R0 = 11, 220 ms conversion, continuous

bool g_present = false;
bool g_valid = false;
float g_celsius = NAN;
uint32_t g_last = 0;

#ifdef NVD_SIM_BOARD
bool configure() { return true; }
bool readRaw(uint16_t &raw) {
  // 23.5 C with a slow +/-0.25 C wander, quantised to 1/16 C like the real part.
  const float t = 23.5f + 0.25f * sinf(millis() / 60000.0f);
  raw = uint16_t(int16_t(lroundf(t * 16)) << 4);
  return true;
}
#else
bool configure() {
  uint8_t cfg;
  return bus::write8(TMP275_ADDR, REG_CONFIG, CONFIG_12BIT) &&
         bus::read8(TMP275_ADDR, REG_CONFIG, cfg) && (cfg & 0x7F) == CONFIG_12BIT;
}
bool readRaw(uint16_t &raw) { return bus::read16(TMP275_ADDR, REG_TEMP, raw); }
#endif

}  // namespace

bool init() {
  g_present = configure();
  g_valid = false;
  g_celsius = NAN;
  // First read 300 ms from now: the first 12-bit conversion takes 220 ms, and the regular
  // once-a-second cadence would otherwise leave the first second with no temperature.
  g_last = millis() - 700;
  return g_present;
}

void poll() {
  const uint32_t now = millis();
  if (!g_present) {
    if (now - g_last >= 5000) init();
    return;
  }
  if (now - g_last < 1000) return;
  g_last = now;
  uint16_t raw;
  if (readRaw(raw)) {
    g_celsius = int16_t(raw) / 256.0f;  // left-justified 12-bit, 1/16 C per LSB
    g_valid = true;
  } else {
    g_present = g_valid = false;
    g_celsius = NAN;
  }
}

bool present() { return g_present; }
bool valid() { return g_valid; }
float celsius() { return g_valid ? g_celsius : NAN; }

}  // namespace tmp275
