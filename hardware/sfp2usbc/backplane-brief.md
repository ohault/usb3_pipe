# Backplane brief: dual SFP to USB-C breakout

Brief for the Backplane agents (KiCad), to paste in a Backplane project thread with this directory in
the project. The schematic and the unrouted board are generated (gen_schematic.py, gen_board.py):
the agents start at Phase 1 (review) and do the routing (Phase 4) and fab outputs (Phase 5). Each
phase ends with a human review: do not start a phase before the previous one is approved.

## Context for the agents

You design a small passive 4-layer PCB in KiCad: two SFP host connectors with 1x1 cages on one edge,
a full-featured USB Type-C receptacle on the opposite edge, carrying two USB 3.2 Gen 1 SuperSpeed
lanes (5Gbps each) from two SFP DAC cables to a USB-C cable. The design intent is fixed:

- `README.md`: design decisions, pin mapping, BOM candidates, PCB rules.
- `netlist.py`: the exact connectivity (refs, pins, net names). Use these refs and net names.
- `sfp2usbc.kicad_sch`/`sfp2usbc.kicad_pcb`/`.kicad_pro`/`.kicad_dru`: generated schematic, unrouted
  placed board, net classes and rules. Change the connectivity only in `netlist.py` (regenerate).
- `check_netlist.py`: must report 0 errors on the schematic netlist export.

Rules:
- Do not change the connectivity or add circuits that are not in `netlist.py` (except test points
  TP*, mounting holes H*, fiducials, logos). Ask if something looks wrong.
- Footprints from the manufacturer datasheets (or KiCad libraries checked against them): report the
  datasheet pages used for J1/J2, J3, U1/U2.
- High-speed pairs: `L0_SFP_RD_P/N`, `L0_SSTX_P/N`, `L0_SSRX_P/N`, `L1_*` (diff pairs, 90 ohm).

## Phase 1: parts and footprints (review)

1. Check the BOM of README.md (datasheet, active, stock), propose alternatives if needed.
2. Check the KiCad footprints against the datasheets: J1/J2 (`Connector_SFP_and_Cage`, TE 2227302:
   pads 1-20, cage pins, PCB edge), J3 (`USB_C_Receptacle_Amphenol_12401610E4-2A`: A/B rows, shell,
   front vs board edge), U1/U2 (USON-10 TPD4E05U06 pinout, flow-through pad pairs).

Review: footprints vs datasheets.

## Phase 2: schematic (review)

1. ERC in KiCad (eeschema): clean or justified.
2. `kicad-cli sch export netlist --format kicadsexpr -o sfp2usbc.net sfp2usbc.kicad_sch` then
   `./check_netlist.py sfp2usbc.net`: 0 errors.

Review: schematic + ERC + check_netlist.py output.

## Phase 3: stackup, rules and placement (review/adjust)

1. Fab stackup with controlled impedance (4 layers 1.6mm, L2 solid GND): set the `HS_90R` net class
   width/gap for 90 ohm differential from the fab calculator (sfp2usbc.kicad_pro, Board Setup).
2. Adjust the placement if needed (AC caps symmetric on the RD pairs, U1/U2 close to J3 in the
   signal flow, cage/J3 edges per the datasheets), intra-pair skew < 0.15mm.

Review: stackup, rules, placement (before routing).

## Phase 4: routing

1. High-speed pairs first, on L1/L4 over solid GND, no vias if possible (P/N swaps allowed, see
   README.md), GND stitching vias next to any signal via, GND voids on L2 under the AC capacitor and
   connector pads as recommended by the datasheets.
2. CC/VBUS/shield/test points, GND pours with stitching along the edges.
3. DRC clean, length/skew report for the 12 high-speed nets.

Review: routing of the high-speed pairs (human, in KiCad), length/skew report.

## Phase 5: fabrication outputs

Gerbers, drill, BOM, placement (CPL), fab notes (stackup, impedance control 90 ohm differential,
press-fit hole tolerances), 3D view/STEP for the cage clearances.

Review: fab preview (Gerber viewer), BOM/CPL rotations, final `check_netlist.py` on the netlist of
the final schematic.
