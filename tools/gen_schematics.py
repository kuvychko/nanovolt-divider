#!/usr/bin/env python3
"""
Bootstrap generator for the nanovolt-divider KiCad project (Rev0).

Writes into hardware/:
  nanovolt-divider.kicad_pro          project file
  nanovolt-divider.kicad_sch          root sheet (metrology topology)
  control.kicad_sch                   ESP32 display module, MCP23017, TMP117, power
  relay_channel.kicad_sch             generic latching-relay channel (instantiated 5x)
  sym-lib-table / fp-lib-table        project-local library tables
  lib/nanovolt-divider.kicad_sym      project symbols (TQ2-L2-5V relay, 3PDT switch)
  lib/nanovolt-divider.pretty/        project footprints (TQ2 THT relay)

Stock symbols are copied from the KiCad installation so the schematics are
self-contained.  UUIDs are derived deterministically (uuid5) from element keys,
so re-running the generator yields stable diffs.

This script is a one-time bootstrap.  Once the schematics are edited in KiCad
the generated files become the source of truth and this script is historical.

Usage:  python tools/gen_schematics.py [--kicad-share "C:/Program Files/KiCad/10.0/share/kicad"]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HW = os.path.join(ROOT, "hardware")
PROJECT = "nanovolt-divider"
NS = uuid.UUID("6f1c2f8e-7b6e-4c1e-9a4d-1e0d2f3a4b5c")  # namespace for deterministic uuids

SCH_VERSION = "20260306"
SYM_VERSION = "20251024"
FP_VERSION = "20260206"
GEN_VERSION = "10.0"


def U(key: str) -> str:
    return str(uuid.uuid5(NS, key))


ROOT_UUID = U("sheet:root")
CONTROL_UUID = U("sheet:control")
RELAY_UUIDS = [U(f"sheet:relay:{i}") for i in range(1, 6)]
RELAY_NAMES = ["RANGE_1E5", "RANGE_1E6", "RANGE_1E7", "POLARITY", "INJECT"]

# --------------------------------------------------------------------------------------
# Minimal s-expression parser / serializer
# --------------------------------------------------------------------------------------


def parse(text: str):
    """Parse an s-expression into nested lists. Atoms are str; quoted strings keep quotes."""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            tokens.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            while text[j] != '"':
                if text[j] == "\\":
                    j += 1
                j += 1
            tokens.append(text[i:j + 1])
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "()":
                j += 1
            tokens.append(text[i:j])
            i = j
    stack = [[]]
    for t in tokens:
        if t == "(":
            stack.append([])
        elif t == ")":
            node = stack.pop()
            stack[-1].append(node)
        else:
            stack[-1].append(t)
    assert len(stack) == 1 and len(stack[0]) == 1, "unbalanced s-expression"
    return stack[0][0]


def dump(node, depth=0) -> str:
    """Serialize nested lists back to KiCad-style indented s-expressions."""
    ind = "\t" * depth
    if isinstance(node, str):
        return ind + node
    if not node:
        return ind + "()"
    if all(isinstance(x, str) for x in node):
        return ind + "(" + " ".join(node) + ")"
    out = [ind + "(" + node[0]]
    inline = []
    rest = node[1:]
    # keep leading atoms on the head line
    k = 0
    while k < len(rest) and isinstance(rest[k], str):
        inline.append(rest[k])
        k += 1
    if inline:
        out[0] += " " + " ".join(inline)
    for child in rest[k:]:
        out.append(dump(child, depth + 1))
    out.append(ind + ")")
    return "\n".join(out)


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def unq(s: str) -> str:
    return s[1:-1] if s.startswith('"') else s


def find(node, head):
    for c in node[1:]:
        if isinstance(c, list) and c and c[0] == head:
            return c
    return None


def find_all(node, head):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == head]


def prop(node, name):
    for p in find_all(node, "property"):
        if unq(p[1]) == name:
            return p
    return None


# --------------------------------------------------------------------------------------
# Stock symbol loading + flattening of derived symbols
# --------------------------------------------------------------------------------------


class SymbolLib:
    def __init__(self, share_dir: str):
        self.share = os.path.join(share_dir, "symbols")
        self._cache: dict[str, str] = {}
        self.defs: dict[str, list] = {}  # "Lib:Name" -> parsed symbol with prefixed name

    def _libtext(self, lib):
        if lib not in self._cache:
            with open(os.path.join(self.share, lib + ".kicad_sym"), encoding="utf8") as f:
                self._cache[lib] = f.read()
        return self._cache[lib]

    def _raw(self, lib, name) -> list:
        s = self._libtext(lib)
        key = '\n\t(symbol "%s"' % name
        i = s.find(key)
        if i < 0:
            raise KeyError(f"{lib}:{name}")
        depth = 0
        j = i + 1
        while True:
            c = s[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            elif c == '"':
                j += 1
                while s[j] != '"':
                    if s[j] == "\\":
                        j += 1
                    j += 1
            j += 1
        return parse(s[i + 1:j + 1])

    def get(self, lib, name) -> list:
        """Return flattened symbol definition named 'lib:name'."""
        full = f"{lib}:{name}"
        if full in self.defs:
            return self.defs[full]
        sym = self._raw(lib, name)
        ext = find(sym, "extends")
        if ext:
            parent = self._raw(lib, unq(ext[1]))
            # flatten: parent body + child's properties
            flat = [x for x in parent if not (isinstance(x, list) and x and x[0] == "property")]
            props = find_all(sym, "property")
            parent_props = {unq(p[1]): p for p in find_all(parent, "property")}
            merged = []
            seen = set()
            for p in props:
                merged.append(p)
                seen.add(unq(p[1]))
            for pn, p in parent_props.items():
                if pn not in seen:
                    merged.append(p)
            # insert properties after the header atoms/flags (before sub-symbols)
            head = [flat[0], flat[1]]
            body = flat[2:]
            pre = [x for x in body if not (isinstance(x, list) and x and x[0] == "symbol")]
            subs = [x for x in body if isinstance(x, list) and x and x[0] == "symbol"]
            # rename sub-symbols from parent name to child name
            pname, cname = unq(ext[1]), name
            for sub in subs:
                sub[1] = q(unq(sub[1]).replace(pname + "_", cname + "_", 1))
            sym = head + pre + merged + subs
        sym[1] = q(full)
        self.defs[full] = sym
        return sym

    def pins(self, full) -> list[dict]:
        """List pins of a (flattened) symbol: dict(unit, x, y, angle, length, name, number, type)."""
        sym = self.defs[full]
        out = []
        for sub in find_all(sym, "symbol"):
            m = re.match(r".*_(\d+)_(\d+)$", unq(sub[1]))
            unit = int(m.group(1))
            for p in find_all(sub, "pin"):
                at = find(p, "at")
                out.append(dict(
                    unit=unit, type=p[1], x=float(at[1]), y=float(at[2]), angle=float(at[3]),
                    length=float(find(p, "length")[1]), name=unq(find(p, "name")[1]),
                    number=unq(find(p, "number")[1])))
        return out


# --------------------------------------------------------------------------------------
# Project-local symbols (authored here; also written to lib/nanovolt-divider.kicad_sym)
# --------------------------------------------------------------------------------------

FONT = "(effects (font (size 1.27 1.27)))"


def _prop(name, value, x, y, hide=False, justify=None):
    h = " (hide yes)" if hide else ""
    j = f" (justify {justify})" if justify else ""
    return (f'(property {q(name)} {q(value)} (at {x} {y} 0){h} (show_name no) (do_not_autoplace no) '
            f'(effects (font (size 1.27 1.27)){j}))')


def _pin(ptype, x, y, angle, name, number, length=2.54):
    return (f'(pin {ptype} line (at {x} {y} {angle}) (length {length}) '
            f'(name {q(name)} {FONT}) (number {q(number)} {FONT}))')


STROKE = "(stroke (width 0.254) (type default))"


def tq2_symbol_text() -> str:
    """Panasonic TQ2-L2-5V, 2-coil latching DPDT, 4 units: SET coil, RESET coil, contact A, contact B.

    Pin numbers per Panasonic ASCTB14E 'Schematic (bottom view), 2 coil latching':
      SET coil  : 1 (+) .. 5 (-)      energize -> COM moves to NO
      RESET coil: 10 (+) .. 6 (-)     energize -> COM returns to NC (state drawn in datasheet)
      Pole A    : 3 COM, 2 NC, 4 NO
      Pole B    : 8 COM, 9 NC, 7 NO
    """
    coil = lambda unit, label, ptop, ntop, pbot, nbot: f'''
    (symbol "TQ2-L2-5V_{unit}_1"
      (rectangle (start -2.54 2.54) (end 2.54 -2.54) {STROKE} (fill (type background)))
      (polyline (pts (xy -2.54 2.54) (xy 2.54 -2.54)) {STROKE} (fill (type none)))
      (text {q(label)} (at -3.81 0 0) (effects (font (size 1.016 1.016)) (justify right)))
      {_pin("passive", 0, 5.08, 270, ptop, ntop)}
      {_pin("passive", 0, -5.08, 90, pbot, nbot)}
    )'''
    contact = lambda unit, com, nc, no, suffix: f'''
    (symbol "TQ2-L2-5V_{unit}_1"
      (circle (center -4.572 0) (radius 0.508) {STROKE} (fill (type none)))
      (circle (center 4.572 2.54) (radius 0.508) {STROKE} (fill (type none)))
      (circle (center 4.572 -2.54) (radius 0.508) {STROKE} (fill (type none)))
      (polyline (pts (xy -4.064 0.254) (xy 4.064 2.286)) {STROKE} (fill (type none)))
      {_pin("passive", -7.62, 0, 0, "COM_" + suffix, com)}
      {_pin("passive", 7.62, 2.54, 180, "NC_" + suffix, nc)}
      {_pin("passive", 7.62, -2.54, 180, "NO_" + suffix, no)}
    )'''
    return f'''
  (symbol "TQ2-L2-5V"
    (pin_names (offset 1.016))
    (exclude_from_sim no) (in_bom yes) (on_board yes) (in_pos_files yes) (duplicate_pin_numbers_are_jumpers no)
    {_prop("Reference", "K", 0, 8.89)}
    {_prop("Value", "TQ2-L2-5V", 0, -8.89)}
    {_prop("Footprint", "nanovolt-divider:Relay_DPDT_Panasonic_TQ2_THT", 0, 0, hide=True)}
    {_prop("Datasheet", "https://mediap.industry.panasonic.eu/assets/download-files/import/ds_61020_en_tq.pdf", 0, 0, hide=True)}
    {_prop("Description", "Signal relay DPDT (2 Form C), 2-coil latching, 5 V coils (125 ohm / 40 mA each), THT, 14x9x5 mm", 0, 0, hide=True)}
    {_prop("MPN", "TQ2-L2-5V", 0, 0, hide=True)}
    {_prop("Manufacturer", "Panasonic", 0, 0, hide=True)}
    {_prop("ki_keywords", "relay latching bistable DPDT 2FormC TQ2", 0, 0, hide=True)}
    {_prop("ki_fp_filters", "Relay*Panasonic*TQ2*", 0, 0, hide=True)}
    {coil(1, "SET (1+ / 5-)", "S+", "1", "S-", "5")}
    {coil(2, "RESET (10+ / 6-)", "R+", "10", "R-", "6")}
    {contact(3, "3", "2", "4", "A")}
    {contact(4, "8", "9", "7", "B")}
    (embedded_fonts no)
  )'''


def sw3pdt_symbol_text() -> str:
    """Generic 3PDT toggle, 3 units. Per pole: NORM throw, COM, HV throw. Lug numbering 1-9 is a placeholder
    until the physical switch is chosen."""
    pole = lambda unit, norm, com, hv: f'''
    (symbol "SW_3PDT_{unit}_1"
      (circle (center -2.032 0) (radius 0.508) {STROKE} (fill (type none)))
      (circle (center 2.032 2.54) (radius 0.508) {STROKE} (fill (type none)))
      (circle (center 2.032 -2.54) (radius 0.508) {STROKE} (fill (type none)))
      (polyline (pts (xy -1.524 0.254) (xy 1.524 2.286)) {STROKE} (fill (type none)))
      {_pin("passive", 5.08, 2.54, 180, "NORM", norm)}
      {_pin("passive", -5.08, 0, 0, "COM", com)}
      {_pin("passive", 5.08, -2.54, 180, "HV", hv)}
    )'''
    return f'''
  (symbol "SW_3PDT"
    (pin_names (offset 1.016))
    (exclude_from_sim no) (in_bom yes) (on_board yes) (in_pos_files yes) (duplicate_pin_numbers_are_jumpers no)
    {_prop("Reference", "SW", 0, 5.08)}
    {_prop("Value", "SW_3PDT", 0, -5.08)}
    {_prop("Footprint", "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-9-5.08_1x09_P5.08mm_Horizontal", 0, 0, hide=True)}
    {_prop("Datasheet", "~", 0, 0, hide=True)}
    {_prop("Description", "3PDT toggle switch, panel mount (NORMAL / HV selector). Footprint is a placeholder for the board-side wiring termination; select a 450 VDC rated switch.", 0, 0, hide=True)}
    {_prop("ki_keywords", "switch toggle 3PDT", 0, 0, hide=True)}
    {pole(1, "1", "2", "3")}
    {pole(2, "4", "5", "6")}
    {pole(3, "7", "8", "9")}
    (embedded_fonts no)
  )'''


def project_symbol_lib_text() -> str:
    return (f'(kicad_symbol_lib (version {SYM_VERSION}) (generator "nanovolt-divider-gen") (generator_version "{GEN_VERSION}")'
            f'{tq2_symbol_text()}{sw3pdt_symbol_text()}\n)\n')


def tq2_footprint_text() -> str:
    """Panasonic TQ2 THT: 10 pins, 2.54 mm pitch, 7.62 mm row spacing, body 14 x 9 mm (ASCTB14E).
    Top view: pins 1..5 left->right on the bottom row (y=+3.81), pins 10..6 left->right on the top row (y=-3.81).
    The polarity/direction bar on the case is at the pin 1 / pin 10 end (left)."""
    pads = []
    for k in range(5):
        x = -5.08 + 2.54 * k
        shape = "rect" if k == 0 else "circle"
        pads.append(f'  (pad "{k + 1}" thru_hole {shape} (at {x:.2f} 3.81) (size 1.6 1.6) (drill 1.0) (layers "*.Cu" "*.Mask") (remove_unused_layers no) (uuid "{U("fp:tq2:pad:" + str(k + 1))}"))')
        pads.append(f'  (pad "{10 - k}" thru_hole circle (at {x:.2f} -3.81) (size 1.6 1.6) (drill 1.0) (layers "*.Cu" "*.Mask") (remove_unused_layers no) (uuid "{U("fp:tq2:pad:" + str(10 - k))}"))')

    def line(layer, x1, y1, x2, y2, w):
        return (f'  (fp_line (start {x1} {y1}) (end {x2} {y2}) (stroke (width {w}) (type solid)) (layer "{layer}") '
                f'(uuid "{U(f"fp:tq2:line:{layer}:{x1}:{y1}:{x2}:{y2}")}"))')

    def rect(layer, hx, hy, w):
        return "\n".join([line(layer, -hx, -hy, hx, -hy, w), line(layer, hx, -hy, hx, hy, w),
                          line(layer, hx, hy, -hx, hy, w), line(layer, -hx, hy, -hx, -hy, w)])

    txt = f'''(footprint "Relay_DPDT_Panasonic_TQ2_THT"
  (version {FP_VERSION})
  (generator "nanovolt-divider-gen")
  (generator_version "{GEN_VERSION}")
  (layer "F.Cu")
  (descr "Panasonic TQ2 series signal relay DPDT (2 Form C), through-hole, 14x9x5 mm, 10 pins on 2.54 mm pitch, 7.62 mm row spacing; datasheet ASCTB14E")
  (tags "relay DPDT latching Panasonic TQ2 TQ2-L2")
  (property "Reference" "REF**" (at 0 -6.35 0) (layer "F.SilkS") (uuid "{U("fp:tq2:ref")}") (effects (font (size 1 1) (thickness 0.15))))
  (property "Value" "Relay_DPDT_Panasonic_TQ2_THT" (at 0 6.35 0) (layer "F.Fab") (uuid "{U("fp:tq2:val")}") (effects (font (size 1 1) (thickness 0.15))))
  (property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{U("fp:tq2:ds")}") (effects (font (size 1 1) (thickness 0.15))))
  (property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{U("fp:tq2:desc")}") (effects (font (size 1 1) (thickness 0.15))))
  (attr through_hole)
{rect("F.Fab", 7.0, 4.5, 0.1)}
{line("F.Fab", -7.0, -3.5, -6.0, -4.5, 0.1)}
{rect("F.SilkS", 7.11, 4.61, 0.12)}
{line("F.SilkS", -7.6, 3.81, -7.6, 2.5, 0.12)}
{line("F.SilkS", -7.6, 3.81, -6.3, 3.81, 0.12)}
{rect("F.CrtYd", 7.25, 4.75, 0.05)}
  (fp_text user "${{REFERENCE}}" (at 0 0 0) (layer "F.Fab") (uuid "{U("fp:tq2:reftext")}") (effects (font (size 1 1) (thickness 0.15))))
{chr(10).join(pads)}
  (embedded_fonts no)
)
'''
    return txt


# --------------------------------------------------------------------------------------
# Schematic builder
# --------------------------------------------------------------------------------------


def xf(px, py, x, y, angle, mirror=None):
    """Transform a library-space point (y up) into schematic space (y down) for a placed symbol."""
    dx, dy = px, -py
    if mirror == "y":
        dx = -dx
    if mirror == "x":
        dy = -dy
    a = int(angle) % 360
    if a == 90:
        dx, dy = dy, -dx
    elif a == 180:
        dx, dy = -dx, -dy
    elif a == 270:
        dx, dy = -dy, dx
    return round(x + dx, 4), round(y + dy, 4)


def fmt(v):
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s if s != "-0" else "0"


@dataclass
class Sheet:
    name: str
    file: str
    uuid: str
    paper: str
    lib: SymbolLib
    paths: list  # list of (path, suffix) sheet-instance paths this file is used in
    items: list = field(default_factory=list)
    used: dict = field(default_factory=dict)
    title: str = ""
    _n: int = 0

    def key(self, k):
        self._n += 1
        return U(f"{self.file}:{k}:{self._n}")

    # -- primitives ------------------------------------------------------------------
    def wire(self, x1, y1, x2, y2):
        self.items.append(f'(wire (pts (xy {fmt(x1)} {fmt(y1)}) (xy {fmt(x2)} {fmt(y2)})) (stroke (width 0) (type default)) (uuid "{self.key("wire")}"))')

    def poly(self, *pts):
        for (a, b) in zip(pts, pts[1:]):
            self.wire(a[0], a[1], b[0], b[1])

    def junction(self, x, y):
        self.items.append(f'(junction (at {fmt(x)} {fmt(y)}) (diameter 0) (color 0 0 0 0) (uuid "{self.key("junc")}"))')

    def noconn(self, x, y):
        self.items.append(f'(no_connect (at {fmt(x)} {fmt(y)}) (uuid "{self.key("nc")}"))')

    def label(self, name, x, y, angle=0):
        j = "left bottom" if angle == 0 else "right bottom"
        self.items.append(f'(label {q(name)} (at {fmt(x)} {fmt(y)} {angle}) (effects (font (size 1.27 1.27)) (justify {j})) (uuid "{self.key("lbl")}"))')

    def hlabel(self, name, shape, x, y, angle=0):
        j = "left" if angle == 0 else "right"
        self.items.append(f'(hierarchical_label {q(name)} (shape {shape}) (at {fmt(x)} {fmt(y)} {angle}) (effects (font (size 1.27 1.27)) (justify {j})) (uuid "{self.key("hl")}"))')

    def text(self, s, x, y, size=1.27):
        self.items.append(f'(text {q(s)} (at {fmt(x)} {fmt(y)} 0) (effects (font (size {size} {size})) (justify left bottom)) (uuid "{self.key("txt")}"))')

    # -- symbols ---------------------------------------------------------------------
    def symbol(self, lib_id, x, y, refs, value, angle=0, mirror=None, unit=1, footprint=None,
               fields=None, ref_pos=None, val_pos=None, hide_value=False, datasheet=None, description=None):
        """Place a symbol. refs: list of references, one per self.paths entry (or a single str)."""
        lib, name = lib_id.split(":", 1)
        sym = self.lib.get(lib, name)
        self.used[lib_id] = sym
        if isinstance(refs, str):
            refs = [refs] * len(self.paths)
        assert len(refs) == len(self.paths)
        def libprop(name):
            p = prop(sym, name)
            return unq(p[2]) if p else ""

        fp = footprint if footprint is not None else libprop("Footprint")
        ds = datasheet if datasheet is not None else libprop("Datasheet")
        desc = description if description is not None else libprop("Description")
        rx, ry = ref_pos or (x + 2.54, y - 1.27)
        vx, vy = val_pos or (x + 2.54, y + 1.27)
        power = refs[0].startswith("#")
        m = f" (mirror {mirror})" if mirror else ""
        lines = [f'(symbol (lib_id {q(lib_id)}) (at {fmt(x)} {fmt(y)} {angle}){m} (unit {unit}) (body_style 1) (exclude_from_sim no) (in_bom yes) (on_board yes) (in_pos_files yes) (dnp no) (uuid "{self.key("sym:" + refs[0])}")']

        def P(n, v, px, py, hide=False, justify="left"):
            h = " (hide yes)" if hide else ""
            lines.append(f'  (property {q(n)} {q(v)} (at {fmt(px)} {fmt(py)} 0){h} (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27)) (justify {justify})))')

        P("Reference", refs[0], rx, ry, hide=power)
        P("Value", value, vx, vy, hide=hide_value)
        P("Footprint", fp, x, y, hide=True)
        P("Datasheet", ds, x, y, hide=True)
        P("Description", desc, x, y, hide=True)
        for k, v in (fields or {}).items():
            P(k, v, x, y, hide=True)
        for p in self.lib.pins(lib_id):
            if p["unit"] in (0, unit):
                lines.append(f'  (pin {q(p["number"])} (uuid "{self.key("pin")}"))')
        lines.append(f'  (instances (project {q(PROJECT)}')
        for (path, r) in zip(self.paths, refs):
            lines.append(f'    (path {q(path)} (reference {q(r)}) (unit {unit}))')
        lines.append("  ))")
        lines.append(")")
        self.items.append("\n".join(lines))

    def pinpos(self, lib_id, x, y, angle, number, mirror=None):
        for p in self.lib.pins(lib_id):
            if p["number"] == number:
                return xf(p["x"], p["y"], x, y, angle, mirror)
        raise KeyError(f"{lib_id} pin {number}")

    def power(self, kind, x, y, ref, angle=0):
        self.symbol(f"power:{kind}", x, y, ref, kind, angle=angle,
                    ref_pos=(x, y + 6.35), val_pos=(x, y + 3.81 if kind.startswith("GND") else y - 3.81))

    def sheet(self, name, file, sheet_uuid, x, y, w, h, left=(), right=(), page="2"):
        lines = [f'(sheet (at {fmt(x)} {fmt(y)}) (size {fmt(w)} {fmt(h)}) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)',
                 '  (stroke (width 0.1524) (type solid)) (fill (color 0 0 0 0.0000))',
                 f'  (uuid "{sheet_uuid}")',
                 f'  (property "Sheetname" {q(name)} (at {fmt(x)} {fmt(y - 0.7116)} 0) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27)) (justify left bottom)))',
                 f'  (property "Sheetfile" {q(file)} (at {fmt(x)} {fmt(y + h + 0.5846)} 0) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27)) (justify left top)))']
        for (pname, shape, off) in left:
            lines.append(f'  (pin {q(pname)} {shape} (at {fmt(x)} {fmt(y + off)} 180) (uuid "{self.key("spin")}") (effects (font (size 1.27 1.27)) (justify left)))')
        for (pname, shape, off) in right:
            lines.append(f'  (pin {q(pname)} {shape} (at {fmt(x + w)} {fmt(y + off)} 0) (uuid "{self.key("spin")}") (effects (font (size 1.27 1.27)) (justify right)))')
        lines.append(f'  (instances (project {q(PROJECT)} (path {q("/" + ROOT_UUID)} (page {q(page)}))))')
        lines.append(")")
        self.items.append("\n".join(lines))

    # -- output ------------------------------------------------------------------------
    def render(self, is_root=False) -> str:
        libs = "\n".join(dump(s, 2) for _, s in sorted(self.used.items()))
        tb = ""
        if self.title:
            tb = f'\n\t(title_block (title {q(self.title)}) (rev "Rev0") (company "nanovolt-divider (open hardware)") (comment 1 "Generated by tools/gen_schematics.py; edit in KiCad from here on."))'
        body = "\n".join("\t" + it.replace("\n", "\n\t") for it in self.items)
        si = f'\n\t(sheet_instances (path "/" (page "1")))' if is_root else ""
        return (f'(kicad_sch (version {SCH_VERSION}) (generator "nanovolt-divider-gen") (generator_version "{GEN_VERSION}")\n'
                f'\t(uuid "{self.uuid}")\n\t(paper {q(self.paper)}){tb}\n\t(lib_symbols\n{libs}\n\t)\n{body}{si}\n\t(embedded_fonts no)\n)\n')


# --------------------------------------------------------------------------------------
# Footprint placeholders / part data
# --------------------------------------------------------------------------------------

FP_R1206 = "Resistor_SMD:R_1206_3216Metric"
FP_C1206 = "Capacitor_SMD:C_1206_3216Metric"
FP_MOX700 = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal"   # TODO verify vs Ohmite MOX-700 drawing
FP_SM102 = "Resistor_THT:R_Box_L14.0mm_W5.0mm_P9.00mm"                          # TODO verify vs Ohmite Slim-Mox SM102 drawing (radial, 14.7 x 2.5 x 8.6 mm)
FP_RS02C = "Resistor_THT:R_Axial_DIN0411_L9.9mm_D3.6mm_P12.70mm_Horizontal"     # TODO verify vs Vishay RS-2C drawing
FP_BANANA = "Connector_Wire:SolderWire-0.25sqmm_1x01_D0.65mm_OD1.7mm"           # panel jack wired to board
FP_JST4 = "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical"                # harness to display module (module side is 1.25 mm JST-style)
TODO = " [FOOTPRINT TBD - verify against datasheet]"


# --------------------------------------------------------------------------------------
# relay_channel.kicad_sch
# --------------------------------------------------------------------------------------


def build_relay_channel(lib: SymbolLib) -> Sheet:
    paths = [f"/{ROOT_UUID}/{u}" for u in RELAY_UUIDS]
    sh = Sheet("relay_channel", "relay_channel.kicad_sch", U("file:relay_channel"), "A4", lib, paths,
               title="Latching relay channel (generic, instantiated 5x)")
    n = list(range(1, 6))
    K = "nanovolt-divider:TQ2-L2-5V"
    Q = "Transistor_BJT:MMBT2222A"
    D = "Diode:1N4148W"
    R = "Device:R"

    def driver(y0, hl, coil_unit, qref, dref, rb_ref, rp_ref, pwr_i):
        """One low-side coil driver: hl -> 1k -> base; 10k pulldown; coil between +5V and collector; flyback diode."""
        # hierarchical label + base resistor
        sh.hlabel(hl, "input", 30.48, y0, 180)
        sh.symbol(R, 40.64, y0, rb_ref, "1k", angle=90, footprint=FP_R1206, ref_pos=(38.1, y0 - 2.54), val_pos=(38.1, y0 + 3.81))
        sh.wire(30.48, y0, 36.83, y0)
        sh.wire(44.45, y0, 50.8, y0)
        sh.junction(48.26, y0)
        # pulldown
        sh.symbol(R, 48.26, y0 + 7.62, rp_ref, "10k", footprint=FP_R1206, ref_pos=(50.8, y0 + 6.35), val_pos=(50.8, y0 + 8.89))
        sh.wire(48.26, y0, 48.26, y0 + 3.81)
        sh.wire(48.26, y0 + 11.43, 48.26, y0 + 13.97)
        sh.power("GND", 48.26, y0 + 13.97, [f"#PWR{i}{pwr_i:02d}" for i in n])
        sh.junction(48.26, y0 + 11.43)
        sh.wire(48.26, y0 + 11.43, 58.42, y0 + 11.43)
        # transistor
        sh.symbol(Q, 55.88, y0, qref, "MMBT2222A", ref_pos=(60.96, y0 - 1.27), val_pos=(60.96, y0 + 1.27))
        b = sh.pinpos(Q, 55.88, y0, 0, "1")
        c = sh.pinpos(Q, 55.88, y0, 0, "3")
        e = sh.pinpos(Q, 55.88, y0, 0, "2")
        assert b == (50.8, y0), b
        sh.wire(e[0], e[1], e[0], y0 + 11.43)
        # coil
        ky = y0 - 25.4
        sh.symbol(K, 58.42, ky, [f"K{i}" for i in n], "TQ2-L2-5V", unit=coil_unit, ref_pos=(48.26, ky - 3.81), val_pos=(48.26, ky + 3.81), hide_value=True)
        top = sh.pinpos(K, 58.42, ky, 0, "1" if coil_unit == 1 else "10")
        bot = sh.pinpos(K, 58.42, ky, 0, "5" if coil_unit == 1 else "6")
        sh.wire(c[0], c[1], c[0], y0 - 15.24)
        sh.junction(c[0], y0 - 15.24)
        sh.wire(c[0], y0 - 15.24, bot[0], bot[1])
        sh.wire(top[0], top[1], top[0], ky - 7.62)
        sh.junction(top[0], ky - 7.62)
        sh.power("+5V", top[0], ky - 7.62, [f"#PWR{i}{pwr_i + 1:02d}" for i in n])
        # flyback diode: cathode to +5V, anode to collector
        sh.symbol(D, 68.58, ky, dref, "1N4148W", angle=270, ref_pos=(71.12, ky - 1.27), val_pos=(71.12, ky + 1.27))
        kat = sh.pinpos(D, 68.58, ky, 270, "1")
        an = sh.pinpos(D, 68.58, ky, 270, "2")
        assert kat[1] < an[1], "diode orientation: cathode must be on top"
        sh.poly((top[0], ky - 7.62), (68.58, ky - 7.62), kat)
        sh.poly(an, (68.58, y0 - 15.24), (c[0], y0 - 15.24))

    driver(63.5, "SET", 1, [f"Q{2 * i - 1}" for i in n], [f"D{2 * i - 1}" for i in n],
           [f"R{4 * i - 3}" for i in n], [f"R{4 * i - 2}" for i in n], 1)
    driver(127.0, "RESET", 2, [f"Q{2 * i}" for i in n], [f"D{2 * i}" for i in n],
           [f"R{4 * i - 1}" for i in n], [f"R{4 * i}" for i in n], 3)

    # contacts
    for (unit, y, suf, com, nc, no) in ((3, 50.8, "A", "3", "2", "4"), (4, 101.6, "B", "8", "9", "7")):
        sh.symbol(K, 139.7, y, [f"K{i}" for i in n], "TQ2-L2-5V", unit=unit, ref_pos=(137.16, y - 6.35), val_pos=(137.16, y + 6.35))
        pc = sh.pinpos(K, 139.7, y, 0, com)
        pnc = sh.pinpos(K, 139.7, y, 0, nc)
        pno = sh.pinpos(K, 139.7, y, 0, no)
        sh.hlabel(f"{suf}_COM", "passive", 124.46, pc[1], 180)
        sh.wire(124.46, pc[1], pc[0], pc[1])
        sh.hlabel(f"{suf}_NC", "passive", 154.94, pnc[1], 0)
        sh.wire(pnc[0], pnc[1], 154.94, pnc[1])
        sh.hlabel(f"{suf}_NO", "passive", 154.94, pno[1], 0)
        sh.wire(pno[0], pno[1], 154.94, pno[1])

    sh.text("Latching relay channel - Panasonic TQ2-L2-5V (2-coil latching DPDT), one MMBT2222A low-side driver per coil.\n"
            "SET pulse  (pins 1+ / 5-)  : both poles COM -> NO\n"
            "RESET pulse (pins 10+ / 6-): both poles COM -> NC (state drawn on the contact symbols)\n"
            "Coils are 125 ohm / 40 mA at 5 V; pulse 10-20 ms, never hold energized. 1N4148W clamps the coil kickback to +5V.\n"
            "Base drive: 3.3 V GPIO -> 1k -> base (~2.6 mA), 10k pulldown keeps the driver off while the MCP23017 is in reset.\n"
            "Pin map per Panasonic ASCTB14E 'Schematic (bottom view), 2 coil latching'.", 25.4, 190.5, 1.27)
    sh.text("Coil drivers (control / warm region)", 25.4, 20.32, 2.0)
    sh.text("Contacts (precision / quiet region)", 121.92, 20.32, 2.0)
    return sh


# --------------------------------------------------------------------------------------
# control.kicad_sch
# --------------------------------------------------------------------------------------


def build_control(lib: SymbolLib) -> Sheet:
    sh = Sheet("control", "control.kicad_sch", U("file:control"), "A4", lib, [f"/{ROOT_UUID}/{CONTROL_UUID}"],
               title="Control: ESP32 display module interface, MCP23017 relay drivers, TMP117")
    C4 = "Connector_Generic:Conn_01x04"
    R = "Device:R"
    C = "Device:C"
    pw = [0]

    def pwr(kind, x, y):
        pw[0] += 1
        sh.power(kind, x, y, f"#PWR9{pw[0]:02d}")

    def flag(x, y, ref):
        sh.symbol("power:PWR_FLAG", x, y, ref, "PWR_FLAG", ref_pos=(x, y - 6.35), val_pos=(x, y - 3.81))

    # ---- ESP32 display module harness connectors ---------------------------------------
    # J1 = module P1 (UART / VIN). mirror y -> pins on the right, pin 1 on top.
    sh.symbol(C4, 38.1, 45.72, "J7", "ESP32_DISP_P1", mirror="y", footprint=FP_JST4,
              description="Harness to ESP32-2432S028R (ELEGOO 2.8in) connector P1: 1 TX(IO1), 2 RX(IO3), 3 VIN(5V), 4 GND",
              ref_pos=(33.02, 39.37), val_pos=(27.94, 41.91))
    p = lambda k: sh.pinpos(C4, 38.1, 45.72, 0, k, mirror="y")
    sh.noconn(*p("1"))
    sh.noconn(*p("2"))
    vin, gnd = p("3"), p("4")
    sh.poly(vin, (50.8, vin[1]), (50.8, 35.56))
    sh.junction(50.8, 35.56)
    pwr("+5V", 50.8, 35.56)
    sh.wire(50.8, 35.56, 58.42, 35.56)
    flag(58.42, 35.56, "#FLG01")
    sh.poly(gnd, (55.88, gnd[1]), (55.88, 58.42))
    sh.junction(55.88, 58.42)
    pwr("GND", 55.88, 58.42)
    sh.wire(55.88, 58.42, 63.5, 58.42)
    flag(63.5, 58.42, "#FLG02")

    # J2 = module CN1 (I2C + 3V3). angle 180 -> pins on the right, pin 1 at the bottom.
    sh.symbol(C4, 38.1, 76.2, "J8", "ESP32_DISP_CN1", angle=180, footprint=FP_JST4,
              description="Harness to ESP32-2432S028R connector CN1: 1 GND, 2 IO22 (SCL), 3 IO27 (SDA), 4 3V3",
              ref_pos=(33.02, 67.31), val_pos=(27.94, 69.85))
    p = lambda k: sh.pinpos(C4, 38.1, 76.2, 180, k)
    g, scl, sda, v33 = p("1"), p("2"), p("3"), p("4")
    sh.poly(v33, (48.26, v33[1]), (48.26, 63.5))
    pwr("+3V3", 48.26, 63.5)
    sh.poly(g, (48.26, g[1]), (48.26, 86.36))
    pwr("GND", 48.26, 86.36)
    sh.wire(scl[0], scl[1], 53.34, scl[1])
    sh.label("SCL", 53.34, scl[1])
    sh.wire(sda[0], sda[1], 53.34, sda[1])
    sh.label("SDA", 53.34, sda[1])

    # J3 = module P3 (GPIO). angle 180.
    sh.symbol(C4, 38.1, 106.68, "J9", "ESP32_DISP_P3", angle=180, footprint=FP_JST4,
              description="Harness to ESP32-2432S028R connector P3: 1 GND, 2 IO35 (input only, HV_SENSE), 3 IO22 (dup. SCL, n/c), 4 IO21 (backlight, n/c)",
              ref_pos=(33.02, 97.79), val_pos=(27.94, 100.33))
    p = lambda k: sh.pinpos(C4, 38.1, 106.68, 180, k)
    g, io35 = p("1"), p("2")
    sh.noconn(*p("3"))
    sh.noconn(*p("4"))
    sh.poly(g, (48.26, g[1]), (48.26, 116.84))
    pwr("GND", 48.26, 116.84)
    sh.wire(io35[0], io35[1], 53.34, io35[1])
    sh.label("HV_SENSE", 53.34, io35[1])

    # ---- I2C pull-ups ------------------------------------------------------------------
    for (x, ref, net) in ((83.82, "R21", "SDA"), (93.98, "R22", "SCL")):
        sh.symbol(R, x, 60.96, ref, "4.7k", footprint=FP_R1206, ref_pos=(x + 2.54, 59.69), val_pos=(x + 2.54, 62.23))
        sh.wire(x, 57.15, x, 53.34)
        pwr("+3V3", x, 53.34)
        sh.wire(x, 64.77, x, 68.58)
        sh.label(net, x, 68.58)

    # ---- U1 MCP23017 -------------------------------------------------------------------
    U1 = "Interface_Expansion:MCP23017x-x-SO"
    ux, uy = 127.0, 114.3
    sh.symbol(U1, ux, uy, "U1", "MCP23017-E/SO", ref_pos=(ux - 12.7, uy - 29.21), val_pos=(ux - 12.7, uy - 26.67),
              fields={"MPN": "MCP23017-E/SO", "Manufacturer": "Microchip"})
    pin = lambda k: sh.pinpos(U1, ux, uy, 0, k)
    sck, sda_ = pin("12"), pin("13")
    sh.wire(sck[0], sck[1], 106.68, sck[1])
    sh.label("SCL", 106.68, sck[1], 180)
    sh.wire(sda_[0], sda_[1], 106.68, sda_[1])
    sh.label("SDA", 106.68, sda_[1], 180)
    for k in ("11", "14", "19", "20"):
        sh.noconn(*pin(k))
    # ~RESET pull-up
    rst = pin("18")
    sh.symbol(R, 106.68, rst[1], "R23", "10k", angle=90, footprint=FP_R1206, ref_pos=(104.14, rst[1] - 2.54), val_pos=(104.14, rst[1] + 3.81))
    sh.wire(110.49, rst[1], rst[0], rst[1])
    sh.poly((102.87, rst[1]), (99.06, rst[1]), (99.06, rst[1] - 5.08))
    pwr("+3V3", 99.06, rst[1] - 5.08)
    # address pins to GND -> 0x20
    a0, a1, a2 = pin("15"), pin("16"), pin("17")
    for a in (a0, a1, a2):
        sh.wire(a[0], a[1], 109.22, a[1])
    sh.wire(109.22, a0[1], 109.22, a1[1])
    sh.wire(109.22, a1[1], 109.22, a2[1])
    sh.wire(109.22, a2[1], 109.22, a2[1] + 5.08)
    sh.junction(109.22, a1[1])
    sh.junction(109.22, a2[1])
    pwr("GND", 109.22, a2[1] + 5.08)
    vss, vdd = pin("10"), pin("9")
    sh.wire(vss[0], vss[1], vss[0], vss[1] + 2.54)
    pwr("GND", vss[0], vss[1] + 2.54)
    sh.wire(vdd[0], vdd[1], vdd[0], vdd[1] - 10.16)
    pwr("+3V3", vdd[0], vdd[1] - 10.16)
    # GPIO -> relay coil control lines
    gp = [("21", "K1_SET"), ("22", "K1_RESET"), ("23", "K2_SET"), ("24", "K2_RESET"), ("25", "K3_SET"),
          ("26", "K3_RESET"), ("27", "K4_SET"), ("28", "K4_RESET"), ("1", "K5_SET"), ("2", "K5_RESET")]
    for (num, name) in gp:
        pp = pin(num)
        sh.wire(pp[0], pp[1], 149.86, pp[1])
        sh.hlabel(name, "output", 149.86, pp[1], 0)
    for num in ("3", "4", "5", "6", "7", "8"):
        sh.noconn(*pin(num))

    # ---- decoupling ---------------------------------------------------------------------
    def cap(x, y, ref, val, rail, desc, mpn=None):
        sh.symbol(C, x, y, ref, val, footprint=FP_C1206, ref_pos=(x + 2.54, y - 1.27), val_pos=(x + 2.54, y + 1.27),
                  description=desc, fields={"MPN": mpn} if mpn else None)
        sh.wire(x, y - 3.81, x, y - 5.08)
        pwr(rail, x, y - 5.08)
        sh.wire(x, y + 3.81, x, y + 5.08)
        pwr("GND", x, y + 5.08)

    cap(139.7, 71.12, "C1", "100n", "+3V3", "MCP23017 decoupling, 100 nF X7R 16 V 1206 (SH31B104K160CT)", "SH31B104K160CT")
    cap(170.18, 45.72, "C3", "22u", "+5V", "5 V bulk, 22 uF X7R 16 V 1206 MLCC (EMK316BB7226ML-T)", "EMK316BB7226ML-T")
    cap(182.88, 45.72, "C4", "22u", "+3V3", "3.3 V bulk, 22 uF X7R 16 V 1206 MLCC (EMK316BB7226ML-T)", "EMK316BB7226ML-T")
    sh.wire(182.88, 40.64, 190.5, 40.64)
    sh.junction(182.88, 40.64)
    flag(190.5, 40.64, "#FLG03")

    # ---- U2 TMP117 -----------------------------------------------------------------------
    U2 = "Sensor_Temperature:TMP117xxYBG"
    tx, ty = 101.6, 172.72
    sh.symbol(U2, tx, ty, "U2", "TMP117MAIYBGR", ref_pos=(tx + 3.81, ty - 12.7), val_pos=(tx + 3.81, ty - 10.16),
              fields={"MPN": "TMP117MAIYBGR", "Manufacturer": "Texas Instruments"},
              description="Precision temperature sensor, +/-0.1 C, I2C addr 0x48 (ADD0=GND). Place adjacent to the 1 ohm resistor; thermal proximity only.")
    tp = lambda k: sh.pinpos(U2, tx, ty, 0, k)
    s_da, s_cl, vp, gn, add0, alert = tp("A1"), tp("A2"), tp("B1"), tp("B2"), tp("C1"), tp("C2")
    sh.wire(s_da[0], s_da[1], 83.82, s_da[1])
    sh.label("SDA", 83.82, s_da[1], 180)
    sh.wire(s_cl[0], s_cl[1], 83.82, s_cl[1])
    sh.label("SCL", 83.82, s_cl[1], 180)
    sh.poly(add0, (86.36, add0[1]), (86.36, gn[1] + 2.54), (gn[0], gn[1] + 2.54), gn)
    sh.junction(gn[0], gn[1] + 2.54)
    pwr("GND", gn[0], gn[1] + 2.54)
    sh.wire(vp[0], vp[1], vp[0], vp[1] - 5.08)
    pwr("+3V3", vp[0], vp[1] - 5.08)
    sh.noconn(*alert)
    cap(121.92, 165.1, "C2", "100n", "+3V3", "TMP117 decoupling, 100 nF X7R 16 V 1206 (SH31B104K160CT)", "SH31B104K160CT")

    # ---- NORMAL/HV mode sense (3PDT pole 3) ------------------------------------------------
    # HV throw -> 10k -> +3V3 ; NORMAL throw -> 10k -> GND ; COM -> HV_SENSE with 100k pulldown.
    sh.hlabel("MODE_SW_HV", "passive", 38.1, 134.62, 180)
    sh.symbol(R, 48.26, 134.62, "R24", "10k", angle=90, footprint=FP_R1206, ref_pos=(45.72, 132.08), val_pos=(45.72, 138.43))
    sh.wire(38.1, 134.62, 44.45, 134.62)
    sh.poly((52.07, 134.62), (55.88, 134.62), (55.88, 129.54))
    pwr("+3V3", 55.88, 129.54)
    sh.hlabel("MODE_SW_NORM", "passive", 38.1, 152.4, 180)
    sh.symbol(R, 48.26, 152.4, "R26", "10k", angle=90, footprint=FP_R1206, ref_pos=(45.72, 149.86), val_pos=(45.72, 156.21))
    sh.wire(38.1, 152.4, 44.45, 152.4)
    sh.poly((52.07, 152.4), (55.88, 152.4), (55.88, 157.48))
    pwr("GND", 55.88, 157.48)
    sh.hlabel("HV_SENSE", "passive", 38.1, 142.24, 180)
    sh.wire(38.1, 142.24, 66.04, 142.24)
    sh.junction(66.04, 142.24)
    sh.wire(66.04, 142.24, 71.12, 142.24)
    sh.label("HV_SENSE", 71.12, 142.24)
    sh.symbol(R, 66.04, 149.86, "R25", "100k", footprint=FP_R1206, ref_pos=(68.58, 148.59), val_pos=(68.58, 151.13))
    sh.wire(66.04, 142.24, 66.04, 146.05)
    sh.wire(66.04, 153.67, 66.04, 157.48)
    pwr("GND", 66.04, 157.48)

    # ---- notes -------------------------------------------------------------------------------
    sh.text("ESP32 2.8in touch display module (ESP32-2432S028R type, ELEGOO) - off-board, connected by 3 harnesses:\n"
            "  P1 : TX / RX / VIN(5V) / GND   -> VIN is the module's USB 5 V rail; it powers the relay coils (+5V).\n"
            "  CN1: GND / IO22 / IO27 / 3V3    -> I2C: SCL = IO22, SDA = IO27. 3V3 from the module LDO feeds U1, U2, pull-ups.\n"
            "  P3 : GND / IO35 / IO22 / IO21   -> IO35 (input only) reads HV_SENSE. IO22 duplicate and IO21 (backlight) left open.\n"
            "I2C addresses: MCP23017 0x20 (A2:A0 = 000), TMP117 0x48 (ADD0 = GND). 4.7k pull-ups to 3V3 on this board.\n"
            "MCP23017 GPA0..GPA7, GPB0, GPB1 -> K1..K5 SET/RESET coil drivers (see relay_channel sheets). GPB2..GPB7 spare.\n"
            "MODE_SW_HV / MODE_SW_NORM / HV_SENSE: third pole of the front-panel 3PDT NORMAL/HV toggle. HV position pulls HV_SENSE high through 10k (~3.0 V);\n"
            "NORMAL position pulls it low through 10k; 100k keeps it low while the switch is in transit. IO35 has no internal pull.",
            172.72, 143.51, 1.0)
    sh.text("ESP32 display module harness", 25.4, 30.48, 2.0)
    sh.text("MCP23017 -> relay coil drivers", 66.04, 80.01, 2.0)
    sh.text("Temperature sensor (near 1 ohm)", 76.2, 152.4, 2.0)
    sh.text("NORMAL / HV mode sense", 25.4, 125.73, 2.0)
    return sh


# --------------------------------------------------------------------------------------
# root: nanovolt-divider.kicad_sch
# --------------------------------------------------------------------------------------


def build_root(lib: SymbolLib) -> Sheet:
    sh = Sheet("root", f"{PROJECT}.kicad_sch", ROOT_UUID, "A3", lib, [f"/{ROOT_UUID}"],
               title="Programmable nanovolt divider / precision attenuator - system")
    J = "Connector_Generic:Conn_01x01"
    R = "Device:R"
    SW = "nanovolt-divider:SW_3PDT"
    RC = "relay_channel.kicad_sch"

    def jack(x, y, ref, value, angle, desc):
        sh.symbol(J, x, y, ref, value, angle=angle, footprint=FP_BANANA, description=desc,
                  ref_pos=(x - 2.54, y - 2.54), val_pos=(x - 2.54, y + 3.81) if angle == 180 else (x - 7.62, y + 3.81),
                  hide_value=False)
        return sh.pinpos(J, x, y, angle, "1")

    # ---- NORMAL input + polarity relay -------------------------------------------------------
    nin_p = jack(33.02, 60.96, "J1", "NORMAL IN +", 180, "Front panel banana jack, NORMAL input +")
    nin_n = jack(33.02, 76.2, "J2", "NORMAL IN -", 180, "Front panel banana jack, NORMAL input -")
    px, py = 55.88, 55.88
    sh.sheet("POLARITY (K4)", RC, RELAY_UUIDS[3], px, py, 38.1, 30.48,
             left=[("A_NC", "passive", 5.08), ("B_NO", "passive", 10.16), ("A_NO", "passive", 17.78), ("B_NC", "passive", 22.86)],
             right=[("B_COM", "passive", 5.08), ("A_COM", "passive", 12.7), ("SET", "input", 20.32), ("RESET", "input", 25.4)],
             page="6")
    # NIN+ -> A_NC and B_NO ; NIN- -> A_NO and B_NC
    sh.wire(nin_p[0], nin_p[1], px, 60.96)
    sh.junction(48.26, 60.96)
    sh.poly((48.26, 60.96), (48.26, 66.04), (px, 66.04))
    sh.wire(nin_n[0], nin_n[1], 43.18, 76.2)
    sh.junction(43.18, 76.2)
    sh.poly((43.18, 76.2), (43.18, 73.66), (px, 73.66))
    sh.poly((43.18, 76.2), (43.18, 78.74), (px, 78.74))
    # K4 control
    sh.wire(px + 38.1, 76.2, 99.06, 76.2)
    sh.label("K4_SET", 99.06, 76.2)
    sh.wire(px + 38.1, 81.28, 99.06, 81.28)
    sh.label("K4_RESET", 99.06, 81.28)
    # SRC+ (A_COM) -> range relay bus ; SRC- (B_COM) -> 3PDT pole 2 NORMAL
    src_p = (px + 38.1, 68.58)
    src_n = (px + 38.1, 60.96)

    # ---- range relays + high legs -----------------------------------------------------------------
    rx = 116.84
    bus_x = 111.76
    rbus_x = 181.61
    ranges = [(40.64, "RANGE_1E5 (K1)", "K1", "R31", "100k", "MOX70031003BZE", FP_MOX700,
               "Ohmite MOX-700, 100 kOhm 0.1% 5 ppm/C, high leg for the 1e-5 range" + TODO, "3"),
              (81.28, "RANGE_1E6 (K2)", "K2", "R32", "1M", "MOX70031004BYE", FP_MOX700,
               "Ohmite MOX-700, 1 MOhm 0.1% 10 ppm/C, high leg for the 1e-6 range" + TODO, "4"),
              (121.92, "RANGE_1E7 (K3)", "K3", "R33", "10M", "SM102031005FE", FP_SM102,
               "Ohmite Slim-Mox SM102, 10 MOhm 1%, high leg for the 1e-7 range" + TODO, "5")]
    a_com_ys, r_out_ys = [], []
    for idx, (y, name, kref, rref, val, mpn, fp, desc, page) in enumerate(ranges):
        sh.sheet(name, RC, RELAY_UUIDS[idx], rx, y, 38.1, 30.48,
                 left=[("A_COM", "passive", 5.08), ("B_COM", "passive", 12.7)],
                 right=[("A_NC", "passive", 5.08), ("A_NO", "passive", 10.16), ("B_NC", "passive", 15.24),
                        ("B_NO", "passive", 20.32), ("SET", "input", 25.4), ("RESET", "input", 27.94)],
                 page=page)
        a_com = (rx, y + 5.08)
        a_com_ys.append(a_com[1])
        sh.wire(bus_x, a_com[1], a_com[0], a_com[1])
        sh.noconn(rx, y + 12.7)
        for off in (5.08, 15.24, 20.32):
            sh.noconn(rx + 38.1, y + off)
        # high-leg resistor
        ry = y + 10.16
        sh.symbol(R, 167.64, ry, rref, val, angle=90, footprint=fp, description=desc,
                  fields={"MPN": mpn, "Manufacturer": "Ohmite"}, ref_pos=(165.1, ry - 2.54), val_pos=(165.1, ry + 3.81))
        sh.wire(rx + 38.1, ry, 163.83, ry)
        sh.wire(171.45, ry, rbus_x, ry)
        r_out_ys.append(ry)
        # control labels
        sh.wire(rx + 38.1, y + 25.4, 160.02, y + 25.4)
        sh.label(f"{kref}_SET", 160.02, y + 25.4)
        sh.wire(rx + 38.1, y + 27.94, 160.02, y + 27.94)
        sh.label(f"{kref}_RESET", 160.02, y + 27.94)
    # SRC+ bus
    sh.wire(src_p[0], src_p[1], bus_x, src_p[1])
    ys = sorted(set(a_com_ys + [src_p[1]]))
    for a, b in zip(ys, ys[1:]):
        sh.wire(bus_x, a, bus_x, b)
    for yy in ys[1:-1]:
        sh.junction(bus_x, yy)
    # high-leg output bus -> INJECT relay
    ix, iy = 193.04, 81.28
    inj_in = (ix, iy + 5.08)
    ys = sorted(set(r_out_ys + [inj_in[1]]))
    for a, b in zip(ys, ys[1:]):
        sh.wire(rbus_x, a, rbus_x, b)
    for yy in ys[1:-1]:
        sh.junction(rbus_x, yy)
    sh.wire(rbus_x, inj_in[1], inj_in[0], inj_in[1])

    # ---- INJECT / ISOLATE relay -------------------------------------------------------------------
    sh.sheet("INJECT (K5)", RC, RELAY_UUIDS[4], ix, iy, 38.1, 30.48,
             left=[("A_COM", "passive", 5.08), ("B_COM", "passive", 12.7)],
             right=[("A_NC", "passive", 5.08), ("A_NO", "passive", 10.16), ("B_NC", "passive", 15.24),
                    ("B_NO", "passive", 20.32), ("SET", "input", 25.4), ("RESET", "input", 27.94)],
             page="7")
    sh.noconn(ix, iy + 12.7)
    for off in (5.08, 15.24, 20.32):
        sh.noconn(ix + 38.1, iy + off)
    sh.wire(ix + 38.1, iy + 25.4, 236.22, iy + 25.4)
    sh.label("K5_SET", 236.22, iy + 25.4)
    sh.wire(ix + 38.1, iy + 27.94, 236.22, iy + 27.94)
    sh.label("K5_RESET", 236.22, iy + 27.94)
    inj_node = (ix + 38.1, iy + 10.16)

    # ---- 3PDT NORMAL / HV selector -------------------------------------------------------------
    swx = 259.08
    sh.symbol(SW, swx, 88.9, "SW1", "SW_3PDT NORMAL/HV", angle=180, unit=1, ref_pos=(swx - 3.81, 82.55), val_pos=(swx - 12.7, 97.79))
    sh.symbol(SW, swx, 60.96, "SW1", "SW_3PDT NORMAL/HV", angle=180, unit=2, ref_pos=(swx - 3.81, 54.61), val_pos=(swx - 12.7, 69.85), hide_value=True)
    sh.symbol(SW, swx, 132.08, "SW1", "SW_3PDT NORMAL/HV", angle=180, unit=3, ref_pos=(swx - 3.81, 125.73), val_pos=(swx - 12.7, 140.97), hide_value=True)
    sp = lambda unit, num: sh.pinpos(SW, swx, {1: 88.9, 2: 60.96, 3: 132.08}[unit], 180, num)
    p1_norm, p1_com, p1_hv = sp(1, "1"), sp(1, "2"), sp(1, "3")
    p2_norm, p2_com, p2_hv = sp(2, "4"), sp(2, "5"), sp(2, "6")
    p3_norm, p3_com, p3_hv = sp(3, "7"), sp(3, "8"), sp(3, "9")
    assert p1_norm[1] > p1_hv[1] and p1_norm[0] < p1_com[0], (p1_norm, p1_com, p1_hv)
    # NORMAL path: INJECT relay output -> pole 1 NORM
    sh.wire(inj_node[0], inj_node[1], p1_norm[0], p1_norm[1])
    assert inj_node[1] == p1_norm[1]
    # analog return: SRC- -> pole 2 NORM (routed along the top of the sheet)
    sh.poly(src_n, (101.6, src_n[1]), (101.6, 27.94), (243.84, 27.94), (243.84, p2_norm[1]), p2_norm)
    # mode sense pole
    sh.wire(p3_norm[0], p3_norm[1], 246.38, p3_norm[1])
    sh.label("MODE_SW_NORM", 246.38, p3_norm[1], 180)
    sh.wire(p3_hv[0], p3_hv[1], 246.38, p3_hv[1])
    sh.label("MODE_SW_HV", 246.38, p3_hv[1], 180)
    sh.wire(p3_com[0], p3_com[1], 271.78, p3_com[1])
    sh.label("HV_SENSE", 271.78, p3_com[1])

    # ---- HV input path ----------------------------------------------------------------------------
    hv_n = jack(111.76, 20.32, "J4", "HV IN -", 180, "Front panel shrouded safety banana jack, HV input - (450 VDC service)")
    hv_p = jack(111.76, 35.56, "J3", "HV IN +", 180, "Front panel shrouded safety banana jack, HV input + (450 VDC service)")
    sh.symbol(R, 127.0, 35.56, "R34", "10M", angle=90, footprint=FP_SM102,
              description="Ohmite Slim-Mox SM102, 10 MOhm 1%, dedicated HV divider high leg (~45 uA / 20 mW at 450 V)" + TODO,
              fields={"MPN": "SM102031005FE", "Manufacturer": "Ohmite"}, ref_pos=(124.46, 30.48), val_pos=(124.46, 40.64))
    sh.wire(hv_p[0], hv_p[1], 123.19, 35.56)
    sh.poly((130.81, 35.56), (238.76, 35.56), (238.76, p1_hv[1]), p1_hv)
    sh.poly(hv_n, (248.92, hv_n[1]), (248.92, p2_hv[1]), p2_hv)

    # ---- measurement node, 1 ohm low leg, output ---------------------------------------------------
    rlx = 289.56
    sh.symbol(R, rlx, 76.2, "R35", "1R", footprint=FP_RS02C,
              description="Vishay Dale RS-2C wirewound 1 Ohm 1% 2.5 W - shared low leg, never switched; TMP117 adjacent" + TODO,
              fields={"MPN": "RS02C1R000FE70", "Manufacturer": "Vishay Dale"}, ref_pos=(292.1, 74.93), val_pos=(292.1, 77.47))
    rl_top, rl_bot = sh.pinpos(R, rlx, 76.2, 0, "1"), sh.pinpos(R, rlx, 76.2, 0, "2")
    out_hi = jack(307.34, 88.9, "J5", "DIVIDER OUT HI", 0, "Front panel banana jack, divider output HI (to DMM HI)")
    out_lo = jack(307.34, 60.96, "J6", "DIVIDER OUT LO", 0, "Front panel banana jack, divider output LO (to DMM LO)")
    sh.wire(p1_com[0], p1_com[1], rlx, p1_com[1])
    sh.junction(rlx, p1_com[1])
    sh.wire(rlx, p1_com[1], rl_bot[0], rl_bot[1])
    sh.wire(rlx, p1_com[1], out_hi[0], out_hi[1])
    sh.wire(p2_com[0], p2_com[1], rlx, p2_com[1])
    sh.junction(rlx, p2_com[1])
    sh.wire(rlx, p2_com[1], rl_top[0], rl_top[1])
    sh.wire(rlx, p2_com[1], out_lo[0], out_lo[1])

    # ---- control sheet ------------------------------------------------------------------------------
    cx, cy = 55.88, 177.8
    right = [(n, "output", 5.08 + 2.54 * i) for i, n in enumerate(
        ["K1_SET", "K1_RESET", "K2_SET", "K2_RESET", "K3_SET", "K3_RESET", "K4_SET", "K4_RESET", "K5_SET", "K5_RESET"])]
    right += [("HV_SENSE", "passive", 30.48), ("MODE_SW_NORM", "passive", 33.02), ("MODE_SW_HV", "passive", 35.56)]
    sh.sheet("CONTROL", "control.kicad_sch", CONTROL_UUID, cx, cy, 60.96, 45.72, right=right, page="2")
    for (n, _, off) in right:
        sh.wire(cx + 60.96, cy + off, 124.46, cy + off)
        sh.label(n, 124.46, cy + off)

    # ---- notes ----------------------------------------------------------------------------------------
    sh.text("Metrology topology (precision / quiet region)", 25.4, 15.24, 2.5)
    sh.text("Control (warm / noisy region)", 25.4, 172.72, 2.5)
    sh.text("Relay states (all relays 2-coil latching, pulsed only):\n"
            "  K4 POLARITY : RESET = normal (SRC+ = NORMAL IN +), SET = inverted\n"
            "  K1..K3 RANGE: SET = range active (one at a time, break-before-make), RESET = open\n"
            "  K5 INJECT   : SET = INJECT (high leg drives 1 ohm), RESET = ISOLATE (1 ohm + DMM path untouched)\n"
            "Nominal factor k = 1 / (R_high + 1); actual factors come from calibration.\n"
            "Nothing switches below the measurement node: the 1 ohm low leg, its pads, and OUT HI/LO are permanent.\n"
            "Analog return (SRC-) is never tied to the digital GND of the control section.\n"
            "HV path: 3PDT pole 1 selects the measurement node source, pole 2 selects the return, pole 3 reports the mode.\n"
            "HV IN / R34 / SW1 must be rated and laid out for 450 VDC (creepage, clearance, shrouded jacks).",
            160.02, 215.9, 1.27)
    sh.text("SRC+", 96.52, 67.31, 1.0)
    sh.text("SRC- (analog return)", 103.0, 26.67, 1.0)
    sh.text("INJ_NODE", 236.22, 90.17, 1.0)
    sh.text("MEAS_NODE", 268.0, 87.63, 1.0)
    sh.text("ANALOG_RTN", 268.0, 59.69, 1.0)
    sh.text("1 ohm low leg - TMP117 (U2) mounted adjacent", 283.0, 70.0, 1.0)
    return sh


# --------------------------------------------------------------------------------------
# Project + tables
# --------------------------------------------------------------------------------------


def project_json() -> str:
    pro = {
        "board": {"design_settings": {"defaults": {}, "rule_severities": {}}, "layer_presets": [], "viewports": []},
        "boards": [],
        "cvpcb": {"equivalence_files": []},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{PROJECT}.kicad_pro", "version": 3},
        "net_settings": {"classes": [{"name": "Default", "clearance": 0.2, "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3,
                                      "priority": 2147483647, "bus_width": 12, "line_style": 0, "wire_width": 6}],
                         "meta": {"version": 4}, "net_colors": None, "netclass_assignments": None, "netclass_patterns": []},
        "pcbnew": {"last_paths": {"gencad": "", "idf": "", "netlist": "", "plot": "", "pos_files": "", "specctra_dsn": "", "step": "", "svg": "", "vrml": ""},
                   "page_layout_descr_file": ""},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [[ROOT_UUID, "Root"], [CONTROL_UUID, "CONTROL"]] + [[u, f"{n} (K{i + 1})"] for i, (u, n) in enumerate(zip(RELAY_UUIDS, RELAY_NAMES))],
        "text_variables": {},
    }
    return json.dumps(pro, indent=2) + "\n"


SYM_TABLE = f'''(sym_lib_table
  (version 7)
  (lib (name "{PROJECT}")(type "KiCad")(uri "${{KIPRJMOD}}/lib/{PROJECT}.kicad_sym")(options "")(descr "Project-local symbols"))
)
'''
FP_TABLE = f'''(fp_lib_table
  (version 7)
  (lib (name "{PROJECT}")(type "KiCad")(uri "${{KIPRJMOD}}/lib/{PROJECT}.pretty")(options "")(descr "Project-local footprints"))
)
'''


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf8", newline="\n") as f:
        f.write(text)
    print("wrote", os.path.relpath(path, ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kicad-share", default=r"C:\Program Files\KiCad\10.0\share\kicad")
    args = ap.parse_args()

    lib = SymbolLib(args.kicad_share)
    # register project symbols so lib.get("nanovolt-divider", ...) works
    proj = parse(project_symbol_lib_text())
    for s in find_all(proj, "symbol"):
        name = unq(s[1])
        s[1] = q(f"{PROJECT}:{name}")
        lib.defs[f"{PROJECT}:{name}"] = s

    relay = build_relay_channel(lib)
    control = build_control(lib)
    root = build_root(lib)

    write(os.path.join(HW, f"{PROJECT}.kicad_pro"), project_json())
    write(os.path.join(HW, f"{PROJECT}.kicad_sch"), root.render(is_root=True))
    write(os.path.join(HW, "control.kicad_sch"), control.render())
    write(os.path.join(HW, "relay_channel.kicad_sch"), relay.render())
    write(os.path.join(HW, "sym-lib-table"), SYM_TABLE)
    write(os.path.join(HW, "fp-lib-table"), FP_TABLE)
    write(os.path.join(HW, "lib", f"{PROJECT}.kicad_sym"), project_symbol_lib_text())
    write(os.path.join(HW, "lib", f"{PROJECT}.pretty", "Relay_DPDT_Panasonic_TQ2_THT.kicad_mod"), tq2_footprint_text())


if __name__ == "__main__":
    main()
