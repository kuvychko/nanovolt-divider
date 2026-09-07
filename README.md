# nanovolt-divider

Programmable nanovolt divider / precision attenuator: a compact bench instrument that turns an
ordinary programmable DC source into a calibrated nanovolt-to-microvolt signal by **passive resistive
attenuation** (1e-5 / 1e-6 / 1e-7), with relay-controlled polarity reversal and a true-zero
(isolate) function, read by an external precision DMM. A separate passive path measures a ~450 V
Geiger-counter supply.

The design rationale, architecture, relay rules, calibration model and Rev0 BOM live in
[docs/nanovolt_divider_rev0.md](docs/nanovolt_divider_rev0.md).

## Status

Rev0: architecture locked, hierarchical schematics drafted, PCB placed (unrouted).

## Repository layout

```
docs/                      design specification, notes
docs/datasheets/           vendor datasheets (git-ignored, copyrighted; see docs/datasheets list below)
hardware/                  KiCad 10 project
  nanovolt-divider.kicad_pro
  nanovolt-divider.kicad_sch   root sheet: metrology topology (inputs, relays, high legs, 3PDT, 1 ohm, outputs)
  control.kicad_sch            ESP32 display-module harness, MCP23017, TMP117, power
  relay_channel.kicad_sch      generic latching-relay channel, instantiated 5x (K1..K5)
  nanovolt-divider.kicad_pcb   board: 60 x 103 mm, 2 layers, placed, not yet routed
  nanovolt-divider.kicad_dru   custom DRC rules (450 V clearance / creepage, DSBGA, 1 ohm bridge)
  lib/                         project-local symbol and footprint libraries
tools/gen_schematics.py    bootstrap script that produced the first version of the schematics
tools/gen_pcb.py           bootstrap script that produced the placed (unrouted) board
```

### Hierarchy

```
nanovolt-divider.kicad_sch (root)
+-- CONTROL          control.kicad_sch
+-- RANGE_1E5 (K1)   relay_channel.kicad_sch
+-- RANGE_1E6 (K2)   relay_channel.kicad_sch
+-- RANGE_1E7 (K3)   relay_channel.kicad_sch
+-- POLARITY  (K4)   relay_channel.kicad_sch
+-- INJECT    (K5)   relay_channel.kicad_sch
```

`relay_channel.kicad_sch` exposes `SET`, `RESET`, `A_COM`, `A_NC`, `A_NO`, `B_COM`, `B_NC`, `B_NO`.
Each instance contains one Panasonic TQ2-L2-5V (2-coil latching DPDT) and two MMBT2222A low-side
coil drivers with 1N4148W flyback diodes. Because all five channels share one sheet file, KiCad's
multichannel / repeat-layout tooling can replicate the driver layout after one channel is routed.

### Relay states

| Relay | RESET (NC) | SET (NO) |
|---|---|---|
| K4 POLARITY | normal (SRC+ = NORMAL IN +) | inverted |
| K1..K3 RANGE | open | range active (only one at a time) |
| K5 INJECT | ISOLATE (1 ohm and DMM path untouched) | INJECT |

### Control wiring

* Controller: integrated 2.8" ESP32 touch-TFT module (ESP32-2432S028R type, ELEGOO), off-board,
  connected by three harnesses (P1: 5 V / GND, CN1: I2C + 3V3, P3: IO35 mode sense).
* MCP23017 (I2C 0x20) GPA0..GPA7 + GPB0..GPB1 drive the ten coil lines K1..K5 SET/RESET.
* TMP117 (I2C 0x48) sits next to the 1 ohm resistor, thermal proximity only.
* The third pole of the NORMAL/HV toggle drives `HV_SENSE` (IO35) through 10 k series resistors.

## Working with the schematics

Open `hardware/nanovolt-divider.kicad_pro` in KiCad 10. Symbols for the relay and the 3PDT switch
are in the project library `hardware/lib/nanovolt-divider.kicad_sym`; the relay footprint is in
`hardware/lib/nanovolt-divider.pretty`. Everything else uses the stock KiCad libraries.

Run ERC / exports from the command line:

```
kicad-cli sch erc --severity-all --exit-code-violations hardware/nanovolt-divider.kicad_sch
kicad-cli sch export pdf --output build/schematic.pdf hardware/nanovolt-divider.kicad_sch
```

`tools/gen_schematics.py` generated the first version of all schematic files. It is kept for
reference; the `.kicad_sch` files are the source of truth from here on and are edited in KiCad.

## Board

`hardware/nanovolt-divider.kicad_pcb` is placed but unrouted:

* 60 x 103 mm portrait, two layers, laid out top-down: display-module harness connectors, the
  MCP23017 (horizontal, caps and pull-ups in columns on both sides), ten coil-driver columns, the
  relay row (each SET/RESET driver pair directly above its relay), then the quiet section.
* Quiet section, top to bottom: NORMAL IN pads and the three high-leg resistors, the 3PDT wiring
  pad grid (3 x 3, 7.62 mm pitch: columns NORM / COM / HV, rows pole 1..3) with R34 and the HV
  input pads, and finally the 1 ohm strip.
* The 1 ohm strip is separated by two edge notches that leave a 10 mm centre bridge; MEAS, the
  analog return, and the TMP117 lines cross there. The TMP117 sits over the resistor body and the
  OUT HI / OUT LO wire pads are at the resistor's own terminals.
* HV input pads, R34 and the switch pads' HV column are spaced for 450 V; the `HV` netclass carries
  3 mm clearance and a 4 mm creepage rule in the `.kicad_dru` file.
* GND pour on B.Cu is restricted to the control section (above the relays); a no-pour keepout covers
  the quiet section so the analog return is never a plane.
* Panel parts (banana jacks, 3PDT toggle) terminate on solder-wire pads.

DRC is clean apart from the unrouted ratsnest and silkscreen-over-pad warnings (reference
designators still need tidying after routing).

## Open items

* Route the board (interactively, or Freerouting), then tidy silkscreen.
* Select the 450 VDC rated 3PDT toggle and shrouded HV banana jacks.
* Confirm the display module variant and its connector pinout (P1 / CN1 / P3) against the board in hand.
* Schematic architecture / safety review before ordering boards.

## Datasheets

Not redistributed in this repository. Panasonic TQ relays: catalog ASCTB14E
(`industry.panasonic.com`); Ohmite MOX-700 and Slim-Mox; Vishay Dale RS/NS; Microchip MCP23017;
TI TMP117.

## License

To be decided before the repository is made public (hardware: CERN-OHL-P or similar; firmware: MIT).
