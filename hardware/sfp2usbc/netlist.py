#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Dual SFP to USB-C (USB 3.2 Gen 1x2) breakout: intended netlist (design intent, see README.md).

Single source of truth for the schematic (gen_schematic.py, KiCad) and its check against the KiCad
netlist export (check_netlist.py). Pins are numbered as in the KiCad library symbols/footprints:
- J1/J2: SFP host connector + 1x1 cage (Interface_Optical:SFP+, Connector:Connector_SFP_and_Cage, TE
         2227302: SFF-8431 pinout, pins 1-20, cage pins CAGE).
- J3   : USB Type-C receptacle, full-featured (Connector:USB_C_Receptacle, Amphenol 12401610E4-2A:
         A1-A12/B1-B12, shell S1).
- U1/U2: TI TPD4E05U06 (Power_Protection:TPD4E05U06DQA, USON-10): D1+ 1, D1- 2, D2+ 4, D2- 5, GND 3/8,
         NC 6/7/9/10 (not internally connected): flow-through routing, each line routed over its pad
         pair 1/10, 2/9, 4/7, 5/6, the NC pad on the line's net.

Data paths (passive SFP DAC cables cross TD <-> RD between their two ends):
- Acorn SFP-0 TD (FPGA TX Lane 0) -> DAC -> J1 RD -> AC caps C1/C2 -> J3 TX1 (device SSTX, Lane 0).
- J3 RX1 (device SSRX, Lane 0) -> J1 TD -> DAC -> Acorn SFP-0 RD (FPGA RX Lane 0).
- Same for Lane 1: Acorn SFP-1 <-> J2 <-> J3 TX2/RX2 (AC caps C3/C4).

The Acorn Baseboard Mini SFP lanes are DC coupled (AC coupling is in SFP modules by standard) and
passive DAC cables are DC: the USB3 transmitter AC coupling capacitors (75-265nF) are on this board,
on the FPGA TX paths only (the host AC couples its own TX), as on the SFP2USB adapter.

P/N swaps (routing without crossings, USB3 receivers invert their polarity: the host and the
USB3PHY, per lane, USB 3.2 6.4.2/6.13.7): Lane 1 SSRX on the SFP TD pins (J2 TD- = L1_SSRX_P: FPGA RX
Lane 1 inverted), Lane 0 SSTX on the USB-C (A3 TX1- = L0_SSTX_P: host RX Lane 0 inverted).
"""

# Components ---------------------------------------------------------------------------------------

# ref: (description, value)
COMPONENTS = {
    "J1"  : ("SFP host connector + cage (SFP-A: to Acorn SFP-0, Lane 0)", "SFP"),
    "J2"  : ("SFP host connector + cage (SFP-B: to Acorn SFP-1, Lane 1)", "SFP"),
    "J3"  : ("USB Type-C receptacle, full-featured 24 pins, USB 3.2", "USB-C"),
    "C1"  : ("Lane 0 SSTX+ AC coupling", "100nF"),
    "C2"  : ("Lane 0 SSTX- AC coupling", "100nF"),
    "C3"  : ("Lane 1 SSTX+ AC coupling", "100nF"),
    "C4"  : ("Lane 1 SSTX- AC coupling", "100nF"),
    "U1"  : ("4-line ESD array, Lane 0 SSTX/SSRX (low capacitance, USB3)", "TPD4E05U06"),
    "U2"  : ("4-line ESD array, Lane 1 SSTX/SSRX (low capacitance, USB3)", "TPD4E05U06"),
    "R1"  : ("CC1 Rd pull-down (UFP)", "5.1k 1%"),
    "R2"  : ("CC2 Rd pull-down (UFP)", "5.1k 1%"),
    "R3"  : ("Shield to GND", "1M"),
    "C5"  : ("Shield to GND", "100nF"),
}

# Nets ---------------------------------------------------------------------------------------------

# SFP host connector pins (SFF-8431): ground and unused low-speed/power pins (no connect: passive
# DAC cables do not carry them to the other end).
SFP_GND_PINS = ["1", "10", "11", "14", "17", "20"]
SFP_NC_PINS  = ["2", "3", "4", "5", "6", "7", "8", "9", "15", "16"]
SFP_RD_N, SFP_RD_P, SFP_TD_P, SFP_TD_N = "12", "13", "18", "19"

# ESD arrays (TPD4E05U06): 4 identical lines (D1+ 1/10, D1- 2/9, D2+ 4/7, D2- 5/6: pin with its
# flow-through NC pad), GND. Lines assigned in the routing order: SSRX on the top rows, SSTX on the
# bottom rows.
ESD_ROWS = [("1", "10"), ("2", "9"), ("4", "7"), ("5", "6")]
ESD_GND  = ["3", "8"]

def _lane_nets(lane, sfp, sfp_td_p, sfp_td_n, tx_p, tx_n, rx_p, rx_n, c_p, c_n, esd, esd_rows):
    """Nets of one lane: SFP RD -> AC caps -> USB-C SSTX, USB-C SSRX -> SFP TD, ESD on the USB-C
    side of the AC caps (esd_rows: ESD rows of SSRX_P, SSRX_N, SSTX_P, SSTX_N)."""
    p = f"L{lane}"
    rows = dict(zip(["SSRX_P", "SSRX_N", "SSTX_P", "SSTX_N"], [ESD_ROWS[i] for i in esd_rows]))
    return {
        f"{p}_SFP_RD_P"  : [(sfp, SFP_RD_P), (c_p, "1")],
        f"{p}_SFP_RD_N"  : [(sfp, SFP_RD_N), (c_n, "1")],
        f"{p}_SSTX_P"    : [(c_p, "2"), ("J3", tx_p)] + [(esd, pin) for pin in rows["SSTX_P"]],
        f"{p}_SSTX_N"    : [(c_n, "2"), ("J3", tx_n)] + [(esd, pin) for pin in rows["SSTX_N"]],
        f"{p}_SSRX_P"    : [("J3", rx_p), (sfp, sfp_td_p)] + [(esd, pin) for pin in rows["SSRX_P"]],
        f"{p}_SSRX_N"    : [("J3", rx_n), (sfp, sfp_td_n)] + [(esd, pin) for pin in rows["SSRX_N"]],
    }

NETS = {}
# Lane 0 (Configuration Lane with the plug in the CC1 orientation): TX1/RX1, TX1 P/N swapped.
NETS.update(_lane_nets(0, "J1", sfp_td_p=SFP_TD_P, sfp_td_n=SFP_TD_N,
    tx_p="A3", tx_n="A2", rx_p="B11", rx_n="B10", c_p="C1", c_n="C2", esd="U1", esd_rows=[1, 0, 2, 3]))
# Lane 1: TX2/RX2, SFP TD P/N swapped.
NETS.update(_lane_nets(1, "J2", sfp_td_p=SFP_TD_N, sfp_td_n=SFP_TD_P,
    tx_p="B2", tx_n="B3", rx_p="A11", rx_n="A10", c_p="C3", c_n="C4", esd="U2", esd_rows=[0, 1, 2, 3]))
NETS.update({
    "CC1"    : [("J3", "A5"), ("R1", "1")],
    "CC2"    : [("J3", "B5"), ("R2", "1")],
    # VBUS not used (no load): the 4 pins joined, to a test pad.
    "VBUS"   : [("J3", "A4"), ("J3", "A9"), ("J3", "B4"), ("J3", "B9")],
    "SHIELD" : [("J3", "S1"), ("R3", "1"), ("C5", "1")],
    "GND"    : (
        [("J1", pin) for pin in SFP_GND_PINS + ["CAGE"]] +
        [("J2", pin) for pin in SFP_GND_PINS + ["CAGE"]] +
        [("J3", pin) for pin in ["A1", "A12", "B1", "B12"]] +
        [("U1", pin) for pin in ESD_GND] +
        [("U2", pin) for pin in ESD_GND] +
        [("R1", "2"), ("R2", "2"), ("R3", "2"), ("C5", "2")]
    ),
})

# No connect pins (checked: on no net, or alone on their net).
NO_CONNECT = (
    [("J1", pin) for pin in SFP_NC_PINS] +
    [("J2", pin) for pin in SFP_NC_PINS] +
    [("J3", pin) for pin in ["A8", "B8"]] + # SBU1/SBU2.
    # USB 2.0 not used (SuperSpeed only, as the SFP2USB adapter).
    [("J3", pin) for pin in ["A6", "A7", "B6", "B7"]]
)

# High-speed differential pairs (layout rules: README.md).
DIFF_PAIRS = [(f"L{lane}_{name}_P", f"L{lane}_{name}_N")
    for lane in range(2) for name in ["SFP_RD", "SSTX", "SSRX"]]
