# nanovolt-divider

Programmable nanovolt divider / precision attenuator: a compact bench instrument that turns an
ordinary programmable DC source into a calibrated nanovolt-to-microvolt signal by **passive resistive
attenuation** (1e-5 / 1e-6 / 1e-7), with relay-controlled polarity reversal and a true-zero
(isolate) function, read by an external precision DMM. A separate passive path measures a ~450 V
Geiger-counter supply.

The design rationale, architecture, relay rules, calibration model and Rev0 BOM live in
[docs/nanovolt_divider_rev0.md](docs/nanovolt_divider_rev0.md).

## Status

Rev0: architecture locked, schematics ERC-clean, PCB placed and DRC-clean (unrouted).

## Repository layout

```
docs/                      design specification, notes
docs/datasheets/           vendor datasheets (git-ignored, copyrighted; see docs/datasheets list below)
hardware/                  KiCad 10 project
  nanovolt-divider.kicad_pro
  nanovolt-divider.kicad_sch   root sheet: metrology topology (inputs, relays, high legs, 3PDT, 1 ohm, outputs)
  control.kicad_sch            ESP32 display-module harness, MCP23017, TMP117, power
  relay_channel.kicad_sch      generic latching-relay channel, instantiated 5x (K1..K5)
  nanovolt-divider.kicad_pcb   board: 60 x 94 mm, 2 layers, placed, not yet routed
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
| K4 POLARITY | normal (`SRC_P` = `NORMAL_IN_P`) | inverted |
| K1..K3 RANGE | open at both ends | range active (only one at a time) |
| K5 INJECT | ISOLATE - both legs open (1 ohm and DMM path untouched) | INJECT |

K1..K3 use **both** poles of their relay: pole A breaks the top of the high leg (`R*_IN`), pole B
breaks the bottom (`R*_OUT`). A deselected resistor is therefore isolated at both ends and never
loads `RANGE_BUS` - worth having on the 10 M range in particular.

K5 does the same for the source as a whole: pole A breaks the high side (`RANGE_BUS` -> `INJ_NODE`)
and pole B breaks the return (`SRC_RTN` -> `INJ_RTN`). In ISOLATE the programmable source is
disconnected from the 1 ohm and the DMM path at both ends, so nothing of the source - not its output
capacitance, not its leakage to earth - remains attached to the measurement node.

### Control wiring

* Controller: integrated 2.8" ESP32 touch-TFT module (ESP32-2432S028R type, ELEGOO), off-board,
  connected by three harnesses (P1: 5 V / GND, CN1: I2C + 3V3, P3: IO35 mode sense).
* Those harnesses are the module's own pigtails, **soldered** to pads at the board end - there is no
  board-side connector. The module end keeps its connector, so the display still unplugs. This is
  why: the module side is a 1.25 mm-class connector, so a board-side header would have meant
  crimping a bespoke pitch-bridging cable for a joint that never needs to unmate, and the panel
  jacks (`J1`-`J3`, `J5`, `J6`) and the 3PDT toggle are already hard-wired the same way.
* Only the eight live conductors have pads: `J7` = P1 pins 3/4, `J8` = CN1 pins 1-4, `J9` = P3
  pins 1/2. The pads keep the *module's* pin numbering rather than being renumbered 1..n. All three
  GND wires are run: P1's returns the pulsed coil current, P3's is the `HV_SENSE` reference, CN1's
  serves I2C. Same net, but three conductors cut the cable-side shared IR drop - do not collapse
  them to one wire.
* MCP23017 (I2C 0x20) GPA0..GPA7 + GPB0..GPB1 drive the ten coil lines K1..K5 SET/RESET.
* TMP117 (I2C 0x48) sits next to the 1 ohm resistor, thermal proximity only.
* The third pole of the NORMAL/HV toggle drives `HV_SENSE` (IO35): the HV throw pulls it high
  through R24 (10 k), R25 (100 k) holds it low otherwise, and C5 (10 nF) filters the harness run.
  The NORMAL throw needs no resistor and no board pad.
* The control ground is the global net `DGND`, deliberately not `GND`, so it cannot be merged with
  the floating analog return (`SRC_RTN` / `ANALOG_RTN`) by accident.

## Working with the schematics

Open `hardware/nanovolt-divider.kicad_pro` in KiCad 10. The project library
`hardware/lib/nanovolt-divider.kicad_sym` holds the TQ2-L2-5V relay, the 3PDT switch, the `DGND`
power symbol and the three ESP32 harness pigtail landings - these carry the module's own pin names
(`SCL_IO22`, `IO35`, ...) rather than `Pin_1..Pin_4`, so a wire on the wrong pin is visible in the
schematic instead of looking plausibly correct. Footprints for the relay, the precision resistors,
the switch pads and the harness pads are in `hardware/lib/nanovolt-divider.pretty`. Everything else
is stock KiCad.

Run ERC / exports from the command line:

```
kicad-cli sch erc --severity-all --exit-code-violations hardware/nanovolt-divider.kicad_sch
kicad-cli sch export pdf --output build/schematic.pdf hardware/nanovolt-divider.kicad_sch
```

`tools/gen_schematics.py` generates all schematic files, the project symbol library and the
project footprints; re-run it after editing the script. It will **not** overwrite an existing
`nanovolt-divider.kicad_pro` - KiCad owns that file, and it holds the DRC severities and the `HV`
netclass that the `.kicad_dru` rules depend on.

## Board

`hardware/nanovolt-divider.kicad_pcb` is placed but unrouted:

* 60 x 94 mm portrait, two layers, laid out top-down: display-module harness pads, the
  MCP23017 (horizontal, caps and pull-ups in columns on both sides), ten coil-driver columns, then
  one self-contained cell per relay.
* **Range cells.** Each relay carries its SET/RESET driver pair directly above it and its own
  high-leg resistor directly below it, standing vertically across the relay's pole A and pole B
  contacts. `RANGE_BUS` then runs as one short chain across the three cells instead of a long
  row-to-row bus.
* There is no strict warm/quiet partition any more. The relay coils are pulsed for 10-20 ms and
  never held, so their average dissipation is ~0 and co-locating them with the range resistors
  costs nothing while making the routing far shorter. What is preserved is the part that actually
  matters for thermal EMF: the continuously powered parts (MCP23017, harness pads, bulk caps) stay
  at the top edge, away from `MEAS_NODE`, and the 1 ohm strip stays physically isolated.
* The 1 ohm strip is separated by two slots that leave a 10 mm centre bridge and 3 mm bridges at
  both board edges for stiffness; `MEAS_NODE`, `ANALOG_RTN` and the TMP117 lines cross the centre
  one. The TMP117 sits over the resistor body and the OUT HI / OUT LO wire pads are at the
  resistor's own terminals. Both lower mounting holes sit *above* the slots: a screw on the island
  would add a thermal and mechanical-stress path straight to the precision resistor.
* **3PDT wire pads.** These are wire-landing pads, not the switch, so they no longer copy its 3 x 3
  lug geometry (which cost ~18 x 18 mm and put a 450 V pad 7.62 mm from `MEAS_NODE`). Seven pads
  remain, split into a 2 x 3 low-voltage cluster and one isolated HV pad:

  ```
  9 MODE_SW_HV   8 HV_SENSE      3.3 V logic, farthest from the measurement pads
  1 INJ_NODE     2 MEAS_NODE
  4 SRC_RTN      5 ANALOG_RTN
  3 HV_DIV       alone, 11 mm away, in the HV island with R34 and J3
  ```

* `HV_IN_P` and `HV_DIV` are on the `HV` netclass: 3 mm clearance, 4 mm creepage and 1.5 mm edge
  clearance, enforced by `nanovolt-divider.kicad_dru`. The patterns are the two net names spelled
  out, never `HV*` - that would sweep in `HV_SENSE`, which is a 3.3 V logic line.
* `DGND` pour on B.Cu covers the digital circuitry (control cluster and coil drivers). The only
  copper keepout is over the isolated 1 ohm island.
* Panel parts (banana jacks, 3PDT toggle) terminate on solder-wire pads.

### Panel wiring (no board connection)

Two switch lugs are wired panel-to-panel and have no pad, which is why they do not appear in the
netlist and are absent from the `SW_3PDT` symbol:

```
HV IN - jack                 ->  SW1 pole 2, HV lug (lug 6)
SW1 pole 3, NORM lug (lug 7) ->  unused
```

DRC is clean (0 errors, 0 schematic-parity issues) apart from the unrouted ratsnest and
silkscreen-over-pad warnings (reference designators still need tidying after routing).

## Open items

* Route the board (interactively, or Freerouting), then tidy silkscreen.
* Select the 3PDT toggle: break-before-make, 450 VDC rated, with pole-to-pole isolation good
  enough that pole 3 (3.3 V `HV_SENSE`) sits beside a 450 V pole. Confirm which lug row the lever
  selects as NORMAL before wiring the panel. Shrouded HV banana jacks still to choose.
* Confirm the display module variant and its connector pinout (P1 / CN1 / P3) against the board in
  hand. With soldered pigtails there is no keyed housing at the board end, so this continuity check
  is the only thing standing between a mis-landed wire and 5 V on an I2C pin.
* Confirm the pigtail conductor gauge fits the 0.8 mm pad drill, and decide how the cable is strain
  relieved at the board end - the board no longer has a housing taking that load.
* Verify pad numbering on the MOX-700, Slim-Mox SM102 and RS-2C footprints against the parts in
  hand. The TQ2 relay footprint is already checked (pads 1-5 / 6-10 in two rows at 2.54 mm, 7.62 mm
  apart, DIP order with 1 opposite 10).
* Schematic architecture / safety review before ordering boards.

## Datasheets

Not redistributed in this repository. Panasonic TQ relays: catalog ASCTB14E
(`industry.panasonic.com`); Ohmite MOX-700 and Slim-Mox; Vishay Dale RS/NS; Microchip MCP23017;
TI TMP117.

## License

To be decided before the repository is made public (hardware: CERN-OHL-P or similar; firmware: MIT).
