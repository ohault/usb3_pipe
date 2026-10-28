# Dual SFP to USB-C breakout (USB 3.2 Gen 1x2)

Passive breakout for USB3-PIPE Gen 1x2 (2x5Gbps) hardware tests
([issue #140](https://github.com/enjoy-digital/usb3_pipe/issues/140),
[gen2-x2-roadmap.md](../../doc/gen2-x2-roadmap.md#gen-1x2-hardware-milestones), M1): two SFP cages
on one side, a USB Type-C receptacle on the other. The LiteX Acorn Baseboard Mini SFP-0/SFP-1
(Lane 0/Lane 1 of `bench/acorn.py --lanes 2`) are connected to the cages with two passive SFP DAC
cables, the USB-C to a USB 3.2 Gen 1x2/Gen 2x2 host with a full-featured USB-C cable.

```
 Acorn Baseboard Mini                       Breakout                                  Host
 FPGA GTP Lane 1 TX ── SFP-1 ══ DAC ══ J2 RD ── C3/C4 (AC) ──┬── J3 TX2 (B2/B3) ══ USB-C ══ RX
 FPGA GTP Lane 1 RX ── SFP-1 ══ DAC ══ J2 TD ────────────────┼── J3 RX2 (A11/A10)          TX (AC at host)
 FPGA GTP Lane 0 TX ── SFP-0 ══ DAC ══ J1 RD ── C1/C2 (AC) ──┼── J3 TX1 (A3/A2)
 FPGA GTP Lane 0 RX ── SFP-0 ══ DAC ══ J1 TD ────────────────┴── J3 RX1 (B11/B10)
                                                       U1/U2 ESD, R1/R2 Rd on CC1/CC2
```

J2 (Lane 1, Acorn SFP-1) is the top cage, J1 (Lane 0, Acorn SFP-0) the bottom cage (as the USB-C
TX2/RX2 and TX1/RX1 pins: no crossings).

## Files

| File | Role |
|---|---|
| [netlist.py](netlist.py) | Design intent: components, pins, nets (single source of truth). |
| [gen_schematic.py](gen_schematic.py) | Generates `sfp2usbc.kicad_sch` from netlist.py (KiCad library symbols, net labels, footprints). |
| [gen_board.py](gen_board.py) | Generates `sfp2usbc.kicad_pcb` (4 layers, outline, footprints/nets, placement, routing), `sfp2usbc.kicad_pro` (net classes) and `sfp2usbc.kicad_dru` (custom rules). |
| [route_board.py](route_board.py) | Routing (called by gen_board.py): planned pair routes, vias, GND planes/pours, stitching. |
| [check_netlist.py](check_netlist.py) | Checks a KiCad netlist export against netlist.py. |
| [backplane-brief.md](backplane-brief.md) | Review and fab outputs with Backplane (or in KiCad). |
| [sfp2usbc-schematic.pdf](sfp2usbc-schematic.pdf), [sfp2usbc-top.png](sfp2usbc-top.png), [sfp2usbc-bottom.png](sfp2usbc-bottom.png) | Previews (schematic, routing on F.Cu/B.Cu without the GND pours). |

```sh
# KiCad 7+ (kicad-cli, pcbnew Python module).
$ ./gen_schematic.py
$ kicad-cli sch export netlist --format kicadsexpr -o sfp2usbc.net sfp2usbc.kicad_sch
$ ./check_netlist.py sfp2usbc.net        # 0 errors.
$ ./gen_board.py --drc drc.rpt           # Routed board + DRC report (clean).
```

`gen_board.py` overwrites the board: once it is edited in KiCad, change the schematic (regenerated
from netlist.py) and use KiCad's "Update PCB from Schematic" (footprints linked to the schematic
symbols) instead of regenerating the board. Tests: `test/test_sfp2usbc_netlist.py` (netlist, KiCad
schematic/board round trips, DRC, pairs skew).

## Design decisions

- **AC coupling on this board, FPGA TX paths only.** The Acorn Baseboard Mini SFP lanes are DC
  coupled to the GTPs (schematic rev 0.2: "SFP: AC coupling on modules by standard") and passive DAC
  cables are DC: the USB3 transmitter AC coupling (75-265nF, 100nF as the SFP2USB adapter) is on the
  breakout, between the SFP RD pins (FPGA TX, after the DAC crossover) and the USB-C TX pins. The
  host AC couples its own TX: no capacitor on the RX paths.
- **Lane mapping.** J1 (bottom cage, to Acorn SFP-0, USB3PHY Lane 0) on TX1/RX1, J2 (top cage, to
  Acorn SFP-1, Lane 1) on TX2/RX2. With the plug in the CC1 orientation, the Configuration Lane
  (Lane 0) is TX1/RX1: lanes match. With the plug flipped, the lanes are swapped: handled in
  gateware (below).
- **Plug orientation in gateware, not with a CC controller.** Passive DAC cables do not carry the SFP
  low-speed pins (I2C, MOD_ABS...) to the other end: a CC controller on the breakout cannot be read by
  the FPGA. The host sends the SuperSpeedPlus Polling LFPS on its Configuration Lane only: the
  USB3PHY can detect the lane receiving them and swap the lanes (to do, roadmap M1). The R1/R2 pads
  give the orientation on the bench (the CC with ~0.4V-2V on its Rd is the active one).
- **UFP (device) Rd on CC1/CC2** (5.1k 1%): the host sources VBUS and enables SuperSpeed. No VCONN,
  no USB PD. VBUS is not used: the 4 VBUS pins joined, to a bottom test pad (TP1).
- **No USB 2.0** (as the SFP2USB adapter, works with Linux xHCI hosts): D+/D- and SBU1/SBU2 not
  connected.
- **P/N swaps.** USB3 receivers invert their RX polarity (host and USB3PHY, per lane, USB 3.2
  6.4.2/6.13.7), the Acorn baseboard already inverts some pairs. The routing has no crossings with
  two swaps: Lane 1 SSRX on the SFP side (J2 TD- = L1_SSRX_P: FPGA RX Lane 1 inverted) and Lane 0
  SSTX on the USB-C side (A3 TX1- = L0_SSTX_P: host RX Lane 0 inverted).
- **SFP low-speed/power pins not connected** (VccT/VccR, TX_DISABLE, MOD_DEF0-2, RS0/RS1, LOS,
  TX_FAULT): nothing to power or read in a passive DAC plug for this use.
- **ESD**: low capacitance 4-line arrays (U1/U2, TI TPD4E05U06, 0.5pF) on the USB-C side of the
  AC capacitors, close to J3. Flow-through routing: each line runs over its pad pair (1/10, 2/9,
  4/7, 5/6), the NC pads (not internally connected) are on the line's net, SSRX on the top rows,
  SSTX on the bottom rows (lines assigned in the routing order), GND vias on both sides.
- **Shield**: 1M || 100nF to GND (R3/C5, as the SFP2USB adapter). Cages to GND.

## Pin mapping

SFP host connector (SFF-8431 pinout): 1/10/11/14/17/20 VeeT/VeeR (GND), 12 RD-, 13 RD+, 18 TD+,
19 TD-, 2-9/15/16 low-speed/power (not connected). Through the DAC cable, the Acorn TD (FPGA TX)
arrives on the breakout RD pins and the breakout TD pins go to the Acorn RD (FPGA RX).

| Net | SFP | AC cap | USB-C | ESD |
|---|---|---|---|---|
| L0_SFP_RD_P / L0_SSTX_P | J1.13 (RD+) | C1 | A3 (TX1-, swapped) | U1.4/7 |
| L0_SFP_RD_N / L0_SSTX_N | J1.12 (RD-) | C2 | A2 (TX1+, swapped) | U1.5/6 |
| L0_SSRX_P | J1.18 (TD+) | - | B11 (RX1+) | U1.2/9 |
| L0_SSRX_N | J1.19 (TD-) | - | B10 (RX1-) | U1.1/10 |
| L1_SFP_RD_P / L1_SSTX_P | J2.13 (RD+) | C3 | B2 (TX2+) | U2.4/7 |
| L1_SFP_RD_N / L1_SSTX_N | J2.12 (RD-) | C4 | B3 (TX2-) | U2.5/6 |
| L1_SSRX_P | J2.19 (TD-, swapped) | - | A11 (RX2+) | U2.1/10 |
| L1_SSRX_N | J2.18 (TD+, swapped) | - | A10 (RX2-) | U2.2/9 |
| CC1 / CC2 | | | A5 / B5 | R1 / R2 5.1k to GND |
| VBUS | | | A4/A9/B4/B9 | TP1 (bottom) |
| SHIELD | | | Shell | R3 1M, C5 100nF to GND |
| GND | 1/10/11/14/17/20, cages | | A1/A12/B1/B12 | U1/U2.3/8 |

## Bill of materials

| Ref | Part | KiCad footprint | Notes |
|---|---|---|---|
| J1, J2 | SFP 20-pin connector + 1x1 press-fit cage (TE drawing 2227302) | `Connector:Connector_SFP_and_Cage` | Order the connector and the cage per the TE drawing; PCB edge 43mm from the footprint origin. |
| J3 | Amphenol 12401610E4#2A (USB-C, 24 pins, USB 3.2, R/A SMT) | `Connector_USB:USB_C_Receptacle_Amphenol_12401610E4-2A` | All 4 SuperSpeed pairs (the 16-pin USB 2.0 receptacles, ex GCT USB4085, do not fit). Alternative: Molex 105450-0101. |
| C1-C4 | 100nF X7R 0402, 16V | `Capacitor_SMD:C_0402_1005Metric` | USB3 75-265nF. |
| U1, U2 | TI TPD4E05U06DQAR | `Package_SON:USON-10_2.5x1.0mm_P0.5mm` | 0.5pF, flow-through. |
| R1, R2 | 5.1k 1% 0402 | `Resistor_SMD:R_0402_1005Metric` | Rd (UFP). |
| R3, C5 | 1M 0402, 100nF 0402 | 0402 | Shield. |
| TP1 | VBUS test pad (bottom side) | `TestPoint:TestPoint_Pad_D1.0mm` | |
| H1-H4 | M3 mounting holes | `MountingHole:MountingHole_3.2mm_M3` | |

Check the datasheets, availability and footprints (pad sizes, J3 front/board edge position) before
ordering.

## PCB

Generated (gen_board.py + route_board.py), DRC clean (KiCad 7: 0 violations, 0 unconnected).

- **Stackup**: 4 layers, 1.6mm: F.Cu signals, In1.Cu/In2.Cu solid GND planes, B.Cu signals (USB-C B
  row pairs, CC2, VBUS, shield ring), GND pours on F.Cu/B.Cu, GND stitching vias (3mm grid where
  free). Set the fab's controlled impedance stackup.
- **Impedance**: 90 ohm differential (USB 3.2; SFP is 100 ohm: negligible on a few cm), net class
  `HS_90R` (all `L*` nets) with 0.30mm width/0.20mm gap: estimate for a ~0.21mm prepreg, to replace
  with the fab's stackup/impedance calculator values (then regenerate: PAIR_PITCH/HS_WIDTH in
  route_board.py). Custom rule: 0.25mm between the HS tracks and the other nets outside the fine
  pitch footprints.
- **Placement**: 78 x 50mm, cages on the left edge (TE 2227302 PCB edge), J3 on the right edge, AC
  caps in line with the SFP RD pads (staggered), ESD arrays (flow-through) between the caps and J3,
  Rd/shield parts next to J3, 4 M3 holes on the right half (the cages take the left half).
- **Routing** (per lane, nested L-shaped routes with 45 degrees corners, no crossings):
  - USB-C A row pairs (L1 SSRX, L0 SSTX) on F.Cu end to end, no vias.
  - USB-C B row pairs (L1 SSTX, L0 SSRX): F.Cu from the SFP to the ESD, then 0.35/0.2mm vias
    (staggered 0.6mm, GND stitching via next to them), B.Cu, and 0.35/0.2mm vias in front of the B
    row (two staggered columns under the connector body: tented), F.Cu stubs to the B pads. A row
    GND/VBUS pins joined to their B row pins across the rows.
  - Lengths 34-36mm per line (lanes within ~2mm, deskewed by the USB3PHY), intra-pair skew <=
    0.043mm: the B row pairs P line (outer via column) is matched with 3 bumps on the N line.
- **Fab**: 0.35mm vias with 0.2mm drills (0.075mm annular ring), 0.15mm clearances, 0.25mm hole
  clearance, 0.25mm copper to edge (J3 footprint: 0.298mm between a NPTH and a shell pad): check
  them against the fab capabilities.
- **To review in KiCad**: impedance values, return paths (GND planes are solid under all the pairs),
  the J3/SFP footprints vs datasheets, the vias under the J3 body (tented), silkscreen.
- **Outputs**: Gerbers, drill, IPC netlist, BOM, placement (CPL), fab stackup/impedance notes.

## Bring-up

1. Continuity/impedance: no short between pairs, Rd 5.1k on CC1/CC2, AC caps in series on the TX paths.
   DAC cables: Acorn SFP-0 to J1 (bottom cage), SFP-1 to J2 (top cage).
2. Acorn `bench/acorn.py --lanes 2 --role device` on both SFPs through the breakout and DAC cables
   (<= 1m, passive), a full-featured USB-C cable (all SuperSpeed pairs: "USB 10Gbps/20Gbps" rated)
   to a USB 3.2 Gen 2x2 host (Gen 1x2 support: ex ASMedia ASM3242).
3. `./bench/usb3_lanes.py status`: SuperSpeedPlus Polling with Gen 1x2 negotiated (x2) and link
   training, both plug orientations (flipped: lanes swapped, until the gateware lane swap is done).
   The `--lanes 2` bitstream has no Link Layer: the host does not enumerate it (the link leaves U0).
   Linux `/sys/bus/usb/devices/*/rx_lanes`/`tx_lanes` once the Gen 1x2 Link Layer is done.
4. Single lane (Gen 1x1) hosts: needs the single lane fallback in the USB3PHY (roadmap).
