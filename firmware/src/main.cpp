// Nanovolt divider Rev A firmware.
//
// Boot order matters: the MCP23017 keeps its output latches across an ESP32 reboot, so its
// latches are cleared before anything else (including the display) is brought up.
#include <Arduino.h>

#include "bus.h"
#include "calibration.h"
#include "coils.h"
#include "instrument.h"
#include "mcp23017.h"
#include "pins.h"
#include "scpi.h"
#include "sdstore.h"
#include "settings.h"
#include "tmp275.h"
#include "ui.h"

namespace {

class NullPrint : public Print {
 public:
  size_t write(uint8_t) override { return 1; }
};

char g_line[256];
size_t g_line_len = 0;
bool g_line_overflow = false;

void pollSerial() {
  while (Serial.available()) {
    const char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (g_line_overflow) {
        scpi::pushError(-112, "Program mnemonic too long;line over 255 chars");
      } else if (g_line_len) {
        g_line[g_line_len] = '\0';
        scpi::execute(g_line, Serial);
      }
      g_line_len = 0;
      g_line_overflow = false;
    } else if (g_line_len < sizeof(g_line) - 1) {
      g_line[g_line_len++] = ch;
    } else {
      g_line_overflow = true;
    }
  }
}

void setLed() {
  const instrument::State &s = instrument::state();
  const bool red = s.board && s.known && s.inject;
  const bool green = s.board && s.known && !s.inject;
  const bool blue = !s.board || !s.known;
  digitalWrite(pins::LED_R, !red);  // active low
  digitalWrite(pins::LED_G, !green);
  digitalWrite(pins::LED_B, !blue);
}

void logChange(const char *event) { sdstore::logEvent(event); }

}  // namespace

void setup() {
  bus::begin();
  mcp::init();  // clears any coil left energised by a reboot mid-pulse

  Serial.begin(115200);
  for (int p : {pins::LED_R, pins::LED_G, pins::LED_B}) {
    pinMode(p, OUTPUT);
    digitalWrite(p, HIGH);
  }

  settings::begin();
  coils::setPulseMs(settings::get().pulseMs);
  coils::setGapMs(settings::get().gapMs);
  cal::begin();
  tmp275::init();

  Serial.printf("# nanovolt-divider fw %s%s\n", NVD_FW_VERSION,
#ifdef NVD_SIM_BOARD
                " (SIMULATED BOARD)"
#else
                ""
#endif
  );
  Serial.printf("# MCP23017 %s, TMP275 %s, boot safe state %s\n",
                mcp::present() ? "found" : "NOT FOUND", tmp275::present() ? "found" : "NOT FOUND",
                settings::get().bootSafe ? "ON" : "OFF (relays not pulsed)");

  instrument::begin(settings::get().bootSafe);
  instrument::setChangeHook(logChange);

  NullPrint np;
  sdstore::info(np);  // sets the SD status indicator

  ui::begin();
  setLed();
  Serial.println("# ready");
}

void loop() {
  pollSerial();
  instrument::poll();
  tmp275::poll();
  sdstore::poll();
  ui::loop();
  setLed();
}
