// Coil pulses for the five TQ2-L2-5V latching relays.
//
// The MCP23017 GPIO order follows the board layout, not the relay numbering (README, "Control
// wiring"): GPB0..GPB7 = K4 SET, K4 RESET, K1 SET, K1 RESET, K2 SET, K2 RESET, K3 SET, K3 RESET;
// GPA0 = K5 RESET, GPA1 = K5 SET.
#pragma once
#include <stdint.h>

namespace coils {

enum Relay : uint8_t { K1 = 0, K2, K3, K4, K5, RELAY_COUNT };
enum Coil : uint8_t { SET = 0, RESET = 1 };

struct Line {
  uint8_t port;  // mcp::Port
  uint8_t bit;
};
Line line(Relay r, Coil c);

// Energises exactly one coil for the pulse width, releases it, confirms both latches read back 0,
// then waits the settle gap. On any I2C failure it keeps trying to clear both latches and returns
// false. Blocking: pulse + gap, 40 ms by default.
bool pulse(Relay r, Coil c);

// Pulse width and gap, ms. The TQ2 needs well under 10 ms to latch; 20 ms leaves margin.
constexpr uint16_t PULSE_MS_MIN = 5, PULSE_MS_MAX = 100;
uint16_t pulseMs();
uint16_t gapMs();
void setPulseMs(uint16_t ms);
void setGapMs(uint16_t ms);

// Prints every pulse to Serial (always on in the cyd_sim build).
void setTrace(bool on);
bool trace();

const char *relayName(Relay r);
const char *coilName(Coil c);

}  // namespace coils
