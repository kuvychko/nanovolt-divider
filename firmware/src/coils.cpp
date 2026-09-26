#include "coils.h"

#include <Arduino.h>

#include "mcp23017.h"

namespace coils {

namespace {

// Indexed [relay][coil]. This table is the only place the layout order lives.
constexpr Line TABLE[RELAY_COUNT][2] = {
    /* K1 */ {{mcp::PORT_B, 2}, {mcp::PORT_B, 3}},
    /* K2 */ {{mcp::PORT_B, 4}, {mcp::PORT_B, 5}},
    /* K3 */ {{mcp::PORT_B, 6}, {mcp::PORT_B, 7}},
    /* K4 */ {{mcp::PORT_B, 0}, {mcp::PORT_B, 1}},
    /* K5 */ {{mcp::PORT_A, 1}, {mcp::PORT_A, 0}},
};

uint16_t g_pulse_ms = 20;
uint16_t g_gap_ms = 20;
#ifdef NVD_SIM_BOARD
bool g_trace = true;
#else
bool g_trace = false;
#endif

bool clearBoth() {
  for (int attempt = 0; attempt < 5; attempt++) {
    bool ok = mcp::writeLatch(mcp::PORT_A, 0) && mcp::writeLatch(mcp::PORT_B, 0);
    uint8_t a, b;
    if (ok && mcp::readLatches(a, b) && a == 0 && b == 0) return true;
    delay(2);
  }
  return false;
}

}  // namespace

Line line(Relay r, Coil c) { return TABLE[r][c]; }

bool pulse(Relay r, Coil c) {
  if (r >= RELAY_COUNT || !mcp::present()) return false;
  const Line l = TABLE[r][c];
  const uint8_t mask = uint8_t(1u << l.bit);

  // Both latches must be idle before we energise anything: one coil at a time, always.
  if (!clearBoth()) return false;

  if (g_trace) {
    Serial.printf("# PULSE %s %s (GP%c%u) %u ms\n", relayName(r), coilName(c),
                  l.port == mcp::PORT_A ? 'A' : 'B', l.bit, g_pulse_ms);
  }

  bool ok = mcp::writeLatch(mcp::Port(l.port), mask);
  delay(g_pulse_ms);
  ok = clearBoth() && ok;
  delay(g_gap_ms);
  return ok;
}

uint16_t pulseMs() { return g_pulse_ms; }
uint16_t gapMs() { return g_gap_ms; }
void setPulseMs(uint16_t ms) { g_pulse_ms = constrain(ms, PULSE_MS_MIN, PULSE_MS_MAX); }
void setGapMs(uint16_t ms) { g_gap_ms = constrain(ms, PULSE_MS_MIN, PULSE_MS_MAX); }
void setTrace(bool on) { g_trace = on; }
bool trace() { return g_trace; }

const char *relayName(Relay r) {
  static const char *names[] = {"K1", "K2", "K3", "K4", "K5"};
  return r < RELAY_COUNT ? names[r] : "K?";
}

const char *coilName(Coil c) { return c == SET ? "SET" : "RESET"; }

}  // namespace coils
