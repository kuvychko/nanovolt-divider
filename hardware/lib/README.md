# Project-local libraries

Both libraries are registered in `../sym-lib-table` and `../fp-lib-table` under the nickname
`nanovolt-divider` using `${KIPRJMOD}` paths, so the project is self-contained.

## nanovolt-divider.kicad_sym

| Symbol | Notes |
|---|---|
| `TQ2-L2-5V` | Panasonic 2-coil latching DPDT signal relay, 4 units: A = SET coil (1+ / 5-), B = RESET coil (10+ / 6-), C = pole A (3 COM, 2 NC, 4 NO), D = pole B (8 COM, 9 NC, 7 NO). Pin numbers per Panasonic catalog ASCTB14E, "Schematic (bottom view), 2 coil latching". Contacts are drawn in the RESET state. |
| `TMP275` | TI TMP275 I2C temperature sensor, SOIC-8 (D). Not in stock KiCad 10 - `Sensor_Temperature` has no TMP275. The pinout is the LM75/TMP75 industry-standard one (1 SDA, 2 SCL, 3 ALERT, 4 GND, 5 A2, 6 A1, 7 A0, 8 V+), so `Sensor_Temperature:LM75B` would have wired up correctly, but it would put "LM75B" in the lib_id and call pin 3 "O.S.". Uses the stock `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm` footprint. |

## nanovolt-divider.pretty

| Footprint | Notes |
|---|---|
| `Relay_DPDT_Panasonic_TQ2_THT` | TQ2 through-hole: 10 pins, 2.54 mm pitch, 7.62 mm row spacing, 1.0 mm drill, 14 x 9 mm body. Top view: pins 1..5 left to right on the bottom row, 10..6 left to right on the top row; the case polarity bar is at the pin 1 / pin 10 end. |
| `R_Axial_Ohmite_MOX700_L7.0mm_D2.7mm_P10.16mm_Horizontal` | Ohmite MOX-700 (R31, R32). Body 7.0 x 2.7 mm and 0.6 mm leads measured on the parts in hand; 10.16 mm pitch, 0.9 mm drill. |
| `R_Radial_Ohmite_SlimMox_SM102_L14.7mm_W2.5mm_P10.16mm` | Ohmite Slim-Mox SM102 (R33), standing radial: 14.73 x 2.54 mm footprint, 8.64 mm tall, 10.16 mm lead pitch, 0.81 mm leads, 1.1 mm drill. |
| `R_Axial_Vishay_RS02C_L15.1mm_D5.6mm_P20.32mm_Horizontal` | Vishay Dale RS-2C (R35, 1 ohm). Body 15.06 x 5.54 mm max, 1.02 mm leads (doc 30204); 20.32 mm pitch, 1.3 mm drill. |
| `J_ESP32_P1_WirePads`, `J_ESP32_CN1_WirePads` | Soldered pigtail landings for the display module's own cable (`J7` = P1 pins 3/4, `J8` = CN1 pins 1-4). Pads keep the module's pin numbers; 0.8 mm drill / 1.6 mm pad for 28-24 AWG. |

Both were authored for this project from the manufacturer's drawings (no third-party library content).
