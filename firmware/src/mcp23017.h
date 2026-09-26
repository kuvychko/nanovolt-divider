// Minimal MCP23017 driver for the ten coil-driver lines (IOCON.BANK = 0 register map).
//
// The chip's ~RESET is tied high by R23, so it is NOT reset when the ESP32 reboots: a reboot in the
// middle of a coil pulse leaves that coil energised. init() therefore clears the output latches
// before it makes any pin an output, and main() calls it before anything else.
#pragma once
#include <Print.h>
#include <stdint.h>

namespace mcp {

enum Port : uint8_t { PORT_A = 0, PORT_B = 1 };

// Output pins used by the board: GPA0/GPA1 (K5) and all of GPB. GPA2..GPA7 are spare inputs.
constexpr uint8_t USED_A = 0x03;
constexpr uint8_t USED_B = 0xFF;

bool init();     // probe, OLATA/B = 0, then IODIR; verified by readback. false = not present / fault
bool present();  // result of the last init() or check()
bool check();    // periodic health check; re-initialises if the chip lost its configuration

// Writes one port's output latch. The caller (coils.cpp) enforces the one-coil-at-a-time rule.
bool writeLatch(Port port, uint8_t value);
bool readLatches(uint8_t &a, uint8_t &b);

void dump(Print &out);  // register dump for DIAG:MCP?

}  // namespace mcp
