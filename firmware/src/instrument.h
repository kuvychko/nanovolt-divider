// Relay state machine. Enforces the Rev A relay rules (spec section 6.3):
//  1. power up into a deterministic safe state (boot pulses; SYST:BOOT:SAFE)
//  2. ISOLATE is established before anything else changes
//  3. only one range relay is ever SET
//  4. range changes are break-before-make
//  5. polarity changes happen while isolated
//  6. coils are only ever pulsed (coils.cpp)
//
// Latching relays cannot be read back. The state here is the one the last successful pulses
// produced; `known` is false until safeState() has run, and after any failed or raw pulse.
#pragma once
#include <stdint.h>

namespace instrument {

enum Range : uint8_t { RANGE_NONE = 0, RANGE_1E5, RANGE_1E6, RANGE_1E7 };
constexpr uint8_t RANGE_COUNT = 4;
enum Polarity : uint8_t { POL_NORM = 0, POL_INV };

struct State {
  bool board;   // MCP23017 answering
  bool known;   // relay state established by pulses since boot
  Range range;
  Polarity polarity;
  bool inject;  // K5 SET
};

// Error codes are SCPI error numbers so the parser can queue them unchanged.
enum Err : int {
  OK = 0,
  E_CONFLICT = -221,      // settings conflict (e.g. INJECT with no range selected)
  E_HW = -240,            // hardware error: a pulse failed; state is now unknown
  E_HW_MISSING = -241,    // no MCP23017
  E_STATE_UNKNOWN = -200, // execution error: send *RST first
};

void begin(bool bootSafe);  // after mcp::init()
void poll();                // periodic MCP health check / re-probe

const State &state();
uint32_t version();  // increments on every state change, for the UI

Err safeState();  // *RST: K5 RESET, K1..K3 RESET, K4 RESET
Err setRange(Range r);
Err setPolarity(Polarity p);
Err setOutput(bool inject);
Err rawPulse(uint8_t relay, uint8_t coil);  // DIAG:PULS - marks the state unknown

const char *rangeName(Range r);    // "1E-5", ... "NONE"
const char *errText(Err e);

// Called after every completed operation that pulsed a coil, with a short event name. main()
// points it at the SD run log.
typedef void (*ChangeHook)(const char *event);
void setChangeHook(ChangeHook hook);

}  // namespace instrument
