#!/usr/bin/env python3
"""
Bootstrap PCB generator for the nanovolt-divider Rev0 board.

Produces hardware/nanovolt-divider.kicad_pcb with:
  * board outline (60 x 103 mm portrait) with two slots that isolate the 1 ohm strip except for a
    10 mm centre bridge and 3 mm bridges at both edges
  * every schematic footprint placed with the design rules from docs/nanovolt_divider_rev0.md
    (warm/noisy control section left, precision section right, HV parts spaced, 1 ohm at the
    output corner with the TMP117 adjacent)
  * pad nets from the exported schematic netlist (so KiCad shows the ratsnest immediately)
  * GND fill on B.Cu restricted to the control section, a no-pour keepout over the precision
    section, four M3 mounting holes and silkscreen labels
  * hardware/nanovolt-divider.kicad_dru with the 450 V clearance / creepage rules

No tracks are routed.  Run once, then route in KiCad; after that the .kicad_pcb is the source
of truth and this script is historical.

Usage: python tools/gen_pcb.py   (runs kicad-cli for the netlist, the format upgrade and DRC)
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
W, H = 60.0, 103.0           # board size (portrait: control on top, precision below)
NOTCH_Y = (87.7, 89.3)       # two slots isolating the 1 ohm strip
EDGE_BRIDGE = 3.0            # material left at both board edges beside the slots
NOTCH_BRIDGE = (25.0, 35.0)  # centre bridge left between the notches (MEAS, RTN, TMP117 lines)
CTRL_MAX_Y = 42.0            # control section copper limit (GND pour); precision keepout starts here


# --------------------------------------------------------------------------------------
# Placement table: ref -> (x, y, rotation) in board coordinates (origin top-left, y down)
# --------------------------------------------------------------------------------------

RELAY_X = {"K4": 9.6, "K1": 19.8, "K2": 30.0, "K3": 40.2, "K5": 50.4}   # relay row, pitch 10.2
RELAY_Y = 50.0


def placement() -> dict:
    P = {}
    # ---- row 1: display-module harness connectors (JST XH, pin 1 at the footprint origin) ----------
    P["J7"] = (11.4, 5.0, 0)                    # P1  (5 V / GND)
    P["J8"] = (25.0, 5.0, 0)                    # CN1 (I2C / 3V3)
    P["J9"] = (38.6, 5.0, 0)                    # P3  (IO35 HV_SENSE)
    # ---- row 2: MCP23017 horizontal, flanked by caps and pull-ups ------------------------------------
    P["U1"] = (30.0, 16.5, 90)
    P["C1"] = (17.5, 13.5, 90)                  # 100n at VDD
    P["C3"] = (17.5, 19.0, 90)                  # 22u 5 V bulk
    P["C4"] = (42.5, 13.5, 90)                  # 22u 3V3 bulk
    P["R21"] = (42.5, 19.0, 90)                 # SDA pull-up
    P["R22"] = (46.5, 13.5, 90)                 # SCL pull-up
    P["R23"] = (46.5, 19.0, 90)                 # ~RESET pull-up
    P["R24"] = (50.5, 13.5, 90)                 # mode sense (HV throw -> 3V3)
    P["R25"] = (50.5, 19.0, 90)                 # mode sense pulldown
    P["R26"] = (54.5, 13.5, 90)                 # mode sense (NORM throw -> GND)
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
    # ---- row 5: relays (rotation 90: coil pins 5/6 face the slot, pins 1/10 face down) ---------------
    for ref, x in RELAY_X.items():
        P[ref] = (x, RELAY_Y, 90)
    # ---- row 6: NORMAL IN pads and high-leg resistors --------------------------------------------------
    P["J1"] = (5.0, 60.5, 0)                    # NORMAL IN +
    P["J2"] = (5.0, 65.5, 0)                    # NORMAL IN -
    P["R31"] = (13.5, 62.0, 0)                  # 100k (MOX-700)   under K1
    P["R32"] = (27.0, 62.0, 0)                  # 1M   (MOX-700)   under K2
    P["R33"] = (41.5, 62.0, 0)                  # 10M  (Slim-Mox)  under K3
    # ---- row 7: 3PDT wiring pads, HV leg, HV input pads ----------------------------------------------
    P["SW1"] = (6.0, 70.0, 0)                   # cols NORM 6 / COM 13.62 / HV 21.24; rows 70 / 77.62 / 85.24
    P["R34"] = (37.5, 70.0, 180)                # HV 10M: pad 1 (HV IN +) toward J3, pad 2 toward the pole-1 HV pad
    P["J3"] = (43.5, 70.0, 0)                   # HV IN +
    P["J4"] = (43.5, 77.62, 0)                  # HV IN -
    # ---- row 8: 1 ohm strip behind the notches ------------------------------------------------------
    P["R35"] = (19.84, 97.0, 0)                # 1 ohm (RS-2C), pads at x = 19.84 / 40.16
    P["J6"] = (14.5, 97.0, 0)                  # DIVIDER OUT LO at the pad-1 end
    P["J5"] = (45.5, 97.0, 0)                  # DIVIDER OUT HI at the pad-2 end
    P["U2"] = (30.0, 91.5, 0)                   # TMP117 over the resistor body
    P["C2"] = (34.5, 91.5, 0)
    return P


MOUNTING_HOLES = [(3.0, 3.0), (57.0, 3.0), (3.0, 100.0), (57.0, 100.0)]


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
    fp.append(prop("Reference", ref, props.get("Reference")))
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

# 450 VDC service on the HV input path (netclass "HV": HV IN +, HV IN -, R34 output to the 3PDT).
# IPC-2221 B4 (external, uncoated, 301-500 V) asks for 2.5 mm; 3 mm clearance and 4 mm creepage
# leave margin for the solder-mask-free pads and the panel wiring.
(rule "HV clearance"
	(constraint clearance (min 3.0mm))
	(condition "A.NetClass == 'HV' || B.NetClass == 'HV'"))

(rule "HV creepage"
	(constraint creepage (min 4.0mm))
	(condition "A.NetClass == 'HV' && B.NetClass != 'HV'"))

(rule "HV edge clearance"
	(constraint edge_clearance (min 1.5mm))
	(condition "A.NetClass == 'HV'"))

# TMP117 DSBGA-6 has a 0.4 mm ball pitch (0.15 mm between pads); relax the default clearance inside it.
(rule "DSBGA pad clearance"
	(constraint clearance (min 0.1mm))
	(condition "A.memberOfFootprint('U2') && B.memberOfFootprint('U2')"))

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
        comp = dict(footprint="MountingHole:MountingHole_3.2mm_M3", value="M3", datasheet="", description="Mounting hole", board_only=True)
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
    g.append(gr_text("NANOVOLT DIVIDER Rev0", 58.6, 86.0, "t_title", 0.9, rot=90))
    g.append(gr_text("P1", 11.4, 10.4, "t_p1", 0.8))
    g.append(gr_text("CN1", 25.0, 10.4, "t_cn1", 0.8))
    g.append(gr_text("P3", 38.6, 10.4, "t_p3", 0.8))
    g.append(gr_text("CONTROL", 1.9, 30.0, "t_ctrl", 0.8, rot=90))
    g.append(gr_text("PRECISION / QUIET", 1.9, 79.0, "t_prec", 0.8, rot=90))
    g.append(gr_text("HV 450V", 40.5, 68.0, "t_hv", 0.9))
    g.append(gr_text("NORM IN", 2.5, 58.5, "t_nin", 0.8))
    g.append(gr_text("1R + TMP117", 24.0, 102.4, "t_1r", 0.8))
    g.append(gr_text("OUT LO", 9.5, 100.6, "t_outlo", 0.8))
    g.append(gr_text("OUT HI", 42.5, 100.6, "t_outhi", 0.8))
    # ---- zones ---------------------------------------------------------------------------------
    gnd = nets_by_name["GND"]
    ctrl = [(0.3, 0.3), (W - 0.3, 0.3), (W - 0.3, CTRL_MAX_Y), (0.3, CTRL_MAX_Y)]
    g.append(zone_fill(gnd, "GND", "B.Cu", ctrl, "GND_control", "z_gnd"))
    prec = [(0.0, CTRL_MAX_Y), (W, CTRL_MAX_Y), (W, H), (0.0, H)]
    g.append(zone_rule_area(prec, "precision_no_pour", "z_prec"))
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
