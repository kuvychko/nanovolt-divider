// Owner of IO18, which is both I2C SCL (to the Rev A board) and the microSD slot's SCK.
//
// The bus is in I2C mode except inside an SdSession. Sharing is safe in both directions:
//  - I2C traffic clocks SCK while SD CS (IO5) is held high, so the card ignores it;
//  - SPI clocks SCL while SDA (IO27) idles high, which never forms an I2C START, so the MCP23017
//    and TMP275 ignore it.
// Only the main loop touches the bus, and never while a coil pulse is in progress, so no locking.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace bus {

void begin();  // I2C mode, SD card deselected

// I2C register helpers. All return false on a NACK or a short read.
bool write8(uint8_t addr, uint8_t reg, uint8_t value);
bool write16(uint8_t addr, uint8_t reg, uint16_t value);  // MSB first
bool read8(uint8_t addr, uint8_t reg, uint8_t &value);
bool read16(uint8_t addr, uint8_t reg, uint16_t &value);  // MSB first
bool probe(uint8_t addr);
size_t scan(uint8_t *found, size_t max);

// Reads IO18 and IO27 with the internal pull-downs on and I2C detached. A pin that reads high has
// an external pull-up (R21/R22 on the board, or one on the module).
void probePullups(bool &io18High, bool &io27High);

// Switches IO18 to SPI and mounts the card at /sd for the session's lifetime; the destructor
// unmounts and returns the bus to I2C. Check ok() before using SD.
class SdSession {
 public:
  SdSession();
  ~SdSession();
  bool ok() const { return ok_; }
  SdSession(const SdSession &) = delete;
  SdSession &operator=(const SdSession &) = delete;

 private:
  bool ok_;
};

}  // namespace bus
