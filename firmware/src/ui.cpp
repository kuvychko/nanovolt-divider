#include "ui.h"

#define LGFX_USE_V1
#include <Arduino.h>
#include <LovyanGFX.hpp>
#include <math.h>

#include "calibration.h"
#include "instrument.h"
#include "mcp23017.h"
#include "pins.h"
#include "scpi.h"
#include "sdstore.h"
#include "settings.h"
#include "tmp275.h"
#include "touch.h"

namespace ui {

namespace {

// ---------------------------------------------------------------- display driver

class LGFX : public lgfx::LGFX_Device {
#if defined(NVD_PANEL_ST7789)
  lgfx::Panel_ST7789 panel_;
#else
  lgfx::Panel_ILI9341 panel_;
#endif
  lgfx::Bus_SPI bus_;
  lgfx::Light_PWM light_;

 public:
  LGFX() {
    {
      auto cfg = bus_.config();
      cfg.spi_host = SPI2_HOST;  // HSPI
      cfg.spi_mode = 0;
      cfg.freq_write = 40000000;
      cfg.freq_read = 16000000;
      cfg.spi_3wire = false;
      cfg.use_lock = true;
      cfg.dma_channel = SPI_DMA_CH_AUTO;
      cfg.pin_sclk = pins::TFT_SCK;
      cfg.pin_mosi = pins::TFT_MOSI;
      cfg.pin_miso = pins::TFT_MISO;
      cfg.pin_dc = pins::TFT_DC;
      bus_.config(cfg);
      panel_.setBus(&bus_);
    }
    {
      auto cfg = panel_.config();
      cfg.pin_cs = pins::TFT_CS;
      cfg.pin_rst = -1;
      cfg.pin_busy = -1;
      cfg.panel_width = 240;
      cfg.panel_height = 320;
      cfg.readable = true;
      cfg.invert = false;
      cfg.rgb_order = false;
      cfg.bus_shared = false;
      panel_.config(cfg);
    }
    {
      auto cfg = light_.config();
      cfg.pin_bl = pins::TFT_BL;
      cfg.invert = false;
      cfg.freq = 12000;
      cfg.pwm_channel = 7;
      light_.config(cfg);
      panel_.setLight(&light_);
    }
    setPanel(&panel_);
  }
};

LGFX lcd;
LGFX_Sprite readout(&lcd);  // drawn off-screen, so the 1 s refresh does not flicker

// ---------------------------------------------------------------- look

constexpr uint16_t rgb(uint8_t r, uint8_t g, uint8_t b) {
  return uint16_t((r & 0xF8) << 8 | (g & 0xFC) << 3 | b >> 3);
}
constexpr uint16_t C_BG = rgb(0, 0, 0);
constexpr uint16_t C_BAR = rgb(28, 32, 40);
constexpr uint16_t C_TEXT = rgb(235, 235, 235);
constexpr uint16_t C_DIM = rgb(120, 125, 135);
constexpr uint16_t C_OK = rgb(60, 200, 90);
constexpr uint16_t C_BAD = rgb(230, 70, 60);
constexpr uint16_t C_WARN = rgb(240, 170, 30);
constexpr uint16_t C_INJECT = rgb(235, 110, 20);
constexpr uint16_t C_ISOLATE = rgb(40, 110, 70);
constexpr uint16_t C_BTN = rgb(45, 55, 75);
constexpr uint16_t C_BTN_ON = rgb(40, 120, 200);
constexpr uint16_t C_BTN_OFF = rgb(30, 32, 36);
constexpr uint16_t C_PRESS = rgb(250, 250, 250);

constexpr int W = 320, H = 240;
constexpr int BAR_H = 20;
constexpr int BANNER_Y = 24, BANNER_H = 46;
constexpr int INFO_Y = 76, READOUT_H = 84;

enum ButtonId { B_R1E5, B_R1E6, B_R1E7, B_POL, B_OUT, B_COUNT };
struct Button {
  int16_t x, y, w, h;
};
constexpr Button BUTTONS[B_COUNT] = {
    {4, 164, 100, 34}, {110, 164, 100, 34}, {216, 164, 100, 34},
    {4, 204, 154, 32}, {162, 204, 154, 32},
};

// ---------------------------------------------------------------- state

uint32_t g_drawn_version = UINT32_MAX;
bool g_drawn_dirty = false, g_drawn_log = false, g_drawn_sd = false, g_drawn_tmp = false;
uint32_t g_last_readout = 0;
bool g_touch_cal_requested = false;
bool g_was_pressed = false;

// ---------------------------------------------------------------- drawing

void text(lgfx::LovyanGFX &g, const char *s, int x, int y, uint16_t fg, uint16_t bg,
          const lgfx::IFont *font, textdatum_t datum) {
  g.setFont(font);
  g.setTextColor(fg, bg);
  g.setTextDatum(datum);
  g.drawString(s, x, y);
}

void text(const char *s, int x, int y, uint16_t fg, uint16_t bg, const lgfx::IFont *font,
          textdatum_t datum) {
  text(lcd, s, x, y, fg, bg, font, datum);
}

void indicator(int x, const char *label, uint16_t color) {
  lcd.fillRoundRect(x, 3, 40, 14, 3, color);
  text(label, x + 20, 10, C_BG, color, &fonts::Font0, middle_center);
}

void drawStatusBar() {
  lcd.fillRect(0, 0, W, BAR_H, C_BAR);
  text("NVD Rev A", 6, 10, C_TEXT, C_BAR, &fonts::Font2, middle_left);
  const instrument::State &s = instrument::state();
  indicator(140, "BOARD", s.board ? C_OK : C_BAD);
  indicator(184, "TEMP", tmp275::present() ? C_OK : C_BAD);
  indicator(228, "SD", sdstore::lastOk() ? C_OK : C_DIM);
  indicator(272, "LOG", sdstore::logging() ? C_WARN : C_DIM);
  g_drawn_log = sdstore::logging();
  g_drawn_sd = sdstore::lastOk();
  g_drawn_tmp = tmp275::present();
}

void drawBanner() {
  const instrument::State &s = instrument::state();
  const char *label;
  const char *sub = nullptr;
  uint16_t bg;
  if (!s.board) {
    label = "NO BOARD";
    sub = "MCP23017 not found";
    bg = C_BTN_OFF;
  } else if (!s.known) {
    label = "STATE UNKNOWN";
    sub = "tap here to reset relays";
    bg = C_BAD;
  } else if (s.inject) {
    label = "INJECT";
    bg = C_INJECT;
  } else {
    label = "ISOLATE";
    bg = C_ISOLATE;
  }
  lcd.fillRect(0, BANNER_Y, W, BANNER_H, bg);
  if (sub) {
    text(label, W / 2, BANNER_Y + 16, C_TEXT, bg, &fonts::FreeSansBold12pt7b, middle_center);
    text(sub, W / 2, BANNER_Y + 37, C_TEXT, bg, &fonts::Font2, middle_center);
  } else {
    text(label, W / 2, BANNER_Y + BANNER_H / 2, C_TEXT, bg, &fonts::FreeSansBold18pt7b,
         middle_center);
  }
}

void drawReadout() {
  const instrument::State &s = instrument::state();
  const float t = tmp275::celsius();
  char b[48];
  readout.fillScreen(C_BG);

  snprintf(b, sizeof(b), "Range %s", instrument::rangeName(s.range));
  text(readout, b, 6, 12, C_TEXT, C_BG, &fonts::Font4, middle_left);
  text(readout, s.polarity == instrument::POL_INV ? "Pol INV" : "Pol NORM", W - 6, 12,
       s.polarity == instrument::POL_INV ? C_WARN : C_TEXT, C_BG, &fonts::Font4, middle_right);

  const double k = cal::factor(s.range, t);
  if (isnan(k)) snprintf(b, sizeof(b), "k  ---");
  else snprintf(b, sizeof(b), "k  %.9e", k);
  text(readout, b, 6, 42, C_TEXT, C_BG, &fonts::Font4, middle_left);

  if (isnan(t)) snprintf(b, sizeof(b), "T  ---");
  else snprintf(b, sizeof(b), "T  %.2f C", t);
  text(readout, b, 6, 70, C_TEXT, C_BG, &fonts::Font2, middle_left);
  if (s.range != instrument::RANGE_NONE) {
    const cal::RangeCal &c = cal::get(s.range);
    snprintf(b, sizeof(b), "Tref %.1f  a %.1e%s", c.t0, c.alpha, cal::dirty() ? "  UNSAVED" : "");
    text(readout, b, W - 6, 70, cal::dirty() ? C_WARN : C_DIM, C_BG, &fonts::Font2, middle_right);
  }
  readout.pushSprite(0, INFO_Y);
  g_drawn_dirty = cal::dirty();
}

void drawButton(ButtonId id, bool pressed = false) {
  const instrument::State &s = instrument::state();
  const bool usable = s.board && s.known;
  const Button &b = BUTTONS[id];
  const char *label = "";
  bool on = false;
  switch (id) {
    case B_R1E5: label = "1E-5"; on = s.range == instrument::RANGE_1E5; break;
    case B_R1E6: label = "1E-6"; on = s.range == instrument::RANGE_1E6; break;
    case B_R1E7: label = "1E-7"; on = s.range == instrument::RANGE_1E7; break;
    case B_POL: label = s.polarity == instrument::POL_INV ? "POL: INV" : "POL: NORM"; break;
    case B_OUT: label = s.inject ? "ISOLATE" : "INJECT"; break;
    default: break;
  }
  uint16_t bg = !usable ? C_BTN_OFF : pressed ? C_PRESS : on ? C_BTN_ON : C_BTN;
  if (usable && id == B_OUT && !pressed) bg = s.inject ? C_ISOLATE : C_INJECT;
  if (usable && id == B_OUT && s.range == instrument::RANGE_NONE) bg = C_BTN_OFF;
  lcd.fillRoundRect(b.x, b.y, b.w, b.h, 5, bg);
  text(label, b.x + b.w / 2, b.y + b.h / 2, usable ? (pressed ? C_BG : C_TEXT) : C_DIM, bg,
       &fonts::Font4, middle_center);
}

void drawAll() {
  drawStatusBar();
  drawBanner();
  drawReadout();
  for (int i = 0; i < B_COUNT; i++) drawButton(ButtonId(i));
  g_drawn_version = instrument::version();
  g_last_readout = millis();
}

// ---------------------------------------------------------------- touch calibration

bool waitTap(int16_t &rx, int16_t &ry, uint32_t timeoutMs) {
  const uint32_t start = millis();
  while (touch::pressed()) {  // wait for release of any earlier touch
    if (millis() - start > timeoutMs) return false;
    delay(10);
  }
  long sx = 0, sy = 0;
  int n = 0;
  while (millis() - start < timeoutMs) {
    int16_t x, y;
    if (touch::readRaw(x, y)) {
      sx += x, sy += y, n++;
      if (n >= 16) break;
    } else if (n) {
      n = 0, sx = sy = 0;  // bounced: start the average again
    }
    delay(10);
  }
  if (n < 16) return false;
  rx = sx / n, ry = sy / n;
  while (touch::pressed()) delay(10);
  return true;
}

void crosshair(int x, int y, uint16_t c) {
  lcd.drawFastHLine(x - 10, y, 21, c);
  lcd.drawFastVLine(x, y - 10, 21, c);
  lcd.drawCircle(x, y, 4, c);
}

void runTouchCal() {
  static const int16_t PX[3] = {20, 300, 20}, PY[3] = {20, 20, 220};
  int16_t rx[3], ry[3];
  lcd.fillScreen(C_BG);
  text("Touch calibration", W / 2, 100, C_TEXT, C_BG, &fonts::Font4, middle_center);
  text("tap each cross with a stylus", W / 2, 130, C_DIM, C_BG, &fonts::Font2, middle_center);
  for (int i = 0; i < 3; i++) {
    crosshair(PX[i], PY[i], C_WARN);
    if (!waitTap(rx[i], ry[i], 30000)) {
      scpi::pushError(-200, "Execution error;touch calibration timed out");
      return;
    }
    crosshair(PX[i], PY[i], C_BG);
  }
  settings::TouchCal c;
  // Moving along screen X (point 0 -> 1): whichever raw channel changes more is the X axis.
  c.swapXY = abs(ry[1] - ry[0]) > abs(rx[1] - rx[0]);
  const float a0 = c.swapXY ? ry[0] : rx[0], a1 = c.swapXY ? ry[1] : rx[1];
  const float b0 = c.swapXY ? rx[0] : ry[0], b2 = c.swapXY ? rx[2] : ry[2];
  const float ax = (a1 - a0) / (PX[1] - PX[0]);  // raw per pixel along X
  const float by = (b2 - b0) / (PY[2] - PY[0]);
  if (fabsf(ax) < 1 || fabsf(by) < 1) {
    scpi::pushError(-200, "Execution error;touch calibration inconsistent");
    return;
  }
  c.x0 = lroundf(a0 - ax * PX[0]);
  c.x1 = lroundf(a0 + ax * (W - 1 - PX[0]));
  c.y0 = lroundf(b0 - by * PY[0]);
  c.y1 = lroundf(b0 + by * (H - 1 - PY[0]));
  c.valid = true;
  settings::get().touch = c;
  if (!settings::save()) scpi::pushError(-200, "Execution error;NVS write failed");
}

// ---------------------------------------------------------------- input

int hit(int16_t x, int16_t y) {
  for (int i = 0; i < B_COUNT; i++) {
    const Button &b = BUTTONS[i];
    if (x >= b.x && x < b.x + b.w && y >= b.y && y < b.y + b.h) return i;
  }
  if (y >= BANNER_Y && y < BANNER_Y + BANNER_H) return B_COUNT;  // the banner
  return -1;
}

void report(instrument::Err e) {
  if (e != instrument::OK) scpi::pushError(e, instrument::errText(e));
}

void onTap(int16_t x, int16_t y) {
  const instrument::State &s = instrument::state();
  const int id = hit(x, y);
  if (id < 0) return;
  if (id == B_COUNT) {
    if (s.board && !s.known) report(instrument::safeState());
    return;
  }
  if (!s.board || !s.known) return;
  drawButton(ButtonId(id), true);
  switch (id) {
    case B_R1E5: report(instrument::setRange(instrument::RANGE_1E5)); break;
    case B_R1E6: report(instrument::setRange(instrument::RANGE_1E6)); break;
    case B_R1E7: report(instrument::setRange(instrument::RANGE_1E7)); break;
    case B_POL:
      report(instrument::setPolarity(s.polarity == instrument::POL_INV ? instrument::POL_NORM
                                                                        : instrument::POL_INV));
      break;
    case B_OUT:
      if (s.inject || s.range != instrument::RANGE_NONE) report(instrument::setOutput(!s.inject));
      break;
  }
  drawButton(ButtonId(id));  // in case the state did not change
}

}  // namespace

void begin() {
  touch::begin();
  lcd.init();
  lcd.setRotation(3);  // landscape, turned 180 degrees for the enclosure (1 = the module's usual way up)
  lcd.setBrightness(200);
  lcd.fillScreen(C_BG);
  readout.setColorDepth(16);
  readout.createSprite(W, READOUT_H);
  // Hold the screen at power-up to calibrate touch (or send DIAG:TOUC:CAL). Never forced, so boot
  // never waits on a tap and SCPI is available at once; until then a default mapping is used.
  if (touch::pressed()) runTouchCal();
  drawAll();
}

void loop() {
  if (g_touch_cal_requested) {
    g_touch_cal_requested = false;
    runTouchCal();
    drawAll();
  }

  int16_t x, y;
  const bool down = touch::read(x, y);
  if (down && !g_was_pressed) onTap(x, y);
  // Release needs the pen to lift, not just one noisy low-pressure sample.
  if (down) g_was_pressed = true;
  else if (!touch::pressed()) g_was_pressed = false;

  if (instrument::version() != g_drawn_version) {
    drawAll();
    return;
  }
  if (sdstore::logging() != g_drawn_log || sdstore::lastOk() != g_drawn_sd ||
      tmp275::present() != g_drawn_tmp)
    drawStatusBar();
  if (cal::dirty() != g_drawn_dirty || millis() - g_last_readout >= 1000) {
    drawReadout();
    g_last_readout = millis();
  }
}

void requestTouchCal() { g_touch_cal_requested = true; }

void invertDisplay(bool on) { lcd.invertDisplay(on); }

void printTouch(Print &out) {
  int16_t rx, ry, sx, sy;
  if (!touch::readRaw(rx, ry) || !touch::read(sx, sy)) {
    out.print("NONE");
    return;
  }
  out.printf("RAW=%d,%d,SCREEN=%d,%d", rx, ry, sx, sy);
}

}  // namespace ui
