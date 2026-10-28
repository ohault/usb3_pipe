#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Dual SFP to USB-C breakout (hardware/sfp2usbc): intended netlist consistency and the KiCad netlist
check (check_netlist.py) on netlists generated from it, with typical schematic mistakes."""

import sys
import copy
import unittest

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hardware" / "sfp2usbc"))

from netlist import COMPONENTS, NETS, NO_CONNECT, DIFF_PAIRS, SYMBOLIC_PIN_REFS
from check_netlist import read_kicad_netlist, check

# Helpers ------------------------------------------------------------------------------------------

def kicad_netlist(nets, components=COMPONENTS, extra_nodes=[]):
    """KiCad netlist export (kicadsexpr) text from {name: [(ref, pin)]}, symbolic pins renumbered
    as footprint pads (as after the footprint assignment)."""
    pads = {}
    def pad(ref, pin):
        if ref not in SYMBOLIC_PIN_REFS:
            return pin
        return pads.setdefault((ref, pin), str(len([k for k in pads if k[0] == ref]) + 1))
    comps = "".join(f'(comp (ref "{ref}") (value "{value}"))' for ref, (_, value) in components.items())
    out = []
    for code, (name, nodes) in enumerate(nets.items()):
        nodes_txt = "".join(f'(node (ref "{r}") (pin "{pad(r, p)}"))' for r, p in nodes)
        out.append(f'(net (code "{code + 1}") (name "/{name}") {nodes_txt})')
    for i, (r, p) in enumerate(extra_nodes):
        out.append(f'(net (code "{1000 + i}") (name "unconnected-({r}-Pad{p})") (node (ref "{r}") (pin "{p}")))')
    return f'(export (version "E") (components {comps}) (nets {"".join(out)}))'

def run_check(nets, **kwargs):
    return check(*read_kicad_netlist(kicad_netlist(nets, **kwargs)))

# Tests --------------------------------------------------------------------------------------------

class TestSFP2USBCNetlist(unittest.TestCase):
    def test_intent(self):
        # Each pin on a single net, all nets' components declared, no connect pins not on nets.
        seen = {}
        for name, nodes in NETS.items():
            for node in nodes:
                self.assertIn(node[0], COMPONENTS, name)
                self.assertNotIn(node, seen, f"{node} on {name} and {seen.get(node)}")
                seen[node] = name
        for node in NO_CONNECT:
            self.assertNotIn(node, seen)
        # USB-C: 24 pins + shield, all accounted for.
        usbc = {pin for ref, pin in list(seen) + NO_CONNECT if ref == "J3"}
        self.assertEqual(usbc, {f"{row}{i}" for row in "AB" for i in range(1, 13)} | {"SHIELD"})
        # SFP connectors: 20 pins each.
        for ref in ["J1", "J2"]:
            pins = {pin for r, pin in list(seen) + NO_CONNECT if r == ref}
            self.assertEqual(pins, {str(i) for i in range(1, 21)})
        # AC coupling capacitors on the FPGA TX (SFP RD) -> USB-C SSTX paths only.
        for lane, (sfp, caps) in enumerate([("J1", ("C1", "C2")), ("J2", ("C3", "C4"))]):
            for pol, cap in zip("PN", caps):
                self.assertIn((cap, "1"), NETS[f"L{lane}_SFP_RD_{pol}"])
                self.assertIn((cap, "2"), NETS[f"L{lane}_SSTX_{pol}"])
                self.assertFalse(any(r.startswith("C") for r, _ in NETS[f"L{lane}_SSRX_{pol}"]))
        # Lane 0 on TX1/RX1 (Configuration Lane with the CC1 orientation), Lane 1 on TX2/RX2.
        self.assertIn(("J3", "A2"),  NETS["L0_SSTX_P"])
        self.assertIn(("J3", "B11"), NETS["L0_SSRX_P"])
        self.assertIn(("J3", "B2"),  NETS["L1_SSTX_P"])
        self.assertIn(("J3", "A11"), NETS["L1_SSRX_P"])
        for p, n in DIFF_PAIRS:
            self.assertIn(p, NETS)
            self.assertIn(n, NETS)

    def test_check_ok(self):
        nc = [node for node in NO_CONNECT]
        errors, warnings = run_check(NETS, extra_nodes=nc)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        # Test points on nets are allowed.
        nets = copy.deepcopy(NETS)
        nets["CC1"].append(("TP1", "1"))
        nets["VBUS"].append(("TP2", "1"))
        components = dict(COMPONENTS, TP1=("", "TestPoint"), TP2=("", "TestPoint"))
        self.assertEqual(run_check(nets, components=components)[0], [])

    def test_check_errors(self):
        def errors_of(mutate, components=COMPONENTS):
            nets = copy.deepcopy(NETS)
            mutate(nets)
            return run_check(nets, components=components)[0]

        # AC coupling capacitor bypassed (SFP RD directly on the USB-C SSTX net).
        def bypass(nets):
            nets["L0_SSTX_P"] += nets.pop("L0_SFP_RD_P")
        self.assertTrue(errors_of(bypass))

        # Lanes swapped on the USB-C side (Lane 0 on TX2).
        def swap(nets):
            nets["L0_SSTX_P"][1], nets["L1_SSTX_P"][1] = nets["L1_SSTX_P"][1], nets["L0_SSTX_P"][1]
        self.assertTrue(errors_of(swap))

        # Missing CC2 Rd (R2 not connected to CC2).
        def no_rd(nets):
            nets["CC2"].remove(("R2", "1"))
        self.assertTrue(errors_of(no_rd))

        # SBU connected to GND (no connect pin).
        def sbu(nets):
            nets["GND"].append(("J3", "A8"))
        self.assertTrue(errors_of(sbu))

        # ESD array pin on two lines of a pair (one line unprotected).
        def esd(nets):
            nets["L1_SSRX_N"].remove(("U2", "IO4"))
        self.assertTrue(errors_of(esd))

        # VBUS row pin missing.
        def vbus(nets):
            nets["VBUS"].remove(("J3", "B9"))
        self.assertTrue(errors_of(vbus))

        # Missing component.
        components = {k: v for k, v in COMPONENTS.items() if k != "C6"}
        def no_c6(nets):
            nets["VBUS"].remove(("C6", "1"))
            nets["GND"].remove(("C6", "2"))
        self.assertTrue(errors_of(no_c6, components=components))

if __name__ == "__main__":
    unittest.main()
