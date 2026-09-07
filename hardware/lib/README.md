# Project-local libraries

Both libraries are registered in `../sym-lib-table` and `../fp-lib-table` under the nickname
`nanovolt-divider` using `${KIPRJMOD}` paths, so the project is self-contained.

## nanovolt-divider.kicad_sym

| Symbol | Notes |
|---|---|
| `TQ2-L2-5V` | Panasonic 2-coil latching DPDT signal relay, 4 units: A = SET coil (1+ / 5-), B = RESET coil (10+ / 6-), C = pole A (3 COM, 2 NC, 4 NO), D = pole B (8 COM, 9 NC, 7 NO). Pin numbers per Panasonic catalog ASCTB14E, "Schematic (bottom view), 2 coil latching". Contacts are drawn in the RESET state. |
| `SW_3PDT` | Generic 3PDT toggle, 3 units, pins named NORM / COM / HV. Lug numbers 1..9 are placeholders until the physical switch is chosen. |

## nanovolt-divider.pretty

| Footprint | Notes |
|---|---|
| `Relay_DPDT_Panasonic_TQ2_THT` | TQ2 through-hole: 10 pins, 2.54 mm pitch, 7.62 mm row spacing, 1.0 mm drill, 14 x 9 mm body. Top view: pins 1..5 left to right on the bottom row, 10..6 left to right on the top row; the case polarity bar is at the pin 1 / pin 10 end. |

Both were authored for this project from the manufacturer's drawings (no third-party library content).
