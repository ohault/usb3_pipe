#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Breakout routing (called by gen_board.py on the placed board): planned routes, not an autorouter.

Layers: F.Cu signals, In1.Cu/In2.Cu GND planes, B.Cu signals (USB-C B row lanes, CC2, VBUS, shield
ring), GND pours on F.Cu/B.Cu with stitching vias.

Per lane (Lane 1 on the top half, Lane 0 on the bottom half, nested L-shaped routes, no crossings):
- SFP RD pair (FPGA TX) -> AC caps (in line, staggered) -> ESD bottom rows -> USB-C.
- USB-C -> ESD top rows -> SFP TD pair (FPGA RX).
- USB-C A row pairs (L1 SSRX, L0 SSTX) on F.Cu, B row pairs (L1 SSTX, L0 SSRX) through vias in
  front of the B row (two staggered columns under the connector body, tented) and B.Cu, back to F.Cu
  before the ESD. A row GND/VBUS pins joined to their B row pins across the rows.
Pairs: 0.30mm/0.20mm (HS_90R net class), 45 degrees corners, routed as offset centerlines.
"""

import math

import pcbnew

# Dimensions (mm) ----------------------------------------------------------------------------------

PAIR_PITCH  = 0.50 # HS_90R: 0.30mm width + 0.20mm gap.
HS_WIDTH    = 0.30
SIG_WIDTH   = 0.20
PWR_WIDTH   = 0.30
GND_WIDTH   = 0.25
HS_VIA      = (0.35, 0.20) # Diameter, drill: pairs layer changes, USB-C B row (0.5mm pitch).
SMALL_VIA   = (0.35, 0.20) # ESD GND (between the pairs).
VIA         = (0.45, 0.20) # Other vias.
B_VIA_X     = (170.7, 171.3) # USB-C: B row (x=169.68) vias, two staggered columns in front of it.

def mm(v):
    return pcbnew.FromMM(v)

def to_mm(v):
    return pcbnew.ToMM(v)

# Geometry -----------------------------------------------------------------------------------------

def offset_polyline(points, d):
    """Polyline offset by d on the left of the travel direction (y down: left of east is north),
    mitered joins."""
    def normal(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy)
        return (dy/n, -dx/n)
    out = []
    for i, p in enumerate(points):
        if i == 0:
            n = normal(points[0], points[1])
            out.append((p[0] + d*n[0], p[1] + d*n[1]))
        elif i == len(points) - 1:
            n = normal(points[-2], points[-1])
            out.append((p[0] + d*n[0], p[1] + d*n[1]))
        else:
            n1 = normal(points[i - 1], p)
            n2 = normal(p, points[i + 1])
            m  = (n1[0] + n2[0], n1[1] + n2[1])
            k  = m[0]*n1[0] + m[1]*n1[1]
            out.append((p[0] + d*m[0]/k, p[1] + d*m[1]/k))
    return out

BUMP_H = 0.5 # Length matching bumps: 45 degrees sides, height (mm).
BUMP_W = 0.5 # Top length (mm).
BUMP_EXTRA = 2*BUMP_H*(math.sqrt(2) - 1) # Extra length per bump (mm).

def add_bumps(line, count, away):
    """Length matching: count 45 degrees bumps (BUMP_EXTRA each) centered on the longest segment of
    line, on its side away from the pair (away: +1 left/-1 right of the travel direction)."""
    i = max(range(len(line) - 1), key=lambda k: math.dist(line[k], line[k + 1]))
    (ax, ay), (bx, by) = line[i], line[i + 1]
    length = math.dist(line[i], line[i + 1])
    ux, uy = (bx - ax)/length, (by - ay)/length
    nx, ny = away*uy, -away*ux # (Left normal for away=+1, y down.)
    base, gap = 2*BUMP_H + BUMP_W, 1.0
    total = count*base + (count - 1)*gap
    assert total + 2.0 <= length, "Not enough room for the bumps."
    s = (length - total)/2
    pts = []
    for k in range(count):
        for t, h in [(0, 0), (BUMP_H, BUMP_H), (BUMP_H + BUMP_W, BUMP_H), (base, 0)]:
            pts.append((ax + ux*(s + t) + nx*h, ay + uy*(s + t) + ny*h))
        s += base + gap
    return line[:i + 1] + pts + line[i + 1:]

def pair_lines(center, p_side):
    """(P, N) lines of a pair from its centerline, P on the left or right of the travel direction."""
    left  = offset_polyline(center, +PAIR_PITCH/2)
    right = offset_polyline(center, -PAIR_PITCH/2)
    return (left, right) if p_side == "left" else (right, left)

# Board items --------------------------------------------------------------------------------------

class Router:
    def __init__(self, board):
        self.board = board
        self.pads  = {}
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                self.pads.setdefault((fp.GetReference(), pad.GetNumber()), []).append(pad)

    def pad(self, ref, number, index=0):
        """Pad position (mm) and net name."""
        pad = sorted(self.pads[(ref, number)], key=lambda p: (p.GetPosition().x, p.GetPosition().y))[index]
        pos = pad.GetPosition()
        return (round(to_mm(pos.x), 4), round(to_mm(pos.y), 4)), pad.GetNetname()

    def net(self, name):
        net = self.board.FindNet(f"/{name}")
        assert net is not None, name
        return net

    def track(self, net, layer, points, width):
        for a, b in zip(points, points[1:]):
            if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-6:
                continue
            t = pcbnew.PCB_TRACK(self.board)
            t.SetStart(pcbnew.VECTOR2I(mm(a[0]), mm(a[1])))
            t.SetEnd(pcbnew.VECTOR2I(mm(b[0]), mm(b[1])))
            t.SetWidth(mm(width))
            t.SetLayer(layer)
            t.SetNet(self.net(net))
            self.board.Add(t)

    def via(self, net, pos, size=VIA):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(pcbnew.VECTOR2I(mm(pos[0]), mm(pos[1])))
        v.SetWidth(mm(size[0]))
        v.SetDrill(mm(size[1]))
        v.SetNet(self.net(net))
        self.board.Add(v)
        return v

    def check(self, ref, number, net, pos=None, index=0):
        """Check a pad (net and position) used as a route end, return its position."""
        p, n = self.pad(ref, number, index)
        assert n == f"/{net}", f"{ref}.{number}: net {n}, expected /{net}."
        if pos is not None:
            assert abs(p[0] - pos[0]) < 1e-3 and abs(p[1] - pos[1]) < 1e-3, f"{ref}.{number} at {p}, expected {pos}."
        return p

    def pair(self, net_p, net_n, layer, center, p_side, ends_p=None, ends_n=None, n_bumps=0):
        """Pair routed on its centerline, ends checked against (ref, pad) at each end, n_bumps length
        matching bumps on the N line (on its side away from P)."""
        p, n = pair_lines(center, p_side)
        if n_bumps:
            n = add_bumps(n, n_bumps, away=+1 if p_side == "right" else -1)
        for line, ends, net in [(p, ends_p, net_p), (n, ends_n, net_n)]:
            for i, end in zip([0, -1], ends or []):
                if end is not None:
                    self.check(*end, net, pos=line[i])
            self.track(net, layer, line, HS_WIDTH)
        return p, n

# Routing ------------------------------------------------------------------------------------------

def route_sfp_side(r, lane, sfp, caps, esd, y_td, x_rx, x_tx, y_esd, rx_p_side, tx_bumps=0, rx_bumps=0):
    """SFP <-> ESD (F.Cu): TD pair (from the ESD top rows), RD pair through the AC caps (to the ESD
    bottom rows), nested L-shaped routes (vertical runs at x_rx/x_tx), GND vias of the SFP pads."""
    F = pcbnew.F_Cu
    L = f"L{lane}"
    x_fan = 142.45
    up = y_esd < y_td # ESD above the SFP (Lane 0).
    sgn = -1 if up else 1
    # ESD rows: SSRX on the top rows (y_esd - 1.0, - 0.5), SSTX on the bottom rows (+ 0.5, + 1.0).
    x_esd = r.pad(esd, "1")[0][0]
    rx_y  = y_esd - 0.75
    tx_y  = y_esd + 0.75

    # TD pair (SSRX): SFP pads 19 (top)/18 (bottom), fan-out to the pair pitch, L route to the ESD.
    td_top, td_bot = "19", "18"
    nets = {pin: r.pad(sfp, pin)[1][1:] for pin in [td_top, td_bot]}
    yc = y_td
    center = [(x_fan, yc), (x_rx - 1.0, yc), (x_rx, yc + sgn*1.0), (x_rx, rx_y - sgn*1.0),
        (x_rx + 1.0, rx_y), (x_esd, rx_y)]
    p_net, n_net = f"{L}_SSRX_P", f"{L}_SSRX_N"
    p, n = r.pair(p_net, n_net, F, center, rx_p_side, n_bumps=rx_bumps)
    for pin, line in [(td_top, p if nets[td_top] == p_net else n), (td_bot, p if nets[td_bot] == p_net else n)]:
        (px, py), _ = r.pad(sfp, pin)
        r.track(nets[pin], F, [(px, py), (x_fan - 0.15, py), line[0]], HS_WIDTH)
    for line, net in [(p, p_net), (n, n_net)]:
        rows = [num for num in ["1", "2", "4", "5"] if r.pad(esd, num)[1] == f"/{net}"]
        assert len(rows) == 1 and abs(r.pad(esd, rows[0])[0][1] - line[-1][1]) < 1e-3, (net, rows, line[-1])

    # RD pair (SSTX): SFP pads 13 (RD+, top)/12 (RD-, bottom) -> AC caps (staggered) -> pair.
    c_p, c_n = caps
    (x13, y13), _ = r.pad(sfp, "13")
    (x12, y12), _ = r.pad(sfp, "12")
    r.check(sfp, "13", f"{L}_SFP_RD_P")
    r.check(sfp, "12", f"{L}_SFP_RD_N")
    cp1 = r.check(c_p, "1", f"{L}_SFP_RD_P")
    cn1 = r.check(c_n, "1", f"{L}_SFP_RD_N")
    cp2 = r.check(c_p, "2", f"{L}_SSTX_P")
    cn2 = r.check(c_n, "2", f"{L}_SSTX_N")
    r.track(f"{L}_SFP_RD_P", F, [(x13, y13), cp1], HS_WIDTH)
    r.track(f"{L}_SFP_RD_N", F, [(x12, y12), cn1], HS_WIDTH)
    yc = (y13 + y12)/2
    x0 = 148.65
    center = [(x0, yc), (x_tx - 1.0, yc), (x_tx, yc + sgn*1.0), (x_tx, tx_y - sgn*1.0),
        (x_tx + 1.0, tx_y), (x_esd, tx_y)]
    p, n = r.pair(f"{L}_SSTX_P", f"{L}_SSTX_N", F, center, "left", n_bumps=tx_bumps)
    r.track(f"{L}_SSTX_P", F, [cp2, (x0 - 0.15, cp2[1]), p[0]], HS_WIDTH)
    r.track(f"{L}_SSTX_N", F, [cn2, (x0 - 0.15, cn2[1]), n[0]], HS_WIDTH)
    for line, net in [(p, f"{L}_SSTX_P"), (n, f"{L}_SSTX_N")]:
        rows = [num for num in ["1", "2", "4", "5"] if r.pad(esd, num)[1] == f"/{net}"]
        assert len(rows) == 1 and abs(r.pad(esd, rows[0])[0][1] - line[-1][1]) < 1e-3, (net, rows, line[-1])

    # SFP GND pads: vias next to the pads (right column: the outer pads 20/11 are in the footprint
    # F.Cu tracks keepout, connected by the GND pour), cage interior side (left column).
    for pin in ["20", "17", "14", "11"]:
        px, py = r.check(sfp, pin, "GND")
        if pin in ["17", "14"]:
            r.track("GND", F, [(px, py), (142.6, py)], GND_WIDTH)
        r.via("GND", (142.6, py))
    for pin in ["1", "10"]:
        px, py = r.check(sfp, pin, "GND")
        r.track("GND", F, [(px, py), (131.25, py)], GND_WIDTH)
        r.via("GND", (131.25, py))

def route_esd(r, esd, y_esd):
    """ESD: flow-through tracks over the pad pairs, GND pads joined, GND vias on both sides between
    the pairs."""
    F = pcbnew.F_Cu
    for a, b in [("1", "10"), ("2", "9"), ("4", "7"), ("5", "6")]:
        (pa, net), (pb, _) = r.pad(esd, a), r.pad(esd, b)
        r.track(net[1:], F, [pa, pb], HS_WIDTH)
    (p3, _), (p8, _) = r.pad(esd, "3"), r.pad(esd, "8")
    assert abs(p3[1] - y_esd) < 1e-3
    xl, xr = p3[0] - 0.92, p8[0] + 0.92
    r.track("GND", F, [(xl, y_esd), p3, p8, (xr, y_esd)], SIG_WIDTH)
    r.via("GND", (xl, y_esd), SMALL_VIA)
    r.via("GND", (xr, y_esd), SMALL_VIA)

def route_usbc(r):
    """ESD <-> USB-C, USB-C B row vias, CC, VBUS, shield."""
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    x_esd_r = r.pad("U2", "10")[0][0]

    # B row: vias in front of the row (staggered columns), F.Cu stubs from the B pads.
    b_row = {"B1": "GND", "B2": "L1_SSTX_P", "B3": "L1_SSTX_N", "B4": "VBUS", "B5": "CC2",
             "B9": "VBUS", "B10": "L0_SSRX_N", "B11": "L0_SSRX_P", "B12": "GND"}
    b_via = {}
    for i, (pin, net) in enumerate(b_row.items()):
        (px, py) = r.check("J3", pin, net)
        x = B_VIA_X[i % 2]
        b_via[pin] = (x, py)
        r.via(net, (x, py), HS_VIA)
        r.track(net, F, [(px, py), (x, py)], SIG_WIDTH)
    # A row GND/VBUS pins joined to their B row pins (F.Cu, across the rows).
    for a_pin, b_pin, net in [("A12", "B1", "GND"), ("A1", "B12", "GND"), ("A9", "B4", "VBUS"), ("A4", "B9", "VBUS")]:
        (ax, ay) = r.check("J3", a_pin, net)
        (bx, by) = r.check("J3", b_pin, net)
        r.track(net, F, [(ax + 0.22, ay), (bx - 0.18, by)], SIG_WIDTH)

    # Lane 1 SSRX (A11/A10, F.Cu): ESD top rows -> USB-C.
    (_, y_rx_p) = r.check("U2", "10", "L1_SSRX_P")
    yc = y_rx_p + 0.25
    a11 = r.check("J3", "A11", "L1_SSRX_P")
    a10 = r.check("J3", "A10", "L1_SSRX_N")
    y_j = (a11[1] + a10[1])/2
    x1  = 163.9
    center = [(x_esd_r, yc), (x1, yc), (x1 + (y_j - yc), y_j), (a11[0], y_j)]
    r.pair("L1_SSRX_P", "L1_SSRX_N", F, center, "left", ends_p=[("U2", "10"), ("J3", "A11")],
        ends_n=[("U2", "9"), ("J3", "A10")])

    # Lane 1 SSTX (B2/B3): ESD bottom rows -> vias (staggered) -> B.Cu -> B row vias.
    (_, y_tx_p) = r.check("U2", "7", "L1_SSTX_P")
    xv = {"L1_SSTX_P": 163.2, "L1_SSTX_N": 163.8}
    for pin, net in [("7", "L1_SSTX_P"), ("6", "L1_SSTX_N")]:
        (px, py) = r.check("U2", pin, net)
        r.track(net, F, [(px, py), (xv[net], py)], HS_WIDTH)
        r.via(net, (xv[net], py), HS_VIA)
    y_j = (b_via["B2"][1] + b_via["B3"][1])/2
    x_j = min(b_via["B2"][0], b_via["B3"][0])
    yc  = y_tx_p + 0.25
    center = [(x_j, y_j), (164.7 + (y_j - yc), y_j), (164.7, yc), (163.8, yc)] # (Westward.)
    p, n = r.pair("L1_SSTX_P", "L1_SSTX_N", B, center, "right")
    r.track("L1_SSTX_P", B, [b_via["B2"], p[0]], HS_WIDTH)
    r.track("L1_SSTX_N", B, [b_via["B3"], n[0]], HS_WIDTH)
    r.track("L1_SSTX_P", B, [p[-1], (xv["L1_SSTX_P"], p[-1][1])], HS_WIDTH)
    r.via("GND", (163.2, y_tx_p + 1.25)) # Stitching (return path of the layer change).

    # Lane 0 SSRX (B10/B11): ESD top rows -> vias (staggered) -> B.Cu -> B row vias.
    (_, y_rx_n) = r.check("U1", "10", "L0_SSRX_N")
    xv = {"L0_SSRX_N": 163.8, "L0_SSRX_P": 163.2}
    for pin, net in [("10", "L0_SSRX_N"), ("9", "L0_SSRX_P")]:
        (px, py) = r.check("U1", pin, net)
        r.track(net, F, [(px, py), (xv[net], py)], HS_WIDTH)
        r.via(net, (xv[net], py), HS_VIA)
    y_j = (b_via["B10"][1] + b_via["B11"][1])/2
    x_j = min(b_via["B10"][0], b_via["B11"][0])
    yc  = y_rx_n + 0.25
    center = [(x_j, y_j), (164.7 + (yc - y_j), y_j), (164.7, yc), (163.8, yc)] # (Westward.)
    p, n = r.pair("L0_SSRX_P", "L0_SSRX_N", B, center, "left")
    r.track("L0_SSRX_P", B, [b_via["B11"], p[0]], HS_WIDTH)
    r.track("L0_SSRX_N", B, [b_via["B10"], n[0]], HS_WIDTH)
    r.track("L0_SSRX_P", B, [p[-1], (xv["L0_SSRX_P"], p[-1][1])], HS_WIDTH)
    r.via("GND", (163.2, y_rx_n - 0.75)) # Stitching.

    # Lane 0 SSTX (A3/A2, F.Cu): ESD bottom rows -> USB-C.
    (_, y_tx_p) = r.check("U1", "7", "L0_SSTX_P")
    yc = y_tx_p + 0.25
    a3 = r.check("J3", "A3", "L0_SSTX_P")
    y_j = (a3[1] + r.pad("J3", "A2")[0][1])/2
    x1  = 163.3
    center = [(x_esd_r, yc), (x1, yc), (x1 + (yc - y_j), y_j), (a3[0], y_j)]
    r.pair("L0_SSTX_P", "L0_SSTX_N", F, center, "left", ends_p=[("U1", "7"), ("J3", "A3")],
        ends_n=[("U1", "6"), ("J3", "A2")])

    # CC1 (A5, F.Cu) -> R1, CC2 (B5 via, B.Cu) -> via -> R2, Rd GND vias.
    a5  = r.check("J3", "A5", "CC1")
    r1  = r.check("R1", "1", "CC1")
    r.track("CC1", F, [a5, r1], SIG_WIDTH)
    r2  = r.check("R2", "1", "CC2")
    y5  = b_via["B5"][1]
    xcc = 166.2
    r.track("CC2", B, [b_via["B5"], (xcc, y5)], SIG_WIDTH)
    r.via("CC2", (xcc, y5))
    r.track("CC2", F, [(xcc, y5), r2], SIG_WIDTH)
    for ref in ["R1", "R2"]:
        (gx, gy) = r.check(ref, "2", "GND")
        r.track("GND", F, [(gx, gy), (gx - 0.8, gy)], GND_WIDTH)
        r.via("GND", (gx - 0.8, gy))

    # VBUS (B.Cu): B4/B9 vias joined under the connector, to the bottom test pad.
    assert b_via["B4"][0] == b_via["B9"][0]
    r.track("VBUS", B, [b_via["B4"], b_via["B9"]], PWR_WIDTH)
    tp = r.check("TP1", "1", "VBUS")
    r.track("VBUS", B, [(b_via["B4"][0], tp[1]), tp], PWR_WIDTH)

    # Shield (B.Cu ring joining the 4 shell pads), to R3/C5 (F.Cu), R3/C5 GND vias.
    s = sorted([r.pad("J3", "S1", i)[0] for i in range(4)])
    (tl, bl), (tr, br) = sorted(s[:2], key=lambda p: p[1]), sorted(s[2:], key=lambda p: p[1])
    r.track("SHIELD", B, [tl, tr, br, bl], 0.4)
    r3 = r.check("R3", "1", "SHIELD")
    c5 = r.check("C5", "1", "SHIELD")
    r.track("SHIELD", F, [bl, (bl[0], r3[1] - 1.0), (r3[0], r3[1])], 0.3)
    r.track("SHIELD", F, [r3, c5], 0.3)
    for ref in ["R3", "C5"]:
        (gx, gy) = r.check(ref, "2", "GND")
        r.track("GND", F, [(gx, gy), (gx, gy + 0.9)], GND_WIDTH)
        r.via("GND", (gx, gy + 0.9))

def add_zones(r, x0, y0, x1, y1):
    """GND planes (In1.Cu, In2.Cu) and pours (F.Cu, B.Cu), filled."""
    board = r.board
    for layer, priority in [(pcbnew.In1_Cu, 0), (pcbnew.In2_Cu, 0), (pcbnew.F_Cu, 0), (pcbnew.B_Cu, 0)]:
        zone = pcbnew.ZONE(board)
        zone.SetLayer(layer)
        zone.SetNet(r.net("GND"))
        zone.SetLocalClearance(mm(0.3))
        zone.SetMinThickness(mm(0.2))
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        zone.SetAssignedPriority(priority)
        outline = zone.Outline()
        outline.NewOutline()
        for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
            outline.Append(mm(x), mm(y))
        board.Add(zone)

def add_stitching(r, x0, y0, x1, y1, pitch=3.0, clearance=0.35, edge=1.0):
    """GND stitching vias on a grid, where they clear all the other copper (and the fine pitch
    footprints/connector bodies)."""
    board = r.board
    radius = VIA[0]/2
    keepouts = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref.startswith(("J1", "J2")):
            # Connector body around the SFP pads (the cage interior is chassis ground: allowed).
            p = fp.GetPosition()
            keepouts.append((to_mm(p.x) - 12.0, to_mm(p.y) - 5.0, to_mm(p.x) + 0.5, to_mm(p.y) + 5.0))
        else:
            bb = fp.GetBoundingBox(False, False)
            keepouts.append((to_mm(bb.GetLeft()), to_mm(bb.GetTop()), to_mm(bb.GetRight()), to_mm(bb.GetBottom())))
    items = []
    for t in board.GetTracks():
        if t.GetNetname() == "/GND" and t.Type() == pcbnew.PCB_VIA_T:
            continue
        items.append(t)
    pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
    def clear(x, y):
        if not (x0 + edge <= x <= x1 - edge and y0 + edge <= y <= y1 - edge):
            return False
        for kx0, ky0, kx1, ky1 in keepouts:
            if kx0 - radius <= x <= kx1 + radius and ky0 - radius <= y <= ky1 + radius:
                return False
        pt = pcbnew.VECTOR2I(mm(x), mm(y))
        for t in items:
            if t.Type() == pcbnew.PCB_VIA_T:
                d = math.hypot(to_mm(t.GetPosition().x) - x, to_mm(t.GetPosition().y) - y)
                if d < radius + t.GetWidth()/2e6 + clearance:
                    return False
            else:
                a, b = t.GetStart(), t.GetEnd()
                ax, ay, bx, by = to_mm(a.x), to_mm(a.y), to_mm(b.x), to_mm(b.y)
                dx, dy = bx - ax, by - ay
                l2 = dx*dx + dy*dy
                u = 0 if l2 == 0 else max(0, min(1, ((x - ax)*dx + (y - ay)*dy)/l2))
                d = math.hypot(ax + u*dx - x, ay + u*dy - y)
                if d < radius + to_mm(t.GetWidth())/2 + clearance:
                    return False
        for p in pads:
            bb = p.GetBoundingBox()
            if (to_mm(bb.GetLeft()) - radius - clearance <= x <= to_mm(bb.GetRight()) + radius + clearance and
                to_mm(bb.GetTop()) - radius - clearance <= y <= to_mm(bb.GetBottom()) + radius + clearance):
                return False
        return True
    count = 0
    y = y0 + edge
    while y <= y1 - edge:
        x = x0 + edge
        while x <= x1 - edge:
            if clear(x, y):
                r.via("GND", (x, y))
                count += 1
            x += pitch
        y += pitch
    return count

def route(board):
    """Route the placed board (gen_board.py placement)."""
    r = Router(board)
    # USB-C B row pairs (L1 SSTX, L0 SSRX): P on the outer via column (F.Cu stub + B.Cu return),
    # matched on the N line.
    bumps = round(2*abs(B_VIA_X[1] - B_VIA_X[0])/BUMP_EXTRA)
    # Lane 1 (top): J2 TD 111.0/111.8 (P on 19: top), RD 115.8/116.6, ESD U2 at y 121.0.
    route_sfp_side(r, 1, "J2", ("C3", "C4"), "U2", y_td=111.4, x_rx=153.5, x_tx=151.0,
        y_esd=121.0, rx_p_side="left", tx_bumps=bumps)
    # Lane 0 (bottom): J1 TD 133.0/133.8 (P on 18: bottom), RD 137.8/138.6, ESD U1 at y 129.75.
    route_sfp_side(r, 0, "J1", ("C1", "C2"), "U1", y_td=133.4, x_rx=151.0, x_tx=153.5,
        y_esd=129.75, rx_p_side="right", rx_bumps=bumps)
    route_esd(r, "U2", 121.0)
    route_esd(r, "U1", 129.75)
    route_usbc(r)
    x0, y0, x1, y1 = 100.0, 100.0, 178.0, 150.0
    add_zones(r, x0, y0, x1, y1)
    add_stitching(r, x0, y0, x1, y1)

def fill_zones(board_file):
    """Fill the zones of a saved board (the filler needs a loaded board/project)."""
    board = pcbnew.LoadBoard(board_file)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(board_file, board)
