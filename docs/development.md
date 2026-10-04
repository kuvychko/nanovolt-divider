# Development

Working on the KiCad design: opening it, the ERC/DRC baseline, the generators and router, and the
fabrication files. Commands run from the repository root. The circuit and board themselves are described in
[hardware.md](hardware.md).

## Working with the design files

Open `hardware/nanovolt-divider.kicad_pro` in KiCad 10. The project library
`hardware/lib/nanovolt-divider.kicad_sym` holds the TQ2-L2-5V relay, the TMP275, the `DGND` power
symbol and the two ESP32 harness pigtail landings. These carry the module's own pin names
(`SCL_IO18`, `SDA_IO27`, ...) rather than `Pin_1..Pin_4`, so a wire on the wrong pin is visible in
the schematic. The harness footprints are kept exactly as fabricated (`HARNESS_PADS_REV_A` in
`gen_schematics.py`), which is why their F.Fab names differ; see
[Display harness](hardware.md#display-harness). Footprints for the
relay, the precision resistors and the harness pads are in `hardware/lib/nanovolt-divider.pretty`;
the TMP275 uses the stock `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`. Everything else is stock KiCad.

ERC, DRC and exports from the command line:

```
kicad-cli sch erc --severity-all --exit-code-violations hardware/nanovolt-divider.kicad_sch
kicad-cli sch export pdf --output build/schematic.pdf hardware/nanovolt-divider.kicad_sch
kicad-cli pcb drc --severity-error --severity-warning hardware/nanovolt-divider.kicad_pcb
```

The baseline is ERC clean, and DRC 0 errors, 0 unconnected and 56 `silk_over_copper` warnings
(silkscreen clipped by solder mask at pad openings, which the fab does anyway). With
`--schematic-parity` there are also 2 `footprint_symbol_field_mismatch` warnings: the Description
field of `J7` and `J8` names the display module, while the board keeps the fabricated text. They
are metadata only. Check that a change does not add to this baseline.

### Generators

`tools/gen_schematics.py` generates all schematic files, the project symbol library and the project
footprints; re-run it after editing the script. It will **not** overwrite an existing
`nanovolt-divider.kicad_pro`, which KiCad owns and which holds the DRC severities. It writes its
files directly with derived UUIDs, so re-running it leaves the working tree clean.

`tools/gen_pcb.py` writes a placed, **unrouted** board from scratch, so running it discards the
routing and any hand edits. The router then reproduces the committed routing exactly (it deletes
every track before applying its own):

```
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py dump  hardware/nanovolt-divider.kicad_pcb %TEMP%/nvd_geom.json
uv run tools/route_pcb.py %TEMP%/nvd_geom.json %TEMP%/nvd_routes.json
"C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py apply hardware/nanovolt-divider.kicad_pcb %TEMP%/nvd_routes.json
```

**A regenerated board produces a large, meaningless diff.** `kicad-cli pcb upgrade` assigns fresh
random UUIDs to the graphics it materialises inside stock footprints, so about 683 of the board's
~1400 UUIDs change on every run, and `kicad-cli` writes CRLF while `.gitattributes` pins the repo to
LF. Neither is a real change. Before acting on a board diff, normalise both sides and compare:

```python
import re, io, subprocess
strip = lambda t: re.sub(r'"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"', '"U"',
                         t.replace("\r\n", "\n"))
cur  = io.open("hardware/nanovolt-divider.kicad_pcb", "rb").read().decode("utf-8")
head = subprocess.run(["git", "show", "HEAD:hardware/nanovolt-divider.kicad_pcb"],
                      capture_output=True).stdout.decode("utf-8")
print(strip(head) == strip(cur))    # True -> nothing changed; restore the file, do not commit it
```

Read both sides as bytes and decode UTF-8 explicitly. Decoding one side through
`subprocess.run(text=True)` uses the locale codec and manufactures fake differences around non-ASCII
characters - KiCad's stock `SolderWire` footprint description genuinely contains a U+FFFD.

What proves a board change is real is the exported netlist and an ERC/DRC comparison, not the
file diff.

## Fabrication files

`hardware/fab/` holds the Rev A Gerbers and drill files exactly as sent to the fab (OSH Park, git
tag `rev-a`). `.gitattributes` marks the folder `-text` so git leaves their CRLF line endings alone.
To order boards, zip the folder's contents. Two things to know about them:

* Their metadata says `Rev0` (`TF.ProjectId` in every Gerber, `Revision` in the job file). The
  copper is the Rev A board's: re-plotting the board and diffing against these files leaves only the
  creation date and the drill marks.
* They are plotted with drill marks **off**. The board file's stored plot settings have them on
  (small), so `kicad-cli pcb export gerbers --board-plot-params` adds a 0.3 / 0.35 mm flash at every
  hole on the copper and mask layers. Turn them off when re-plotting.
