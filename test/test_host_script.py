#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Scripted USB host of the hardware tests (bench/usb3_soc.py USB3HostScript): LUP keep-alive out of
the script runs, Hot Reset directed before each run, script started between two LUPs after the Hot
Reset, no LUP during a run, run restarted with a new Hot Reset on a U0 exit, run result held out of
U0 until disabled (one run per enable)."""

import os
import sys
import unittest
from unittest import mock

from migen import *

from litex.soc.interconnect import stream

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench"))
import usb3_soc
from usb3_soc import USB3HostScript, usb3_host_script, usb3_host_idle_script

from usb3_pipe.lanes      import link_pairs_layout
from usb3_core.host_model import OP_SEND, link_command, LUP, HostScript

class FakeLink:
    def __init__(self):
        self.sink   = stream.Endpoint(link_pairs_layout())
        self.source = stream.Endpoint(link_pairs_layout())
        self.u0            = Signal()
        self.hot_reset_req = Signal()
        self.hot_reset     = Signal()
        self.polling_idle  = Signal()
        self.x2            = Signal(reset=1) # Gen 1x2 negotiated: SuperSpeedPlus script.

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
            yield dut._control.fields.idle_init.eq(0) # Test runs only.
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

    def test_result_held_until_disabled(self):
        # Short script (sends only: done without a Device), then a U0 exit after the run: no new
        # Hot Reset/run until disabled, done status held.
        def short_script(ssp=True):
            script = HostScript(ssp=ssp)
            script.send(link_command(LUP()))
            script.end()
            return script
        link = FakeLink()
        with mock.patch.object(usb3_soc, "usb3_host_script", short_script):
            dut = USB3HostScript(link, sys_clk_freq=10e6)
        resets = []
        done   = {}
        def generator():
            yield link.sink.ready.eq(1)
            yield dut._control.fields.idle_init.eq(0) # Test runs only.
            yield link.u0.eq(1)
            req_d     = 0
            hot_reset = None
            for cycle in range(600):
                if cycle == 50:
                    yield dut._control.fields.enable.eq(1)
                if cycle == 200:
                    yield link.u0.eq(0) # U0 exit after the run (Recovery).
                if cycle == 220:
                    yield link.u0.eq(1)
                if cycle == 400:
                    yield dut._control.fields.enable.eq(0)
                if cycle == 420:
                    yield dut._control.fields.enable.eq(1) # Next run.
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
                        hot_reset = None
                req_d = req
                yield
                if cycle in [190, 300, 390, 590]:
                    done[cycle] = (yield dut._status.fields.done)
            self.passes = (yield dut._passes.status)
        run_simulation(dut, generator())
        self.assertEqual(done[190], 1)                 # Run done.
        self.assertEqual((done[300], done[390]), (1, 1)) # Held after the U0 exit, no new run.
        self.assertEqual(len(resets), 2)               # One Hot Reset per enable.
        self.assertTrue(50 <= resets[0] < 60 and 420 <= resets[1] < 430)
        self.assertEqual(done[590], 1)                 # Second run done.
        self.assertEqual(self.passes, 2)

    def test_script_of_the_negotiated_link(self):
        # Both scripts in the ROM: SuperSpeedPlus at Gen 1x2, SuperSpeed at Gen 1x1 (first sends of
        # the run, after the Hot Reset).
        for x2 in [1, 0]:
            with self.subTest(x2=x2):
                link = FakeLink()
                dut  = USB3HostScript(link, sys_clk_freq=10e6)
                expected = [s[1] for s in usb3_host_script(ssp=bool(x2)).steps if s[0] == OP_SEND][:6]
                tx = []
                def generator():
                    yield link.sink.ready.eq(1)
                    yield dut._control.fields.idle_init.eq(0) # Test runs only.
                    yield link.u0.eq(1)
                    yield link.x2.eq(x2)
                    hot_reset = None
                    for cycle in range(400):
                        if cycle == 20:
                            yield dut._control.fields.enable.eq(1)
                        if (yield link.hot_reset_req) and hot_reset is None:
                            hot_reset = cycle
                            yield link.u0.eq(0)
                        if hot_reset is not None:
                            yield link.hot_reset.eq(cycle == hot_reset + 5)
                            if cycle == hot_reset + 20:
                                yield link.u0.eq(1)
                        yield
                        if (yield link.sink.valid) and hot_reset is not None and cycle > hot_reset + 20:
                            tx.append((yield link.sink.data) & 0xffffffff)
                    self.ssp_csr = (yield dut._ssp.status)
                run_simulation(dut, generator())
                # The run first sends (LUP keep-alives only before/after the run).
                starts = [i for i in range(len(tx)) if tx[i:i + len(expected)] == expected]
                self.assertTrue(starts, f"x2={x2}: script first sends not found")
                self.assertEqual(self.ssp_csr, x2)

    def test_idle_init(self):
        # Out of the test runs (enable = 0), on the U0 entry: a Hot Reset then the idle link
        # initialization (first sends: Advertisements), not counted as a run; a test run enabled
        # later supersedes it (new Hot Reset, the test script, counted).
        link = FakeLink()
        dut  = USB3HostScript(link, sys_clk_freq=10e6, idle_delay=2e-6) # Idle init after 20 cycles.
        idle_first = [s[1] for s in usb3_host_idle_script(ssp=True).steps if s[0] == OP_SEND][:4]
        test_first = [s[1] for s in usb3_host_script(ssp=True).steps if s[0] == OP_SEND][:4]
        tx      = []
        resets  = []
        def generator():
            yield link.sink.ready.eq(1)
            yield link.u0.eq(1)
            req_d, hot_reset = 0, None
            for cycle in range(900):
                if cycle == 450:
                    yield dut._control.fields.enable.eq(1)
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
                        hot_reset = None
                req_d = req
                yield
                if (yield link.sink.valid):
                    tx.append((cycle, (yield link.sink.data) & 0xffffffff))
            self.resets_csr = (yield dut._resets.status)
            self.passes     = (yield dut._passes.status)
            self.status     = (yield dut._status.status)
        run_simulation(dut, generator())
        def contains(words, seq):
            return any(words[i:i + len(seq)] == seq for i in range(len(words)))
        idle_tx = [w for c, w in tx if c < 450]
        test_tx = [w for c, w in tx if c > 450]
        self.assertTrue(resets and 20 <= resets[0] < 60)    # Idle: Hot Reset after idle_delay.
        self.assertTrue(contains(idle_tx, idle_first))      # Idle link initialization.
        self.assertTrue(any(c > 450 for c in resets))       # Test run: a new Hot Reset.
        self.assertTrue(contains(test_tx, test_first))      # Test script.
        self.assertEqual(self.resets_csr, 1)                # Only the test run Hot Reset counted.

if __name__ == "__main__":
    unittest.main()
