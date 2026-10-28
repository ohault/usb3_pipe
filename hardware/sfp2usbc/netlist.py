#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Dual SFP to USB-C (USB 3.2 Gen 1x2) breakout: intended netlist (design intent, see README.md).

Single source of truth for the schematic (drawn in KiCad/Backplane) and its check against the KiCad
netlist export (check_netlist.py). Connector pins are numbered as in the KiCad footprints:
- J1/J2: SFP host connectors (SFF-8431 host pinout, 20 pins), with their 1x1 cages (CG1/CG2).
- J3   : USB Type-C receptacle, full-featured (24 pins: A1-A12/B1-B12, SHIELD: shell).

Data paths (passive SFP DAC cables cross TD <-> RD between their two ends):
- Acorn SFP-0 TD (FPGA TX Lane 0) -> DAC -> J1 RD -> AC caps C1/C2 -> J3 TX1 (device SSTX, Lane 0).
- J3 RX1 (device SSRX, Lane 0) -> J1 TD -> DAC -> Acorn SFP-0 RD (FPGA RX Lane 0).
- Same for Lane 1: Acorn SFP-1 <-> J2 <-> J3 TX2/RX2 (AC caps C3/C4).

The Acorn Baseboard Mini SFP lanes are DC coupled (AC coupling is in SFP modules by standard) and
passive DAC cables are DC: the USB3 transmitter AC coupling capacitors (75-265nF) are on this board,
on the FPGA TX paths only (the host AC couples its own TX), as on the SFP2USB adapter.

P/N may be swapped on any pair (layout): USB3 receivers invert their polarity (both the host and the
USB3PHY, per lane).
"""

# Components ---------------------------------------------------------------------------------------

# ref: (description, value)
COMPONENTS = {
    "J1"  : ("SFP host connector, 20 pins (SFP-A: to Acorn SFP-0, Lane 0)", "SFP"),
    "J2"  : ("SFP host connector, 20 pins (SFP-B: to Acorn SFP-1, Lane 1)", "SFP"),
    "CG1" : ("SFP 1x1 cage (J1)", "SFP cage"),
    "CG2" : ("SFP 1x1 cage (J2)", "SFP cage"),
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
    "C6"  : ("VBUS decoupling (<= 10uF: USB device limit)", "1uF"),
}

# Nets ---------------------------------------------------------------------------------------------

# SFP host connector pins (SFF-8431): ground and unused low-speed/power pins (no connect: passive
# DAC cables do not carry them to the other end).
SFP_GND_PINS = ["1", "10", "11", "14", "17", "20"]
SFP_NC_PINS  = ["2", "3", "4", "5", "6", "7", "8", "9", "15", "16"]
SFP_RD_N, SFP_RD_P, SFP_TD_P, SFP_TD_N = "12", "13", "18", "19"

# ESD arrays: logical I/O pins (the footprint pins are checked by net membership only).
ESD_IO = ["IO1", "IO2", "IO3", "IO4"]

def _lane_nets(lane, sfp, tx_p, tx_n, rx_p, rx_n, c_p, c_n, esd):
    """Nets of one lane: SFP RD -> AC caps -> USB-C SSTX, USB-C SSRX -> SFP TD, ESD on the USB-C
    side of the AC caps."""
    p = f"L{lane}"
    return {
        f"{p}_SFP_RD_P"  : [(sfp, SFP_RD_P), (c_p, "1")],
        f"{p}_SFP_RD_N"  : [(sfp, SFP_RD_N), (c_n, "1")],
        f"{p}_SSTX_P"    : [(c_p, "2"), ("J3", tx_p), (esd, "IO1")],
        f"{p}_SSTX_N"    : [(c_n, "2"), ("J3", tx_n), (esd, "IO2")],
        f"{p}_SSRX_P"    : [("J3", rx_p), (sfp, SFP_TD_P), (esd, "IO3")],
        f"{p}_SSRX_N"    : [("J3", rx_n), (sfp, SFP_TD_N), (esd, "IO4")],
    }

NETS = {}
# Lane 0 (Configuration Lane with the plug in the CC1 orientation): TX1/RX1.
NETS.update(_lane_nets(0, "J1", tx_p="A2", tx_n="A3", rx_p="B11", rx_n="B10", c_p="C1", c_n="C2", esd="U1"))
# Lane 1: TX2/RX2.
NETS.update(_lane_nets(1, "J2", tx_p="B2", tx_n="B3", rx_p="A11", rx_n="A10", c_p="C3", c_n="C4", esd="U2"))
NETS.update({
    "CC1"    : [("J3", "A5"), ("R1", "1")],
    "CC2"    : [("J3", "B5"), ("R2", "1")],
    "VBUS"   : [("J3", "A4"), ("J3", "A9"), ("J3", "B4"), ("J3", "B9"), ("C6", "1")],
    # USB 2.0 not used (SuperSpeed only, as the SFP2USB adapter): D+/D- of both rows joined, to
    # test points.
    "USB2_DP": [("J3", "A6"), ("J3", "B6")],
    "USB2_DN": [("J3", "A7"), ("J3", "B7")],
    "SHIELD" : [("J3", "SHIELD"), ("R3", "1"), ("C5", "1")],
    "GND"    : (
        [("J1", pin) for pin in SFP_GND_PINS] +
        [("J2", pin) for pin in SFP_GND_PINS] +
        [("CG1", "GND"), ("CG2", "GND")] +
        [("J3", pin) for pin in ["A1", "A12", "B1", "B12"]] +
        [("U1", "GND"), ("U2", "GND")] +
        [("R1", "2"), ("R2", "2"), ("R3", "2"), ("C5", "2"), ("C6", "2")]
    ),
})

# No connect pins (checked: on no net, or alone on their net).
NO_CONNECT = (
    [("J1", pin) for pin in SFP_NC_PINS] +
    [("J2", pin) for pin in SFP_NC_PINS] +
    [("J3", pin) for pin in ["A8", "B8"]] # SBU1/SBU2.
)

# High-speed differential pairs (layout rules: README.md).
DIFF_PAIRS = [(f"L{lane}_{name}_P", f"L{lane}_{name}_N")
    for lane in range(2) for name in ["SFP_RD", "SSTX", "SSRX"]]

# Components checked by net membership only (logical pin names, footprint pinout to verify).
SYMBOLIC_PIN_REFS = ["U1", "U2", "CG1", "CG2"]
