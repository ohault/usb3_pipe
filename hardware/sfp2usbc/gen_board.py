#!/usr/bin/env python3

#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Generate the breakout KiCad 7 board (sfp2usbc.kicad_pcb) and project (sfp2usbc.kicad_pro) from
netlist.py/gen_schematic.py: 4-layer board outline, footprints with their nets, placement, mounting
holes, net classes (90 ohm differential pairs for the lanes), design rules and the routing
(route_board.py: tracks, vias, GND planes/pours, stitching). The footprints are linked to the
schematic symbols (Update PCB from Schematic keeps them).

Run with the KiCad Python (pcbnew module):
  ./gen_board.py --drc drc.rpt   # Routed board + DRC report.
  ./gen_board.py --no-route      # Placement only.
"""

import os
import sys
import json
import argparse

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from netlist import COMPONENTS, NETS
from gen_schematic import PARTS, EXTRA_PARTS, ROOT_UUID, symbol_uuid

import route_board

KICAD_FOOTPRINTS = "/usr/share/kicad/footprints"

# Board --------------------------------------------------------------------------------------------

# Outline (mm): SFP cages on the left edge (TE 2227302: PCB edge 43mm from the footprint origin),
# USB-C on the right edge.
X0, Y0 = 100.0, 100.0
WIDTH  = 78.0
HEIGHT = 50.0

# ref: (x, y, rotation in degrees[, "bottom"]) relative to (X0, Y0). Lane 1 on the top half, Lane 0
# on the bottom half (as the USB-C TX2/RX2 and TX1/RX1 pins): the routing has no crossings.
PLACEMENT = {
    "J2"  : (43.0, 14.0,   0), # SFP-B cage/connector (Lane 1), front on the left edge.
    "J1"  : (43.0, 36.0,   0), # SFP-A cage/connector (Lane 0).
    "C3"  : (45.5, 15.8,   0), # Lane 1 TX AC coupling, in line with the J2 RD+/RD- pads (staggered).
    "C4"  : (47.5, 16.6,   0),
    "C1"  : (45.5, 37.8,   0), # Lane 0 TX AC coupling, in line with the J1 RD+/RD- pads (staggered).
    "C2"  : (47.5, 38.6,   0),
    "U2"  : (61.5, 21.0,   0), # ESD (flow-through, left to right), close to J3.
    "U1"  : (61.5, 29.75,  0),
    "J3"  : (73.0, 25.0,  90), # USB-C, opening on the right edge.
    "R2"  : (64.6, 24.5, 180), # CC2/CC1 Rd (pad 1 on the right: CC).
    "R1"  : (64.6, 25.75, 180),
    "R3"  : (70.0, 32.6, 270), # Shield (pad 1 on the top: SHIELD).
    "C5"  : (71.6, 32.6, 270),
    "TP1" : (73.0, 25.25,  0, "bottom"), # VBUS test pad, under J3.
    "H1"  : (49.0,  4.0,   0),
    "H2"  : (49.0, 46.0,   0),
    "H3"  : (74.0,  4.0,   0),
    "H4"  : (74.0, 46.0,   0),
}

# Net classes / rules (mm). HS_90R: ~90 ohm differential on L1/L4 over the L2 GND of a 4-layer
# 1.6mm FR-4 board (estimate for a ~0.21mm prepreg: set width/gap from the fab's stackup and
# impedance calculator before routing).
NET_CLASSES = [
    # name,     track, clearance, dp width, dp gap, via diameter, via drill.
    ("Default", 0.20,  0.15,      0.20,     0.25,   0.60,         0.30),
    ("HS_90R",  0.30,  0.15,      0.30,     0.20,   0.60,         0.30),
    ("Power",   0.40,  0.15,      0.20,     0.25,   0.60,         0.30),
]
# Custom rules (sfp2usbc.kicad_dru): HS_90R tracks spaced from the other nets, except the tracks
# entering the fine pitch footprints (SFP connectors, USB-C, ESD arrays: net class clearance).
CUSTOM_RULES = """(version 1)

(rule "HS_90R tracks spacing"
  (condition "A.Type == 'track' && A.NetClass == 'HS_90R' && B.NetClass != 'HS_90R' && !A.intersectsCourtyard('J1') && !A.intersectsCourtyard('J2') && !A.intersectsCourtyard('J3') && !A.intersectsCourtyard('U1') && !A.intersectsCourtyard('U2')")
  (constraint clearance (min 0.25mm)))
"""

# 3D models of the parts missing from the KiCad 3D library (3d/gen_models.py).
MODELS_3D = {
    "J1" : "${KIPRJMOD}/3d/SFP_Cage_TE_2227302.wrl",
    "J2" : "${KIPRJMOD}/3d/SFP_Cage_TE_2227302.wrl",
    "J3" : "${KIPRJMOD}/3d/USB_C_Receptacle_Amphenol_12401610E4-2A.wrl",
}

NET_CLASS_PATTERNS = [
    ("HS_90R", "/L*"),
    ("Power",  "/VBUS"),
    ("Power",  "/GND"),
]

def net_name(name):
    """Board net name of a netlist.py net (as the schematic local label nets)."""
    return f"/{name}"

# Generation ---------------------------------------------------------------------------------------

def mm(v):
    return pcbnew.FromMM(v)

def build(board_file, route=True):
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    board.GetDesignSettings().SetBoardThickness(mm(1.6))

    # Nets.
    pin_net = {}
    nets    = {}
    for name in list(NETS) + [net for *_, net in EXTRA_PARTS.values() if net]:
        if name not in nets:
            nets[name] = pcbnew.NETINFO_ITEM(board, net_name(name))
            board.Add(nets[name])
    for name, nodes in NETS.items():
        for node in nodes:
            pin_net[node] = name
    for ref, (_, footprint, *_, net) in EXTRA_PARTS.items():
        if net and footprint: # (Power flags: schematic only.)
            pin_net[(ref, "1")] = net

    # Footprints.
    parts = {ref: (footprint, COMPONENTS[ref][1]) for ref, (_, footprint, _, _) in PARTS.items()}
    parts.update({ref: (footprint, value) for ref, (_, footprint, value, *_) in EXTRA_PARTS.items()
        if footprint})
    assert set(parts) == set(PLACEMENT), set(parts) ^ set(PLACEMENT)
    for ref, (footprint, value) in parts.items():
        lib, name = footprint.split(":")
        fp = pcbnew.FootprintLoad(os.path.join(KICAD_FOOTPRINTS, f"{lib}.pretty"), name)
        fp.SetReference(ref)
        fp.SetValue(value)
        fp.SetPath(pcbnew.KIID_PATH(f"/{symbol_uuid(ref)}"))
        fp.SetFPIDAsString(footprint)
        x, y, rot, *side = PLACEMENT[ref]
        fp.SetPosition(pcbnew.VECTOR2I(mm(X0 + x), mm(Y0 + y)))
        fp.SetOrientationDegrees(rot)
        if ref in MODELS_3D:
            models = fp.Models()
            if len(models) == 0:
                models.push_back(pcbnew.FP_3DMODEL())
            models[0].m_Filename = MODELS_3D[ref]
        if ref.startswith(("H", "C", "R", "TP")):
            fp.Reference().SetVisible(False) # (Small parts/holes: references on the fab layer.)
        board.Add(fp)
        if side == ["bottom"]:
            fp.Flip(fp.GetPosition(), False) # (After board.Add: layers from the board.)
        for pad in fp.Pads():
            net = pin_net.get((ref, pad.GetNumber()))
            if net is not None:
                pad.SetNet(nets[net])

    # Pads of the netlist all on the board.
    pads = {(fp.GetReference(), pad.GetNumber()) for fp in board.GetFootprints() for pad in fp.Pads()}
    missing = sorted(node for node in pin_net if node not in pads)
    assert not missing, f"Netlist pins without footprint pads: {missing}."

    # Outline.
    corners = [(X0, Y0), (X0 + WIDTH, Y0), (X0 + WIDTH, Y0 + HEIGHT), (X0, Y0 + HEIGHT)]
    for (xa, ya), (xb, yb) in zip(corners, corners[1:] + corners[:1]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(mm(xa), mm(ya)))
        seg.SetEnd(pcbnew.VECTOR2I(mm(xb), mm(yb)))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(mm(0.1))
        board.Add(seg)

    # Title block.
    tb = board.GetTitleBlock()
    tb.SetTitle("Dual SFP to USB-C breakout (USB 3.2 Gen 1x2)")
    tb.SetCompany("USB3-PIPE")
    tb.SetComment(0, "Generated by gen_board.py (placement, routing: route_board.py).")

    apply_rules(board)
    if route:
        route_board.route(board)
    pcbnew.SaveBoard(board_file, board) # (Also saves the project file.)
    patch_project(os.path.splitext(board_file)[0] + ".kicad_pro")
    with open(os.path.splitext(board_file)[0] + ".kicad_dru", "w") as f:
        f.write(CUSTOM_RULES)
    # Unload the project saved with the board (kept open by KiCad): reloaded with the patterns.
    pcbnew.GetSettingsManager().UnloadProject(board.GetProject(), False)
    if route:
        route_board.fill_zones(board_file)
    return board

def apply_rules(board):
    """Board design rules and net classes (saved by KiCad in the project file)."""
    ds = board.GetDesignSettings()
    ds.m_MinClearance            = mm(0.127)
    ds.m_TrackMinWidth           = mm(0.127)
    ds.m_ViasMinSize             = mm(0.35) # (USB-C rows: 0.35/0.2mm vias between the rows.)
    ds.m_MinThroughDrill         = mm(0.2)
    ds.m_ViasMinAnnularWidth     = mm(0.075)
    ds.m_HoleToHoleMin           = mm(0.25)
    ds.m_HoleClearance           = mm(0.25)
    ds.m_CopperEdgeClearance     = mm(0.25) # (J3 footprint: 0.298mm between a NPTH and a shell pad.)
    for name, track, clearance, dp_width, dp_gap, via_dia, via_drill in NET_CLASSES:
        nc = ds.m_NetSettings.m_DefaultNetClass if name == "Default" else pcbnew.NETCLASS(name)
        nc.SetTrackWidth(mm(track))
        nc.SetClearance(mm(clearance))
        nc.SetDiffPairWidth(mm(dp_width))
        nc.SetDiffPairGap(mm(dp_gap))
        nc.SetViaDiameter(mm(via_dia))
        nc.SetViaDrill(mm(via_drill))
        if name != "Default":
            ds.m_NetSettings.m_NetClasses[name] = nc

def patch_project(pro_file):
    """Net class patterns in the project file saved by KiCad (not exposed by the KiCad 7 Python API)."""
    project = json.load(open(pro_file))
    project["net_settings"]["netclass_patterns"] = [{"netclass": c, "pattern": p}
        for c, p in NET_CLASS_PATTERNS]
    project["sheets"] = [[ROOT_UUID, ""]]
    with open(pro_file, "w") as f:
        json.dump(project, f, indent=2)
        f.write("\n")

def drc(board_file, report):
    """DRC report of the board (with the project rules), returns the violations counts per type."""
    board = pcbnew.LoadBoard(board_file)
    pcbnew.WriteDRCReport(board, report, pcbnew.EDA_UNITS_MILLIMETRES, True)
    counts = {}
    for line in open(report):
        if line.startswith("["):
            kind = line.split("]")[0][1:]
            counts[kind] = counts.get(kind, 0) + 1
    return counts

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="Generate the breakout KiCad board (placement, routing).")
    parser.add_argument("--output",   default=os.path.join(here, "sfp2usbc.kicad_pcb"))
    parser.add_argument("--no-route", action="store_true", help="Placement only (unrouted board).")
    parser.add_argument("--drc",      default=None, help="Write a DRC report.")
    args = parser.parse_args()

    build(args.output, route=not args.no_route)
    print(f"Wrote {args.output}.")
    if args.drc:
        counts = drc(args.output, args.drc)
        print(f"DRC: {counts}")

if __name__ == "__main__":
    main()
