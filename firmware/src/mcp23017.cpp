#include "mcp23017.h"

#include <Arduino.h>

#include "bus.h"
#include "pins.h"

namespace mcp {

namespace {

enum Reg : uint8_t {
  IODIRA = 0x00,
  IODIRB = 0x01,
  GPPUA = 0x0C,
  GPPUB = 0x0D,
  GPIOA = 0x12,
  GPIOB = 0x13,
  OLATA = 0x14,
  OLATB = 0x15,
  IOCON = 0x0A,
};

constexpr uint8_t IODIR_A = uint8_t(~USED_A);  // 1 = input
constexpr uint8_t IODIR_B = uint8_t(~USED_B);

bool g_present = false;

#ifdef NVD_SIM_BOARD
uint8_t sim_regs[0x16] = {0xFF, 0xFF};  // IODIR resets to all inputs
bool wr(uint8_t reg, uint8_t v) {
  sim_regs[reg] = v;
  if (reg == OLATA) sim_regs[GPIOA] = v;
  if (reg == OLATB) sim_regs[GPIOB] = v;
  return true;
}
bool rd(uint8_t reg, uint8_t &v) {
  v = sim_regs[reg];
  return true;
}
#else
bool wr(uint8_t reg, uint8_t v) { return bus::write8(MCP23017_ADDR, reg, v); }
bool rd(uint8_t reg, uint8_t &v) { return bus::read8(MCP23017_ADDR, reg, v); }
#endif

bool configured() {
  uint8_t da, db, la, lb;
  if (!rd(IODIRA, da) || !rd(IODIRB, db) || !rd(OLATA, la) || !rd(OLATB, lb)) return false;
  return da == IODIR_A && db == IODIR_B;
}

}  // namespace

bool init() {
  // Latches first: if a coil was left on by a reboot mid-pulse, this is what turns it off.
  // IOCON stays at its power-on default (BANK = 0, SEQOP = 0), which the register map relies on.
  g_present = wr(OLATA, 0) && wr(OLATB, 0) && wr(GPPUA, 0) && wr(GPPUB, 0) &&
              wr(IODIRA, IODIR_A) && wr(IODIRB, IODIR_B);
  if (g_present) {
    uint8_t la, lb;
    g_present = configured() && readLatches(la, lb) && la == 0 && lb == 0;
  }
  return g_present;
}

bool present() { return g_present; }

bool check() {
  if (g_present && configured()) return true;
  // A brown-out reset returns IODIR to all-inputs (drivers off via their 10k pull-downs), which
  // is safe but leaves us unable to pulse. Re-initialise; the relays latch, so their state stands.
  return init();
}

bool writeLatch(Port port, uint8_t value) { return wr(port == PORT_A ? OLATA : OLATB, value); }

bool readLatches(uint8_t &a, uint8_t &b) { return rd(OLATA, a) && rd(OLATB, b); }

void dump(Print &out) {
  static const struct {
    const char *name;
    uint8_t reg;
  } regs[] = {{"IODIRA", IODIRA}, {"IODIRB", IODIRB}, {"IOCON", IOCON}, {"GPPUA", GPPUA},
              {"GPPUB", GPPUB},   {"GPIOA", GPIOA},   {"GPIOB", GPIOB}, {"OLATA", OLATA},
              {"OLATB", OLATB}};
  bool first = true;
  for (auto &r : regs) {
    uint8_t v;
    if (!first) out.print(',');
    first = false;
    if (rd(r.reg, v))
      out.printf("%s=0x%02X", r.name, v);
    else
      out.printf("%s=NACK", r.name);
  }
}

}  // namespace mcp
