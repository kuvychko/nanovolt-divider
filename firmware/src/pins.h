// Pin map for the ESP32-2432S028R ("Cheap Yellow Display") as wired to the Rev A board.
// Board-side wiring: see the "Display harness" table in the top-level README.
#pragma once
#include <stdint.h>

namespace pins {

// I2C to the Rev A board (J8). The module has no IO22, so the bus lives on the SPI connector:
// SDA = IO27, SCL = IO18. Pull-ups are R21/R22 (4.7k to 3V3) on the board.
constexpr int I2C_SDA = 27;
constexpr int I2C_SCL = 18;

// microSD slot (VSPI pins). SCK is IO18 - shared with I2C SCL; see bus.h for arbitration.
constexpr int SD_SCK = 18;
constexpr int SD_MISO = 19;
constexpr int SD_MOSI = 23;
constexpr int SD_CS = 5;

// TFT (HSPI).
constexpr int TFT_SCK = 14;
constexpr int TFT_MOSI = 13;
constexpr int TFT_MISO = 12;
constexpr int TFT_CS = 15;
constexpr int TFT_DC = 2;
constexpr int TFT_BL = 21;

// XPT2046 resistive touch - its own pins, read by bit-bang (touch.cpp) so it takes no SPI host.
constexpr int TOUCH_CLK = 25;
constexpr int TOUCH_MOSI = 32;
constexpr int TOUCH_MISO = 39;  // input-only pin
constexpr int TOUCH_CS = 33;
constexpr int TOUCH_IRQ = 36;   // input-only pin, low while touched

// RGB status LED, active low.
constexpr int LED_R = 4;
constexpr int LED_G = 16;
constexpr int LED_B = 17;

}  // namespace pins

// I2C addresses on the Rev A board.
constexpr uint8_t MCP23017_ADDR = 0x20;  // A2:A0 = 000
constexpr uint8_t TMP275_ADDR = 0x48;    // A2:A0 = DGND
