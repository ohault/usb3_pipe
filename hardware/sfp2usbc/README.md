# Dual SFP to USB-C breakout (USB 3.2 Gen 1x2)

Passive breakout for USB3-PIPE Gen 1x2 (2x5Gbps) hardware tests
([issue #140](https://github.com/enjoy-digital/usb3_pipe/issues/140),
[gen2-x2-roadmap.md](../../doc/gen2-x2-roadmap.md#gen-1x2-hardware-milestones), M1): two SFP cages
on one side, a USB Type-C receptacle on the other. The LiteX Acorn Baseboard Mini SFP-0/SFP-1
(Lane 0/Lane 1 of `bench/acorn.py --lanes 2`) are connected to the cages with two passive SFP DAC
cables, the USB-C to a USB 3.2 Gen 1x2/Gen 2x2 host with a full-featured USB-C cable.

```
 Acorn Baseboard Mini                       Breakout                                  Host
 FPGA GTP Lane 0 TX ── SFP-0 ══ DAC ══ J1 RD ── C1/C2 (AC) ──┬── J3 TX1 (A2/A3) ══ USB-C ══ RX
 FPGA GTP Lane 0 RX ── SFP-0 ══ DAC ══ J1 TD ────────────────┼── J3 RX1 (B11/B10)          TX (AC at host)
 FPGA GTP Lane 1 TX ── SFP-1 ══ DAC ══ J2 RD ── C3/C4 (AC) ──┼── J3 TX2 (B2/B3)
 FPGA GTP Lane 1 RX ── SFP-1 ══ DAC ══ J2 TD ────────────────┴── J3 RX2 (A11/A10)
                                                       U1/U2 ESD, R1/R2 Rd on CC1/CC2
```

## Files

| File | Role |
|---|---|
| [netlist.py](netlist.py) | Design intent: components, pins, nets (single source of truth). |
| [gen_schematic.py](gen_schematic.py) | Generates `sfp2usbc.kicad_sch` from netlist.py (KiCad library symbols, net labels, footprints). |
| [gen_board.py](gen_board.py) | Generates `sfp2usbc.kicad_pcb` (4 layers, outline, footprints/nets, placement), `sfp2usbc.kicad_pro` (net classes) and `sfp2usbc.kicad_dru` (custom rules): unrouted. |
| [check_netlist.py](check_netlist.py) | Checks a KiCad netlist export against netlist.py. |
| [backplane-brief.md](backplane-brief.md) | Routing and fab outputs with Backplane (or by hand in KiCad). |
| [sfp2usbc-schematic.pdf](sfp2usbc-schematic.pdf), [sfp2usbc-placement.png](sfp2usbc-placement.png) | Previews (schematic, board placement before routing). |

```sh
# KiCad 7+ (kicad-cli, pcbnew Python module).
$ ./gen_schematic.py
$ kicad-cli sch export netlist --format kicadsexpr -o sfp2usbc.net sfp2usbc.kicad_sch
$ ./check_netlist.py sfp2usbc.net        # 0 errors.
$ ./gen_board.py --drc drc.rpt           # Unrouted board + DRC report (unconnected items before routing).
```

`gen_board.py` overwrites the board: once the routing has started in KiCad, change the schematic
(regenerated from netlist.py) and use KiCad's "Update PCB from Schematic" (footprints linked to the
schematic symbols) instead of regenerating the board. Tests: `test/test_sfp2usbc_netlist.py`.

## Design decisions

- **AC coupling on this board, FPGA TX paths only.** The Acorn Baseboard Mini SFP lanes are DC
  coupled to the GTPs (schematic rev 0.2: "SFP: AC coupling on modules by standard") and passive DAC
  cables are DC: the USB3 transmitter AC coupling (75-265nF, 100nF as the SFP2USB adapter) is on the
  breakout, between the SFP RD pins (FPGA TX, after the DAC crossover) and the USB-C TX pins. The
  host AC couples its own TX: no capacitor on the RX paths.
- **Lane mapping.** J1 (to Acorn SFP-0, USB3PHY Lane 0) on TX1/RX1, J2 (to Acorn SFP-1, Lane 1) on
  TX2/RX2. With the plug in the CC1 orientation, the Configuration Lane (Lane 0) is TX1/RX1: lanes
  match. With the plug flipped, the lanes are swapped: handled in gateware (below).
- **Plug orientation in gateware, not with a CC controller.** Passive DAC cables do not carry the SFP
  low-speed pins (I2C, MOD_ABS...) to the other end: a CC controller on the breakout cannot be read by
  the FPGA. The host sends the SuperSpeedPlus Polling LFPS on its Configuration Lane only: the
  USB3PHY can detect the lane receiving them and swap the lanes (to do, roadmap M1). CC1/CC2 test
  points give the orientation on the bench (the CC with ~0.4V-2V on Rd is the active one).
- **UFP (device) Rd on CC1/CC2** (5.1k 1%): the host sources VBUS and enables SuperSpeed. No VCONN,
  no USB PD. VBUS is not used (C6 decoupling, test point; <= 10uF on VBUS for a USB device).
- **No USB 2.0** (as the SFP2USB adapter, works with Linux xHCI hosts): D+/D- of both rows joined
  to test points. SBU1/SBU2 not connected.
- **Polarity free.** USB3 receivers invert their RX polarity (host and USB3PHY, per lane), the Acorn
  baseboard already inverts some pairs: P/N may be swapped on any pair to avoid vias/crossings.
- **SFP low-speed/power pins not connected** (VccT/VccR, TX_DISABLE, MOD_DEF0-2, RS0/RS1, LOS,
  TX_FAULT): nothing to power or read in a passive DAC plug for this use.
- **ESD**: low capacitance 4-line arrays (U1/U2, TI TPD4E05U06, 0.5pF) on the USB-C side of the
  AC capacitors, close to J3. Flow-through routing: each line runs over its pad pair (1/10, 2/9,
  4/7, 5/6), the NC pads (not internally connected) are on the line's net.
- **Shield**: 1M || 100nF to GND (R3/C5, as the SFP2USB adapter). Cages to GND.

## Pin mapping

SFP host connector (SFF-8431 pinout): 1/10/11/14/17/20 VeeT/VeeR (GND), 12 RD-, 13 RD+, 18 TD+,
19 TD-, 2-9/15/16 low-speed/power (not connected). Through the DAC cable, the Acorn TD (FPGA TX)
arrives on the breakout RD pins and the breakout TD pins go to the Acorn RD (FPGA RX).

| Net | SFP | AC cap | USB-C | ESD |
|---|---|---|---|---|
| L0_SFP_RD_P / L0_SSTX_P | J1.13 (RD+) | C1 | A2 (TX1+) | U1 |
| L0_SFP_RD_N / L0_SSTX_N | J1.12 (RD-) | C2 | A3 (TX1-) | U1 |
| L0_SSRX_P | J1.18 (TD+) | - | B11 (RX1+) | U1 |
| L0_SSRX_N | J1.19 (TD-) | - | B10 (RX1-) | U1 |
| L1_SFP_RD_P / L1_SSTX_P | J2.13 (RD+) | C3 | B2 (TX2+) | U2 |
| L1_SFP_RD_N / L1_SSTX_N | J2.12 (RD-) | C4 | B3 (TX2-) | U2 |
| L1_SSRX_P | J2.18 (TD+) | - | A11 (RX2+) | U2 |
| L1_SSRX_N | J2.19 (TD-) | - | A10 (RX2-) | U2 |
| CC1 / CC2 | | | A5 / B5 | R1 / R2 5.1k to GND |
| VBUS | | | A4/A9/B4/B9 | C6 1uF |
| GND | 1/10/11/14/17/20, cages | | A1/A12/B1/B12 | |

## Bill of materials

| Ref | Part | KiCad footprint | Notes |
|---|---|---|---|
| J1, J2 | SFP 20-pin connector + 1x1 press-fit cage (TE drawing 2227302) | `Connector:Connector_SFP_and_Cage` | Order the connector and the cage per the TE drawing; PCB edge 43mm from the footprint origin. |
| J3 | Amphenol 12401610E4#2A (USB-C, 24 pins, USB 3.2, R/A SMT) | `Connector_USB:USB_C_Receptacle_Amphenol_12401610E4-2A` | All 4 SuperSpeed pairs (the 16-pin USB 2.0 receptacles, ex GCT USB4085, do not fit). Alternative: Molex 105450-0101. |
| C1-C4 | 100nF X7R 0402, 16V | `Capacitor_SMD:C_0402_1005Metric` | USB3 75-265nF. |
| U1, U2 | TI TPD4E05U06DQAR | `Package_SON:USON-10_2.5x1.0mm_P0.5mm` | 0.5pF, flow-through. |
| R1, R2 | 5.1k 1% 0402 | `Resistor_SMD:R_0402_1005Metric` | Rd (UFP). |
| R3, C5 | 1M 0402, 100nF 0402 | 0402 | Shield. |
| C6 | 1uF 0402 | 0402 | VBUS. |
| TP1-TP6 | Test pads (CC1, CC2, VBUS, USB2_DP, USB2_DN, GND) | `TestPoint:TestPoint_Pad_D1.0mm` | |
| H1-H4 | M3 mounting holes | `MountingHole:MountingHole_3.2mm_M3` | |

Check the datasheets, availability and footprints (pad sizes, J3 front/board edge position) before
ordering.

## PCB

- **Stackup**: 4 layers, 1.6mm (L1 signals, L2 GND, L3 GND/VBUS, L4 signals/GND), FR-4 from the fab's
  controlled impedance stackup.
- **Impedance**: 90 ohm differential (USB 3.2; SFP is 100 ohm: negligible on a few cm), net class
  `HS_90R` (all `L*` nets) with 0.30mm width/0.20mm gap (estimate for a ~0.21mm prepreg, to replace
  with the fab's stackup/impedance calculator values before routing). Reference all pairs to the
  solid L2 GND, no plane splits under them. Custom rule: 0.3mm between the HS tracks and other nets
  (pads: net class clearance, fine pitch connectors).
- **Lengths**: pairs as short as possible (< 50mm), intra-pair skew < 0.15mm (5 mil); lane-to-lane
  skew not critical (deskewed by the USB3PHY: keep within ~25mm).
- **No vias** on the high-speed pairs if possible (P/N swaps allowed); else GND stitching vias next
  to each signal via.
- **AC caps/ESD**: symmetric placement per pair, ESD close to J3 with flow-through routing, GND voids
  on L2 under the AC capacitor and SFP/USB-C pads (pad capacitance), per the connector datasheets.
- **Placement** (gen_board.py): 78 x 50mm, cages on the left edge, J3 on the right edge, AC caps on
  the SFP RD pairs, ESD arrays between the caps and J3, Rd/VBUS/shield parts next to J3, test pads
  in the middle, 4 M3 holes on the right half (the cages take the left half). GND stitching along
  the edges.
- **Known DRC items before routing**: unconnected items (to route), J3 footprint own NPTH-to-shield
  pad spacing (0.298mm, under the 0.3mm edge clearance: footprint from the connector drawing).
- **Outputs**: Gerbers, drill, IPC netlist, BOM, placement (CPL), fab stackup/impedance notes.

## Bring-up

1. Continuity/impedance: no short between pairs, Rd 5.1k on CC1/CC2, AC caps in series on the TX paths.
2. Acorn `bench/acorn.py --lanes 2 --role device` on both SFPs through the breakout and DAC cables
   (<= 1m, passive), a full-featured USB-C cable (all SuperSpeed pairs: "USB 10Gbps/20Gbps" rated)
   to a USB 3.2 Gen 2x2 host (Gen 1x2 support: ex ASMedia ASM3242).
3. `./bench/usb3_lanes.py status`: SuperSpeedPlus Polling with Gen 1x2 negotiated (x2) and link
   training, both plug orientations (flipped: lanes swapped, until the gateware lane swap is done).
   The `--lanes 2` bitstream has no Link Layer: the host does not enumerate it (the link leaves U0).
   Linux `/sys/bus/usb/devices/*/rx_lanes`/`tx_lanes` once the Gen 1x2 Link Layer is done.
4. Single lane (Gen 1x1) hosts: needs the single lane fallback in the USB3PHY (roadmap).
