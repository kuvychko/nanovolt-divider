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
    T += control_band_tracks()
    return T


# ---- control band ------------------------------------------------------------------------------
# U1 (MCP23017, SOIC-28W at 90 deg): lower pad row 1..14 left to right at y 11.75, facing the drivers;
# upper row 15..28 right to left at y 2.45, facing the board edge.
def LX(n):
    return 31.245 + 1.27 * (n - 1)


def UX(m):
    return 47.755 - 1.27 * (m - 15)


U1_LO, U1_UP = 11.75, 2.45
FAN_LEFT = [(1, "/K4_SET", 7.6), (2, "/K4_RESET", 11.6), (3, "/K1_SET", 17.8), (4, "/K1_RESET", 21.8),
            (5, "/K2_SET", 28.0)]


def control_band_tracks():
    T = []
    # Coil fan-out.  GPB0..GPB7 (pins 1-8) carry eight lines in the driver columns' own order, so they
    # drop off the lower row and fan out without crossing.  Five go left: pin 1 leaves its pad sideways,
    # pins 2-5 pass under pin 1 and over R7 in four 0.2 mm lanes at 0.4 pitch - the most that fit
    # between the pad row (12.775) and R7's top (14.58).
    for n, net, x in FAN_LEFT:
        y = 12.675 + 0.4 * (n - 1)
        T.append((net, "F", 0.2, [(LX(n), U1_LO if n > 1 else y), (LX(n), y), (x, y), (x, 15.14)]))
    # K2_RESET ends at R7, under the lanes above it, so it goes below them and enters R7 from the side.
    T.append(("/K2_RESET", "F", 0.2, [(LX(6), U1_LO), (LX(6), 13.6), (36.525, 14.675), (33.3, 14.675),
                                      (32.835, 15.14), (32.0, 15.14)]))
    T.append(("/K3_SET", "F", 0.2, [(LX(7), U1_LO), (LX(7), 15.14)]))
    T.append(("/K3_RESET", "F", 0.2, [(LX(8), U1_LO), (LX(8), 15.14), (41.6, 15.14)]))
    # K5 is on GPA0/GPA1 (upper row): under the package to the right, down the channel beside C1.
    T.append(("/K5_RESET", "F", 0.2, [(UX(21), U1_UP), (UX(21), 3.8), (49.4, 3.8), (49.4, 12.6), (50.1, 13.3),
                                      (51.7, 13.3), (52.4, 14.0), (52.4, 15.14)]))
    T.append(("/K5_SET", "F", 0.2, [(UX(22), U1_UP), (UX(22), 4.25), (48.55, 4.25), (48.55, 15.14)]))
    # I2C and 3V3 reach U1 under its body, below the K5 lanes, stacked in the order they drop to their
    # pins: SDA (pin 13) outermost, 3V3 (pin 9) innermost.
    T.append(("/CONTROL/SDA", "F", 0.25, [(26.5, 2.64), (28.2, 2.64), (30.36, 4.8), (LX(13), 4.8), (LX(13), U1_LO)]))
    T.append(("/CONTROL/SCL", "F", 0.25, [(26.5, 8.14), (28.0, 8.14), (30.89, 5.25), (LX(12), 5.25), (LX(12), U1_LO)]))
    T.append(("+3V3", "F", 0.25, [(26.5, 11.08), (28.4, 11.08), (33.78, 5.7), (LX(9), 5.7), (LX(9), U1_LO)]))
    T.append(("DGND", "F", 0.3, [(LX(10), U1_LO), (LX(10), 9.6)]))                      # VSS
    T.append(("DGND", "F", 0.3, [(UX(17), U1_UP), (48.75, U1_UP)]))                     # A2..A0
    T.append(("Net-(U1-~{RESET})", "F", 0.25, [(UX(18), U1_UP), (UX(18), 0.85), (51.2, 0.85), (52.6, 2.25),
                                               (52.6, 2.64)]))
    # C1 / R23 3V3: the bus runs under U1 and the K5 lines fence the right-hand channel, so this one
    # hops on B.Cu from pin 9 to C1.
    T.append(("+3V3", "F", 0.25, [(LX(9), U1_LO), (LX(9), 13.45)]))
    T.append(("+3V3", "B", 0.25, [(LX(9), 13.45), (49.0, 13.45), (50.7, 11.75), (50.7, 11.0)]))
    T.append(("+3V3", "F", 0.25, [(50.7, 11.0), (51.9, 11.0)]))
    T.append(("+3V3", "F", 0.25, [(52.6, 11.08), (54.1, 11.08), (54.1, 5.56), (52.6, 5.56)]))
    T.append(("DGND", "F", 0.3, [(52.6, 8.12), (50.7, 8.12)]))
    # Harness: SDA and SCL cross over CN1's 3V3 pad and pass between C3 and C4 in two 0.2 mm lanes;
    # 3V3 goes through C4 to R22; +5V runs to C3 and down the left edge to the coil bus.
    T.append(("/CONTROL/SDA", "F", 0.2, [(12.98, 7.0), (12.98, 5.9), (13.63, 5.25), (17.3, 5.25), (18.605, 6.555),
                                         (22.7, 6.555), (24.6, 4.655), (24.6, 2.64), (26.5, 2.64)]))
    T.append(("/CONTROL/SCL", "F", 0.2, [(10.44, 7.0), (11.74, 8.3), (13.55, 8.3), (14.25, 7.6), (14.25, 6.35),
                                         (14.95, 5.65), (17.0, 5.65), (18.305, 6.955), (23.5, 6.955), (24.685, 8.14),
                                         (26.5, 8.14)]))
    T.append(("+3V3", "F", 0.3, [(15.52, 7.0), (15.52, 8.2), (18.4, 11.08), (26.5, 11.08)]))
    T.append(("+5V", "F", 0.5, [(7.9, 2.2), (10.3, 4.6), (20.42, 4.6), (21.4, 5.58)]))
    T.append(("+5V", "F", 0.5, [(7.9, 2.2), (5.8, 2.2), (5.0, 3.0), (5.0, 31.0), (6.5, 32.5), (7.6, BUS_5V_Y)]))
    T.append(("DGND", "F", 0.3, [(21.4, 2.62), (19.6, 2.62)]))
    T.append(("DGND", "F", 0.3, [(21.4, 8.12), (19.6, 8.12)]))
    # TMP275 spine tops to the bus.  The coil lanes run between them, so each rises on B.Cu, straight,
    # and lands on its own bus line: SDA on its diagonal past C3, SCL on its diagonal into R22, 3V3 at
    # R22's supply pad.
    T.append(("/CONTROL/SDA", "B", 0.25, [(23.9, 5.355), (23.9, 15.3)]))
    T.append(("/CONTROL/SDA", "F", 0.25, [(23.9, 15.3), (23.9, 16.0)]))
    T.append(("/CONTROL/SCL", "B", 0.25, [(24.55, 8.005), (24.55, 16.0)]))
    T.append(("+3V3", "F", 0.25, [(25.85, 11.3), (25.85, 11.9)]))
    T.append(("+3V3", "B", 0.25, [(25.85, 11.9), (25.85, 16.0)]))
    # R21's supply pad sits between SDA (above) and SCL (below) and is fenced in by both on F.Cu.
    T.append(("+3V3", "F", 0.25, [(26.5, 5.56), (28.1, 5.56)]))
    T.append(("+3V3", "B", 0.25, [(28.1, 5.56), (28.1, 11.08)]))
    return T


def control_band_vias():
    return [("DGND", LX(10), 9.6), ("DGND", 48.75, U1_UP), ("+3V3", LX(9), 13.45), ("+3V3", 50.7, 11.0),
            ("DGND", 50.7, 8.12), ("DGND", 19.6, 2.62), ("DGND", 19.6, 8.12),
            ("/CONTROL/SDA", 23.9, 5.355), ("/CONTROL/SDA", 23.9, 15.3), ("/CONTROL/SCL", 24.55, 8.005),
            ("/CONTROL/SCL", 24.55, 16.0), ("+3V3", 25.85, 11.9), ("+3V3", 25.85, 16.0),
            ("+3V3", 28.1, 5.56), ("+3V3", 28.1, 11.08)]


def vias():
    V = []
    for x, n in COLUMNS:
        V += [("DGND", x + 1.3, 22.86), ("DGND", x - 1.44, 27.05), ("+5V", x, BUS_5V_Y)]
    for k, kx in RELAY_X.items():
        V.append((f"Net-(D{CELL_Q[k][1]}-A)", kx + 3.0, 33.4))
    V.append(("DGND", 25.2, 17.5))      # TMP275 bundle ground, straight into the pour; set below
                                        # the other spine tops so they stay reachable
    return V + control_band_vias()


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
    # way onto the island is the spine.  Coils and the MCP23017 lines are hand-routed already, so for
    # them the router has nothing left to do; +5V goes last because it is the most flexible.
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
