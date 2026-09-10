#!/usr/bin/env python3
"""
Bootstrap PCB generator for the nanovolt-divider Rev0 board.

Produces hardware/nanovolt-divider.kicad_pcb with:
  * board outline (60 x 69.1 mm portrait) with two slots that isolate the 1 ohm strip except for a
    10 mm centre bridge and 3 mm bridges at both edges
  * every schematic footprint placed with the design rules from docs/nanovolt_divider_rev0.md
    (control cluster on top, then one self-contained cell per relay - drivers, relay and its own
    high-leg resistor - the HV parts spaced, and the 1 ohm strip isolated behind two slots)
  * pad nets from the exported schematic netlist (so KiCad shows the ratsnest immediately)
  * DGND fill on B.Cu over the digital circuitry (control cluster + coil drivers), a no-pour
    keepout over the isolated 1 ohm island only, four M3 mounting holes and silkscreen labels
  * hardware/nanovolt-divider.kicad_dru with the 450 V clearance / creepage rules

No tracks are routed.  Run once, then route in KiCad; after that the .kicad_pcb is the source
of truth and this script is historical.

Re-running is not idempotent: `kicad-cli pcb upgrade` assigns fresh random UUIDs to the graphics
it materialises inside stock footprints, so ~705 of the board's ~1521 UUIDs change every run and
the file reads as heavily modified even when nothing about the board did.  (The 816 the generator
derives itself, via G.U(), are stable.)  Diff with UUIDs normalised before believing a change is
real.

Usage: python tools/gen_pcb.py

It shells out to kicad-cli twice: once to export the schematic netlist it reads pad nets from, and
once to upgrade the board it just wrote to the current file format.  It does NOT run DRC - run that
yourself (the command is in README.md).  Expect a non-empty report: the board is unrouted, so every
net shows as unconnected, and the silkscreen sits over pads that have no soldermask openings routed
around them yet.  Compare against the previous run rather than expecting zero.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_schematics as G  # noqa: E402
from gen_schematics import U, q, unq, parse, dump, find, find_all  # noqa: E402

KICAD_CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
SHARE = r"C:\Program Files\KiCad\10.0\share\kicad"
HW = G.HW
PROJECT = G.PROJECT
BOARD = os.path.join(HW, f"{PROJECT}.kicad_pcb")

OX, OY = 50.0, 50.0          # board origin on the KiCad sheet
W, H = 60.0, 69.1            # board size (portrait: control on top, precision below).  24.9 mm shorter
                             # than it was before the HV divider came out.  Row 7 (the 3PDT wire pads
                             # and the HV island) is gone outright, and with J1/J2 moved up beside K4
                             # the lower mounting holes could follow the slots up by the same 20 mm.
                             # 9 mm more came from laying R31-R33 flat (see row 5): standing
                             # vertically they reached y 67.7 and were what held the slots down.
                             # The last 3.4 mm came from folding the harness pads into the MCP23017
                             # row (see row 1) instead of giving them a row of their own.
SHIFT_Y = 9.4                # uniform upward shift applied to every row below the harness pads.  A
                             # single translation keeps all the reviewed relative spacing - slot
                             # geometry, HV island separation, the 1 ohm strip - exactly as it was.
NOTCH_Y = (54.1, 55.7)       # two slots isolating the 1 ohm strip
EDGE_BRIDGE = 3.0            # material left at both board edges beside the slots
NOTCH_BRIDGE = (25.0, 35.0)  # centre bridge left between the notches (MEAS, RTN, TMP275 lines)
DGND_MAX_Y = 32.6            # DGND pour limit: it follows the digital circuitry (control + coil
                             # drivers), not an arbitrary cut across the board.  There is no blanket
                             # keepout below it any more - only the 1 ohm island is kept clear.


# --------------------------------------------------------------------------------------
# Placement table: ref -> (x, y, rotation) in board coordinates (origin top-left, y down)
# --------------------------------------------------------------------------------------

RELAY_X = {"K4": 9.6, "K1": 19.8, "K2": 30.0, "K3": 40.2, "K5": 50.4}   # relay row, pitch 10.2
RELAY_Y = 50.0


# Harness pads: six live conductors, grouped P1 | CN1, in the left end of the control band rather
# than in a row of their own.  They are 2.9 mm tall against U1's 11.9, so beside it they cost no
# height at all - which is the whole 3.4 mm.  P1 and CN1 are separate 4-pin connectors on the
# module, so these are two independent pigtails and nothing has to cross.
# P3 went with the HV mode sense - IO35 was the only thing it carried.
# Footprint origin is the lowest-numbered pad; pads run left to right at PAD_PITCH (2.54 mm).
# Kept clear of the M2 hole at x = 3.
# P1 stacked above CN1 rather than beside it.  Side by side the two groups are 17.2 mm wide, and
# once every column's designator is counted the band needs 48.2 mm of the 49.1 mm between the top
# mounting holes - it does not fit.  Stacked the block is 11.1 mm wide and 7.7 mm tall, which still
# clears U1's 11.9 mm band, so the width comes free.  They are separate 4-pin connectors on the
# module and therefore separate pigtails, so one landing above the other crosses nothing.
HARNESS_POS = {"J7": (7.9, 2.2),                   # P1  pads 3,4   - upper, x 6.45..12.49
               "J8": (7.9, 7.0)}                   # CN1 pads 1-4   - lower, x 6.45..17.57


def placement() -> dict:
    P = {}
    # ---- row 1: display-module harness pigtail pads (flat, no body, no mating envelope) -----------
    for _ref, (_hx, _hy) in HARNESS_POS.items():
        P[_ref] = (_hx, _hy, 0)
    # ---- row 1 continued: MCP23017 horizontal, flanked by caps and pull-ups, right of the harness ----
    # The whole control band is now one row: [H1] J7 J8 | C1/C3 | U1 | C4/R21 | R22/R23 [H2], which
    # fits x 6.45..53.73 of the 49.1 mm between the two top mounting holes.  The gaps are set
    # by each column's *designator*, which sits 1.85 mm to its left, not by the parts.
    P["U1"] = (34.4, 16.5, 90)
    P["C1"] = (21.2, 13.5, 90)                  # 100n at VDD
    P["C3"] = (21.2, 19.0, 90)                  # 22u 5 V bulk
    P["C4"] = (47.6, 13.5, 90)                  # 22u 3V3 bulk
    P["R21"] = (47.6, 19.0, 90)                 # SDA pull-up
    P["R22"] = (52.6, 13.5, 90)                 # SCL pull-up
    P["R23"] = (52.6, 19.0, 90)                 # ~RESET pull-up
    # ---- row 3: coil drivers, one SET and one RESET column above each relay ---------------------------
    for n, kref in enumerate(("K1", "K2", "K3", "K4", "K5"), 1):
        kx = RELAY_X[kref]
        for dx, rb, rp, qq, dd in ((-2.0, 4 * n - 3, 4 * n - 2, 2 * n - 1, 2 * n - 1),
                                   (2.0, 4 * n - 1, 4 * n, 2 * n, 2 * n)):
            x = kx + dx
            P[f"R{rb}"] = (x, 26.0, 90)         # 1k base
            P[f"R{rp}"] = (x, 30.8, 90)         # 10k pulldown
            P[f"Q{qq}"] = (x, 35.0, 0)          # MMBT2222A
            P[f"D{dd}"] = (x, 39.2, 90)         # 1N4148W
    # ---- row 4: relays (rotation 90: coil pins 5/6 face down, contact pins face the resistors) -------
    for ref, x in RELAY_X.items():
        P[ref] = (x, RELAY_Y, 90)
    # ---- row 5: the three high legs, flat in one row under the relays --------------------------------
    # Standing them vertically under their own relays cost 16 mm of height each and put the bottom of
    # R33 at y 67.7, which is what held the slots - and the whole 1 ohm island - down the board.  Flat
    # they are 3.2 mm tall, and the row clears the relays by 0.55 mm.
    #
    # They no longer sit one-per-cell, because they cannot: three 12+ mm resistors do not fit in three
    # 10.2 mm relay cells.  Nothing is lost by that - A_NO and B_NO are both on the relay's *upper*
    # contact row (y 41.46), so a vertical resistor hanging below the relay never landed across them
    # either; it ran 14 mm to one and 24 mm to the other.  Flat and offset, both runs are ~2-5 mm.
    #
    # rotation 180 so pad 1 (R*_IN, from A_NO) is on the right, matching A_NO's side of the relay.
    P["R31"] = (21.0, 59.4, 180)                # 100k (MOX-700),  pads at x 21.0 / 10.84
    P["R32"] = (34.0, 59.4, 180)                # 1M   (MOX-700),  pads at x 34.0 / 23.84
    P["R33"] = (48.5, 59.4, 180)                # 10M  (Slim-Mox), pads at x 48.5 / 38.34
    # ---- row 6: NORMAL IN pads, genuinely beside K4 now rather than below it -------------------------
    # They used to sit under the relay row, which put them directly above the left mounting hole and
    # pinned it - and through it the slots and the whole 1 ohm island - 10 mm lower than it needed to
    # be.  In the 4.85 mm strip left of K4 they clear the hole entirely, and the run to K4's pole A /
    # pole B contacts gets shorter into the bargain.
    P["J1"] = (2.5, 48.0, 0)                    # NORMAL IN +, beside K4 pin 7 (pole B NO)
    P["J2"] = (2.5, 54.0, 0)                    # NORMAL IN -, beside K4 pin 9 (pole B NC)
    # ---- row 7: 1 ohm strip behind the slots ---------------------------------------------------------
    # The 1 ohm row sits 1.5 mm lower than it did with the TMP117.  A SOIC-8 courtyard is 5.4 mm
    # tall and the band between the slots and R35 was 5.38 mm, so U2 had to gain room somewhere;
    # taking it from the bottom margin keeps the slots, the mounting holes and everything above
    # them exactly where the Rev0 review left them.  R35's silk still clears the board edge by
    # 0.6 mm and its pads by 2.5 mm.
    P["R35"] = (19.84, 75.0, 0)                 # 1 ohm (RS-2C), pads at x = 19.84 / 40.16
    P["J6"] = (14.5, 75.0, 0)                   # DIVIDER OUT LO at the pad-1 end
    P["J5"] = (45.5, 75.0, 0)                   # DIVIDER OUT HI at the pad-2 end
    # TMP275 in SOIC-8 is 7.4 x 5.4 mm over the courtyard, far larger than the TMP117 DSBGA it
    # replaced, so it no longer fits in the gap over the resistor body.  It sits on the same
    # thermally isolated island, centred on the resistor's midpoint, 0.7 mm below the slots and
    # 0.8 mm above R35's courtyard - the island is what couples it to R35, not the millimetre of
    # air over the body.
    P["U2"] = (30.0, 68.5, 0)                   # TMP275 (SOIC-8) on the 1 ohm island, above R35
    P["C2"] = (37.5, 68.5, 0)
    # Everything except the harness pads moves up by SHIFT_Y.  Doing it as one translation here,
    # rather than editing every literal above, keeps this table readable against the Rev0 review
    # notes and guarantees no row drifts relative to another.
    for ref, (x, y, rot) in P.items():
        if ref not in HARNESS_POS:
            P[ref] = (x, y - SHIFT_Y, rot)
    return P


# Reference-designator overrides: ref -> (local x, local y, layer).  The footprint's own refdes
# position is used everywhere else; these two are on the 1 ohm island, where a SOIC-8 and a 20 mm
# resistor share a 6.9 mm band between the slots and the board edge and the stock positions collide.
#   U2  - goes to F.Fab.  There is no silk line left for it: 0.7 mm above the part to the slot and
#         0.8 mm below to R35's courtyard.  The island is already labelled "1R + TMP275" in silk.
#         Same reasoning as the harness pads at the top edge.
#   R35 - moves from the body centre (where U2 now sits) to the pad-1 end, still on silk.
#   H1-H4 - to F.Fab.  The stock footprint puts the refdes 3.15 mm above the hole, which for the
#           top pair lands across the board edge; and a silk designator on a board_only part that
#           is excluded from the BOM and the pick-and-place is noise anyway.
REF_OVERRIDE = {
    "U2": (0.0, 0.0, "F.Fab"),
    "R35": (0.0, -3.92, "F.SilkS"),
    **{f"H{i}": (0.0, 0.0, "F.Fab") for i in (1, 2, 3, 4)},
}


# M2, not M3: the hole itself is only 1 mm smaller but the courtyard radius drops 3.45 -> 2.45, and
# both ends of that count here - the top sets how close the hole can sit under K4/K5, the bottom sets
# how close the slots can sit under the hole.  1.5 mm of board height, for screws that only hold a
# 60 x 72 mm board in an enclosure.
#
# The two lower holes sit ABOVE the slots: a screw on the 1 ohm island would add a thermal and
# mechanical-stress path straight to the precision resistor.  The island hangs on the two 3 mm
# edge bridges plus the 10 mm centre bridge, which is ample for a 15 mm strip.
MOUNTING_HOLES = [(3.0, 3.0), (57.0, 3.0), (3.0, 50.6), (57.0, 50.6)]


# --------------------------------------------------------------------------------------
# Netlist
# --------------------------------------------------------------------------------------

def export_netlist(path):
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "--output", path,
                    os.path.join(HW, f"{PROJECT}.kicad_sch")], check=True, capture_output=True)
    tree = parse(open(path, encoding="utf8").read())
    nets = []            # (code, name)
    pin_net = {}         # (ref, pin) -> name
    for net in find_all(find(tree, "nets"), "net"):
        code = int(unq(find(net, "code")[1]))
        name = unq(find(net, "name")[1])
        nets.append((code, name))
        for node in find_all(net, "node"):
            pin_net[(unq(find(node, "ref")[1]), unq(find(node, "pin")[1]))] = name
    return nets, pin_net


# --------------------------------------------------------------------------------------
# Footprint loading
# --------------------------------------------------------------------------------------

_fp_cache = {}


def load_footprint(lib_id):
    if lib_id in _fp_cache:
        return _fp_cache[lib_id]
    lib, name = lib_id.split(":", 1)
    cands = [os.path.join(HW, "lib", lib + ".pretty", name + ".kicad_mod"),
             os.path.join(SHARE, "footprints", lib + ".pretty", name + ".kicad_mod")]
    for c in cands:
        if os.path.exists(c):
            _fp_cache[lib_id] = parse(open(c, encoding="utf8").read())
            return _fp_cache[lib_id]
    raise FileNotFoundError(lib_id)


def deepcopy(node):
    return [deepcopy(c) for c in node] if isinstance(node, list) else node


def renew_uuids(node, keyprefix, counter):
    if isinstance(node, list):
        if node and node[0] == "uuid":
            counter[0] += 1
            node[1] = q(U(f"{keyprefix}:{counter[0]}"))
        else:
            for c in node:
                renew_uuids(c, keyprefix, counter)


def footprint_instance(ref, comp, x, y, rot, nets_by_name, pin_net, extra_attr=()):
    lib_id = comp["footprint"]
    src = deepcopy(load_footprint(lib_id))
    body = [c for c in src[2:] if not (isinstance(c, list) and c and c[0] in
                                       ("version", "generator", "generator_version", "property", "layer", "uuid", "embedded_fonts"))]
    props = {unq(p[1]): p for p in find_all(src, "property")}

    def prop(name, value, template=None, hide=False):
        if template is not None:
            p = deepcopy(template)
            p[2] = q(value)
            # property angle is absolute in board files
            at = find(p, "at")
            if at is not None and len(at) >= 4:
                at[3] = G.fmt((float(at[3]) + rot) % 360)
            elif at is not None:
                at.append(G.fmt(rot))
            return p
        h = ["hide", "yes"] if hide else None
        p = ["property", q(name), q(value), ["at", "0", "0", G.fmt(rot)], ["layer", '"F.Fab"']]
        if h:
            p.append(h)
        p.append(["uuid", q(U(f"pcb:{ref}:prop:{name}"))])
        p.append(["effects", ["font", ["size", "1", "1"], ["thickness", "0.15"]]])
        return p

    fp = ["footprint", q(lib_id), ["layer", '"F.Cu"'], ["uuid", q(U(f"pcb:{ref}:fp"))],
          ["at", G.fmt(OX + x), G.fmt(OY + y), G.fmt(rot)]]
    for tag in ("descr", "tags"):
        n = find(src, tag)
        if n:
            fp.append(n)
    refprop = prop("Reference", ref, props.get("Reference"))
    if ref in REF_OVERRIDE:
        ox_, oy_, layer = REF_OVERRIDE[ref]
        at = find(refprop, "at")
        at[1], at[2] = G.fmt(ox_), G.fmt(oy_)
        find(refprop, "layer")[1] = q(layer)
    fp.append(refprop)
    fp.append(prop("Value", comp["value"], props.get("Value")))
    fp.append(prop("Footprint", lib_id, hide=True))
    fp.append(prop("Datasheet", comp.get("datasheet", ""), hide=True))
    fp.append(prop("Description", comp.get("description", ""), hide=True))
    for k, v in comp.get("fields", {}).items():
        fp.append(prop(k, v, hide=True))
    if comp.get("path"):
        fp.append(["path", q(comp["path"])])
        fp.append(["sheetname", q(comp["sheetname"])])
        fp.append(["sheetfile", q(comp["sheetfile"])])
    attr = find(src, "attr")
    attr_items = [a for a in (attr[1:] if attr else []) if a != "exclude_from_bom" or comp.get("board_only")]
    attr_items += list(extra_attr)
    if attr_items:
        fp.append(["attr"] + attr_items)
    for c in body:
        if isinstance(c, list) and c and c[0] in ("descr", "tags", "attr"):
            continue
        if isinstance(c, list) and c and c[0] == "pad":
            num = unq(c[1])
            at = find(c, "at")
            if len(at) >= 4:
                at[3] = G.fmt((float(at[3]) + rot) % 360)
            else:
                at.append(G.fmt(rot))
            net = pin_net.get((ref, num))
            if net is not None:
                # insert net after layers
                idx = next(i for i, cc in enumerate(c) if isinstance(cc, list) and cc and cc[0] == "layers") + 1
                c.insert(idx, ["net", str(nets_by_name[net]), q(net)])
        fp.append(c)
    fp.append(["embedded_fonts", "no"])
    renew_uuids(fp[5:], f"pcb:{ref}", [0])
    return fp


# --------------------------------------------------------------------------------------
# Board
# --------------------------------------------------------------------------------------

LAYERS = '''(layers
	(0 "F.Cu" signal)
	(2 "B.Cu" signal)
	(9 "F.Adhes" user "F.Adhesive")
	(11 "B.Adhes" user "B.Adhesive")
	(13 "F.Paste" user)
	(15 "B.Paste" user)
	(5 "F.SilkS" user "F.Silkscreen")
	(7 "B.SilkS" user "B.Silkscreen")
	(1 "F.Mask" user)
	(3 "B.Mask" user)
	(17 "Dwgs.User" user "User.Drawings")
	(19 "Cmts.User" user "User.Comments")
	(21 "Eco1.User" user "User.Eco1")
	(23 "Eco2.User" user "User.Eco2")
	(25 "Edge.Cuts" user)
	(27 "Margin" user)
	(31 "F.CrtYd" user "F.Courtyard")
	(29 "B.CrtYd" user "B.Courtyard")
	(35 "F.Fab" user)
	(33 "B.Fab" user)
	(39 "User.1" user)
	(41 "User.2" user)
	(43 "User.3" user)
	(45 "User.4" user)
	(47 "User.5" user)
	(49 "User.6" user)
	(51 "User.7" user)
	(53 "User.8" user)
	(55 "User.9" user)
)'''

SETUP = '''(setup
	(pad_to_mask_clearance 0)
	(allow_soldermask_bridges_in_footprints no)
	(tenting front back)
	(pcbplotparams
		(layerselection 0x00000000_00000000_000010fc_ffffffff)
		(plot_on_all_layers_selection 0x00000000_00000000_00000000_00000000)
		(disableapertmacros no)
		(usegerberextensions no)
		(usegerberattributes yes)
		(usegerberadvancedattributes yes)
		(creategerberjobfile yes)
		(dashed_line_dash_ratio 12.000000)
		(dashed_line_gap_ratio 3.000000)
		(svgprecision 4)
		(plotframeref no)
		(mode 1)
		(useauxorigin no)
		(hpglpennumber 1)
		(hpglpenspeed 20)
		(hpglpendiameter 15.000000)
		(pdf_front_fp_property_popups yes)
		(pdf_back_fp_property_popups yes)
		(pdf_metadata yes)
		(pdf_single_document no)
		(dxfpolygonmode yes)
		(dxfimperialunits yes)
		(dxfusepcbnewfont yes)
		(psnegative no)
		(psa4output no)
		(plot_black_and_white yes)
		(plotinvisibletext no)
		(sketchpadsonfab no)
		(plotpadnumbers no)
		(hidednponfab no)
		(sketchdnponfab yes)
		(crossoutdnponfab yes)
		(subtractmaskfromsilk no)
		(outputformat 1)
		(mirror no)
		(drillshape 1)
		(scaleselection 1)
		(outputdirectory "")
	)
)'''

DRU = '''(version 1)

# The 1 ohm strip is reached only through the centre bridge between the two notches; keep those tracks narrow.
(rule "bridge tracks"
	(constraint track_width (max 0.4mm))
	(condition "A.intersectsArea('bridge_1ohm')"))
'''


def xy(x, y):
    return f"(xy {G.fmt(OX + x)} {G.fmt(OY + y)})"


def gr_rect(x1, y1, x2, y2, layer, key, width=0.05):
    return (f'(gr_rect (start {G.fmt(OX + x1)} {G.fmt(OY + y1)}) (end {G.fmt(OX + x2)} {G.fmt(OY + y2)}) '
            f'(stroke (width {width}) (type default)) (fill no) (layer "{layer}") (uuid "{U("pcb:" + key)}"))')


def gr_poly(pts, layer, key, width=0.05):
    return (f'(gr_poly (pts {" ".join(xy(*p) for p in pts)}) (stroke (width {width}) (type default)) (fill no) '
            f'(layer "{layer}") (uuid "{U("pcb:" + key)}"))')


def gr_text(txt, x, y, key, size=1.0, layer="F.SilkS", rot=0, justify="left bottom"):
    return (f'(gr_text {q(txt)} (at {G.fmt(OX + x)} {G.fmt(OY + y)} {rot}) (layer "{layer}") (uuid "{U("pcb:" + key)}") '
            f'(effects (font (size {size} {size}) (thickness {round(size * 0.15, 3)})) (justify {justify})))')


def zone_fill(net_code, net_name, layer, pts, name, key):
    return (f'(zone (net {net_code}) (net_name {q(net_name)}) (layer "{layer}") (uuid "{U("pcb:" + key)}") (name {q(name)}) '
            f'(hatch edge 0.5) (priority 0) (connect_pads (clearance 0.3)) (min_thickness 0.25) (filled_areas_thickness no) '
            f'(fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts {" ".join(xy(*p) for p in pts)})))')


def zone_rule_area(pts, name, key, layers=('F.Cu', 'B.Cu'), copperpour="not_allowed", tracks="allowed", vias="allowed"):
    ls = " ".join(f'"{l}"' for l in layers)
    return (f'(zone (net 0) (net_name "") (layers {ls}) (uuid "{U("pcb:" + key)}") (name {q(name)}) (hatch edge 0.5) '
            f'(connect_pads (clearance 0)) (min_thickness 0.25) (filled_areas_thickness no) '
            f'(keepout (tracks {tracks}) (vias {vias}) (pads allowed) (copperpour {copperpour}) (footprints allowed)) '
            f'(fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts {" ".join(xy(*p) for p in pts)})))')


def build():
    lib = G.SymbolLib(SHARE)
    proj = parse(G.project_symbol_lib_text())
    for s in find_all(proj, "symbol"):
        name = unq(s[1])
        s[1] = q(f"{PROJECT}:{name}")
        lib.defs[f"{PROJECT}:{name}"] = s
    sheets = {"relay": G.build_relay_channel(lib), "control": G.build_control(lib), "root": G.build_root(lib)}
    sheetnames = {f"/{G.ROOT_UUID}": ("/", f"{PROJECT}.kicad_sch"),
                  f"/{G.ROOT_UUID}/{G.CONTROL_UUID}": ("/CONTROL/", "control.kicad_sch")}
    for u, n, i in zip(G.RELAY_UUIDS, G.RELAY_NAMES, range(1, 6)):
        sheetnames[f"/{G.ROOT_UUID}/{u}"] = (f"/{n} (K{i})/", "relay_channel.kicad_sch")

    comps = {}
    for sh in sheets.values():
        for p in sh.placed:
            for path, ref in zip(sh.paths, p["refs"]):
                if ref.startswith("#"):
                    continue
                if ref in comps and p["unit"] != 1:
                    continue
                if ref in comps and comps[ref]["unit"] == 1:
                    continue
                sn, sf = sheetnames[path]
                comps[ref] = dict(unit=p["unit"], path=f"{path}/{p['uuid']}", footprint=p["footprint"], value=p["value"],
                                  datasheet=p["datasheet"], description=p["description"], sheetname=sn, sheetfile=sf,
                                  fields=p["fields"])

    scratch = os.environ.get("TEMP", HW)
    nets, pin_net = export_netlist(os.path.join(scratch, "nvd_pcb.net"))
    nets_by_name = {name: code for code, name in nets}

    P = placement()
    missing = sorted(set(comps) - set(P))
    extra = sorted(set(P) - set(comps))
    assert not missing and not extra, (missing, extra)

    items = []
    for ref in sorted(comps, key=lambda r: (r.rstrip("0123456789"), int("".join(ch for ch in r if ch.isdigit()) or 0))):
        x, y, rot = P[ref]
        items.append(dump(footprint_instance(ref, comps[ref], x, y, rot, nets_by_name, pin_net), 1))
    for i, (hx, hy) in enumerate(MOUNTING_HOLES, 1):
        comp = dict(footprint="MountingHole:MountingHole_2.2mm_M2", value="M2", datasheet="", description="Mounting hole", board_only=True)
        items.append(dump(footprint_instance(f"H{i}", comp, hx, hy, 0, nets_by_name, pin_net,
                                             extra_attr=("board_only", "exclude_from_pos_files", "exclude_from_bom")), 1))

    # ---- outline and the two 1 ohm isolation slots -------------------------
    ny0, ny1 = NOTCH_Y
    bx0, bx1 = NOTCH_BRIDGE
    g = [gr_rect(0, 0, W, H, "Edge.Cuts", "outline")]
    # two internal slots: 3 mm edge bridges on both sides plus the centre bridge
    g.append(gr_rect(EDGE_BRIDGE, ny0, bx0, ny1, "Edge.Cuts", "slot_1ohm_left"))
    g.append(gr_rect(bx1, ny0, W - EDGE_BRIDGE, ny1, "Edge.Cuts", "slot_1ohm_right"))
    # ---- silkscreen ----------------------------------------------------------------------------
    g.append(gr_text("NANOVOLT DIVIDER Rev0", 58.6, 33.6, "t_title", 0.9, rot=90))
    # No harness group labels here: the P1 / CN1 / P3 name and the module pin numbers are silk on
    # the harness footprints themselves, which keeps them attached to the pads if the row moves.
    for txt, x, y, key, size, rot in (
            ("CONTROL", 1.9, 22.0, "t_ctrl", 0.8, 90),
            # RANGE CELLS moved to the right edge: J1/J2 now occupy the left strip beside the relays.
            ("RANGE CELLS", 57.5, 56.0, "t_cells", 0.8, 90),
            # Vertical: at the 0.8 mm minimum text height 'NORM IN' is 6.2 mm long, and the strip
            # left of K4's pad column is only 4.99 mm wide.  It runs up the margin above J1 instead.
            ("NORM IN", 1.2, 51.5, "t_nin", 0.8, 90),
            # The island labels moved above the resistor when the 1 ohm row dropped 1.5 mm: R35's
            # own silk outline now reaches y 93.4 and there is no legible line left below it.
            ("1R + TMP275", 16.0, 68.5, "t_1r", 0.8, 0),
            ("OUT LO", 9.5, 71.5, "t_outlo", 0.8, 0),
            ("OUT HI", 42.5, 71.5, "t_outhi", 0.8, 0)):
        g.append(gr_text(txt, x, y - SHIFT_Y, key, size, rot=rot))
    # ---- zones ---------------------------------------------------------------------------------
    gnd = nets_by_name["DGND"]
    ctrl = [(0.3, 0.3), (W - 0.3, 0.3), (W - 0.3, DGND_MAX_Y), (0.3, DGND_MAX_Y)]
    g.append(zone_fill(gnd, "DGND", "B.Cu", ctrl, "DGND_control", "z_gnd"))
    # No blanket keepout over everything below the pour: the relays and their drivers are pulsed for
    # 10-20 ms and never held, so their average dissipation is ~0 and co-locating them with the range
    # resistors costs nothing while making the routing far shorter.  Only the 1 ohm island stays clear.
    island = [(0.0, ny1), (W, ny1), (W, H), (0.0, H)]
    g.append(zone_rule_area(island, "island_1ohm_no_pour", "z_prec"))
    g.append(zone_rule_area([(bx0, ny0 - 1.0), (bx1, ny0 - 1.0), (bx1, ny1 + 1.0), (bx0, ny1 + 1.0)],
                            "bridge_1ohm", "z_b1r", copperpour="allowed"))

    netlines = "\n".join(f'\t(net {code} {q(name)})' for code, name in [(0, "")] + nets)
    body = "\n".join(items + ["\t" + x for x in g])
    text = (f'(kicad_pcb (version 20241229) (generator "pcbnew") (generator_version "9.0")\n'
            f'\t(general (thickness 1.6) (legacy_teardrops no))\n\t(paper "A4")\n'
            f'\t(title_block (title "Nanovolt divider Rev0") (rev "Rev0") (company "nanovolt-divider (open hardware)"))\n'
            + "\t" + LAYERS.replace("\n", "\n\t") + "\n\t" + SETUP.replace("\n", "\n\t") + "\n"
            + netlines + "\n" + body + "\n\t(embedded_fonts no)\n)\n")
    G.write(BOARD, text)
    G.write(os.path.join(HW, f"{PROJECT}.kicad_dru"), DRU)
    r = subprocess.run([KICAD_CLI, "pcb", "upgrade", BOARD], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())


if __name__ == "__main__":
    build()
