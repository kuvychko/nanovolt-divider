# nanovolt-divider

Programmable nanovolt divider / precision attenuator: a compact bench instrument that turns an
ordinary programmable DC source into a calibrated nanovolt-to-microvolt signal by **passive resistive
attenuation** (1e-5 / 1e-6 / 1e-7), with relay-controlled polarity reversal and a true-zero
(isolate) function, read by an external precision DMM. A separate passive path measures a ~450 V
Geiger-counter supply.

The design rationale, architecture, relay rules, calibration model and Rev0 BOM live in
[docs/nanovolt_divider_rev0.md](docs/nanovolt_divider_rev0.md).

## Status

Rev0: architecture locked, hierarchical schematics drafted, PCB layout not started.

## Repository layout

```
docs/                      design specification, notes
docs/datasheets/           vendor datasheets (git-ignored, copyrighted; see docs/datasheets list below)
hardware/                  KiCad 10 project
  nanovolt-divider.kicad_pro
  nanovolt-divider.kicad_sch   root sheet: metrology topology (inputs, relays, high legs, 3PDT, 1 ohm, outputs)
  control.kicad_sch            ESP32 display-module harness, MCP23017, TMP117, power
  relay_channel.kicad_sch      generic latching-relay channel, instantiated 5x (K1..K5)
  lib/                         project-local symbol and footprint libraries
tools/gen_schematics.py    bootstrap script that produced the first version of the schematics
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

## Open items before layout

* Footprints marked `[FOOTPRINT TBD]` in the schematic: Ohmite MOX-700 (R31, R32), Ohmite Slim-Mox
  SM102 radial (R33, R34), Vishay RS-2C (R35). Placeholders are stock axial/box footprints.
* Select the 450 VDC rated 3PDT toggle and shrouded HV banana jacks; the switch footprint is a
  placeholder terminal block for the board-side wiring.
* Confirm the display module variant and its connector pinout (P1 / CN1 / P3) against the board in hand.
* Schematic architecture / safety review, then PCB placement with the precision region isolated
  from the control region.

## Datasheets

Not redistributed in this repository. Panasonic TQ relays: catalog ASCTB14E
(`industry.panasonic.com`); Ohmite MOX-700 and Slim-Mox; Vishay Dale RS/NS; Microchip MCP23017;
TI TMP117.

## License

To be decided before the repository is made public (hardware: CERN-OHL-P or similar; firmware: MIT).
