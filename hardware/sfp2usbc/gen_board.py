#!/usr/bin/env python3

#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Generate the breakout KiCad 7 board (sfp2usbc.kicad_pcb, unrouted) and project (sfp2usbc.kicad_pro)
from netlist.py/gen_schematic.py: 4-layer board outline, footprints with their nets, placement,
mounting holes, net classes (90 ohm differential pairs for the lanes) and design rules. The footprints
are linked to the schematic symbols (Update PCB from Schematic keeps them).

The routing is done in KiCad (by hand or with Backplane, README.md: PCB). Run with the KiCad Python
(pcbnew module):
  ./gen_board.py
  ./gen_board.py --drc drc.rpt   # DRC report (unrouted connections expected before the routing).
"""

import os
import sys
import json
import argparse

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from netlist import COMPONENTS, NETS
from gen_schematic import PARTS, EXTRA_PARTS, ROOT_UUID, symbol_uuid

KICAD_FOOTPRINTS = "/usr/share/kicad/footprints"

# Board --------------------------------------------------------------------------------------------

# Outline (mm): SFP cages on the left edge (TE 2227302: PCB edge 43mm from the footprint origin),
# USB-C on the right edge.
X0, Y0 = 100.0, 100.0
WIDTH  = 78.0
HEIGHT = 50.0

# ref: (x, y, rotation in degrees) relative to (X0, Y0).
PLACEMENT = {
    "J1"  : (43.0, 14.0,   0), # SFP-A cage/connector (Lane 0), front on the left edge.
    "J2"  : (43.0, 36.0,   0), # SFP-B cage/connector (Lane 1).
    "C1"  : (49.0, 15.0,   0), # Lane 0 TX AC coupling, on the J1 RD+/RD- pair.
    "C2"  : (49.0, 17.8,   0),
    "C3"  : (49.0, 37.0,   0), # Lane 1 TX AC coupling, on the J2 RD+/RD- pair.
    "C4"  : (49.0, 39.8,   0),
    "U1"  : (63.0, 18.0,   0), # ESD, close to J3.
    "U2"  : (63.0, 32.0,   0),
    "J3"  : (73.0, 25.0,  90), # USB-C, opening on the right edge.
    "R1"  : (64.5, 22.2,   0), # CC1/CC2 Rd.
    "R2"  : (64.5, 27.8,   0),
    "C6"  : (64.5, 25.0,   0), # VBUS.
    "R3"  : (70.0, 33.2,   0), # Shield.
    "C5"  : (70.0, 36.0,   0),
    "TP1" : (51.0, 23.0,   0),
    "TP2" : (54.0, 23.0,   0),
    "TP3" : (57.0, 23.0,   0),
    "TP4" : (51.0, 27.0,   0),
    "TP5" : (54.0, 27.0,   0),
    "TP6" : (57.0, 27.0,   0),
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
    ("Power",   0.40,  0.20,      0.20,     0.25,   0.60,         0.30),
]
# Custom rules (sfp2usbc.kicad_dru): HS_90R tracks spaced from the other nets (pads: fine pitch
# connectors/ESD arrays, net class clearance).
CUSTOM_RULES = """(version 1)

(rule "HS_90R tracks spacing"
  (condition "A.Type == 'track' && A.NetClass == 'HS_90R' && B.NetClass != 'HS_90R'")
  (constraint clearance (min 0.3mm)))
"""

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

def build(board_file):
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
        x, y, rot = PLACEMENT[ref]
        fp.SetPosition(pcbnew.VECTOR2I(mm(X0 + x), mm(Y0 + y)))
        fp.SetOrientationDegrees(rot)
        if ref.startswith("H"):
            fp.Reference().SetVisible(False) # (Mounting holes near the board edges.)
        board.Add(fp)
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
    tb.SetComment(0, "Generated by gen_board.py (placement), routing in KiCad.")

    apply_rules(board)
    pcbnew.SaveBoard(board_file, board) # (Also saves the project file.)
    patch_project(os.path.splitext(board_file)[0] + ".kicad_pro")
    with open(os.path.splitext(board_file)[0] + ".kicad_dru", "w") as f:
        f.write(CUSTOM_RULES)
    # Unload the project saved with the board (kept open by KiCad): reloaded with the patterns.
    pcbnew.GetSettingsManager().UnloadProject(board.GetProject(), False)
    return board

def apply_rules(board):
    """Board design rules and net classes (saved by KiCad in the project file)."""
    ds = board.GetDesignSettings()
    ds.m_MinClearance            = mm(0.127)
    ds.m_TrackMinWidth           = mm(0.127)
    ds.m_ViasMinSize             = mm(0.45)
    ds.m_MinThroughDrill         = mm(0.2)
    ds.m_HoleToHoleMin           = mm(0.25)
    ds.m_HoleClearance           = mm(0.25)
    ds.m_CopperEdgeClearance     = mm(0.3)
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
    parser = argparse.ArgumentParser(description="Generate the breakout KiCad board (placement, unrouted).")
    parser.add_argument("--output", default=os.path.join(here, "sfp2usbc.kicad_pcb"))
    parser.add_argument("--drc",    default=None, help="Write a DRC report.")
    args = parser.parse_args()

    build(args.output)
    print(f"Wrote {args.output}.")
    if args.drc:
        counts = drc(args.output, args.drc)
        print(f"DRC: {counts}")

if __name__ == "__main__":
    main()
