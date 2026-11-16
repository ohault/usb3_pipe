#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from migen import *

from litex.gen import *

from usb3_pipe.gw5    import gw5_usb3_rate_writes, gw5_usb3_csr_config, gw5_usb3_csr_config_x2
from usb3_pipe.serdes import GW5RateSequencer, GW5TXElectricalIdle, GW5UPARPort, GW5UPARArbiter, GW5CDRToggle

class FakeUPAR(LiteXModule):
    """GTR12UPAR user port model: a write takes 3 cycles once granted."""
    def __init__(self):
        self.addr   = Signal(24)
        self.wrdata = Signal(32)
        self.we     = Signal()
        self.re     = Signal()
        self.done   = Signal()
        self.writes = []
        self.busy   = Signal(2)
        self.sync += [
            self.done.eq(0),
            If(self.busy != 0,
                self.busy.eq(self.busy - 1),
                If(self.busy == 1, self.done.eq(1)),
            ).Elif(self.we & ~self.done,
                self.busy.eq(3),
            )
        ]

class TestGW5RateSequencer(unittest.TestCase):
    def test_rate_writes(self):
        for lane in [0, 1]:
            writes = gw5_usb3_rate_writes(lane)
            # Rate dependent registers: CDR, QPLL1, TX lanes clock tree x2, TX/RX gear FIFOs.
            self.assertEqual(len(writes), 6)

    def test_sequencer(self):
        writes = gw5_usb3_rate_writes(0)
        upar   = FakeUPAR()
        dut    = GW5RateSequencer(upar, writes, settle_cycles=8)
        dut.submodules += upar
        log    = []
        def generator():
            for rate in [1, 0]:
                yield dut.rate_10g.eq(rate)
                for _ in range(8):
                    yield
                self.assertEqual((yield dut.busy), 1)
                for _ in range(200):
                    if (yield upar.we) and not (yield upar.busy) and not (yield upar.done):
                        log.append((rate, (yield upar.addr), (yield upar.wrdata)))
                    if not (yield dut.busy):
                        break
                    yield
                self.assertEqual((yield dut.busy), 0)
        run_simulation(dut, generator())
        expected = [(1, a, v10) for a, v5, v10 in writes] + [(0, a, v5) for a, v5, v10 in writes]
        self.assertEqual(log, expected)

class TestGW5CDRToggle(unittest.TestCase):
    def test_toggle_with_tx_idle(self):
        # Lane CDR re-acquisition (signal detect bit 16 set then cleared) on a RX reset rising edge,
        # sharing the UPAR with the lane TX Electrical Idle writer (arbiter), a request during the
        # writes served after them: both toggles complete, the TX idle writes still served.
        upar   = FakeUPAR()
        ports  = [GW5UPARPort(), GW5UPARPort()]
        idle   = GW5TXElectricalIdle(ports[0], 0x9003a4, 1, 7)
        toggle = GW5CDRToggle(ports[1], 0x90053e, 0x10000, 0)
        dut    = GW5UPARArbiter(ports, upar)
        dut.submodules += upar, idle, toggle
        log    = []
        def generator():
            for step in range(120):
                if step == 5:
                    yield toggle.request.eq(1)
                    yield idle.idle.eq(0)
                if step == 8:
                    yield toggle.request.eq(0)
                if step == 12:
                    yield toggle.request.eq(1) # During the first toggle writes.
                if (yield upar.we) and not (yield upar.busy) and not (yield upar.done):
                    log.append(((yield upar.addr), (yield upar.wrdata)))
                yield
            self.assertEqual((yield toggle.count), 2)
        run_simulation(dut, generator())
        toggles = [w for w in log if w[0] == 0x90053e]
        self.assertEqual(toggles, [(0x90053e, 0x10000), (0x90053e, 0), (0x90053e, 0x10000), (0x90053e, 0)])
        self.assertIn((0x9003a4, 7), log)

class TestGW5CSRMerge(unittest.TestCase):
    def test_x2_merge(self):
        # Lanes 0/1 configuration merged from the single lane ones: every write of each kept, except
        # the other lane's 0x55 reset transient writes and the quad registers merged (cfg_quad_cmn,
        # FPCS clock root preload: ORed).
        import re
        def writes(csr):
            return re.findall(r"upar_write_driver\((0x[0-9a-fA-F]+),(0x[0-9a-fA-F]+)\)", csr)
        x2  = writes(gw5_usb3_csr_config_x2())
        ln0 = writes(gw5_usb3_csr_config(0, "5G", "100M"))
        ln1 = writes(gw5_usb3_csr_config(1, "5G", "100M"))
        merged = {(int(a, 16), int(v, 16)) for a, v in x2}
        dropped = {(0x900400, 0x55), (0x900402, 0x550000), (0x900b91, 0xF100), (0x900b91, 0xF300),
            (0x908870, 0x0), (0x908870, 0x10000)}
        for a, v in ln0 + ln1:
            w = (int(a, 16), int(v, 16))
            self.assertTrue(w in merged or w in dropped, f"missing write {a}={v}")
        self.assertIn((0x900b91, 0xF300), merged)
        self.assertIn((0x908870, 0x10000), merged)
        self.assertNotIn((0x900400, 0x55), merged)
        # Both lanes enabled (cfg_ln writes of lanes 0 and 1), lanes 2/3 as in both configurations.
        for addr in [0x9003a6, 0x9005a6, 0x909070, 0x909270]:
            self.assertIn(addr, {a for a, _ in merged})

class TestGW5UPARArbiter(unittest.TestCase):
    def test_two_lanes_tx_idle(self):
        # Two lanes TX Electrical Idle writers on one UPAR (Gen 1x2 quad): toggled together, every
        # requested value written once per lane (the arbiter serving one at a time), last values
        # written.
        upar  = FakeUPAR()
        ports = [GW5UPARPort(), GW5UPARPort()]
        idles = [GW5TXElectricalIdle(port, 0x100 + 0x200*n, 1, 7) for n, port in enumerate(ports)]
        dut   = GW5UPARArbiter(ports, upar)
        dut.submodules += upar, *idles
        log   = []
        def generator():
            for value in [0, 1, 0]:
                for idle in idles:
                    yield idle.idle.eq(value)
                for _ in range(40):
                    if (yield upar.we) and not (yield upar.busy) and not (yield upar.done):
                        log.append(((yield upar.addr), (yield upar.wrdata)))
                    yield
        run_simulation(dut, generator())
        # Start (idle at reset: 1), then 0, 1, 0 on each lane, lane 0 first.
        expected = []
        for v in [1, 7, 1, 7]:
            expected += [(0x100, v), (0x300, v)]
        self.assertEqual(log, expected)

if __name__ == "__main__":
    unittest.main()
