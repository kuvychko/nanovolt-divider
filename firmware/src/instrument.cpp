#include "instrument.h"

#include <Arduino.h>

#include "coils.h"
#include "mcp23017.h"

namespace instrument {

namespace {

State g_state = {false, false, RANGE_NONE, POL_NORM, false};
uint32_t g_version = 0;
ChangeHook g_hook = nullptr;
uint32_t g_last_poll = 0;

void changed(const char *event) {
  g_version++;
  if (g_hook) g_hook(event);
}

coils::Relay rangeRelay(Range r) {
  switch (r) {
    case RANGE_1E5: return coils::K1;
    case RANGE_1E6: return coils::K2;
    default: return coils::K3;
  }
}

// One pulse; on failure the relay state can no longer be trusted.
bool tryPulse(coils::Relay r, coils::Coil c) {
  if (coils::pulse(r, c)) return true;
  g_state.known = false;
  g_state.board = mcp::present();
  return false;
}

Err failed(const char *event) {
  changed(event);
  return E_HW;
}

Err ready() {
  if (!g_state.board) return E_HW_MISSING;
  if (!g_state.known) return E_STATE_UNKNOWN;
  return OK;
}

// Break-before-make body shared by range and polarity changes: isolate, run `change`, then put the
// output back the way it was (if the new configuration can inject at all).
template <typename F>
Err whileIsolated(const char *event, F change) {
  const bool wasInject = g_state.inject;
  if (wasInject) {
    if (!tryPulse(coils::K5, coils::RESET)) return failed(event);
    g_state.inject = false;
  }
  if (!change()) return failed(event);
  if (wasInject && g_state.range != RANGE_NONE) {
    if (!tryPulse(coils::K5, coils::SET)) return failed(event);
    g_state.inject = true;
  }
  changed(event);
  return OK;
}

}  // namespace

void begin(bool bootSafe) {
  g_state.board = mcp::present();
  g_state.known = false;
  if (g_state.board && bootSafe) safeState();
  g_version++;
}

void poll() {
  if (millis() - g_last_poll < 2000) return;
  g_last_poll = millis();
  const bool was = g_state.board;
  g_state.board = mcp::check();
  if (g_state.board != was) {
    // A board that (re)appears is never pulsed automatically: its relays are in an unknown
    // state until *RST.
    g_state.known = false;
    changed(g_state.board ? "BOARD_FOUND" : "BOARD_LOST");
  }
}

const State &state() { return g_state; }
uint32_t version() { return g_version; }

Err safeState() {
  if (!g_state.board) return E_HW_MISSING;
  g_state.known = false;
  static const coils::Relay order[] = {coils::K5, coils::K1, coils::K2, coils::K3, coils::K4};
  for (coils::Relay r : order) {
    if (!tryPulse(r, coils::RESET)) return failed("SAFE_FAIL");
  }
  g_state.known = true;
  g_state.range = RANGE_NONE;
  g_state.polarity = POL_NORM;
  g_state.inject = false;
  changed("SAFE");
  return OK;
}

Err setRange(Range r) {
  if (Err e = ready()) return e;
  if (r == g_state.range) return OK;
  return whileIsolated("RANGE", [&] {
    if (g_state.range != RANGE_NONE) {  // break
      if (!tryPulse(rangeRelay(g_state.range), coils::RESET)) return false;
      g_state.range = RANGE_NONE;
    }
    if (r != RANGE_NONE) {  // make
      if (!tryPulse(rangeRelay(r), coils::SET)) return false;
      g_state.range = r;
    }
    return true;
  });
}

Err setPolarity(Polarity p) {
  if (Err e = ready()) return e;
  if (p == g_state.polarity) return OK;
  return whileIsolated("POLARITY", [&] {
    if (!tryPulse(coils::K4, p == POL_INV ? coils::SET : coils::RESET)) return false;
    g_state.polarity = p;
    return true;
  });
}

Err setOutput(bool inject) {
  if (Err e = ready()) return e;
  if (inject && g_state.range == RANGE_NONE) return E_CONFLICT;
  // Pulsed even when already in the requested state: repeating a latch pulse is harmless, and an
  // explicit OUTP OFF should always physically re-assert ISOLATE.
  const bool ok = tryPulse(coils::K5, inject ? coils::SET : coils::RESET);
  if (ok) g_state.inject = inject;
  changed(inject ? "INJECT" : "ISOLATE");
  return ok ? OK : E_HW;
}

Err rawPulse(uint8_t relay, uint8_t coil) {
  if (!g_state.board) return E_HW_MISSING;
  if (relay >= coils::RELAY_COUNT || coil > coils::RESET) return E_CONFLICT;
  g_state.known = false;
  const bool ok = coils::pulse(coils::Relay(relay), coils::Coil(coil));
  g_state.board = mcp::present();
  changed("RAW_PULSE");
  return ok ? OK : E_HW;
}

const char *rangeName(Range r) {
  static const char *names[] = {"NONE", "1E-5", "1E-6", "1E-7"};
  return r < RANGE_COUNT ? names[r] : "?";
}

const char *errText(Err e) {
  switch (e) {
    case OK: return "No error";
    case E_CONFLICT: return "Settings conflict";
    case E_HW: return "Hardware error;coil pulse failed, relay state unknown";
    case E_HW_MISSING: return "Hardware missing;MCP23017 not found";
    case E_STATE_UNKNOWN: return "Execution error;relay state unknown, send *RST";
  }
  return "Error";
}

void setChangeHook(ChangeHook hook) { g_hook = hook; }

}  // namespace instrument
