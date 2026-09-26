#include "touch.h"

#include <Arduino.h>

#include "pins.h"
#include "settings.h"

namespace touch {

namespace {

constexpr uint8_t CMD_X = 0xD0, CMD_Y = 0x90, CMD_Z1 = 0xB0, CMD_Z2 = 0xC0;
constexpr int Z_MIN = 300;  // pressure threshold; below it a reading is unreliable
constexpr int SAMPLES = 5;

// Default mapping for display rotation 3, overwritten by the on-screen calibration (DIAG:TOUCh:CAL,
// or touch at boot). Rotation 3 is rotation 1 turned 180 degrees, so both axes run high -> low.
constexpr settings::TouchCal DEFAULT_CAL = {true, false, 3700, 200, 3800, 240};

uint16_t transfer(uint8_t cmd) {
  for (int i = 7; i >= 0; i--) {
    digitalWrite(pins::TOUCH_MOSI, (cmd >> i) & 1);
    digitalWrite(pins::TOUCH_CLK, HIGH);
    delayMicroseconds(1);
    digitalWrite(pins::TOUCH_CLK, LOW);
    delayMicroseconds(1);
  }
  uint16_t v = 0;
  for (int i = 11; i >= 0; i--) {
    digitalWrite(pins::TOUCH_CLK, HIGH);
    delayMicroseconds(1);
    digitalWrite(pins::TOUCH_CLK, LOW);
    delayMicroseconds(1);
    v |= uint16_t(digitalRead(pins::TOUCH_MISO)) << i;
  }
  return v;
}

int16_t mapAxis(int16_t raw, int16_t r0, int16_t r1, int16_t size) {
  if (r1 == r0) return 0;
  const long v = long(raw - r0) * (size - 1) / (r1 - r0);
  return constrain(v, 0, size - 1);
}

void sortSmall(int16_t *a, int n) {
  for (int i = 1; i < n; i++)
    for (int j = i; j > 0 && a[j - 1] > a[j]; j--) std::swap(a[j - 1], a[j]);
}

}  // namespace

void begin() {
  pinMode(pins::TOUCH_CLK, OUTPUT);
  pinMode(pins::TOUCH_MOSI, OUTPUT);
  pinMode(pins::TOUCH_CS, OUTPUT);
  pinMode(pins::TOUCH_MISO, INPUT);
  pinMode(pins::TOUCH_IRQ, INPUT);
  digitalWrite(pins::TOUCH_CS, HIGH);
  digitalWrite(pins::TOUCH_CLK, LOW);
}

bool pressed() { return digitalRead(pins::TOUCH_IRQ) == LOW; }

bool readRaw(int16_t &x, int16_t &y) {
  if (!pressed()) return false;
  int16_t xs[SAMPLES], ys[SAMPLES];
  digitalWrite(pins::TOUCH_CS, LOW);
  const int z = int(transfer(CMD_Z1)) + 4095 - int(transfer(CMD_Z2));
  for (int i = 0; i < SAMPLES; i++) {
    xs[i] = transfer(CMD_X);
    ys[i] = transfer(CMD_Y);
  }
  transfer(0x80);  // power down between conversions, PENIRQ enabled
  digitalWrite(pins::TOUCH_CS, HIGH);
  if (z < Z_MIN) return false;
  sortSmall(xs, SAMPLES);
  sortSmall(ys, SAMPLES);
  x = xs[SAMPLES / 2];
  y = ys[SAMPLES / 2];
  return true;
}

bool read(int16_t &sx, int16_t &sy) {
  int16_t rx, ry;
  if (!readRaw(rx, ry)) return false;
  const settings::TouchCal &c = settings::get().touch.valid ? settings::get().touch : DEFAULT_CAL;
  const int16_t alongX = c.swapXY ? ry : rx;
  const int16_t alongY = c.swapXY ? rx : ry;
  sx = mapAxis(alongX, c.x0, c.x1, 320);
  sy = mapAxis(alongY, c.y0, c.y1, 240);
  return true;
}

}  // namespace touch
