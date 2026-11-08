#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Scripted USB host of the hardware tests (bench/usb3_soc.py USB3HostScript): LUP keep-alive out of
the script runs, Hot Reset directed before each run, script started between two LUPs after the Hot
Reset, no LUP during a run, run restarted with a new Hot Reset on a U0 exit."""

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
        self.u0            = Signal()
        self.hot_reset_req = Signal()
        self.hot_reset     = Signal()
        self.polling_idle  = Signal()

class TestUSB3HostScript(unittest.TestCase):
    def test_lup_keep_alive_hot_reset_and_script(self):
        link = FakeLink()
        dut  = USB3HostScript(link, sys_clk_freq=10e6) # LUP every 10us = 100 cycles.
        lup  = [w for w, c in link_command(LUP())]
        first_sends = [s[1] for s in usb3_host_script().steps if s[0] == OP_SEND][:6]
        tx      = [] # (cycle, word, first, last)
        resets  = [] # Cycles of the Hot Reset requests (rising edges).
        u0_back = [] # Cycles of the U0 returns after a Hot Reset.
        def generator():
            yield link.sink.ready.eq(1)
            yield link.u0.eq(1)
            req_d     = 0
            hot_reset = None # Cycle of the Hot Reset request being served by the fake PHY.
            for cycle in range(900):
                if cycle == 250:
                    yield dut._control.fields.enable.eq(1) # (CSRs not simulated: fields driven.)
                if cycle == 500:
                    yield link.u0.eq(0) # U0 exit during the run (Recovery).
                if cycle == 510:
                    yield link.u0.eq(1)
                if cycle == 750:
                    yield dut._control.fields.enable.eq(0)
                # Fake PHY: Hot Reset (out of U0, hot_reset pulse, U0 again 20 cycles later).
                req = (yield link.hot_reset_req)
                if req and not req_d:
                    resets.append(cycle)
                if req and hot_reset is None:
                    hot_reset = cycle
                    yield link.u0.eq(0)
                if hot_reset is not None:
                    yield link.hot_reset.eq(cycle == hot_reset + 5)
                    if cycle == hot_reset + 20:
                        yield link.u0.eq(1)
                        u0_back.append(cycle)
                        hot_reset = None
                req_d = req
                yield
                if (yield link.sink.valid):
                    tx.append((cycle, (yield link.sink.data) & 0xffffffff,
                        (yield link.sink.first), (yield link.sink.last)))
            self.resets_csr = (yield dut._resets.status)
        run_simulation(dut, generator())
        idle   = [t for t in tx if t[0] < 250]
        run0   = [t for t in tx if u0_back[0] <= t[0] < 500]
        run1   = [t for t in tx if u0_back[1] <= t[0] < 750]
        after  = [t for t in tx if t[0] >= 755]
        # Idle in U0: LUPs (2 words, first/last) every ~10us, no Hot Reset.
        self.assertGreaterEqual(len(idle), 4)
        self.assertEqual([t[1] for t in idle[:2]], lup)
        self.assertEqual((idle[0][2], idle[1][3]), (1, 1))
        self.assertLess(idle[2][0] - idle[0][0], 110)
        # Enabled: a Hot Reset first, nothing sent until U0 again, then the script (no LUP).
        self.assertEqual(len(resets), 2)
        self.assertTrue(250 <= resets[0] < 260)
        self.assertEqual([t for t in tx if resets[0] < t[0] < u0_back[0]], [])
        self.assertEqual([t[1] for t in run0[:6]], first_sends)
        self.assertNotIn(lup[1], [t[1] for t in run0])
        # U0 exit during the run: a new Hot Reset, then the script restarted from its beginning.
        self.assertTrue(510 <= resets[1] < 520)
        self.assertEqual([t[1] for t in run1[:6]], first_sends)
        self.assertNotIn(lup[1], [t[1] for t in run1])
        self.assertEqual(self.resets_csr, 2)
        # Script disabled: LUPs again.
        self.assertIn(lup[1], [t[1] for t in after])

if __name__ == "__main__":
    unittest.main()
