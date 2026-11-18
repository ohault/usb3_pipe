#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from types import SimpleNamespace

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from usb3_pipe.common import K
from usb3_pipe.ltssm  import U0_EXIT_CAUSES
from usb3_pipe.debug  import USB3PHYDebug, USB3LanesDebug, LanesNoiseMonitor, LanesTrainingWatchdog, USB3PHY_DEBUG_HISTORY_DEPTH

# Fake PHY/SerDes ----------------------------------------------------------------------------------

PIPE_EVENTS = ["ts_rx_ts1", "ts_rx_ts1_inv", "ts_rx_ts2", "lfps_rx_polling", "lfps_rx_ping",
    "lfps_rx_exit_u1", "lfps_rx_exit_u2", "lfps_rx_wakeup_u3", "lfps_rx_reset"]

U3 = 30 # Fake LTSSM U3 state encoding.

def fake_phy(pipe_cd=None):
    """PHY/SerDes stand-ins for USB3PHYDebug (pipe_cd: PIPE/SerDes in another clock domain, the
    PIPE events then taken from the LTSSM inputs)."""
    pipe = SimpleNamespace(**{name: Signal(name=name) for name in PIPE_EVENTS})
    phy  = SimpleNamespace(
        reset           = Signal(),
        serdes_rx_reset = Signal(),
        ltssm_state     = Signal(5),
        ltssm_states    = {"U3": U3},
        ltssm           = SimpleNamespace(u0=Signal(), recovery=Signal(), u1=Signal(), u2=Signal(),
            u3=Signal(), u0_exit_causes=Signal(len(U0_EXIT_CAUSES)),
            **{name: Signal(name=name) for name in PIPE_EVENTS}),
        pipe            = pipe,
        pipes           = [pipe],
        pipe_cd         = pipe_cd,
    )
    serdes = SimpleNamespace(
        ready       = Signal(),
        rx_idle     = Signal(),
        rx_polarity = Signal(),
        rx_errors   = Signal(),
        source      = stream.Endpoint([("data", 32), ("ctrl", 4)]),
    )
    return phy, serdes

class DUT(LiteXModule):
    def __init__(self, pipe_cd=None):
        self.phy, self.serdes = fake_phy(pipe_cd)
        self.submodules.debug = USB3PHYDebug(self.phy, self.serdes, sys_clk_freq=4e6)

# Test ---------------------------------------------------------------------------------------------

class TestUSB3PHYDebug(unittest.TestCase):
    def test_counters_history_reset(self):
        dut = DUT()
        dbg = dut.debug
        def generator():
            # Events: edges counted once, levels counted per cycle.
            yield dut.phy.pipe.ts_rx_ts1.eq(1)
            for _ in range(3):
                yield
            yield dut.phy.pipe.ts_rx_ts1.eq(0)
            yield dut.serdes.rx_errors.eq(1)
            for _ in range(5):
                yield
            yield dut.serdes.rx_errors.eq(0)
            yield dut.serdes.source.valid.eq(1)
            yield dut.serdes.source.ready.eq(1)
            yield dut.serdes.source.ctrl.eq(0b0100)
            yield dut.serdes.source.data.eq(K(28, 4) << 16)
            yield
            yield dut.serdes.source.valid.eq(0)
            yield
            yield
            self.assertEqual((yield dbg._ts1_count.status), 1)
            self.assertEqual((yield dbg._rx_errors_cycles_count.status), 5)
            self.assertEqual((yield dbg._k28_4_count.status), 1)

            # History: more transitions than the depth, read back oldest first.
            n = USB3PHY_DEBUG_HISTORY_DEPTH + 3
            for i in range(n):
                yield dut.phy.ltssm_state.eq(1 + (i % 20))
                yield
                yield
            self.assertEqual((yield dbg._history_count.status), n)
            states = []
            for i in range(USB3PHY_DEBUG_HISTORY_DEPTH):
                yield dbg._history_index.storage.eq(i)
                yield
                states.append((yield dbg._history_state.status))
            expected = [1 + (i % 20) for i in range(n)][-USB3PHY_DEBUG_HISTORY_DEPTH:]
            self.assertEqual(states, expected)

            # Status / PHY reset / clear.
            yield dbg._phy_reset.storage.eq(1)
            yield
            self.assertEqual((yield dut.phy.reset), 1)
            self.assertEqual((yield dbg._status.fields.ltssm_state), 1 + ((n - 1) % 20))
            yield dbg._clear.re.eq(1)
            yield
            yield dbg._clear.re.eq(0)
            yield
            self.assertEqual((yield dbg._ts1_count.status), 0)
            self.assertEqual((yield dbg._history_count.status), 0)

        run_simulation(dut, generator())

    def test_u0_exit_causes(self):
        dut = DUT()
        dbg = dut.debug
        ts1      = 1 << U0_EXIT_CAUSES.index("ts1")
        directed = 1 << U0_EXIT_CAUSES.index("directed")
        lanes    = 1 << U0_EXIT_CAUSES.index("lanes_deskew_lost")
        def u0_exit(causes):
            # Triggers active on the last U0 cycle, the LTSSM leaves U0 on the next one.
            yield dut.phy.ltssm.u0.eq(1)
            for _ in range(3):
                yield
            yield dut.phy.ltssm.u0_exit_causes.eq(causes)
            yield
            yield dut.phy.ltssm.u0.eq(0)
            yield dut.phy.ltssm.u0_exit_causes.eq(0)
            for _ in range(3):
                yield
        def generator():
            # Triggers outside U0 not counted.
            yield dut.phy.ltssm.u0_exit_causes.eq(ts1)
            for _ in range(3):
                yield
            yield dut.phy.ltssm.u0_exit_causes.eq(0)
            yield from u0_exit(ts1)
            yield from u0_exit(directed | lanes)
            self.assertEqual((yield dbg._u0_exit_cause.status), directed | lanes)
            self.assertEqual((yield dbg._u0_exit_ts1_count.status), 1)
            self.assertEqual((yield dbg._u0_exit_directed_count.status), 1)
            self.assertEqual((yield dbg._u0_exit_lanes_deskew_lost_count.status), 1)
            self.assertEqual((yield dbg._u0_exit_timeout_count.status), 0)
            yield dbg._clear.re.eq(1)
            yield
            yield dbg._clear.re.eq(0)
            yield
            self.assertEqual((yield dbg._u0_exit_cause.status), 0)
            self.assertEqual((yield dbg._u0_exit_ts1_count.status), 0)
        run_simulation(dut, generator())

    def test_pipe_cd_resynchronization(self):
        # PIPE/SerDes in another clock domain (pipe, twice the sys frequency): PIPE events from the
        # LTSSM inputs, SerDes levels and K28.4 pulses resynchronized, each event counted once.
        dut = DUT(pipe_cd="pipe")
        dbg = dut.debug

        def sys_generator():
            yield dut.phy.ltssm.ts_rx_ts1.eq(1)
            yield
            yield dut.phy.ltssm.ts_rx_ts1.eq(0)
            for _ in range(64):
                yield
            self.assertEqual((yield dbg._ts1_count.status), 1)
            self.assertEqual((yield dbg._rx_idle_count.status), 1)
            self.assertEqual((yield dbg._k28_4_count.status), 2)
            self.assertEqual((yield dbg._status.fields.rx_idle), 1)
            self.assertEqual((yield dbg._status.fields.serdes_ready), 1)

        def pipe_generator():
            yield dut.serdes.source.ready.eq(1)
            yield dut.serdes.ready.eq(1)
            for _ in range(4):
                yield
            yield dut.serdes.rx_idle.eq(1)
            # Two K28.4 words (one symbol each), 8 cycles apart (pulse resynchronization).
            for _ in range(2):
                yield dut.serdes.source.valid.eq(1)
                yield dut.serdes.source.data.eq(K(28, 4))
                yield dut.serdes.source.ctrl.eq(0b0001)
                yield
                yield dut.serdes.source.valid.eq(0)
                for _ in range(8):
                    yield
            for _ in range(64):
                yield

        run_simulation(dut, {"sys": [sys_generator()], "pipe": [pipe_generator()]},
            clocks={"sys": 16, "pipe": 8})

    def test_history_u3_exit(self):
        # Frozen full history, armed: the U3 exit restarts it (first entry: the state after U3).
        dut = DUT()
        dbg = dut.debug
        def read_history():
            count  = (yield dbg._history_count.status)
            states = []
            for i in range(min(count, USB3PHY_DEBUG_HISTORY_DEPTH)):
                yield dbg._history_index.storage.eq(i)
                yield
                states.append((yield dbg._history_state.status))
            return states
        def generator():
            yield dbg._history_freeze.storage.eq(1)
            for i in range(USB3PHY_DEBUG_HISTORY_DEPTH + 2):
                yield dut.phy.ltssm_state.eq(1 + (i % 20))
                yield
            self.assertEqual((yield dbg._history_count.status), USB3PHY_DEBUG_HISTORY_DEPTH)
            # Arm, enter U3 (no restart), stay, exit.
            yield dbg._history_u3_exit.storage.eq(1)
            yield dbg._history_u3_exit.re.eq(1)
            yield
            yield dbg._history_u3_exit.re.eq(0)
            for state in [U3, U3, U3, 7, 8, 9, 8]:
                yield dut.phy.ltssm_state.eq(state)
                yield
            yield
            self.assertEqual((yield from read_history()), [7, 8, 9, 8])
            # One shot: a second U3 exit does not restart the history.
            for state in [U3, 5]:
                yield dut.phy.ltssm_state.eq(state)
                yield
            yield
            self.assertEqual((yield from read_history()), [7, 8, 9, 8, U3, 5])

        run_simulation(dut, generator())

# Lanes Debug --------------------------------------------------------------------------------------

def fake_lanes_phy():
    pipes = [SimpleNamespace(**{name: Signal(name=f"lane{lane}_{name}") for name in PIPE_EVENTS})
        for lane in range(2)]
    phy = SimpleNamespace(x2=Signal(), gen2=Signal(), deskew_aligned=Signal(), lane_swap=Signal(),
        pipes=pipes)
    serdes = [SimpleNamespace(ready=Signal(), rx_idle=Signal(), rx_polarity=Signal(),
        rx_errors=Signal(), reinit=Signal()) for _ in range(2)]
    return phy, serdes

class LanesDUT(Module):
    def __init__(self):
        self.phy, self.serdes = fake_lanes_phy()
        self.submodules.debug = USB3LanesDebug(self.phy, self.serdes)

class LanesReinitDUT(Module):
    def __init__(self):
        self.phy, self.serdes = fake_lanes_phy()
        self.submodules.debug = USB3LanesDebug(self.phy, self.serdes, reinit_cycles=5)

class LanesXcvrDUT(Module):
    def __init__(self):
        self.phy, self.serdes = fake_lanes_phy()
        for s in self.serdes:
            s.lock        = Signal()
            s.bufstatus   = Signal(2)
            s.xcvr_status = [("qpll_lock", s.lock), ("tx_bufstatus", s.bufstatus)]
            s.xcvr_events = [("qpll_lock_lost", ~s.lock, 1)]
        self.submodules.debug = USB3LanesDebug(self.phy, self.serdes)

class LanesLinkDUT(Module):
    def __init__(self):
        self.phy, self.serdes = fake_lanes_phy()
        self.link = SimpleNamespace(rx_drop=Signal())
        self.submodules.debug = USB3LanesDebug(self.phy, self.serdes, link=self.link)

class TestUSB3LanesDebug(unittest.TestCase):
    def test_xcvr_status(self):
        # Per SerDes transceiver status fields and events (A7USB3SerDes xcvr_status/xcvr_events).
        dut = LanesXcvrDUT()
        dbg = dut.debug
        def generator():
            yield dut.serdes[1].lock.eq(1)
            yield dut.serdes[1].bufstatus.eq(0b10)
            yield
            yield
            self.assertEqual((yield dbg._lane0_xcvr_status.fields.qpll_lock), 0)
            self.assertEqual((yield dbg._lane1_xcvr_status.fields.qpll_lock), 1)
            self.assertEqual((yield dbg._lane1_xcvr_status.fields.tx_bufstatus), 0b10)
            yield dbg._clear.re.eq(1)
            yield
            yield dbg._clear.re.eq(0)
            for v in [0, 1, 0, 1]: # Two lock losses.
                yield dut.serdes[1].lock.eq(v)
                yield
            yield
            self.assertEqual((yield dbg._lane1_qpll_lock_lost_count.status), 2)
        run_simulation(dut, generator())

    def test_xcvr_reinit(self):
        # Transceivers re-initialization: both SerDes reinit held reinit_cycles from the write.
        dut = LanesReinitDUT()
        dbg = dut.debug
        def generator():
            trace = []
            yield dbg._xcvr_reinit.re.eq(1)
            yield
            yield dbg._xcvr_reinit.re.eq(0)
            for _ in range(8):
                yield
                trace.append(((yield dut.serdes[0].reinit), (yield dut.serdes[1].reinit)))
            self.assertEqual(trace, [(1, 1)]*5 + [(0, 0)]*3)
        run_simulation(dut, generator())

    def test_rx_overflow(self):
        # USB3PHYX2Link RX buffer: dropped entries counted (per cycle), overflow status set until a
        # clear; no rx_drop counter without a link.
        self.assertFalse(hasattr(LanesDUT().debug, "_rx_drop_count"))
        dut = LanesLinkDUT()
        dbg = dut.debug
        def generator():
            yield
            self.assertEqual((yield dbg._status.fields.rx_overflow), 0)
            yield dut.link.rx_drop.eq(1)
            for _ in range(3):
                yield
            yield dut.link.rx_drop.eq(0)
            yield
            yield
            self.assertEqual((yield dbg._rx_drop_count.status), 3)
            self.assertEqual((yield dbg._status.fields.rx_overflow), 1)
            yield dbg._clear.re.eq(1)
            yield
            yield dbg._clear.re.eq(0)
            yield
            self.assertEqual((yield dbg._rx_drop_count.status), 0)
            self.assertEqual((yield dbg._status.fields.rx_overflow), 0)
        run_simulation(dut, generator())

    def test_status_counters(self):
        dut = LanesDUT()
        dbg = dut.debug
        def generator():
            # Status.
            yield dut.phy.x2.eq(1)
            yield dut.serdes[0].ready.eq(1)
            yield dut.serdes[1].ready.eq(1)
            yield dut.serdes[1].rx_idle.eq(1)
            yield dut.serdes[1].rx_polarity.eq(1)
            yield
            fields = dbg._status.fields # (CSRs are not simulated: their fields are checked.)
            self.assertEqual((yield fields.x2),             1)
            self.assertEqual((yield fields.gen2),           0)
            self.assertEqual((yield fields.deskew_aligned), 0)
            self.assertEqual((yield fields.ready),          0b11)
            self.assertEqual((yield fields.rx_idle),        0b10)
            self.assertEqual((yield fields.rx_polarity),    0b10)
            self.assertEqual((yield fields.lane_swap),      0)
            yield dut.phy.lane_swap.eq(1)
            yield
            self.assertEqual((yield fields.lane_swap),      1)

            # Per lane events: edges counted once, levels counted per cycle.
            yield dut.phy.pipes[1].ts_rx_ts1_inv.eq(1)
            yield dut.phy.pipes[0].ts_rx_ts2.eq(1)
            yield dut.phy.deskew_aligned.eq(1)
            for _ in range(3):
                yield
            yield dut.phy.pipes[1].ts_rx_ts1_inv.eq(0)
            yield dut.phy.pipes[0].ts_rx_ts2.eq(0)
            yield dut.phy.deskew_aligned.eq(0)
            yield
            yield dut.phy.deskew_aligned.eq(1)
            yield dut.serdes[1].rx_errors.eq(1)
            for _ in range(4):
                yield
            yield dut.serdes[1].rx_errors.eq(0)
            yield
            yield
            self.assertEqual((yield dbg._lane1_ts1_inv_count.status), 1)
            self.assertEqual((yield dbg._lane0_ts1_inv_count.status), 0)
            self.assertEqual((yield dbg._lane0_ts2_count.status), 1)
            self.assertEqual((yield dbg._deskew_count.status), 2)
            self.assertEqual((yield dbg._lane1_rx_errors_cycles_count.status), 4)
            self.assertEqual((yield dbg._lane0_rx_errors_cycles_count.status), 0)

            # Clear.
            yield dbg._clear.re.eq(1)
            yield
            yield dbg._clear.re.eq(0)
            yield
            self.assertEqual((yield dbg._deskew_count.status), 0)
            self.assertEqual((yield dbg._lane1_rx_errors_cycles_count.status), 0)

        run_simulation(dut, generator())

class MonitorDUT(Module):
    def __init__(self):
        self.disparity = [Signal(32) for _ in range(2)]
        self.recovery  = Signal()
        self.hot_reset = Signal()
        self.u3        = Signal()
        self.clear     = Signal()
        self.submodules.monitor = LanesNoiseMonitor(self.disparity, self.recovery, self.u3,
            tick_cycles=2, clear=self.clear, hot_reset=self.hot_reset)

class TestLanesNoiseMonitor(unittest.TestCase):
    def run_monitor(self, windows, control, thresholds, u3=False, ratio={}):
        # windows: (lane 0 disparity errors, lane 1 disparity errors, Recovery entries) per window
        # (window_ms 4 x 2 cycles = 8 cycles); returns the windows of the reinit pulses, the last window
        # readings at each window end and the counters.
        dut = MonitorDUT()
        mon = dut.monitor
        out = {"reinits": [], "readings": []}
        state = {"last": None}
        def snapshot():
            # Last window readings at each window end (windows/holdoff counters change).
            key = ((yield mon._windows_count.status), (yield mon._window_status.fields.holdoff),
                (yield mon._reinits_count.status))
            if key != state["last"]:
                state["last"] = key
                out["readings"].append(((yield mon._window.fields.disparity0),
                    (yield mon._window.fields.disparity1), (yield mon._window_status.fields.recoveries)))
                out.setdefault("hot_resets", []).append((yield mon._window_hot_resets.status))
        def generator():
            for name, value in control.items():
                yield getattr(mon._control.fields, name).eq(value)
            for name, value in thresholds.items():
                yield getattr(mon._thresholds.fields, name).eq(value)
            for name, value in ratio.items():
                yield getattr(mon._ratio.fields, name).eq(value)
            yield mon._control.fields.window_ms.eq(4)
            yield dut.u3.eq(int(u3))
            yield
            # Align on a window end.
            while not (yield mon.reinit) and (yield mon._windows_count.status) == 0 and \
                  (yield mon._window_status.fields.holdoff) == 0:
                yield
                if (yield mon._windows_count.status) != 0:
                    break
            counts = [0, 0]
            for index, window in enumerate(windows):
                d0, d1, rec = window[:3]
                hot = window[3] if len(window) > 3 else 0
                counts[0] += d0
                counts[1] += d1
                yield dut.disparity[0].eq(counts[0])
                yield dut.disparity[1].eq(counts[1])
                for cycle in range(8):
                    yield dut.recovery.eq(int(cycle < 2*rec and cycle % 2 == 0))
                    yield dut.hot_reset.eq(int(cycle < 2*hot and cycle % 2 == 0))
                    yield
                    if (yield mon.reinit):
                        out["reinits"].append(index)
                    yield from snapshot()
            for _ in range(10):
                yield
                if (yield mon.reinit):
                    out["reinits"].append(len(windows))
                yield from snapshot()
            out["windows"] = (yield mon._windows_count.status)
            out["noisy"]   = (yield mon._noisy_count.status)
            out["count"]   = (yield mon._reinits_count.status)
            out["budget"]  = (yield mon._window_status.fields.budget)
            yield dut.clear.eq(1)
            yield
            yield dut.clear.eq(0)
            yield
            out["cleared"] = ((yield mon._windows_count.status), (yield mon._noisy_count.status),
                (yield mon._reinits_count.status))
        run_simulation(dut, generator())
        return out

    def test_disabled_measures(self):
        # Enable 0: windows measured and counted, no re-initialization.
        out = self.run_monitor([(200, 0, 0)]*4 + [(3, 7, 2)], {"enable": 0}, {"disparity": 100})
        self.assertEqual(out["reinits"], [])
        self.assertEqual(out["noisy"], 4)
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["readings"][1:6], [(200, 0, 0)]*4 + [(3, 7, 2)]) # [0]: before the first window.
        self.assertEqual(out["cleared"], (0, 0, 0))

    def test_consecutive_windows_holdoff(self):
        # 2 consecutive noisy windows (any lane) -> re-init, then 2 windows held off; an isolated
        # noisy window resets nothing.
        windows = [(200, 0, 0), (0, 0, 0), (0, 150, 0), (101, 0, 0), (500, 500, 0), (500, 500, 0),
            (0, 0, 0), (0, 300, 0), (300, 0, 0)]
        out = self.run_monitor(windows, {"enable": 1, "windows": 2, "holdoff": 2}, {"disparity": 100})
        self.assertEqual(out["reinits"], [3, 8])
        self.assertEqual(out["count"], 2)
        # Windows 4/5 held off after the first re-init (on window 3), second re-init on window 8.
        self.assertEqual(out["windows"], len(windows) + 1 - 2) # + the window after the last one.
        self.assertEqual(out["noisy"], 5)

    def test_recoveries_threshold_budget_u3(self):
        # Recovery entries criterion, the budget (1 re-init) and no re-init in U3.
        windows = [(0, 0, 3)]*6
        out = self.run_monitor(windows, {"enable": 1, "windows": 1, "holdoff": 0, "max_reinits": 1},
            {"disparity": 0, "recoveries": 2})
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["budget"], 1)
        self.assertEqual(out["readings"][1], (0, 0, 3))
        out = self.run_monitor(windows, {"enable": 1, "windows": 1, "holdoff": 0}, {"recoveries": 2}, u3=True)
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["noisy"], 6)

    def test_disparity_per_training(self):
        # Ratio criterion alone (absolute thresholds 0): worst lane > 10 x trainings with >= 2
        # trainings (Recovery + Hot Reset entries; Recovery only without with_hot_reset).
        windows = [
            (25, 0, 2, 0),  # 25 > 20: noisy.
            (0, 39, 2, 2),  # 39 <= 40: clean.
            (50, 0, 1, 0),  # 1 training < min_trainings: clean.
            (0, 41, 2, 2),  # 41 > 40: noisy.
            (300, 0, 0, 0), # No training: clean.
        ]
        out = self.run_monitor(windows, {"enable": 0}, {"disparity": 0, "recoveries": 0},
            ratio={"disparity_per_training": 10, "min_trainings": 2, "with_hot_reset": 1})
        self.assertEqual(out["noisy"], 2)
        self.assertEqual(out["hot_resets"][1:6], [0, 2, 0, 2, 0])
        # Recovery entries only: window 1 (39 > 20) and window 3 (41 > 20) noisy too.
        out = self.run_monitor(windows, {"enable": 0}, {"disparity": 0, "recoveries": 0},
            ratio={"disparity_per_training": 10, "min_trainings": 2, "with_hot_reset": 0})
        self.assertEqual(out["noisy"], 3)
        # Disabled (reset): no noisy window.
        out = self.run_monitor(windows, {"enable": 0}, {"disparity": 0, "recoveries": 0})
        self.assertEqual(out["noisy"], 0)

if __name__ == "__main__":
    unittest.main()

# Lanes Training Watchdog --------------------------------------------------------------------------

class WatchdogDUT(LiteXModule):
    STATES = {"Rx.Detect.Quiet": 0, "Polling.LFPS": 1, "Polling.RxEQ": 2, "eSS.Inactive": 3, "U0": 4,
        "Recovery.Active": 5, "U3": 6, "WarmReset": 7}
    def __init__(self, timeout_ms):
        self.phy = SimpleNamespace(ltssm_state=Signal(4), ltssm_states=self.STATES, u0=Signal())
        self.comb += self.phy.u0.eq(self.phy.ltssm_state == self.STATES["U0"])
        self.watchdog = LanesTrainingWatchdog(self.phy, tick_cycles=4, timeout_ms=timeout_ms,
            u0_stable_ms=5, warm_delay_ms=2, warm_max_ms=4)

class TestLanesTrainingWatchdog(unittest.TestCase):
    def run_watchdog(self, states, timeout_ms=5, warm_ack=False):
        # states: (LTSSM state name, cycles); returns the cycles of the reinit pulses, of the Warm Reset
        # request starts and the count. warm_ack: the LTSSM enters WarmReset on the request (one cycle).
        dut = WatchdogDUT(timeout_ms)
        out = {"reinits": [], "warm": [], "warm_cycles": 0}
        def generator():
            cycle, req_d = 0, 0
            for name, cycles in states:
                for _ in range(cycles):
                    req = (yield dut.watchdog.warm_reset_req)
                    state = "WarmReset" if (warm_ack and req) else name
                    yield dut.phy.ltssm_state.eq(dut.STATES[state])
                    yield
                    if (yield dut.watchdog.reinit):
                        out["reinits"].append(cycle)
                    if req and not req_d:
                        out["warm"].append(cycle)
                    out["warm_cycles"] += req
                    req_d = req
                    cycle += 1
            out["count"] = (yield dut.watchdog._count.status)
        run_simulation(dut, generator())
        return out

    def test_training_without_u0(self):
        # Training loop (Polling/eSS.Inactive, Rx.Detect visits not counted, brief U0 visits not
        # clearing the training time) without a stable U0: a re-initialization per 5ms (20 cycles) of
        # training time, each followed by a Warm Reset request ~2ms (8 cycles) later.
        loop = [("Polling.LFPS", 8), ("Polling.RxEQ", 8), ("U0", 2), ("Polling.RxEQ", 4), ("eSS.Inactive", 4),
            ("Rx.Detect.Quiet", 30)]
        out = self.run_watchdog(loop*12, warm_ack=True)
        self.assertGreaterEqual(out["count"], 3)
        self.assertEqual(len(out["reinits"]), out["count"])
        self.assertEqual(len(out["warm"]), out["count"])
        for r, w in zip(out["reinits"], out["warm"]):
            self.assertTrue(4 <= w - r <= 12, (r, w))

    def test_warm_request_bounded(self):
        # No WarmReset entry: the request is held warm_max_ms (4ms, 16 cycles) at most.
        out = self.run_watchdog([("Polling.RxEQ", 60)])
        self.assertEqual(out["count"], 1)
        self.assertTrue(12 <= out["warm_cycles"] <= 20, out["warm_cycles"])

    def test_u0_reached(self):
        # Stable U0 reached within the timeout: no re-initialization (the training time restarts).
        out = self.run_watchdog([("Polling.RxEQ", 16), ("U0", 40), ("Recovery.Active", 16), ("U0", 40)]*3)
        self.assertEqual(out["count"], 0)

    def test_no_partner_disabled(self):
        # Rx.Detect only (no link partner), Polling.LFPS (a partner reloading its bitstream, t24), U3:
        # no re-initialization; timeout 0: disabled.
        self.assertEqual(self.run_watchdog([("Rx.Detect.Quiet", 400), ("Polling.LFPS", 400),
            ("U3", 400)])["count"], 0)
        out = self.run_watchdog([("Polling.RxEQ", 400)], timeout_ms=0)
        self.assertEqual((out["count"], out["warm_cycles"]), (0, 0))
