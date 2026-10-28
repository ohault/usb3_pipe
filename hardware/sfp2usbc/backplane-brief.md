# Backplane brief: dual SFP to USB-C breakout

Brief for the Backplane agents (KiCad), to paste in a Backplane project thread with this directory in
the project. The schematic and the routed board are generated (gen_schematic.py, gen_board.py,
route_board.py: DRC clean): the agents review them (Phases 1-4) and produce the fab outputs
(Phase 5). Each phase ends with a human review: do not start a phase before the previous one is
approved.

## Context for the agents

You design a small passive 4-layer PCB in KiCad: two SFP host connectors with 1x1 cages on one edge,
a full-featured USB Type-C receptacle on the opposite edge, carrying two USB 3.2 Gen 1 SuperSpeed
lanes (5Gbps each) from two SFP DAC cables to a USB-C cable. The design intent is fixed:

- `README.md`: design decisions, pin mapping, BOM candidates, PCB rules.
- `netlist.py`: the exact connectivity (refs, pins, net names). Use these refs and net names.
- `sfp2usbc.kicad_sch`/`sfp2usbc.kicad_pcb`/`.kicad_pro`/`.kicad_dru`: generated schematic, routed
  board, net classes and rules. Change the connectivity only in `netlist.py` (regenerate).
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

## Phase 3: stackup and rules (review/adjust)

1. Fab stackup with controlled impedance (4 layers 1.6mm, In1/In2 solid GND): 90 ohm differential
   width/gap from the fab calculator. If they differ from 0.30/0.20mm: update `PAIR_PITCH`/`HS_WIDTH`
   (route_board.py) and the `HS_90R` net class (gen_board.py), regenerate, DRC.
2. Fab capabilities: 0.35/0.2mm vias (0.075mm annular ring), 0.15mm clearances, 0.25mm hole
   clearance and copper to edge.

Review: stackup, rules.

## Phase 4: routing (review)

1. High-speed pairs (12 nets `L*`): routes, 45 degrees corners, layer changes (B row pairs: vias near
   the ESD and in front of the USB-C B row, under the connector body: tented), return paths (GND
   stitching next to the layer changes, solid planes under all the pairs), length matching bumps.
2. DRC clean, length/skew report (README.md: P/N within 0.15mm per pair).
3. GND pours/stitching, CC/VBUS/shield, silkscreen.

Review: routing (human, in KiCad), DRC, skew report.

## Phase 5: fabrication outputs

Gerbers, drill, BOM, placement (CPL), fab notes (stackup, impedance control 90 ohm differential,
tented vias, press-fit hole tolerances), 3D view/STEP for the cage clearances.

Review: fab preview (Gerber viewer), BOM/CPL rotations, final `check_netlist.py` on the netlist of
the final schematic.
