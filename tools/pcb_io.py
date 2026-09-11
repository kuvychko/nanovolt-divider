#!/usr/bin/env python3
"""pcbnew side of tools/route_pcb.py.  Run with KiCad's own Python, which has pcbnew:

    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py dump  BOARD OUT.json
    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py apply BOARD ROUTES.json

dump   writes the pads (copper outline, net, layer) and the Edge.Cuts rectangles the router needs, in
       board coordinates (mm from the board's top-left corner).
apply  deletes EVERY track and via on BOARD, adds the routed ones, refills the zones and saves BOARD
       in place with LF line endings (pcbnew writes CRLF on Windows; .gitattributes pins LF).
"""
import json
import sys

import pcbnew

OX, OY = 50.0, 50.0          # board origin on the KiCad sheet, as in gen_pcb.py


def mm(v):
    return round(pcbnew.ToMM(v), 4)


def xy(p):
    return [round(mm(p.x) - OX, 4), round(mm(p.y) - OY, 4)]


def dump(board_path, out):
    b = pcbnew.LoadBoard(board_path)
    d = {"pads": [], "edges": []}
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                if not pad.IsOnLayer(layer):
                    continue
                sp = pcbnew.SHAPE_POLY_SET()
                pad.TransformShapeToPolygon(sp, layer, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_INSIDE)
                polys = [[xy(sp.Outline(i).CPoint(j)) for j in range(sp.Outline(i).PointCount())]
                         for i in range(sp.OutlineCount())]
                d["pads"].append({"ref": fp.GetReference(), "num": pad.GetNumber(), "net": pad.GetNetname(),
                                  "layer": "F" if layer == pcbnew.F_Cu else "B", "poly": polys,
                                  "pos": xy(pad.GetPosition()), "drill": mm(pad.GetDrillSize().x)})
    for dr in b.GetDrawings():
        if dr.GetLayer() == pcbnew.Edge_Cuts:
            d["edges"].append({"start": xy(dr.GetStart()), "end": xy(dr.GetEnd()), "shape": dr.GetShapeStr()})
    json.dump(d, open(out, "w"))
    print(f"{len(d['pads'])} pad outlines, {len(d['edges'])} edge shapes -> {out}")


def apply(board_path, routes):
    b = pcbnew.LoadBoard(board_path)
    P = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x + OX), pcbnew.FromMM(y + OY))  # noqa: E731
    for t in list(b.GetTracks()):
        b.Remove(t)
    nets = b.GetNetsByName()
    r = json.load(open(routes))
    n = 0
    for net, layer, w, pts in r["tracks"]:
        for a, c in zip(pts, pts[1:]):
            if a == c:
                continue
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(P(*a))
            t.SetEnd(P(*c))
            t.SetWidth(pcbnew.FromMM(w))
            t.SetLayer(pcbnew.F_Cu if layer == 0 else pcbnew.B_Cu)
            t.SetNet(nets[net])
            b.Add(t)
            n += 1
    for net, x, y in r["vias"]:
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(P(x, y))
        v.SetWidth(pcbnew.FromMM(0.6))
        v.SetDrill(pcbnew.FromMM(0.3))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(nets[net])
        b.Add(v)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(board_path, b)
    raw = open(board_path, "rb").read()
    open(board_path, "wb").write(raw.replace(b"\r\n", b"\n"))
    print(f"{n} track segments, {len(r['vias'])} vias -> {board_path}"
          + (f"   FAILED NETS: {r['failed']}" if r.get("failed") else ""))


if __name__ == "__main__":
    cmd, board, path = sys.argv[1:4]
    {"dump": dump, "apply": apply}[cmd](board, path)
