#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Dual SFP to USB-C breakout (hardware/sfp2usbc): intended netlist consistency and the KiCad netlist
check (check_netlist.py) on netlists generated from it, with typical schematic mistakes."""

import sys
import copy
import shutil
import tempfile
import unittest
import importlib.util
import subprocess

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hardware" / "sfp2usbc"))

from netlist import COMPONENTS, NETS, NO_CONNECT, DIFF_PAIRS
from check_netlist import read_kicad_netlist, check

# Helpers ------------------------------------------------------------------------------------------

def kicad_netlist(nets, components=COMPONENTS, extra_nodes=[]):
    """KiCad netlist export (kicadsexpr) text from {name: [(ref, pin)]}."""
    comps = "".join(f'(comp (ref "{ref}") (value "{value}"))' for ref, (_, value) in components.items())
    out = []
    for code, (name, nodes) in enumerate(nets.items()):
        nodes_txt = "".join(f'(node (ref "{r}") (pin "{p}"))' for r, p in nodes)
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
        self.assertEqual(usbc, {f"{row}{i}" for row in "AB" for i in range(1, 13)} | {"S1"})
        # SFP connectors: 20 pins + cage each, ESD arrays: 10 pins each.
        for ref in ["J1", "J2"]:
            pins = {pin for r, pin in list(seen) + NO_CONNECT if r == ref}
            self.assertEqual(pins, {str(i) for i in range(1, 21)} | {"CAGE"})
        for ref in ["U1", "U2"]:
            pins = {pin for r, pin in list(seen) + NO_CONNECT if r == ref}
            self.assertEqual(pins, {str(i) for i in range(1, 11)})
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

        # ESD array line not connected (one line unprotected).
        def esd(nets):
            nets["L1_SSRX_N"].remove(("U2", "5"))
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

# KiCad (optional: skipped without KiCad 7+) -------------------------------------------------------

HAS_KICAD_CLI = shutil.which("kicad-cli") is not None and Path("/usr/share/kicad/symbols").exists()
HAS_PCBNEW    = importlib.util.find_spec("pcbnew") is not None and Path("/usr/share/kicad/footprints").exists()

class TestSFP2USBCKiCad(unittest.TestCase):
    @unittest.skipUnless(HAS_KICAD_CLI, "KiCad (kicad-cli, symbols) not installed.")
    def test_schematic(self):
        # Generated schematic -> KiCad netlist export -> check_netlist: 0 errors/warnings.
        import gen_schematic
        with tempfile.TemporaryDirectory() as d:
            sch = Path(d) / "sfp2usbc.kicad_sch"
            sch.write_text(gen_schematic.build())
            net = Path(d) / "sfp2usbc.net"
            subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr",
                "-o", str(net), str(sch)], check=True, capture_output=True)
            errors, warnings = check(*read_kicad_netlist(net.read_text()))
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])

    @unittest.skipUnless(HAS_PCBNEW, "KiCad (pcbnew Python module, footprints) not installed.")
    def test_board(self):
        # Generated board: pads nets as netlist.py, lanes in the 90 ohm net class.
        import pcbnew
        import gen_board
        with tempfile.TemporaryDirectory() as d:
            pcb = str(Path(d) / "sfp2usbc.kicad_pcb")
            gen_board.build(pcb)
            board = pcbnew.LoadBoard(pcb)
            pads  = {(fp.GetReference(), pad.GetNumber()): pad.GetNetname()
                for fp in board.GetFootprints() for pad in fp.Pads()}
            for name, nodes in NETS.items():
                for node in nodes:
                    self.assertEqual(pads[node], f"/{name}", node)
            for node in NO_CONNECT:
                self.assertEqual(pads[node], "", node)
            for p, n in DIFF_PAIRS:
                self.assertEqual(board.FindNet(f"/{p}").GetNetClassName(), "HS_90R")
            self.assertEqual(board.GetCopperLayerCount(), 4)

if __name__ == "__main__":
    unittest.main()
