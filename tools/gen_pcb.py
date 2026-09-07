#!/usr/bin/env python3
"""
Bootstrap PCB generator for the nanovolt-divider Rev0 board.

Produces hardware/nanovolt-divider.kicad_pcb with:
  * board outline (100 x 62 mm), a thermal/isolation slot between the control and precision
    sections, and an L-shaped slot around the 1 ohm low-leg corner
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
W, H = 100.0, 62.0           # board size
SLOT_X = (44.5, 46.1)        # isolation slot between sections (x range), y 8..54
CTRL_MAX_X = 44.0            # control section copper limit


# --------------------------------------------------------------------------------------
# Placement table: ref -> (x, y, rotation) in board coordinates (origin top-left, y down)
# --------------------------------------------------------------------------------------

def placement() -> dict:
    P = {}
    # ---- control section -------------------------------------------------------------
    for n in range(1, 6):                       # driver blocks, one per relay, along the top bridge
        bx = 7.5 + 8.0 * (n - 1)
        for col, dx, rb, rp, qq, dd in ((0, -2.0, 4 * n - 3, 4 * n - 2, 2 * n - 1, 2 * n - 1),
                                        (1, 2.0, 4 * n - 1, 4 * n, 2 * n, 2 * n)):
            x = bx + dx
            P[f"R{rb}"] = (x, 3.0, 90)          # 1k base
            P[f"R{rp}"] = (x, 7.8, 90)          # 10k pulldown
            P[f"Q{qq}"] = (x, 12.0, 0)          # MMBT2222A
            P[f"D{dd}"] = (x, 16.2, 90)         # 1N4148W
    P["U1"] = (25.0, 33.0, 0)                  # MCP23017 SOIC-28W
    P["C1"] = (33.5, 26.0, 90)
    P["R21"] = (13.0, 26.0, 0)                  # SDA pull-up
    P["R22"] = (13.0, 29.5, 0)                  # SCL pull-up
    P["R23"] = (13.0, 33.0, 0)                  # ~RESET pull-up
    P["C3"] = (12.0, 52.0, 0)                   # 5 V bulk (near J7 / P1)
    P["C4"] = (25.0, 52.0, 0)                   # 3V3 bulk (near J8 / CN1)
    P["R24"] = (35.0, 48.0, 0)                  # mode sense
    P["R25"] = (40.0, 48.0, 0)
    P["R26"] = (35.0, 52.0, 0)
    P["J7"] = (10.0, 57.5, 0)                   # P1  (5 V / GND)
    P["J8"] = (23.5, 57.5, 0)                   # CN1 (I2C / 3V3)
    P["J9"] = (37.0, 57.5, 0)                   # P3  (IO35 HV_SENSE)
    # ---- precision section -------------------------------------------------------------
    for ref, x in (("K4", 51.5), ("K1", 61.7), ("K2", 71.9), ("K3", 82.1), ("K5", 92.3)):
        P[ref] = (x, 14.0, 90)                  # coil pins 5/6 face the top bridge
    P["J1"] = (49.5, 25.0, 0)                   # NORMAL IN +
    P["J2"] = (49.5, 30.0, 0)                   # NORMAL IN -
    P["R31"] = (57.9, 25.0, 0)                  # 100k  (MOX-700)
    P["R32"] = (57.9, 30.0, 0)                  # 1M    (MOX-700)
    P["R33"] = (74.9, 26.5, 0)                  # 10M   (Slim-Mox)
    P["SW1"] = (51.0, 36.0, 0)                  # 3PDT wiring pads: cols NORM/COM/HV, rows pole 1..3
    P["R34"] = (81.6, 36.0, 180)                # HV 10M (Slim-Mox): pad 1 (HV IN +) at J3, pad 2 toward the pole-1 HV pad
    P["J3"] = (86.5, 36.0, 0)                   # HV IN +
    P["J4"] = (86.5, 42.0, 0)                   # HV IN -
    P["U2"] = (86.5, 48.2, 0)                   # TMP117, between the slot and the 1 ohm body
    P["C2"] = (91.5, 48.5, 0)
    P["R35"] = (76.34, 53.0, 0)                 # 1 ohm low leg (RS-2C), pads at x=76.34 / 96.66
    P["J6"] = (76.34, 58.5, 0)                  # DIVIDER OUT LO (at the R35 pad-1 end)
    P["J5"] = (96.66, 58.5, 0)                  # DIVIDER OUT HI (at the R35 pad-2 end)
    return P


MOUNTING_HOLES = [(3.0, 22.5), (3.0, 42.0), (97.0, 3.0), (97.0, 26.0)]


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

# Coil drive lines cross the isolation slot only at the bridges; keep them narrow and on one layer.
(rule "slot bridge tracks"
	(constraint track_width (max 0.4mm))
	(condition "A.intersectsArea('top_bridge') || A.intersectsArea('bottom_bridge')"))
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

    # ---- outline and slots ------------------------------------------------------------------
    g = [gr_rect(0, 0, W, H, "Edge.Cuts", "outline")]
    g.append(gr_rect(SLOT_X[0], 8.0, SLOT_X[1], 54.0, "Edge.Cuts", "slot_main"))
    g.append(gr_poly([(71.2, 45.2), (97.0, 45.2), (97.0, 46.8), (72.8, 46.8), (72.8, 59.0), (71.2, 59.0)], "Edge.Cuts", "slot_1ohm"))
    # ---- silkscreen ----------------------------------------------------------------------------
    g.append(gr_text("NANOVOLT DIVIDER Rev0", 1.0, 20.5, "t_title", 1.2))
    g.append(gr_text("CONTROL", 1.0, 23.0, "t_ctrl", 0.9))
    g.append(gr_text("PRECISION / QUIET", 48.5, 33.0, "t_prec", 0.9))
    g.append(gr_text("HV 450V", 90.5, 33.5, "t_hv", 1.0, justify="right bottom"))
    g.append(gr_text("1R + TMP117", 79.0, 49.5, "t_1r", 0.8))
    g.append(gr_text("NORM IN", 47.9, 23.3, "t_nin", 0.8))
    g.append(gr_text("OUT LO", 73.5, 61.2, "t_outlo", 0.8))
    g.append(gr_text("OUT HI", 93.6, 61.2, "t_outhi", 0.8))
    g.append(gr_text("P1", 4.8, 54.2, "t_p1", 0.8))
    g.append(gr_text("CN1", 18.3, 54.2, "t_cn1", 0.8))
    g.append(gr_text("P3", 31.8, 54.2, "t_p3", 0.8))
    # ---- zones ---------------------------------------------------------------------------------
    gnd = nets_by_name["GND"]
    ctrl = [(0.3, 0.3), (CTRL_MAX_X, 0.3), (CTRL_MAX_X, H - 0.3), (0.3, H - 0.3)]
    g.append(zone_fill(gnd, "GND", "B.Cu", ctrl, "GND_control", "z_gnd"))
    prec = [(SLOT_X[0], 0.0), (W, 0.0), (W, H), (SLOT_X[0], H)]
    g.append(zone_rule_area(prec, "precision_no_pour", "z_prec"))
    g.append(zone_rule_area([(SLOT_X[0] - 1.0, 0.0), (SLOT_X[1] + 1.0, 0.0), (SLOT_X[1] + 1.0, 8.0), (SLOT_X[0] - 1.0, 8.0)],
                            "top_bridge", "z_tb", copperpour="allowed"))
    g.append(zone_rule_area([(SLOT_X[0] - 1.0, 54.0), (SLOT_X[1] + 1.0, 54.0), (SLOT_X[1] + 1.0, H), (SLOT_X[0] - 1.0, H)],
                            "bottom_bridge", "z_bb", copperpour="allowed"))

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
