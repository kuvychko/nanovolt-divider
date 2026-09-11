# /// script
# dependencies = ["numpy", "scipy", "pillow"]
# ///
"""Bootstrap router for the nanovolt-divider Rev0 board.

Hand routes (design intent) come from route_hand.py; everything else is routed by A* on a 0.1 mm grid,
two layers, 45-degree moves with turn penalties, clearance from Euclidean distance transforms of the
copper already placed.  Nets are routed one at a time in route_hand.order(); there is no rip-up, so if
a net fails, change the order or add a hand route rather than loosening a rule.

    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py dump  hardware/nanovolt-divider.kicad_pcb %TEMP%/nvd_geom.json
    uv run tools/route_pcb.py %TEMP%/nvd_geom.json %TEMP%/nvd_routes.json
    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/pcb_io.py apply hardware/nanovolt-divider.kicad_pcb %TEMP%/nvd_routes.json

`apply` deletes every track and via on the board first.  Like gen_pcb.py this produced the first
routed board and is historical once the board has been edited by hand: re-running it throws those
edits away.  The routing itself is deterministic, but KiCad gives every new track a random UUID, so
the board diff is large even when the copper is identical - compare routes JSON, or DRC, instead.
It does not run DRC.
"""
import heapq
import json
import math
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route_hand as HR  # noqa: E402

G = 0.1
BW, BH = 60.0, 69.1
NX, NY = int(round(BW / G)) + 1, int(round(BH / G)) + 1
MARG = 0.08            # raster slack added to every clearance
CLR = 0.2
EDGE = 0.5
HOLE = 0.3
VIA_D = 0.6
VIA_COST = 1.6         # mm-equivalent
TURN = (0.0, 0.12, 0.5)  # 0, 45, 90 degree turn penalties (mm)
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
INF = float("inf")


def blank():
    return Image.new("1", (NX, NY), 0)


def arr(img):
    return np.array(img, dtype=bool)


def draw_poly(dr, pts):
    dr.polygon([(x / G, y / G) for x, y in pts], fill=1, outline=1)


def draw_circle(dr, x, y, r):
    dr.ellipse([(x - r) / G, (y - r) / G, (x + r) / G, (y + r) / G], fill=1, outline=1)


def draw_seg(dr, a, b, w):
    (x1, y1), (x2, y2) = a, b
    r = w / 2
    L = math.hypot(x2 - x1, y2 - y1)
    if L > 1e-9:
        nx, ny = -(y2 - y1) / L * r, (x2 - x1) / L * r
        draw_poly(dr, [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)])
    for x, y in (a, b):
        draw_circle(dr, x, y, r)


def rect_mask(x0, y0, x1, y1):
    img = blank()
    draw_poly(ImageDraw.Draw(img), [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    return arr(img)


class Board:
    def __init__(self, geom):
        self.net_id = {}
        self.names = []
        self.own = [np.full((NY, NX), -1, np.int32) for _ in range(2)]
        # edges: outside of the board plus slots
        edge = np.ones((NY, NX), bool)
        edge[1:-1, 1:-1] = False
        for e in geom["edges"]:
            if e["shape"] == "Rect" and e["start"] != [0.0, 0.0]:
                edge |= rect_mask(*e["start"], *e["end"])
        self.d_edge = ndimage.distance_transform_edt(~edge) * G
        hole = np.zeros((NY, NX), bool)
        self.pads = {}   # net -> list of pad dicts with masks
        for p in geom["pads"]:
            if not p["net"] and p["drill"] > 0:
                img = blank()
                draw_circle(ImageDraw.Draw(img), p["pos"][0], p["pos"][1], p["drill"] / 2)
                hole |= arr(img)
                continue
            L = 0 if p["layer"] == "F" else 1
            img = blank()
            dr = ImageDraw.Draw(img)
            for pp in p["poly"]:
                draw_poly(dr, pp)
            m = arr(img)
            nid = self.nid(p["net"])
            self.own[L][m & (self.own[L] == -1)] = nid
            key = (p["ref"], p["num"])
            lst = self.pads.setdefault(p["net"], [])
            ent = next((q for q in lst if q["key"] == key), None)
            if ent is None:
                ent = {"key": key, "pos": p["pos"], "mask": [None, None]}
                lst.append(ent)
            ent["mask"][L] = m
        self.d_hole = ndimage.distance_transform_edt(~hole) * G
        self.tracks = []   # (net, layer, w, pts)
        self.vias = []     # (net, x, y)

    def nid(self, name):
        if name not in self.net_id:
            self.net_id[name] = len(self.names)
            self.names.append(name)
        return self.net_id[name]

    def add_track(self, net, L, w, pts):
        img = blank()
        dr = ImageDraw.Draw(img)
        for a, b in zip(pts, pts[1:]):
            draw_seg(dr, a, b, w)
        m = arr(img)
        nid = self.nid(net)
        clash = m & (self.own[L] >= 0) & (self.own[L] != nid)
        self.own[L][m & (self.own[L] == -1)] = nid
        self.tracks.append((net, L, w, [tuple(map(float, p)) for p in pts]))
        return m, int(clash.sum())

    def add_via(self, net, x, y):
        img = blank()
        draw_circle(ImageDraw.Draw(img), x, y, VIA_D / 2)
        m = arr(img)
        nid = self.nid(net)
        for L in (0, 1):
            self.own[L][m & (self.own[L] == -1)] = nid
        self.vias.append((net, float(x), float(y)))
        return m


def cells(mask):
    j, i = np.nonzero(mask)
    return list(zip(j.tolist(), i.tolist()))


def astar(srcs, tgt, blk, vblk, cost, hxy):
    """srcs: list of (L, j, i); tgt: [mask F, mask B]; returns list of (L, j, i) or None."""
    tx, ty = hxy
    ti, tj = tx / G, ty / G

    def h(i, j):
        dx, dy = abs(i - ti), abs(j - tj)
        return (max(dx, dy) + 0.4142 * min(dx, dy)) * G

    best = {}
    parent = {}
    openh = []
    for (L, j, i) in srcs:
        s = (L, j, i, 8)
        best[s] = 0.0
        heapq.heappush(openh, (h(i, j), 0.0, s))
    n = 0
    while openh:
        f, gc, s = heapq.heappop(openh)
        if gc > best.get(s, INF):
            continue
        L, j, i, d = s
        n += 1
        if n > 3_000_000:
            return None
        if tgt[L][j, i]:
            path = [s]
            while s in parent:
                s = parent[s]
                path.append(s)
            return [(p[0], p[1], p[2]) for p in reversed(path)]
        bl = blk[L]
        cl = cost[L]
        for k, (di, dj) in enumerate(DIRS):
            if d != 8:
                t = (k - d) % 8
                t = min(t, 8 - t)
                if t > 2:
                    continue
                tc = TURN[t]
            else:
                tc = 0.0
            ni, nj = i + di, j + dj
            if ni < 0 or nj < 0 or ni >= NX or nj >= NY or bl[nj, ni]:
                continue
            diag = di != 0 and dj != 0
            if diag and (bl[j, ni] or bl[nj, i]):
                continue
            ng = gc + (1.41421 if diag else 1.0) * G * cl[nj, ni] + tc
            ns = (L, nj, ni, k)
            if ng < best.get(ns, INF):
                best[ns] = ng
                parent[ns] = s
                heapq.heappush(openh, (ng + h(ni, nj), ng, ns))
        if not vblk[j, i]:
            ns = (1 - L, j, i, 8)
            ng = gc + VIA_COST
            if ng < best.get(ns, INF):
                best[ns] = ng
                parent[ns] = s
                heapq.heappush(openh, (ng + h(i, j), ng, ns))
    return None


def path_to_items(path):
    """-> list of (layer, [(x, y), ...]) polylines and list of via (x, y)."""
    polys, vias = [], []
    cur = [path[0]]
    for p in path[1:]:
        if p[0] != cur[-1][0]:
            if len(cur) > 1:
                polys.append(cur)
            vias.append((p[2] * G, p[1] * G))
            cur = [p]
        else:
            cur.append(p)
    if len(cur) > 1:
        polys.append(cur)
    out = []
    for poly in polys:
        pts = [(poly[0][2], poly[0][1])]
        for a, b, c in zip(poly, poly[1:], poly[2:]):
            if (b[2] - a[2], b[1] - a[1]) != (c[2] - b[2], c[1] - b[1]):
                pts.append((b[2], b[1]))
        pts.append((poly[-1][2], poly[-1][1]))
        out.append((poly[0][0], [(round(i * G, 3), round(j * G, 3)) for i, j in pts]))
    return out, vias


def snap_ends(polys, own_tracks):
    """A path ends wherever it first touches same-net copper, which for a track is usually its
    edge, not its centreline - KiCad calls that dangling.  Extend such ends onto the centreline."""
    for end in (0, -1):
        if not polys:
            return
        L, pts = polys[end]
        px, py = pts[end]
        best = None
        for _, tl, tw, tpts in own_tracks:
            if tl != L:
                continue
            for (ax, ay), (bx, by) in zip(tpts, tpts[1:]):
                dx, dy = bx - ax, by - ay
                ll = dx * dx + dy * dy
                t = 0.0 if ll == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ll))
                qx, qy = ax + t * dx, ay + t * dy
                d = math.hypot(px - qx, py - qy)
                if d <= tw / 2 + G and (best is None or d < best[0]):
                    best = (d, (round(qx, 4), round(qy, 4)))
        if best and best[0] > 1e-3:
            if end == 0:
                pts.insert(0, best[1])
            else:
                pts.append(best[1])


def main():
    geom = json.load(open(sys.argv[1]))
    B = Board(geom)
    yy, xx = np.mgrid[0:NY, 0:NX] * G

    # ---- hand routes ------------------------------------------------------------------------
    comp_extra = {}   # net -> list of [maskF, maskB] for hand-routed copper
    for net, layer, w, pts in HR.tracks():
        L = 0 if layer == "F" else 1
        m, clash = B.add_track(net, L, w, pts)
        if clash:
            print(f"  hand track {net} {layer} {pts[:2]}... overlaps other copper ({clash} cells)")
        ms = [np.zeros((NY, NX), bool), np.zeros((NY, NX), bool)]
        ms[L] = m
        comp_extra.setdefault(net, []).append(ms)
    for net, x, y in HR.vias():
        m = B.add_via(net, x, y)
        comp_extra.setdefault(net, []).append([m, m])

    high, lows = HR.HIGH, HR.LOWS
    failed = []
    t0 = time.time()
    for net in HR.order(list(B.pads)):
        w = HR.width(net)
        nid = B.nid(net)
        # items: pads + hand copper; union-find by overlap
        items = [pd["mask"] for pd in B.pads[net]]
        items = [[m if m is not None else np.zeros((NY, NX), bool) for m in it] for it in items]
        items += comp_extra.get(net, [])
        if net == "DGND":
            pour = (xx > 0.9) & (xx < 59.1) & (yy > 0.9) & (yy < 31.9)
            items.append([np.zeros((NY, NX), bool), pour])
        parent = list(range(len(items)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        lab = [ndimage.label(np.logical_or.reduce([it[L] for it in items]))[0] for L in (0, 1)]
        for L in (0, 1):
            for a, it in enumerate(items):
                if it[L].any():
                    ls = set(np.unique(lab[L][it[L]]).tolist()) - {0}
                    for b, it2 in enumerate(items[:a]):
                        if it2[L].any() and ls & set(np.unique(lab[L][it2[L]]).tolist()):
                            parent[find(a)] = find(b)
        # THT pads join both layers (same item), vias too (same item): done by construction.

        def blocked(extra=0.0):
            res = []
            for L in (0, 1):
                other = (B.own[L] >= 0) & (B.own[L] != nid)
                d = ndimage.distance_transform_edt(~other) * G
                b = d < CLR + w / 2 + MARG
                if net in high or net in lows:
                    enemy = lows if net in high else high
                    ids = [B.net_id[n] for n in enemy if n in B.net_id]
                    em = np.isin(B.own[L], ids)
                    if em.any():
                        de = ndimage.distance_transform_edt(~em) * G
                        b |= de < HR.SEP + w / 2 + MARG
                b |= B.d_edge < EDGE + w / 2 + MARG
                b |= B.d_hole < HOLE + w / 2 + MARG
                b |= HR.region_block(net, xx, yy, L)
                res.append((b, d))
            vb = np.zeros((NY, NX), bool)
            for L in (0, 1):
                vb |= res[L][1] < CLR + VIA_D / 2 + MARG
            vb |= B.d_edge < EDGE + VIA_D / 2 + MARG
            vb |= B.d_hole < HOLE + VIA_D / 2 + MARG
            vb |= res[0][0] | res[1][0]
            vb |= HR.via_block(net, xx, yy)
            return [res[0][0], res[1][0]], vb

        cost = [HR.cost(net, xx, yy, L) for L in (0, 1)]
        guard = 0
        while len({find(a) for a in range(len(items))}) > 1 and guard < 50:
            guard += 1
            blk, vblk = blocked()
            roots = {}
            for a in range(len(items)):
                roots.setdefault(find(a), []).append(a)
            start_root = find(0)
            src_m = [np.logical_or.reduce([items[a][L] for a in roots[start_root]]) for L in (0, 1)]
            # nearest other component (by cell distance)
            dsrc = ndimage.distance_transform_edt(~(src_m[0] | src_m[1]))
            best_r, best_d = None, INF
            for r, mem in roots.items():
                if r == start_root:
                    continue
                mm = np.logical_or.reduce([items[a][0] | items[a][1] for a in mem])
                dd = dsrc[mm].min()
                if dd < best_d:
                    best_d, best_r = dd, r
            tgt_m = [np.logical_or.reduce([items[a][L] for a in roots[best_r]]) for L in (0, 1)]
            tgt = [tgt_m[L] & ~blk[L] for L in (0, 1)]
            srcs = [(L, j, i) for L in (0, 1) for (j, i) in cells(src_m[L] & ~blk[L])]
            if not srcs or not (tgt[0].any() or tgt[1].any()):
                print(f"  {net}: no free source/target cells")
                failed.append(net)
                break
            tj, ti = np.nonzero(tgt[0] | tgt[1])
            hxy = (ti.mean() * G, tj.mean() * G)
            path = astar(srcs, tgt, blk, vblk, cost, hxy)
            if path is None:
                print(f"  {net}: FAILED between components")
                failed.append(net)
                break
            polys, vias = path_to_items(path)
            snap_ends(polys, [t for t in B.tracks if t[0] == net])
            new = [np.zeros((NY, NX), bool), np.zeros((NY, NX), bool)]
            for L, pts in polys:
                m, _ = B.add_track(net, L, w, pts)
                new[L] |= m
            for (x, y) in vias:
                m = B.add_via(net, x, y)
                new[0] |= m
                new[1] |= m
            items.append(new)
            parent.append(len(parent))
            parent[find(len(items) - 1)] = find(start_root)
            parent[find(best_r)] = find(start_root)
        print(f"{net:28s} w={w} {'FAIL' if net in failed else 'ok'}  t={time.time() - t0:.1f}s", flush=True)

    json.dump({"tracks": B.tracks, "vias": B.vias, "failed": failed}, open(sys.argv[2], "w"))
    print("failed:", failed)


if __name__ == "__main__":
    main()
