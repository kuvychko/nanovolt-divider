# nanovolt-divider

Programmable nanovolt divider / precision attenuator: a compact bench instrument that turns an
ordinary programmable DC source into a calibrated nanovolt-to-microvolt signal by **passive resistive
attenuation** (1e-5 / 1e-6 / 1e-7), with relay-controlled polarity reversal and a true-zero
(isolate) function, read by an external precision DMM.

The design rationale, architecture, relay rules, calibration model and Rev0 BOM live in
[docs/nanovolt_divider_rev0.md](docs/nanovolt_divider_rev0.md).

### The 450 V path was removed

Rev0 originally carried a second, passive input for measuring a ~450 V Geiger-counter supply,
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
measurement moves out of this instrument entirely. What this bought Rev0: `R34`, `J3`, `SW1` and
the panel toggle, `R24`/`R25`/`C5`, the `J9`/P3 harness, the `HV` netclass and its three creepage
and clearance rules, and 11 mm of board.

## Status

Rev0: architecture locked, schematics ERC-clean, PCB placed and DRC-clean (unrouted).

## Repository layout

```
docs/                      design specification, notes
docs/datasheets/           vendor datasheets (git-ignored, copyrighted; see docs/datasheets list below)
hardware/                  KiCad 10 project
  nanovolt-divider.kicad_pro
  nanovolt-divider.kicad_sch   root sheet: metrology topology (inputs, relays, high legs, 1 ohm, outputs)
  control.kicad_sch            ESP32 display-module harness, MCP23017, TMP275, power
  relay_channel.kicad_sch      generic latching-relay channel, instantiated 5x (K1..K5)
  nanovolt-divider.kicad_pcb   board: 60 x 72.5 mm, 2 layers, placed, not yet routed
  nanovolt-divider.kicad_dru   custom DRC rules (1 ohm bridge track width)
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
* MCP23017 (I2C 0x20) GPA0..GPA7 + GPB0..GPB1 drive the ten coil lines K1..K5 SET/RESET.
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

Neither generator script runs DRC - run it yourself with the command above. It will **not** come
back clean while the board is unrouted: every net reports as unconnected, and the silkscreen
reports over pads. Treat the current count as the baseline and check that a change does not add to
it, rather than expecting zero.

`tools/gen_schematics.py` generates all schematic files, the project symbol library and the
project footprints; re-run it after editing the script. It will **not** overwrite an existing
`nanovolt-divider.kicad_pro` - KiCad owns that file, and it holds the DRC severities.

### Regenerating the board produces a huge, meaningless diff

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

`hardware/nanovolt-divider.kicad_pcb` is placed but unrouted:

* 60 x 72.5 mm portrait, two layers, laid out top-down: display-module harness pads, the
  MCP23017 (horizontal, caps and pull-ups in columns on both sides), ten coil-driver columns, the
  five relays, then the three high legs flat in one row.
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
  that only hold a 60 x 72.5 mm board in an enclosure. The lower pair now sits in the same band as
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

DRC is clean (0 errors, 0 schematic-parity issues) apart from the unrouted ratsnest and
silkscreen-over-pad warnings (reference designators still need tidying after routing).

## Open items

* Route the board (interactively, or Freerouting), then tidy silkscreen.
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
