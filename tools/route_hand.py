"""Hand routes and routing policy for tools/route_pcb.py (board coordinates, mm, origin top-left, y down).

Everything that carries design intent is laid here by hand, and route_pcb.py routes the rest around it:
  * the MEAS_NODE / ANALOG_RTN pair and the DMM sense runs at R35
  * one driver-cell template repeated for all ten coil drivers, and one coil-crossing template per relay
  * the TMP275 bundle (SDA, SCL, DGND, +3V3) as a single spine onto the 1 ohm island
The policy half says which nets are routed first, how wide, where they may not go, and which net
classes must keep extra distance from each other (HIGH vs LOWS: see SEP).
"""
import numpy as np

# Driver columns: (x, Q/D number).  SET column at relay x - 2, RESET at relay x + 2.
RELAY_X = {"K4": 9.6, "K1": 19.8, "K2": 30.0, "K3": 40.2, "K5": 50.4}
CELL_Q = {"K1": (1, 2), "K2": (3, 4), "K3": (5, 6), "K4": (7, 8), "K5": (9, 10)}
COLUMNS = [(RELAY_X[k] + dx, CELL_Q[k][s]) for k in RELAY_X for s, dx in ((0, -2.0), (1, 2.0))]

HIGH = {"/SRC_P", "/NORMAL_IN_P", "/NORMAL_IN_N", "/R100K_IN", "/R1M_IN", "/R10M_IN"}
LOWS = {"/RANGE_BUS", "/R100K_OUT", "/R1M_OUT", "/R10M_OUT", "/MEAS_NODE"}
# HIGH sits at the source voltage, LOWS at the bottom of the selected high leg.  Surface leakage
# between the two is a resistor in parallel with the high leg - 10 ppm of error at 1e12 ohm on the
# 10 M range - so same-layer copper of the two classes keeps SEP apart instead of the 0.2 default.
# Opposite layers are separated by 1.6 mm of FR4 bulk, which is orders of magnitude better, so the
# rule is per layer.  SRC_RTN and ANALOG_RTN are in neither class: leakage from HIGH into them only
# loads the source.  Leakage from digital nets into LOWS lands on the 1 ohm node and is negligible.
SEP = 0.5
PRECISION = HIGH | LOWS | {"/SRC_RTN", "/ANALOG_RTN"}
ISLAND = {"/MEAS_NODE", "/ANALOG_RTN", "+3V3", "/CONTROL/SCL", "/CONTROL/SDA", "DGND"}
BUS_5V_Y = 32.5


def tracks():
    T = []
    # ---- MEAS_NODE / ANALOG_RTN: one tight pair on B.Cu from K5 to R35 --------------------
    # ANALOG_RTN runs on the side facing the high-leg pads so it, not MEAS_NODE, takes any
    # surface leakage from R*_IN.  The pair stays together down to R35's axis and then splits
    # along it, so the current loop is the resistor itself rather than a triangle beside it.
    # It crosses the centre bridge on the board's centre line and splits symmetrically, so the two
    # R35 terminals see the same copper path back to the rest of the board.
    T.append(("/ANALOG_RTN", "B", 0.4, [(46.59, 38.06), (51.0, 38.06), (51.0, 52.3), (29.65, 52.3),
                                         (29.65, 64.9), (28.95, 65.6), (19.84, 65.6)]))
    T.append(("/MEAS_NODE", "B", 0.4, [(54.21, 38.06), (51.7, 38.06), (51.7, 53.0), (30.35, 53.0),
                                        (30.35, 64.9), (31.05, 65.6), (40.16, 65.6)]))
    # DMM sense: leaves R35's pads on the outer side, carrying no injection current.
    T.append(("/ANALOG_RTN", "F", 0.4, [(14.5, 65.6), (19.84, 65.6)]))
    T.append(("/MEAS_NODE", "F", 0.4, [(40.16, 65.6), (45.5, 65.6)]))
    # ---- driver cells ------------------------------------------------------------------------
    for x, n in COLUMNS:
        b, c = f"Net-(Q{n}-B)", f"Net-(D{n}-A)"
        T.append((b, "F", 0.25, [(x, 18.06), (x, 19.94)]))
        T.append((b, "F", 0.25, [(x, 19.94), (x - 1.35, 19.94), (x - 1.35, 24.65)]))
        T.append(("DGND", "F", 0.3, [(x, 22.86), (x + 1.3, 22.86)]))
        T.append(("DGND", "F", 0.3, [(x - 0.94, 26.55), (x - 1.44, 27.05)]))
        T.append((c, "F", 0.3, [(x + 1.0, 25.6), (x + 1.0, 27.14), (x, 28.14)]))
        T.append(("+5V", "F", 0.4, [(x, 31.45), (x, BUS_5V_Y)]))
    xs = [x for x, _ in COLUMNS]
    T.append(("+5V", "B", 0.5, [(min(xs), BUS_5V_Y), (max(xs), BUS_5V_Y)]))
    # ---- coil drive: SET column (kx-2) feeds the right coil pin 5, RESET (kx+2) the left pin 6 ----
    # They cross once per relay: SET stays on F.Cu along y 33.8, RESET drops to B.Cu along y 33.4.
    # This way round the left half of the relay's top is free on F.Cu, which is where the TMP275
    # bundle enters K2.
    for k, kx in RELAY_X.items():
        ns, nr = CELL_Q[k]
        T.append((f"Net-(D{ns}-A)", "F", 0.3, [(kx - 1.0, 27.14), (kx - 1.0, 32.8), (kx, 33.8),
                                               (kx + 2.3, 33.8), (kx + 3.81, 35.31), (kx + 3.81, 35.52)]))
        T.append((f"Net-(D{nr}-A)", "F", 0.3, [(kx + 3.0, 27.14), (kx + 3.0, 33.4)]))
        T.append((f"Net-(D{nr}-A)", "B", 0.3, [(kx + 3.0, 33.4), (kx - 2.3, 33.4), (kx - 3.81, 34.91),
                                               (kx - 3.81, 35.52)]))
    # ---- TMP275 bundle: SDA, SCL, DGND, +3V3 on one F.Cu spine --------------------------------
    # Down the gap between the K1 and K2 driver pairs, into K2's interior over its left half, under
    # R32's body and across the centre bridge, left of the MEAS/RTN pair.  Pitch 0.65 so the 45
    # degree jog keeps clearance.  The precision chains cross it on B.Cu.  At the island SCL passes
    # under U2's body to pin 2, DGND ties pins 4-7 and C2, +3V3 fans out to pin 8 and C2.
    for i, net in enumerate(("/CONTROL/SDA", "/CONTROL/SCL", "DGND", "+3V3")):
        xc, xa = 23.9 + 0.65 * i, 27.35 + 0.65 * i
        T.append((net, "F", 0.25, [(xc, 17.5 if net == "DGND" else 16.0), (xc, 31.35), (xa, 34.8), (xa, 53.3)]))
    T.append(("/CONTROL/SDA", "F", 0.25, [(27.35, 53.3), (27.35, 57.19)]))
    T.append(("/CONTROL/SCL", "F", 0.25, [(28.0, 53.3), (28.0, 54.8), (28.95, 55.75), (28.95, 58.47),
                                          (27.53, 58.47)]))
    T.append(("DGND", "F", 0.25, [(28.65, 53.3), (28.65, 54.2), (30.8, 56.35), (30.8, 58.47), (32.47, 58.47),
                                  (32.47, 61.0), (27.53, 61.0)]))
    T.append(("DGND", "F", 0.3, [(32.47, 61.0), (38.97, 61.0), (38.97, 59.1)]))
    T.append(("+3V3", "F", 0.25, [(29.3, 53.3), (31.1, 55.1), (33.0, 55.1), (36.03, 58.13), (36.03, 59.1)]))
    T.append(("+3V3", "F", 0.25, [(32.47, 55.1), (32.47, 57.19)]))
    return T


def vias():
    V = []
    for x, n in COLUMNS:
        V += [("DGND", x + 1.3, 22.86), ("DGND", x - 1.44, 27.05), ("+5V", x, BUS_5V_Y)]
    for k, kx in RELAY_X.items():
        V.append((f"Net-(D{CELL_Q[k][1]}-A)", kx + 3.0, 33.4))
    V.append(("DGND", 25.2, 17.5))      # TMP275 bundle ground, straight into the pour; set below
                                        # the other spine tops so they stay reachable
    return V


def width(net):
    if net in ("/MEAS_NODE", "/ANALOG_RTN"):
        return 0.4
    if net in PRECISION:
        return 0.3
    if net == "+5V":
        return 0.5
    if net == "DGND":
        return 0.4
    return 0.25


def order(nets):
    first = ["/RANGE_BUS", "/SRC_P", "/R10M_IN", "/R10M_OUT", "/R1M_IN", "/R1M_OUT", "/R100K_IN",
             "/R100K_OUT", "/NORMAL_IN_P", "/NORMAL_IN_N", "/SRC_RTN", "/MEAS_NODE", "/ANALOG_RTN"]
    tmp = ["/CONTROL/SCL", "/CONTROL/SDA", "+3V3"]
    coils = sorted(n for n in nets if n.startswith("Net-(D"))
    power = ["+5V"]
    mcp = sorted(n for n in nets if n.startswith("/K") and ("_SET" in n or "_RESET" in n))
    ctrl = ["Net-(U1-~{RESET})"]
    # Precision first, so its chains get the clean paths.  Then the TMP275 nets and DGND, whose only
    # way onto the island is the spine.  Coils are hand-routed already.  The MCP23017 lines before
    # +5V: +5V is the more flexible of the two, and routed first it forced K4_SET through 10 vias.
    seq = first + tmp + ["DGND"] + coils + mcp + ctrl + power
    rest = sorted(n for n in nets if n not in seq and n)
    return [n for n in seq + rest if n in nets]


def region_block(net, xx, yy, L):
    b = np.zeros(xx.shape, bool)
    if net not in ISLAND:
        b |= yy > 55.7
        b |= (yy > 53.2) & (xx > 24.0) & (xx < 36.0)
    else:
        # The island is reached through the centre bridge only.  A track over an edge bridge would
        # bring heat in at one end of R35, and a gradient between its terminals is a thermal EMF.
        b |= (yy > 53.2) & (yy < 56.5) & ((xx < 24.5) | (xx > 35.5))
    if net in PRECISION:
        b |= yy < 33.0
    return b


def via_block(net, xx, yy):
    # no vias on the centre bridge: it is the island's mechanical support
    return (yy > 52.9) & (yy < 56.9) & (xx > 24.0) & (xx < 36.0)


def cost(net, xx, yy, L):
    c = np.ones(xx.shape)
    if L == 1 and net != "DGND":
        c[yy < 32.6] = 3.0          # keep the DGND pour whole
    if net not in PRECISION and net not in ISLAND and not net.startswith("Net-(D") and net != "+5V":
        c[yy > 33.5] *= 1.5          # digital nets stay out of the precision area
    return c
