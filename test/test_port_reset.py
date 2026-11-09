#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Host port reset policy of the hardware tests (bench/usb3_soc.py USB3HostPortReset): Warm Reset
requested when U0 is not reached for the timeout, held until the WarmReset state, dropped on U0, not
requested while in U0."""

import os
import sys
import unittest

from migen import *

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench"))
from usb3_soc import USB3HostPortReset

STATES = {"Polling.LFPS": 1, "U0": 2, "WarmReset": 3}

class FakePHY:
    def __init__(self):
        self.u0             = Signal()
        self.ltssm_state    = Signal(4)
        self.ltssm_states   = STATES
        self.warm_reset_req = Signal()

class TestUSB3HostPortReset(unittest.TestCase):
    def test_port_reset(self):
        phy = FakePHY()
        dut = USB3HostPortReset(phy, sys_clk_freq=1e3, timeout=0.05) # Timeout: 50 cycles.
        req = []
        def generator():
            def state(name):
                yield phy.ltssm_state.eq(STATES[name])
                yield phy.u0.eq(name == "U0")
            # In U0: no request.
            yield from state("U0")
            for _ in range(120):
                yield
                req.append(("u0", (yield phy.warm_reset_req)))
            # Out of U0 (Polling.LFPS, partner in Compliance): request after the timeout, held.
            yield from state("Polling.LFPS")
            for _ in range(80):
                yield
                req.append(("polling", (yield phy.warm_reset_req)))
            # WarmReset entered: request dropped, then no new request before a new timeout.
            yield from state("WarmReset")
            for _ in range(10):
                yield
                req.append(("warm", (yield phy.warm_reset_req)))
            # Back in Polling, U0 reached before the timeout: no request.
            yield from state("Polling.LFPS")
            for _ in range(30):
                yield
                req.append(("polling2", (yield phy.warm_reset_req)))
            yield from state("U0")
            for _ in range(60):
                yield
                req.append(("u0_2", (yield phy.warm_reset_req)))
            self.count = (yield dut._count.status)
        run_simulation(dut, generator())
        def values(phase):
            return [v for p, v in req if p == phase]
        self.assertEqual(sum(values("u0")), 0)
        polling = values("polling")
        first = polling.index(1)
        self.assertTrue(45 <= first <= 55, first)      # After ~timeout.
        self.assertTrue(all(polling[first:]))           # Held until WarmReset.
        self.assertEqual(sum(values("warm")[2:]), 0)    # Dropped in WarmReset.
        self.assertEqual(sum(values("polling2")), 0)    # New timeout not elapsed.
        self.assertEqual(sum(values("u0_2")), 0)        # U0: never.
        self.assertEqual(self.count, 1)

if __name__ == "__main__":
    unittest.main()
