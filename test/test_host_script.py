#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Scripted USB host of the hardware tests (bench/usb3_soc.py USB3HostScript): LUP keep-alive out of
the script runs, script started between two LUPs, no LUP during a run."""

import os
import sys
import unittest

from migen import *

from litex.soc.interconnect import stream

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench"))
from usb3_soc import USB3HostScript, usb3_host_script

from usb3_pipe.lanes      import link_pairs_layout
from usb3_core.host_model import OP_SEND, link_command, LUP

class FakeLink:
    def __init__(self):
        self.sink   = stream.Endpoint(link_pairs_layout())
        self.source = stream.Endpoint(link_pairs_layout())
        self.u0     = Signal()

class TestUSB3HostScript(unittest.TestCase):
    def test_lup_keep_alive_and_script(self):
        link = FakeLink()
        dut  = USB3HostScript(link, sys_clk_freq=10e6) # LUP every 10us = 100 cycles.
        lup  = [w for w, c in link_command(LUP())]
        first_sends = [s[1] for s in usb3_host_script().steps if s[0] == OP_SEND][:6]
        tx = [] # (cycle, word, first, last)
        def generator():
            yield link.sink.ready.eq(1)
            yield link.u0.eq(1)
            for cycle in range(700):
                if cycle == 250:
                    yield dut._control.fields.enable.eq(1) # (CSRs not simulated: fields driven.)
                if cycle == 450:
                    yield dut._control.fields.enable.eq(0)
                yield
                if (yield link.sink.valid):
                    tx.append((cycle, (yield link.sink.data) & 0xffffffff,
                        (yield link.sink.first), (yield link.sink.last)))
        run_simulation(dut, generator())
        idle   = [t for t in tx if t[0] < 250]
        script = [t for t in tx if 252 <= t[0] < 450]
        after  = [t for t in tx if t[0] >= 455]
        # Idle in U0: LUPs (2 words, first/last) every ~10us.
        self.assertGreaterEqual(len(idle), 4)
        self.assertEqual([t[1] for t in idle[:2]], lup)
        self.assertEqual((idle[0][2], idle[1][3]), (1, 1))
        self.assertLess(idle[2][0] - idle[0][0], 110)
        # Script running: its first packets (Advertisements), no LUP.
        self.assertEqual([t[1] for t in script[:6]], first_sends)
        self.assertNotIn(lup[1], [t[1] for t in script])
        # Script disabled: LUPs again.
        self.assertIn(lup[1], [t[1] for t in after])

if __name__ == "__main__":
    unittest.main()
