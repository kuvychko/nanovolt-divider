# nanovolt-divider

Programmable nanovolt divider / precision attenuator: a compact bench instrument that turns an
ordinary programmable DC source into a calibrated nanovolt-to-microvolt signal by **passive resistive
attenuation** (1e-5 / 1e-6 / 1e-7), with relay-controlled polarity reversal and a true-zero
(isolate) function, read by an external precision DMM.

The design rationale, architecture, relay rules, calibration model and Rev A BOM live in
[docs/nanovolt_divider_rev_a.md](docs/nanovolt_divider_rev_a.md).

### The 450 V path was removed

Rev A originally carried a second, passive input for measuring a ~450 V Geiger-counter supply,
sharing the 1 ohm low leg through a 3PDT NORMAL/HV toggle. It is gone, and the reasoning is worth
keeping:

* The shared 1 ohm leg capped what the HV range could be. With a 10 M high leg the output was
  45 uV; getting more meant a smaller high leg, and 1 M draws 450 uA where 10 M draws 45 uA.
* A Geiger supply is built to source microamps into a tube that draws almost none, so its output
  impedance is high and often set by a series anode resistor. Loading it at 450 uA measures the
  divider, not the supply - and the error moves with the supply's operating point, so calibration
  cannot remove it.
* The HV path had no polarity reversal (K4 serves the NORMAL input only), so thermal EMF and DMM
  offset could not be nulled by ABBA the way they are on the normal ranges. That is exactly where
  more output would have helped, and it was the one thing the 1 ohm leg would not give.

A dedicated fixed divider has none of those constraints - it can pick its own low leg - so the HV
measurement moves out of this instrument entirely. What this bought Rev A: `R34`, `J3`, `SW1` and
the panel toggle, `R24`/`R25`/`C5`, the `J9`/P3 harness, the `HV` netclass and its three creepage
and clearance rules, and 11 mm of board.

## Status

Rev A: sent to OSH Park for fabrication on 2026-09-11 (git tag `rev-a`). Schematics ERC-clean;
PCB placed, routed and silkscreen tidied: DRC 0 errors, 0 unconnected, 56 benign
silkscreen-clipped-by-mask warnings.

### Fabrication files

`hardware/fab/` holds the Gerbers and drill files exactly as sent to OSH Park - byte for byte, so
`.gitattributes` marks the folder `-text` and git leaves their CRLF line endings alone. The zip that
was uploaded is just these files zipped and is not committed. Two things to know about them:

* They were plotted before the revision was renamed, so their metadata still says `Rev0`
  (`TF.ProjectId` in every Gerber, `Revision` in the job file). The copper is the tagged board's:
  re-plotting the board and diffing against these files leaves only the creation date and the drill
  marks.
* They were plotted with drill marks **off**. The board file's stored plot settings have them on
  (small), so `kicad-cli pcb export gerbers --board-plot-params` adds a 0.3 / 0.35 mm flash at every
  hole on the copper and mask layers. Turn them off when re-plotting for comparison or for a re-order.

## Repository layout

```
docs/                      design specification, notes
docs/datasheets/           vendor datasheets (git-ignored, copyrighted; see docs/datasheets list below)
hardware/                  KiCad 10 project
  nanovolt-divider.kicad_pro
  nanovolt-divider.kicad_sch   root sheet: metrology topology (inputs, relays, high legs, 1 ohm, outputs)
  control.kicad_sch            ESP32 display-module harness, MCP23017, TMP275, power
  relay_channel.kicad_sch      generic latching-relay channel, instantiated 5x (K1..K5)
  nanovolt-divider.kicad_pcb   board: 60 x 69.1 mm, 2 layers, placed and routed
  nanovolt-divider.kicad_dru   custom DRC rules (1 ohm bridge track width)
  lib/                         project-local symbol and footprint libraries
  fab/                         Rev A Gerbers and drill files, as sent to OSH Park
tools/gen_schematics.py    bootstrap script that produced the first version of the schematics
tools/gen_pcb.py           bootstrap script that produced the placed (unrouted) board
tools/route_pcb.py         bootstrap maze router that produced the first routing (see Routing below)
tools/route_hand.py        its hand routes and routing policy - the design intent of the routing
tools/pcb_io.py            pcbnew side of the router: dump pads, apply routes
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

K5 does the same for the source as a whole: pole A breaks the high side (`RANGE_BUS` -> `MEAS_NODE`)
and pole B breaks the return (`SRC_RTN` -> `ANALOG_RTN`). In ISOLATE the programmable source is
disconnected from the 1 ohm and the DMM path at both ends, so nothing of the source - not its output
capacitance, not its leakage to earth - remains attached to the measurement node.

### Control wiring

* Controller: integrated 2.8" ESP32 touch-TFT module (ESP32-2432S028R type, ELEGOO), off-board,
  connected by two harnesses (P1: 5 V / GND, CN1: I2C + 3V3).
* Those harnesses are the module's own pigtails, **soldered** to pads at the board end - there is no
  board-side connector. The module end keeps its connector, so the display still unplugs. This is
  why: the module side is a 1.25 mm-class connector, so a board-side header would have meant
  crimping a bespoke pitch-bridging cable for a joint that never needs to unmate, and the panel
  jacks (`J1`, `J2`, `J5`, `J6`) are already hard-wired the same way.
* Only the six live conductors have pads: `J7` = P1 pins 3/4, `J8` = CN1 pins 1-4. The pads keep
  the *module's* pin numbering rather than being renumbered 1..n. Both GND wires are run: P1's
  returns the pulsed coil current and CN1's serves I2C. Same net, but two conductors cut the
  cable-side shared IR drop - do not collapse them to one wire.
* MCP23017 (I2C 0x20) drives the ten coil lines: GPB0..GPB7 = K4 SET, K4 RESET, K1 SET, K1 RESET,
  K2 SET, K2 RESET, K3 SET, K3 RESET; GPA0 = K5 RESET, GPA1 = K5 SET; GPA2..GPA7 spare. The order
  is the board's, not the relays': GPB0..GPB7 are the package row that faces the driver columns, and
  in the columns' left-to-right order the lines fan out without a single crossing or via (see
  Routing). The firmware maps GPIO to coil by table.
* TMP275 (I2C 0x48, `A2:A0` all on `DGND`) sits next to the 1 ohm resistor, thermal proximity only.
  It replaced a TMP117 because the whole board is hand-soldered and the TMP117 only comes in a
  DSBGA-6 at 0.4 mm ball pitch. The price is absolute accuracy - +/-0.5 C and 12-bit (0.0625 C)
  instead of +/-0.1 C and 16-bit - which is not what this sensor is for: it tracks the *change* in
  the 1 ohm region's temperature for the optional ratio correction, and that needs short-term
  repeatability, not absolute accuracy. The address is unchanged, so nothing on the bus moves.
* The control ground is the global net `DGND`, deliberately not `GND`, so it cannot be merged with
  the floating analog return (`SRC_RTN` / `ANALOG_RTN`) by accident.

## Working with the schematics

Open `hardware/nanovolt-divider.kicad_pro` in KiCad 10. The project library
`hardware/lib/nanovolt-divider.kicad_sym` holds the TQ2-L2-5V relay, the TMP275, the `DGND` power
symbol and the two ESP32 harness pigtail landings - these carry the module's own pin names
(`SCL_IO22`, `SDA_IO27`, ...) rather than `Pin_1..Pin_4`, so a wire on the wrong pin is visible in
the schematic instead of looking plausibly correct. Footprints for the relay, the precision
resistors and the harness pads are in `hardware/lib/nanovolt-divider.pretty`; the TMP275 uses the
stock `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`. Everything else is stock KiCad.

Run ERC / exports from the command line:

```
kicad-cli sch erc --severity-all --exit-code-violations hardware/nanovolt-divider.kicad_sch
kicad-cli sch export pdf --output build/schematic.pdf hardware/nanovolt-divider.kicad_sch
kicad-cli pcb drc --severity-error --severity-warning hardware/nanovolt-divider.kicad_pcb
```

None of the generator scripts runs DRC - run it yourself with the command above. The baseline is
0 errors, 0 unconnected, 0 schematic-parity issues and 56 `silk_over_copper` warnings (silkscreen
clipped by solder mask at pad openings, which the fab does anyway; judged benign). Check that a change
does not add to it.

`tools/gen_schematics.py` generates all schematic files, the project symbol library and the
project footprints; re-run it after editing the script. It will **not** overwrite an existing
`nanovolt-divider.kicad_pro` - KiCad owns that file, and it holds the DRC severities.

### Regenerating the board produces a huge, meaningless diff

The board is routed now, and `tools/gen_pcb.py` writes an unrouted one from scratch: re-running it
throws the routing away. If you must, re-run the routing pipeline (see Routing) straight after, and
know that any hand edits made in KiCad since are gone either way.

`tools/gen_pcb.py` is **not idempotent**, and this has been rediscovered three times. `kicad-cli pcb
upgrade` assigns fresh random UUIDs to the graphics it materialises inside stock footprints, so
about 683 of the board's ~1400 UUIDs change on *every* run. Re-running the script with no edits at
all still reports ~680 changed lines. On top of that `kicad-cli` writes CRLF while `.gitattributes`
pins the repo to LF, so git warns about line endings too.

Neither is a real change. Before you act on a board diff, normalise both and compare again:

```python
import re, io, subprocess
strip = lambda t: re.sub(r'"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"', '"U"',
                         t.replace("
", "
"))
cur  = io.open("hardware/nanovolt-divider.kicad_pcb", "rb").read().decode("utf-8")
head = subprocess.run(["git", "show", "HEAD:hardware/nanovolt-divider.kicad_pcb"],
                      capture_output=True).stdout.decode("utf-8")
print(strip(head) == strip(cur))    # True -> nothing changed; restore the file, do not commit it
```

Read both sides as bytes and decode UTF-8 explicitly. Decoding one side through
`subprocess.run(text=True)` uses the locale codec and manufactures fake differences around non-ASCII
characters - KiCad's stock `SolderWire` footprint description genuinely contains a U+FFFD, which is
in the vendor file and not corruption.

What actually proves a board change is real: the exported netlist, and an ERC/DRC comparison against
the previous run. Not the file diff.

`tools/gen_schematics.py` does not have this problem - it writes its files directly with derived
UUIDs and never round-trips through `kicad-cli`, so re-running it leaves the working tree clean.

## Board

`hardware/nanovolt-divider.kicad_pcb` is placed and routed (first pass; see Routing below):

* 60 x 69.1 mm portrait, two layers, laid out top-down: one control band, ten coil-driver columns,
  the five relays, then the three high legs flat in one row.
* **The control band is a single row**, not a harness row above an MCP23017 row:
  `[H1] P1/CN1 | C3,C4 | R21,R22 | U1 | R23,C1 [H2]`. The harness pads are 2.9 mm tall against
  `U1`'s 11.9, so putting them beside it rather than above it costs no height at all - 3.4 mm off
  the board. `P1` is stacked above `CN1`: side by side the two groups are 17.2 mm wide and the band
  needs 48.2 mm of the 49.1 mm available, which does not fit. They are separate 4-pin connectors on
  the module and therefore separate pigtails, so one landing above the other crosses nothing. What
  sets the column gaps is each column's *designator*, which sits 1.85 mm to its left, not the parts.
* **The passive columns follow the nets.** `U1`'s `VDD`/`VSS`/`SCL`/`SDA` are all on its lower pad
  row at x 36-41 and `~RESET` on the upper row; power and I2C both arrive at the harness on the far
  left. So the bulk caps sit at the power entry, the I2C pull-ups sit between `CN1` and `U1` - so
  the bus runs left to right instead of doubling back past the chip, which is what it did when they
  were on the far side - and `C1` sits right of `U1`, the closest slot to its mid-row power pins.
  Measured against the previous arrangement: SCL bus 56.1 -> 35.3 mm, SDA 41.1 -> 34.5 mm,
  `C4` to the 3V3 entry 32.1 -> 7.2 mm, `C1` to `VDD` 16.3 -> 11.2 mm.
* **Driver cells.** Each relay carries its SET/RESET driver pair directly above it, so
  `RANGE_BUS` runs as one short chain across the three cells instead of a long row-to-row bus.
* **The three high legs lie flat in one row** under the relays, rather than standing vertically
  one per cell. Standing, each was 16 mm tall and `R33` reached y 67.7 - that, not the mounting
  holes, was what held the slots and the whole 1 ohm island down the board. Flat they are 3.2 mm
  tall and the row clears the relays by 0.55 mm. They no longer align one-per-relay, because they
  cannot: three 12 mm-plus resistors do not fit in three 10.2 mm relay cells. Nothing is lost by
  that - `A_NO` and `B_NO` are both on the relay's *upper* contact row, so a resistor hanging below
  the relay never landed across them either; it ran 14 mm to one and 24 mm to the other. Flat and
  offset, both runs are 2-5 mm.
* **M2 mounting holes, not M3.** The hole is 1 mm smaller but the courtyard radius drops
  3.45 -> 2.45, and both ends of that count: the top sets how close the hole sits under `K4`/`K5`,
  the bottom sets how close the slots sit under the hole. Worth 1.5 mm of board height for screws
  that only hold a 60 x 69.1 mm board in an enclosure. The lower pair now sits in the same band as
  the high-leg row, flanking it at the board edges.
* There is no strict warm/quiet partition any more. The relay coils are pulsed for 10-20 ms and
  never held, so their average dissipation is ~0 and co-locating them with the range resistors
  costs nothing while making the routing far shorter. What is preserved is the part that actually
  matters for thermal EMF: the continuously powered parts (MCP23017, harness pads, bulk caps) stay
  at the top edge, away from `MEAS_NODE`, and the 1 ohm strip stays physically isolated.
* The 1 ohm strip is separated by two slots that leave a 10 mm centre bridge and 3 mm bridges at
  both board edges for stiffness; `MEAS_NODE`, `ANALOG_RTN` and the TMP275 lines cross the centre
  one. The OUT HI / OUT LO wire pads are at the resistor's own terminals. Both lower mounting holes
  sit *above* the slots: a screw on the island would add a thermal and mechanical-stress path
  straight to the precision resistor.
* The TMP275 sits on that island above `R35`, not over the resistor body: a SOIC-8 courtyard is
  5.4 mm tall and the band between the slots and `R35` is 5.38 mm. What couples the sensor to `R35`
  is the island, not the millimetre of air over the body. `U2`'s designator is on F.Fab and `R35`'s
  is at its pad-1 end (`REF_OVERRIDE` in `gen_pcb.py`) - there is no silk line left between them.
* **`J1` / `J2` sit beside `K4`, not below it.** In the 4.85 mm strip left of the polarity relay
  they clear the lower-left mounting hole, and they land opposite the K4 pole-B contacts they wire
  to. While they were below the relay row they pinned that hole - and through it the slots and the
  whole 1 ohm island - 11 mm further down the board.
* `DGND` pour on B.Cu covers the digital circuitry (control cluster and coil drivers). The only
  copper keepout is over the isolated 1 ohm island.
* Panel parts (four banana jacks) terminate on solder-wire pads. Nothing is wired panel-to-panel,
  so every conductor appears in the netlist.

DRC is clean (0 errors, 0 unconnected, 0 schematic-parity issues) apart from 56 benign
silkscreen-clipped-by-mask warnings.

### Routing

The routing came from `tools/route_pcb.py`: a grid maze router that routes around a set of
hand-laid tracks in `tools/route_hand.py`. The hand-laid part is the design - the precision path,
the driver cells and the whole control band; the router only filled in the rest (the precision
chains between relays, +5V to the coils, DGND ties). Rules the routing follows, and that hand edits
should keep:

* **`MEAS_NODE` and `ANALOG_RTN` run as one tight pair on B.Cu** from K5 to R35: 0.4 mm, 0.3 mm
  apart, via-free. `ANALOG_RTN` is on the side facing the high-leg pads, so it rather than
  `MEAS_NODE` takes any surface leakage from `R*_IN`. The pair crosses the centre bridge on the
  board's centre line and only splits under R35, along its axis, so the current loop is the
  resistor itself and both terminals have the same copper path back to the board.
* **Kelvin at R35.** The injection current lands on R35's pads from the inside; J5 / J6 (the DMM)
  leave them on the outside on F.Cu, and carry no current.
* **Source-side and low-side copper keep 0.5 mm apart on the same layer.** `SRC_P`, `NORMAL_IN_*`
  and `R*_IN` sit at the source voltage; `RANGE_BUS`, `R*_OUT` and `MEAS_NODE` at the bottom of the
  selected high leg. Leakage between them is a resistor across the high leg - 10 ppm at 1e12 ohm on
  the 10 M range. Where the two chains must cross they do it on opposite layers, through 1.6 mm of
  FR4 bulk. `SRC_RTN` / `ANALOG_RTN` are in neither class: leakage into them only loads the source.
* **Nothing reaches the 1 ohm island except over the centre bridge**, and the bridge carries no
  vias. A track over an edge bridge brings heat in at one end of R35, and a temperature difference
  between its terminals is a thermal EMF in series with the measurement.
* **The TMP275 lines are one F.Cu spine**: SDA, SCL, DGND, +3V3 at 0.65 mm pitch, down the gap
  between the K1 and K2 driver pairs, through the left half of K2, under R32's body and onto the
  island left of the pair. The precision chains cross it on B.Cu.
* **Driver cells are identical.** Each column is the same template: the base node runs straight
  from the 1k to the 10k, which is why R1-R20 sit at 270 degrees rather than 90 (at 90 the MCP23017
  line landed on the 1k's lower pad and the base node had to run past it). DGND goes to the B.Cu
  pour through a via beside the 10k and one beside the emitter; cathodes drop to a +5V bus on B.Cu
  at y 32.5 along the bottom of the pour.
* **One coil crossing per relay, the same for all five.** The SET column feeds the right-hand coil
  pin and the RESET column the left, so they cross: SET stays on F.Cu, RESET drops to B.Cu. That
  way round leaves the left half of each relay's top free on F.Cu, which is how the TMP275 spine
  gets into K2.
* **The MCP23017 fan-out has no crossings and no vias.** That is the GPIO order above, not the
  routing: eight lines drop off U1's lower row in the driver columns' order, five of them left in
  0.2 mm lanes at 0.4 mm pitch (four is all that fits between pin 1 and R7's pad), and K5's two leave
  under the package to the right. SDA, SCL and 3V3 reach U1 under its body, stacked in the order
  they drop to pins 13, 12 and 9. Before the remap the same ten lines took 30 vias and 237 mm; now
  161 mm and none.
* **What the control band still needs vias for**, and why each is unavoidable: the TMP275 spine's
  SDA, SCL and 3V3 each rise on B.Cu past the coil lanes (the spine runs between U1 and the K4/K1
  columns, so every ordering crosses it); R21's 3V3 pad is fenced in by SDA and SCL; and C1/R23 sit
  beyond the K5 lines, so their 3V3 hops from pin 9 on B.Cu. SDA and SCL squeeze between C3 and C4
  in two 0.2 mm lanes; +5V comes down the left edge from P1.

The router is deterministic and reproduces the committed routing exactly, but `pcb_io.py apply`
deletes every track first, so it is historical as soon as the board is edited by hand:

```
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py dump  hardware/nanovolt-divider.kicad_pcb %TEMP%/nvd_geom.json
uv run tools/route_pcb.py %TEMP%/nvd_geom.json %TEMP%/nvd_routes.json
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py apply hardware/nanovolt-divider.kicad_pcb %TEMP%/nvd_routes.json
```

## Open items

* Firmware: the GPIO-to-coil table must follow the layout order above (GPB0..GPB7, GPA0 = K5
  RESET, GPA1 = K5 SET), not the relay numbering.
* Confirm the display module variant and its connector pinout (P1 / CN1) against the board in
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
TI TMP275.

## License

To be decided before the repository is made public (hardware: CERN-OHL-P or similar; firmware: MIT).
