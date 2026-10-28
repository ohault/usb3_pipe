# Backplane brief: dual SFP to USB-C breakout

Brief for the Backplane agents (KiCad), to paste in a Backplane project thread with this directory
(README.md, netlist.py, check_netlist.py) in the project. The agents work in phases, each ending with
a human review: do not start a phase before the previous one is approved.

## Context for the agents

You design a small passive 4-layer PCB in KiCad: two SFP host connectors with 1x1 cages on one edge,
a full-featured USB Type-C receptacle on the opposite edge, carrying two USB 3.2 Gen 1 SuperSpeed
lanes (5Gbps each) from two SFP DAC cables to a USB-C cable. The design intent is fixed:

- `README.md`: design decisions, pin mapping, BOM candidates, PCB rules.
- `netlist.py`: the exact connectivity (refs, pins, net names). Use these refs and net names.
- `check_netlist.py`: must report 0 errors on the schematic netlist export.

Rules:
- Do not change the connectivity or add circuits that are not in `netlist.py` (except test points
  TP*, mounting holes H*, fiducials, logos). Ask if something looks wrong.
- Footprints from the manufacturer datasheets (or KiCad libraries checked against them): report the
  datasheet pages used for J1/J2, CG1/CG2, J3, U1/U2.
- High-speed pairs: `L0_SFP_RD_P/N`, `L0_SSTX_P/N`, `L0_SSRX_P/N`, `L1_*` (diff pairs, 90 ohm).

## Phase 1: parts and footprints

1. Check the BOM candidates of README.md (datasheet, active, stock), propose alternatives if needed.
2. Symbols/footprints for J1/J2 (SFP connector, SFF-8431 pinout, pads 1-20), CG1/CG2 (cage, press-fit
   holes, board thickness), J3 (24-pin USB-C, pins A1-A12/B1-B12, shell), U1/U2 (map the netlist.py
   IO1-IO4/GND to the datasheet pins, flow-through).

Review: footprints vs datasheets (pad sizes, pin 1, J3 A/B rows, cage/connector alignment).

## Phase 2: schematic

1. Schematic with the refs, values and net labels of `netlist.py` (one sheet: SFP-A/Lane 0, SFP-B/
   Lane 1, USB-C, CC/VBUS/shield), no connect flags on the `NO_CONNECT` pins, test points on CC1,
   CC2, VBUS, USB2_DP, USB2_DN, GND.
2. ERC clean.
3. `kicad-cli sch export netlist --format kicadsexpr -o sfp2usbc.net sfp2usbc.kicad_sch` then
   `./check_netlist.py sfp2usbc.net`: 0 errors.

Review: schematic + check_netlist.py output.

## Phase 3: board setup and placement

1. Board ~50 x 45mm, 4 layers 1.6mm, fab stackup with controlled impedance (L2 solid GND), 4 M3
   mounting holes.
2. Net classes/diff pair rules: 90 ohm differential widths/gaps from the fab calculator, intra-pair
   skew < 0.15mm, clearance to other nets >= 3x the trace width.
3. Placement: cages + J1/J2 on one edge (front per the cage datasheet), J3 on the opposite edge,
   AC caps C1-C4 symmetric per pair, U1/U2 close to J3 (flow-through), R1/R2/R3/C5/C6 near J3.

Review: placement, stackup, rules (before routing).

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
