#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""USB3 PHY debug (doc/manual: Debugging): LTSSM state history and counters (USB3PHYDebug), Gen 1x2
lanes status/counters (USB3LanesDebug), RX errors (USB3RXErrorsDebug), SerDes controls and
measurements (USB3SerDesDebug), LiteScope probes groups (usb3_analyzer_groups).
"""

from migen import *
from migen.genlib.cdc import BusSynchronizer, GrayCounter, MultiReg, PulseSynchronizer

from litex.gen import *

from litex.soc.interconnect.csr import *

from litex.soc.cores.freqmeter import FreqMeter

from liteiclink.serdes.common import DRPControl

from usb3_pipe.common   import K
from usb3_pipe.datapath import GEN2_RX_COUNTERS

# Helpers ------------------------------------------------------------------------------------------

# LTSSM states receiving Symbols (RX 8b/10b errors counted: not Rx.Detect/Polling.LFPS/U1-U3).
LTSSM_SYMBOL_STATES = ["Polling.RxEQ", "Polling.Active", "Polling.Configuration", "Polling.Idle", "U0",
    "Recovery.Active", "Recovery.Configuration", "Recovery.Idle", "HotReset.Active", "HotReset.Exit"]

def ltssm_symbols(phy):
    """LTSSM in a state receiving Symbols (expression, phy.ltssm_state clock domain)."""
    states = phy.ltssm_states
    return Reduce("OR", [phy.ltssm_state == states[state] for state in LTSSM_SYMBOL_STATES if state in states])

def gray_decode(gray):
    """Gray to binary decoding (combinatorial)."""
    n = len(gray)
    return Cat(*[Reduce("XOR", [gray[j] for j in range(i, n)]) for i in range(n)])

# USB3 PHY Debug -----------------------------------------------------------------------------------

USB3PHY_DEBUG_HISTORY_DEPTH = 32

class USB3PHYDebug(LiteXModule):
    """USB3 PHY Debug (CSRs, hardware bring-up).

    Lightweight always-on observability of a USB3PHY, polled from the host (UARTBone/JTAGBone):
    - LTSSM state, SerDes ready.
    - LTSSM state history (last `USB3PHY_DEBUG_HISTORY_DEPTH` transitions, or the first ones after a
      clear with history_freeze, state + us timestamp).
    - Event counters (TS/LFPS detections, RX errors/idle, K28.4 substitutions, U0/Recovery/U1/U2/U3
      entries).
    - PHY reset (re-runs link training from Polling) and counters/history clear.
    - SerDes RX re-initialization (transceiver RX reset sequence).

    With pipe_cd (PIPE and SerDes in another clock domain): the PIPE events are taken from the
    LTSSM inputs (resynchronized by the PHY), the SerDes levels/pulses are resynchronized here
    (rx_errors_cycles then counts sys cycles).
    """
    def __init__(self, phy, serdes, sys_clk_freq):
        ltssm  = phy.ltssm
        pipe   = phy.pipes[0] # Configuration Lane (Lane 0) with 2 lanes.
        cd     = phy.pipe_cd
        events = pipe if cd is None else ltssm

        def level(s):
            if cd is None:
                return s
            s_sys = Signal()
            self.specials += MultiReg(s, s_sys)
            return s_sys

        def pulse(s):
            if cd is None:
                return s
            s_r  = Signal()
            sync = getattr(self.sync, cd)
            sync += s_r.eq(s)
            ps = PulseSynchronizer(cd, "sys")
            self.submodules += ps
            self.comb += ps.i.eq(s_r)
            return ps.o

        self._phy_reset       = CSRStorage(description="PHY (PIPE + LTSSM) reset (level).")
        self._serdes_rx_reset = CSRStorage(description="SerDes RX re-initialization (level).")
        self._clear           = CSR() # Clear counters and history (write).
        self._status          = CSRStatus(fields=[
            CSRField("ltssm_state",  size=8, description="LTSSM state (get_ltssm_states)."),
            CSRField("serdes_ready", size=1, description="SerDes ready."),
            CSRField("rx_idle",      size=1, description="SerDes RX electrical idle."),
            CSRField("rx_polarity",  size=1, description="SerDes RX polarity inverted."),
        ])
        self._timestamp       = CSRStatus(32, description="Timestamp (us).")

        # # #

        self.comb += phy.serdes_rx_reset.eq(self._serdes_rx_reset.storage)

        clear = Signal()
        self.comb += [
            clear.eq(self._clear.re),
            phy.reset.eq(self._phy_reset.storage),
            self._status.fields.ltssm_state.eq(phy.ltssm_state),
            self._status.fields.serdes_ready.eq(level(serdes.ready)),
            self._status.fields.rx_idle.eq(level(serdes.rx_idle)),
            self._status.fields.rx_polarity.eq(level(serdes.rx_polarity)),
        ]

        # Timestamp (us).
        timestamp = self._timestamp.status
        prescaler = Signal(max=int(sys_clk_freq/1e6))
        self.sync += [
            prescaler.eq(prescaler + 1),
            If(prescaler == (int(sys_clk_freq/1e6) - 1),
                prescaler.eq(0),
                timestamp.eq(timestamp + 1),
            )
        ]

        # LTSSM State History.
        depth = USB3PHY_DEBUG_HISTORY_DEPTH
        self._history_count  = CSRStatus(32, description="Number of LTSSM state transitions.")
        self._history_index  = CSRStorage(log2_int(depth),
            description="History entry to read (0 = oldest).")
        self._history_state  = CSRStatus(8,  description="History entry state.")
        self._history_time   = CSRStatus(32, description="History entry timestamp (us).")
        self._history_freeze = CSRStorage(
            description="Keep the first transitions after a clear (else the last ones).")
        self._history_u3_exit = CSRStorage(
            description="Write 1: restart the history on the next U3 exit (with history_freeze: "
            "the first transitions after the U3 exit are kept).")
        history_count = self._history_count.status
        history       = Memory(8 + 32, depth)
        history_wr    = history.get_port(write_capable=True)
        history_rd    = history.get_port(async_read=True)
        self.specials += history, history_wr, history_rd
        state   = Signal(8)
        state_d = Signal(8)
        self.comb += state.eq(phy.ltssm_state)
        self.sync += state_d.eq(state)

        # U3 exit restart (one shot): the transition out of U3 is written as the first entry.
        u3_exit_armed = Signal()
        u3_exit       = Signal()
        self.comb += u3_exit.eq(u3_exit_armed & (state_d == phy.ltssm_states["U3"]) &
            (state != state_d))
        self.sync += If(self._history_u3_exit.re,
            u3_exit_armed.eq(self._history_u3_exit.storage)
        ).Elif(u3_exit,
            u3_exit_armed.eq(0)
        )

        self.comb += [
            history_wr.adr.eq(Mux(u3_exit, 0, history_count)),
            history_wr.dat_w.eq(Cat(state, timestamp)),
            history_wr.we.eq((state != state_d) & (u3_exit |
                ~(self._history_freeze.storage & (history_count >= depth)))),
            # Read relative to the oldest entry still in memory.
            If(history_count > depth,
                history_rd.adr.eq(history_count + self._history_index.storage)
            ).Else(
                history_rd.adr.eq(self._history_index.storage)
            ),
            self._history_state.status.eq(history_rd.dat_r[:8]),
            self._history_time.status.eq(history_rd.dat_r[8:]),
        ]
        self.sync += If(clear,
            history_count.eq(0)
        ).Elif(u3_exit,
            history_count.eq(1)
        ).Elif(history_wr.we,
            history_count.eq(history_count + 1)
        )

        # Event Counters.
        k28_4 = Signal()
        self.comb += k28_4.eq(serdes.source.valid & serdes.source.ready & Reduce("OR", [
            serdes.source.ctrl[i] & (serdes.source.data[8*i:8*(i+1)] == K(28, 4))
            for i in range(4)]))
        events = [
            # Name,               Signal,                     Edge (1) or Level (0).
            ("ts1",               events.ts_rx_ts1,           1),
            ("ts1_inv",           events.ts_rx_ts1_inv,       1),
            ("ts2",               events.ts_rx_ts2,           1),
            ("lfps_polling",      events.lfps_rx_polling,     1),
            ("lfps_ping",         events.lfps_rx_ping,        1),
            ("lfps_exit_u1",      events.lfps_rx_exit_u1,     1),
            ("lfps_exit_u2",      events.lfps_rx_exit_u2,     1),
            ("lfps_wakeup_u3",    events.lfps_rx_wakeup_u3,   1),
            ("lfps_reset",        events.lfps_rx_reset,       1),
            ("rx_idle",           level(serdes.rx_idle),      1),
            ("rx_errors_cycles",  level(serdes.rx_errors),    0),
            ("k28_4",             pulse(k28_4),               0),
            ("u0",                ltssm.u0,                   1),
            ("recovery",          ltssm.recovery,             1),
            ("u1",                ltssm.u1,                   1),
            ("u2",                ltssm.u2,                   1),
            ("u3",                ltssm.u3,                   1),
        ]
        for name, signal, edge in events:
            csr = CSRStatus(32, name=f"{name}_count",
                description=f"{name} {'events' if edge else 'cycles'} count (saturating).")
            setattr(self, f"_{name}_count", csr)
            signal_d = Signal()
            self.sync += signal_d.eq(signal)
            event = (signal & ~signal_d) if edge else signal
            self.sync += If(clear,
                csr.status.eq(0)
            ).Elif(event & (csr.status != (2**32 - 1)),
                csr.status.eq(csr.status + 1)
            )

        # U0 exits: triggers active on the last U0 cycle (LTSSM u0_exit_causes, registered: the
        # last cycle seen on the U0 exit), latched in u0_exit_cause and counted per trigger
        # (16-bit saturating). The trigger of a Recovery: which side starts it (TS1 = the partner in
        # Recovery, directed = own Link Layer, lanes_deskew_lost = own Gen 1x2 lanes).
        from usb3_pipe.ltssm import U0_EXIT_CAUSES
        if not hasattr(ltssm, "u0_exit_causes"):
            return
        causes   = Signal(len(U0_EXIT_CAUSES))
        u0_d     = Signal()
        self._u0_exit_cause = CSRStatus(len(U0_EXIT_CAUSES),
            description="Triggers of the last U0 exit (bits: " + ", ".join(U0_EXIT_CAUSES) + ").")
        self.sync += [
            u0_d.eq(ltssm.u0),
            If(ltssm.u0, causes.eq(ltssm.u0_exit_causes)),
            If(clear,
                self._u0_exit_cause.status.eq(0)
            ).Elif(u0_d & ~ltssm.u0,
                self._u0_exit_cause.status.eq(causes)
            ),
        ]
        for i, name in enumerate(U0_EXIT_CAUSES):
            csr = CSRStatus(16, name=f"u0_exit_{name}_count",
                description=f"U0 exits with the {name} trigger active (saturating).")
            setattr(self, f"_u0_exit_{name}_count", csr)
            self.sync += If(clear,
                csr.status.eq(0)
            ).Elif(u0_d & ~ltssm.u0 & causes[i] & (csr.status != (2**16 - 1)),
                csr.status.eq(csr.status + 1)
            )

# USB3 Lanes Debug ---------------------------------------------------------------------------------

class USB3LanesDebug(LiteXModule):
    """USB3 Gen 1x2 Lanes Debug (CSRs, hardware bring-up of USB3PHY(lanes=2)), with USB3PHYDebug on
    the Configuration Lane (Lane 0):
    - Status: negotiated x2/gen2, lanes deskewed/swapped, per lane SerDes ready/RX idle/RX polarity.
    - Per lane event counters (TS1/TS1 inverted/TS2 detections, RX errors cycles) and deskew
      acquisitions; per lane RX 8b/10b errors by type (decode, running disparity, and both on the
      Symbol just before a COM: the first COM of an Ordered Set received with an error).
    - With link (USB3PHYX2Link): RX buffer overflow status (since the last clear) and dropped
      entries counter (Gen 1x2 RX: the Link Layer did not consume the words fast enough).
    - Transceivers re-initialization (xcvr_reinit, write): both SerDes TX and RX reset sequences
      restarted together after reinit_cycles, with the Quad PLL of a SerDes resetting its own PLL
      (Acorn Gen 1x2: the Lane 0 GTP Quad PLL, shared by Lane 1): a runtime equivalent of the
      transceivers initialization at the bitstream load (the link retrains or falls back to
      Rx.Detect, then trains again).
    - With monitor_tick_cycles (sys cycles per ms) and the per lane RX error counters: lanes noise
      monitor (LanesNoiseMonitor, monitor_*), transceivers re-initialization on a sustained RX
      disparity errors/Recovery rate.
    - With monitor_tick_cycles and training_watchdog_ms: training watchdog (LanesTrainingWatchdog,
      watchdog_timeout/count CSRs), transceivers re-initialization after training_watchdog_ms of link
      training without U0 (0: disabled).
    """
    def __init__(self, phy, serdes, link=None, reinit_cycles=1024, monitor_tick_cycles=None,
        with_counters=True, training_watchdog_ms=None, with_cd_counters=False):
        # with_counters=False: status/control/re-initialization only, no event/RX errors counters
        # nor noise monitor (lean builds: timings on slow fabrics). With a PHY lanes logic in its
        # pipe_cd: status resynchronized to sys, re-initialization to pipe_cd, no counters.
        assert len(serdes) == 2
        cd = getattr(phy, "pipe_cd", None)
        # pipe_cd with with_cd_counters: the lanes events counted in pipe_cd (registered, wrapping,
        # through BusSynchronizers, cleared by a snapshot in sys), without the LTSSM gated ones, the RX
        # errors by type and the noise monitor (opt-in: on the Tang Mega 138K Pro they took the lanes
        # clock from 125.2MHz to 100MHz, t23).
        cd_counters = with_counters and with_cd_counters and (cd is not None)
        if cd is not None:
            with_counters = False
        def level(s):
            if cd is None:
                return s
            o = Signal(len(s))
            self.specials += MultiReg(s, o)
            return o
        with_rx_drop = hasattr(link, "rx_drop")
        self._clear   = CSR() # Clear counters (write).
        self._control = CSRStorage(fields=[
            CSRField("idle_recovery", size=1, offset=0, reset=1,
                description="Recovery on a lane in electrical idle for 10us in U0 at Gen 1x2 (0: disabled)."),
            CSRField("rx_errors_reinit", size=1, offset=1, reset=1,
                description="RX re-initialization of a lane with continuous decode errors (0: disabled)."),
            CSRField("realign_recovery", size=1, offset=2, reset=1,
                description="Recovery on a lane realigned (comma realignment/RX re-initialization) in U0 at Gen 1x2 (0: disabled)."),
            CSRField("x2_enable", size=1, offset=3, reset=1,
                description="Gen 1x2 advertised in the SuperSpeedPlus Polling (0: Gen 1x1 only), from the next training (retrain), with a PHY built x2 capable."),
            CSRField("skp_recovery", size=1, offset=4, reset=1,
                description="Recovery on a lane SKP run of odd length (lane shifted by one Symbol) in U0 at Gen 1x2 (0: disabled, still counted)."),
            CSRField("com_recovery", size=1, offset=5, reset=1,
                description="Deskew cleared (Recovery in U0) on a partial COM word with the lanes deskewed and their COM words disagreeing (lane shifted at the end of a TS burst) at Gen 1x2 (0: disabled, still counted)."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("x2",             size=1, offset=0, description="Gen 1x2 negotiated (SuperSpeedPlus Polling)."),
            CSRField("gen2",           size=1, offset=1, description="Gen 2 negotiated."),
            CSRField("deskew_aligned", size=1, offset=2, description="Lanes deskewed."),
            CSRField("lane_swap",      size=1, offset=3, description="Lanes swapped (Configuration Lane on SerDes 1)."),
            CSRField("ready",          size=2, offset=4, description="SerDes ready (per lane)."),
            CSRField("rx_idle",        size=2, offset=6, description="SerDes RX idle (per lane)."),
            CSRField("rx_polarity",    size=2, offset=8, description="SerDes RX polarity (per lane)."),
            CSRField("rx_overflow",    size=1, offset=10, description="Link RX buffer overflow since the last clear (USB3PHYX2Link, 0 without)."),
        ])

        # # #

        self.comb += [
            self._status.fields.x2.eq(phy.x2),
            self._status.fields.gen2.eq(phy.gen2),
            self._status.fields.deskew_aligned.eq(level(phy.deskew_aligned)),
            self._status.fields.lane_swap.eq(level(phy.lane_swap)),
            self._status.fields.ready.eq(level(Cat(*[s.ready for s in serdes]))),
            self._status.fields.rx_idle.eq(level(Cat(*[s.rx_idle for s in serdes]))),
            self._status.fields.rx_polarity.eq(level(Cat(*[s.rx_polarity for s in serdes]))),
        ]

        # Last deskew pairing loss (USB3PHY lanes_deskew_loss, held until the next one).
        if hasattr(phy, "lanes_deskew_loss"):
            self._deskew_loss = CSRStatus(fields=[
                CSRField("clear",       size=1, offset=0, description="Pairing cleared (clear sources: bits 4-7)."),
                CSRField("overflow",    size=1, offset=1, description="Deskew FIFO overflow (lanes skewed beyond the FIFOs)."),
                CSRField("mismatch",    size=1, offset=2, description="Second marker mismatch (lanes no longer paired)."),
                CSRField("plain",       size=1, offset=3, description="Marker against a plain data word (lanes paired Ordered Sets apart)."),
                CSRField("lane_idle",   size=1, offset=4, description="Clear: lane in electrical idle (10us)."),
                CSRField("realign",     size=1, offset=5, description="Clear: lane realigned in U0 (comma realignment, RX re-initialization, odd SKP run)."),
                CSRField("debug_clear", size=1, offset=6, description="Clear: debug/simulation clear."),
                CSRField("com_slip",    size=1, offset=7, description="Clear: partial COM word, deskewed lanes disagreeing."),
            ], description="Last deskew pairing loss (held until the next one).")
            # Through the fields (a CSRStatus with fields drives its status from them: an assignment
            # of the status itself was overridden, read 0 on hardware, t41).
            deskew_loss = level(phy.lanes_deskew_loss)
            self.comb += [getattr(self._deskew_loss.fields, name).eq(deskew_loss[i])
                for i, name in enumerate(["clear", "overflow", "mismatch", "plain", "lane_idle",
                    "realign", "debug_clear", "com_slip"])]

        if hasattr(phy, "lanes_idle_recovery"):
            self.comb += phy.lanes_idle_recovery.eq(self._control.fields.idle_recovery)
        if hasattr(phy, "lanes_realign_recovery"):
            self.comb += phy.lanes_realign_recovery.eq(self._control.fields.realign_recovery)
        if hasattr(phy, "rx_errors_reinit_enable"):
            self.comb += phy.rx_errors_reinit_enable.eq(self._control.fields.rx_errors_reinit)
        if hasattr(phy, "lanes_skp_recovery"):
            self.comb += phy.lanes_skp_recovery.eq(self._control.fields.skp_recovery)
        if hasattr(phy, "lanes_com_recovery"):
            self.comb += phy.lanes_com_recovery.eq(self._control.fields.com_recovery)
        if hasattr(phy, "x2_enable"):
            self.comb += phy.x2_enable.eq(self._control.fields.x2_enable)

        # Event Counters.
        events = [("deskew", phy.deskew_aligned, 1)]
        with_triggers = hasattr(phy, "lanes_idle") # USB3PHY(lanes=2) Recovery triggers.
        if with_triggers:
            u0 = phy.ltssm.u0
            events += [
                # U0 exits requested by the lanes (Recovery): deskew lost, lane in electrical idle.
                ("deskew_lost_u0", u0 & phy.lanes_deskew_lost, 1),
                ("lane_idle_u0",   u0 & phy.lanes_idle,        1),
                ("realign_u0",     phy.lanes_realign,          0),
                # Lane shifted by its SKP removal in U0 (odd SKP run), counted even when its
                # Recovery is disabled (skp_recovery).
                ("skp_odd_u0",     phy.lanes_skp_odd,          0),
                # Lane shifted since the pairing (partial COM word, lanes deskewed and disagreeing), any state.
                ("com_slip",       phy.lanes_com_slip,         0),
            ]
        if with_rx_drop:
            events += [("rx_drop", link.rx_drop, 0)] # Dropped RX buffer entries.
        for lane, (pipe, s) in enumerate(zip(phy.pipes, serdes)):
            events += [
                # Name,                          Signal,             Edge (1) or Level (0).
                (f"lane{lane}_ts1",              pipe.ts_rx_ts1,     1),
                (f"lane{lane}_ts1_inv",          pipe.ts_rx_ts1_inv, 1),
                (f"lane{lane}_ts2",              pipe.ts_rx_ts2,     1),
                (f"lane{lane}_rx_errors_cycles", s.rx_errors,        0),
            ]
            if with_triggers:
                events += [(f"lane{lane}_rx_idle_u0_cycles", u0 & phy.x2 & s.rx_idle, 0)]
            # SerDes RX status: elastic buffer errors, comma realignments (physical SerDes), RX
            # re-initializations on continuous decode errors.
            if with_triggers and hasattr(s, "rx_idle_raw"):
                events += [(f"lane{lane}_rx_idle_raw_u0_cycles", u0 & phy.x2 & s.rx_idle_raw, 0)]
            for name in ["rx_buferror", "rx_realign", "rx_skp_odd"]:
                if hasattr(s, name):
                    events += [(f"lane{lane}_{name}", getattr(s, name), 0)]
            if hasattr(phy, "rx_errors_reinit"):
                events += [(f"lane{lane}_rx_errors_reinit", phy.rx_errors_reinit[lane], 0)]
            if hasattr(phy, "lanes_com_partial"):
                events += [(f"lane{lane}_rx_com_partial", phy.lanes_com_partial[lane], 0)]
            # Transceiver events (A7USB3SerDes: Quad PLL lock losses, TX buffer errors).
            for name, signal, edge in getattr(s, "xcvr_events", []):
                events += [(f"lane{lane}_{name}", signal, edge)]
        # Per lane RX 8b/10b errors by type (USB3SerDes, counted in the SerDes RX clock domain,
        # accumulated in sys): only with the LTSSM in a state receiving symbols (Polling.RxEQ to U0,
        # Recovery, Hot Reset) and the lane RX not idle (not the LFPS/electrical idle: no symbols);
        # cleared by a snapshot on clear.
        # Per SerDes TX post-cursor pre-emphasis (runtime control when the target exposes it: Acorn
        # Gen 1x2, SerDes n on SFP-n; reset to the build value).
        for lane, s in enumerate(serdes):
            if hasattr(s, "tx_postcursor"):
                csr = CSRStorage(len(s.tx_postcursor), reset=s.tx_postcursor.reset.value,
                    name=f"lane{lane}_tx_postcursor",
                    description=f"SerDes {lane} TX post-cursor pre-emphasis (GTP TXPOSTCURSOR).")
                setattr(self, f"_lane{lane}_tx_postcursor", csr)
                self.comb += s.tx_postcursor.eq(csr.storage)
        # Per SerDes TX differential swing and forced TX electrical idle (debug, runtime controls when
        # the target exposes them: Acorn Gen 1x2; reset to the build values).
        for lane, s in enumerate(serdes):
            for name, desc in [("tx_diffctrl", "TX differential swing (GTP TXDIFFCTRL)"),
                ("tx_idle_force", "TX electrical idle forced (debug)")]:
                if hasattr(s, name):
                    sig = getattr(s, name)
                    csr = CSRStorage(len(sig), reset=sig.reset.value, name=f"lane{lane}_{name}",
                        description=f"SerDes {lane} {desc}.")
                    setattr(self, f"_lane{lane}_{name}", csr)
                    self.comb += sig.eq(csr.storage)
        counted = [s for s in serdes if hasattr(s, "add_rx_errors_count") and hasattr(s, "rx_substitution")]
        if not with_counters:
            counted = []
        if counted:
            symbols = Signal()
            self.comb += symbols.eq(ltssm_symbols(phy))
        for lane, s in enumerate(serdes):
            if s not in counted:
                continue
            s.add_rx_errors_count(enable=symbols & ~s.rx_idle)
            for name, value in s.rx_errors_counts.items():
                csr  = CSRStatus(32, name=f"lane{lane}_{name}_count",
                    description=f"Lane {lane} {name.replace('_', ' ')} count (RX Symbols, since the last clear).")
                base = Signal(32)
                setattr(self, f"_lane{lane}_{name}_count", csr)
                self.sync += If(self._clear.re, base.eq(value))
                self.comb += csr.status.eq(value - base)
        if cd_counters:
            # Lanes events in pipe_cd (Tang Mega 138K Pro split builds: lane word misalignment, t22).
            cd_names = {"deskew", "realign_u0", "skp_odd_u0", "com_slip"}
            for lane in range(2):
                cd_names |= {f"lane{lane}_{n}" for n in ["ts1", "ts1_inv", "ts2", "rx_errors_cycles",
                    "rx_buferror", "rx_realign", "rx_skp_odd", "rx_com_partial"]}
            for name, signal, edge in events:
                if name not in cd_names:
                    continue
                csr = CSRStatus(32, name=f"{name}_count",
                    description=f"{name} {'events' if edge else 'cycles'} count (wrapping, since the last clear).")
                setattr(self, f"_{name}_count", csr)
                value    = Signal(32)
                signal_r = Signal()
                signal_d = Signal()
                event    = Signal()
                getattr(self.sync, cd).__iadd__([
                    signal_r.eq(signal),
                    signal_d.eq(signal_r),
                    event.eq((signal_r & ~signal_d) if edge else signal_r),
                    If(event, value.eq(value + 1)),
                ])
                bs   = BusSynchronizer(32, cd, "sys")
                base = Signal(32)
                self.submodules += bs
                self.comb += [bs.i.eq(value), csr.status.eq(bs.o - base)]
                self.sync += If(self._clear.re, base.eq(bs.o))
        if not with_counters:
            events = []
        for name, signal, edge in events:
            csr = CSRStatus(32, name=f"{name}_count",
                description=f"{name} {'events' if edge else 'cycles'} count (saturating).")
            setattr(self, f"_{name}_count", csr)
            signal_d = Signal()
            self.sync += signal_d.eq(signal)
            event = (signal & ~signal_d) if edge else signal
            self.sync += If(self._clear.re,
                csr.status.eq(0)
            ).Elif(event & (csr.status != (2**32 - 1)),
                csr.status.eq(csr.status + 1)
            )
            if name == "rx_drop":
                self.comb += self._status.fields.rx_overflow.eq(csr.status != 0)

        # Transceivers re-initialization (last CSR: earlier CSRs addresses unchanged): SerDes reinit
        # held reinit_cycles from the write.
        self._xcvr_reinit = CSR() # Transceivers (both SerDes and the Quad PLL) re-initialization (write).
        reinit         = Signal(max=reinit_cycles + 1)
        reinit_request = Signal() # Lanes noise monitor re-initialization (below).
        self.sync += If(self._xcvr_reinit.re | reinit_request,
            reinit.eq(reinit_cycles)
        ).Elif(reinit != 0,
            reinit.eq(reinit - 1)
        )
        for s in serdes:
            if not hasattr(s, "reinit"):
                continue
            if cd is None:
                self.comb += s.reinit.eq(reinit != 0)
            else:
                self.specials += MultiReg(reinit != 0, s.reinit, cd)

        # Per SerDes transceiver status (A7USB3SerDes: ready, Quad PLL lock/reference clock lost,
        # TX/RX buffer status, CDR lock) and DRP access (channel attributes/status read back between
        # the transceivers start-up draws; selected on the transceiver DRP mux during the accesses).
        for lane, s in enumerate(serdes):
            if hasattr(s, "xcvr_status"):
                fields, offset = [], 0
                for name, signal in s.xcvr_status:
                    fields.append(CSRField(name, size=len(signal), offset=offset))
                    offset += len(signal)
                csr = CSRStatus(fields=fields, name=f"lane{lane}_xcvr_status",
                    description=f"SerDes {lane} transceiver status.")
                setattr(self, f"_lane{lane}_xcvr_status", csr)
                self.comb += [getattr(csr.fields, name).eq(signal) for name, signal in s.xcvr_status]
            xcvr = getattr(s, s.xcvr_name, None) if getattr(s, "xcvr_name", None) else None
            if hasattr(xcvr, "drp_mux") and hasattr(xcvr, "drp"):
                drp_sel = CSRStorage(name=f"lane{lane}_drp_sel",
                    description=f"SerDes {lane}: select DRP access on the transceiver DRP mux.")
                drp     = DRPControl(xcvr.drp)
                setattr(self, f"_lane{lane}_drp_sel", drp_sel)
                setattr(self, f"lane{lane}_drp", drp)
                drp_index = xcvr.drp_mux.interfaces.index(xcvr.drp)
                self.comb += xcvr.drp_mux.sel.eq(Mux(drp_sel.storage, drp_index, 0))

        # Lanes noise monitor (per lane RX disparity errors counters required).
        requests = [0]
        if monitor_tick_cycles is not None and len(counted) == len(serdes):
            states = phy.ltssm_states
            recovery, hot_reset, u3 = Signal(), Signal(), Signal()
            self.comb += [
                recovery.eq(phy.ltssm_state == states["Recovery.Active"]),
                hot_reset.eq(phy.ltssm_state == states["HotReset.Active"]),
                u3.eq(phy.ltssm_state == states["U3"]),
            ]
            self.monitor = LanesNoiseMonitor(
                disparity   = [s.rx_errors_counts["rx_disparity_errors"] for s in serdes],
                recovery    = recovery,
                hot_reset   = hot_reset,
                u3          = u3,
                tick_cycles = monitor_tick_cycles,
                clear       = self._clear.re)
            requests.append(self.monitor.reinit)

        # Training watchdog.
        if monitor_tick_cycles is not None and training_watchdog_ms is not None:
            self.watchdog = LanesTrainingWatchdog(phy, tick_cycles=monitor_tick_cycles,
                timeout_ms=training_watchdog_ms)
            requests.append(self.watchdog.reinit)
        self.comb += reinit_request.eq(Reduce("OR", requests))

# Lanes Training Watchdog -------------------------------------------------------------------------

class LanesTrainingWatchdog(LiteXModule):
    """Gen 1x2 training watchdog: transceivers re-initialization and Warm Reset when the link trains
    without reaching U0.

    Some transceivers start-ups (bitstream loads, re-initializations) give a link that never trains
    at Gen 1x2: Acorn Mini Host (Artix7 GTP) <-> Tang Mega 138K Pro Device (GW5AST GTR12), ~85% of the
    Acorn loads, both directions failing (Tang CDRs unlocked, Acorn decode errors on both lanes) while
    the same load trains at Gen 1x1 at once; a runtime re-initialization of the Acorn transceivers
    (Quad PLL and both channels) followed by a retrain of both PHYs re-draws it: 3 of 4 bad loads
    recovered after 1-3 re-initializations, then clean (t16z); the re-initialization alone (no retrain)
    did not recover them (t17).

    The watchdog counts the time (tick_cycles sys cycles per ms) spent in the training states
    (Polling past the LFPS handshake, Recovery, Hot Reset, eSS.Inactive: a link partner present, not
    Rx.Detect nor Polling.Entry/LFPS/LFPSPlus/ExitToRxDetect: a partner reloading its bitstream, t24) since the last
    stable U0 (U0 held u0_stable_ms: the failing link passes through U0 ~65 times per second, t17).
    After timeout_ms of it (timeout CSR, runtime: 0 disables), it pulses reinit (one sys cycle), then
    after warm_delay_ms (transceivers initialization) requests a Warm Reset (warm_reset_req, Host:
    both PHYs retrained) until the WarmReset state (warm_reset, i) or warm_max_ms, then counts again
    (a re-initialization per timeout until U0).
    """
    def __init__(self, phy, tick_cycles, timeout_ms=2000, u0_stable_ms=100, warm_delay_ms=5,
        warm_max_ms=50):
        from litex.soc.interconnect.csr import CSRStorage, CSRStatus
        self.reinit         = Signal() # o
        self.warm_reset_req = Signal() # o
        self._timeout = CSRStorage(16, reset=timeout_ms,
            description="Link training time without U0 (ms) before a transceivers re-initialization (0: disabled).")
        self._count   = CSRStatus(32,
            description="Transceivers re-initializations by the training watchdog.")

        # # #

        states    = phy.ltssm_states
        training  = Signal()
        warm      = Signal()
        self.comb += [
            training.eq(Reduce("OR", [phy.ltssm_state == value for name, value in
                states.items() if (name.split(".")[0] in ["Polling", "Recovery", "HotReset", "eSS"]) and
                (name not in ["Polling.Entry", "Polling.LFPS", "Polling.LFPSPlus", "Polling.ExitToRxDetect"])])),
            warm.eq(phy.ltssm_state == states["WarmReset"]) if "WarmReset" in states else warm.eq(0),
        ]
        tick    = Signal()
        ticks   = Signal(max=max(2, tick_cycles))
        self.sync += [
            tick.eq(0),
            ticks.eq(ticks + 1),
            If(ticks == (tick_cycles - 1),
                ticks.eq(0),
                tick.eq(1),
            ),
        ]
        # Stable U0.
        u0_ms     = Signal(max=u0_stable_ms + 1)
        u0_stable = Signal()
        self.comb += u0_stable.eq(u0_ms == u0_stable_ms)
        self.sync += If(~phy.u0,
            u0_ms.eq(0)
        ).Elif(tick & ~u0_stable,
            u0_ms.eq(u0_ms + 1)
        )
        # Training time, re-initialization then Warm Reset request.
        elapsed  = Signal(16)
        wait_ms  = Signal(max=warm_delay_ms + warm_max_ms + 1)
        timeout  = self._timeout.storage
        self.fsm = fsm = FSM(reset_state="COUNT")
        fsm.act("COUNT",
            If((timeout != 0) & (elapsed >= timeout),
                self.reinit.eq(1),
                NextValue(self._count.status, self._count.status + 1),
                NextValue(wait_ms, 0),
                NextState("REINIT")
            )
        )
        fsm.act("REINIT",
            If(tick,
                NextValue(wait_ms, wait_ms + 1),
                If(wait_ms == (warm_delay_ms - 1),
                    NextValue(wait_ms, 0),
                    NextState("WARM_RESET")
                )
            )
        )
        fsm.act("WARM_RESET",
            self.warm_reset_req.eq(~warm),
            If(warm | u0_stable,
                NextState("COUNT")
            ).Elif(tick,
                NextValue(wait_ms, wait_ms + 1),
                If(wait_ms == (warm_max_ms - 1),
                    NextState("COUNT")
                )
            )
        )
        self.sync += If(u0_stable | (timeout == 0) | ~fsm.ongoing("COUNT"),
            elapsed.eq(0)
        ).Elif(training & tick & (elapsed < timeout),
            elapsed.eq(elapsed + 1)
        )

# Lanes Noise Monitor -----------------------------------------------------------------------------

class LanesNoiseMonitor(LiteXModule):
    """Gen 1x2 lanes noise monitor: transceivers re-initialization on a sustained noise rate.

    The line noise of a Gen 1x2 link is drawn at the transceivers start-up and sets the rate of noise
    episodes (doc/gen1x2-hardware-validation.md t12/t13): a check at the start-up only catches the
    draws noisy all the time. The monitor measures, per window of window_ms ticks (tick_cycles sys
    cycles), the RX running disparity errors of each lane (disparity: sys free running counts) and
    the Recovery entries (recovery: level); a window is noisy when a lane exceeds the disparity
    threshold or the Recovery entries exceed the recoveries threshold (0: criterion disabled).
    After `windows` consecutive noisy windows, with enable, out of U3 (u3) and under the
    re-initializations budget (max_reinits since the last clear, 0: unlimited), reinit pulses (one
    sys cycle) and the next `holdoff` windows are not evaluated (link training after the re-init).
    The windows are measured and counted with enable at 0 too (thresholds calibration). Reset values
    from the t14 calibration (scripted host bursts, ~2.5 runs/s): 2s windows (the errors of a run
    burst arrive within ~0.5s: shorter windows rarely see 2 noisy windows in a row), disparity 200
    per lane, 30 Recovery entries. The thresholds are absolute counts per window (traffic pattern
    dependent); on the Acorn Gen 1x2 pair, only the Host re-initializations quiet a load (t14).

    Traffic independent criterion (ratio CSR): a window is also noisy when a lane's disparity errors
    exceed disparity_per_training x the window trainings, with at least min_trainings trainings
    (Recovery entries, + the Hot Reset entries with with_hot_reset: hot_reset level): the errors
    arrive around the trainings (an idle U0 has none, t9/t14), so the errors per training measure the
    line quality whatever the trainings rate (t12/t13 classes: disparity errors per Host reset). 0
    disables it (reset); set the absolute thresholds to 0 to use it alone.
    """
    def __init__(self, disparity, recovery, u3, tick_cycles, clear=None, hot_reset=None):
        self.reinit = Signal() # o: Transceivers re-initialization request (pulse).
        n = len(disparity)

        self._control = CSRStorage(fields=[
            CSRField("enable",      size=1,  offset=0,  reset=0,
                description="Transceivers re-initialization on a sustained noise rate (0: windows measured only)."),
            CSRField("windows",     size=4,  offset=1,  reset=2,
                description="Consecutive noisy windows triggering a re-initialization (0: as 1)."),
            CSRField("holdoff",     size=4,  offset=5,  reset=2,
                description="Windows not evaluated after a re-initialization."),
            CSRField("window_ms",   size=12, offset=9,  reset=2000,
                description="Window length (ms, 0: as 1)."),
            CSRField("max_reinits", size=8,  offset=21, reset=8,
                description="Re-initializations budget since the last clear (0: unlimited)."),
        ])
        self._thresholds = CSRStorage(fields=[
            CSRField("disparity",  size=16, offset=0,  reset=200,
                description="Noisy window: RX disparity errors of a lane above (0: disabled)."),
            CSRField("recoveries", size=16, offset=16, reset=30,
                description="Noisy window: Recovery entries above (0: disabled)."),
        ])
        self._window = CSRStatus(fields=
            [CSRField(f"disparity{i}", size=16, offset=16*i,
                description=f"Lane {i} RX disparity errors of the last window (saturated).") for i in range(n)])
        self._window_status = CSRStatus(fields=[
            CSRField("recoveries", size=16, offset=0,  description="Recovery entries of the last window (saturated)."),
            CSRField("streak",     size=4,  offset=16, description="Current consecutive noisy windows."),
            CSRField("holdoff",    size=4,  offset=20, description="Remaining windows not evaluated."),
            CSRField("budget",     size=1,  offset=24, description="Re-initializations budget reached."),
        ])
        self._windows_count = CSRStatus(32, description="Windows evaluated (since the last clear).")
        self._noisy_count   = CSRStatus(32, description="Noisy windows (evaluated, since the last clear).")
        self._reinits_count = CSRStatus(32, description="Re-initializations requested by the monitor (since the last clear).")
        self._ratio = CSRStorage(fields=[
            CSRField("disparity_per_training", size=8, offset=0,  reset=0,
                description="Noisy window: RX disparity errors of a lane above this many per training (0: disabled)."),
            CSRField("min_trainings",          size=8, offset=8,  reset=2,
                description="Trainings in the window required by the disparity per training criterion (0: as 1)."),
            CSRField("with_hot_reset",         size=1, offset=16, reset=1,
                description="Trainings: Recovery entries + Hot Reset entries (0: Recovery entries only)."),
        ])
        self._window_hot_resets = CSRStatus(16, description="Hot Reset entries of the last window (saturated).")

        # # #

        ctrl      = self._control.fields
        thr       = self._thresholds.fields
        ratio     = self._ratio.fields
        clear     = Signal() if clear is None else clear
        hot_reset = Signal() if hot_reset is None else hot_reset

        # Window timer: ms ticks.
        tick       = Signal()
        prescaler  = Signal(max=max(tick_cycles, 2))
        window_end = Signal()
        ms         = Signal(12)
        self.sync += [
            tick.eq(0),
            If(prescaler == 0,
                prescaler.eq(tick_cycles - 1),
                tick.eq(1)
            ).Else(
                prescaler.eq(prescaler - 1)
            ),
            window_end.eq(0),
            If(tick,
                If(ms + 1 >= ctrl.window_ms,
                    ms.eq(0),
                    window_end.eq(1)
                ).Else(
                    ms.eq(ms + 1)
                )
            )
        ]

        # Per window measurements: disparity errors per lane (count difference), Recovery entries.
        def sat16(v):
            return Mux(v > 0xffff, 0xffff, v[:16])
        last     = [Signal(32) for _ in range(n)]
        current  = [Signal(16) for _ in range(n)]
        recovery_d = Signal()
        entries  = Signal(16)
        self.sync += recovery_d.eq(recovery)
        self.sync += If(window_end,
            entries.eq(0)
        ).Elif(recovery & ~recovery_d & (entries != 0xffff),
            entries.eq(entries + 1)
        )
        for i in range(n):
            delta = Signal(32)
            self.comb += delta.eq(disparity[i] - last[i])
            self.comb += current[i].eq(sat16(delta))
            self.sync += If(window_end,
                last[i].eq(disparity[i]),
                getattr(self._window.fields, f"disparity{i}").eq(current[i])
            )
        hot_reset_d = Signal()
        hot_resets  = Signal(16)
        self.sync += hot_reset_d.eq(hot_reset)
        self.sync += If(window_end,
            hot_resets.eq(0)
        ).Elif(hot_reset & ~hot_reset_d & (hot_resets != 0xffff),
            hot_resets.eq(hot_resets + 1)
        )
        self.sync += If(window_end,
            self._window_status.fields.recoveries.eq(entries),
            self._window_hot_resets.status.eq(hot_resets)
        )

        # Disparity errors per training: worst lane > disparity_per_training x trainings (registered,
        # one cycle behind the counts: negligible on a window).
        trainings     = Signal(17)
        worst         = Signal(16)
        limit         = Signal(25)
        enough        = Signal()
        ratio_noisy   = Signal()
        min_trainings = Signal(8)
        self.comb += [
            trainings.eq(entries + Mux(ratio.with_hot_reset, hot_resets, 0)),
            min_trainings.eq(Mux(ratio.min_trainings == 0, 1, ratio.min_trainings)),
        ]
        worst_comb = current[0]
        for i in range(1, n):
            worst_comb = Mux(current[i] > worst_comb, current[i], worst_comb)
        self.sync += [
            worst.eq(worst_comb),
            limit.eq(ratio.disparity_per_training * trainings),
            enough.eq(trainings >= min_trainings),
        ]
        self.comb += ratio_noisy.eq((ratio.disparity_per_training != 0) & enough & (worst > limit))

        noisy = Signal()
        self.comb += noisy.eq(
            ((thr.disparity  != 0) & Reduce("OR", [current[i] > thr.disparity for i in range(n)])) |
            ((thr.recoveries != 0) & (entries > thr.recoveries)) |
            ratio_noisy)

        # Decision at the window end.
        streak  = self._window_status.fields.streak
        holdoff = self._window_status.fields.holdoff
        reinits = self._reinits_count.status
        budget  = Signal()
        self.comb += [
            budget.eq((ctrl.max_reinits != 0) & (reinits >= ctrl.max_reinits)),
            self._window_status.fields.budget.eq(budget),
        ]
        trigger = Signal()
        self.comb += trigger.eq(((streak + 1) >= ctrl.windows) & ctrl.enable & ~u3 & ~budget)
        def incr(c):
            return If(c != (2**32 - 1), c.eq(c + 1))
        self.sync += [
            self.reinit.eq(0),
            If(clear,
                streak.eq(0),
                holdoff.eq(0),
                self._windows_count.status.eq(0),
                self._noisy_count.status.eq(0),
                reinits.eq(0),
            ).Elif(window_end,
                If(holdoff != 0,
                    holdoff.eq(holdoff - 1),
                    streak.eq(0)
                ).Else(
                    incr(self._windows_count.status),
                    If(noisy,
                        incr(self._noisy_count.status),
                        If(trigger,
                            self.reinit.eq(1),
                            incr(reinits),
                            streak.eq(0),
                            holdoff.eq(ctrl.holdoff)
                        ).Elif(streak != 15,
                            streak.eq(streak + 1)
                        )
                    ).Else(
                        streak.eq(0)
                    )
                )
            )
        ]

# USB3 RX Error Types Debug -----------------------------------------------------------------------

class USB3RXErrorTypesDebug(LiteXModule):
    """USB3 RX 8b/10b errors by type (CSRs, single lane SerDes: the per lane counters of
    USB3LanesDebug): decode errors, running disparity errors, and both on the Symbol just before a
    COM (USB3SerDes.add_rx_errors_count: reset-less RX counters, counted only with the LTSSM in a
    state receiving Symbols and the RX not idle), cleared (snapshot) with `clear`.

    serdes_cd: clock domain of the SerDes "sys" (ex: "tx" on the Tang Mega 138K Pro, SerDes logic on
    the GTR12 TX clock): enable resynchronized to it, counts synchronized back to sys
    (BusSynchronizer). phy.ltssm_state in sys.
    """
    def __init__(self, phy, serdes, serdes_cd="sys"):
        self._clear = CSR() # Clear the counters (write: snapshot).

        # # #

        symbols = Signal()
        self.comb += symbols.eq(ltssm_symbols(phy))
        if serdes_cd != "sys":
            symbols_s = Signal()
            self.specials += MultiReg(symbols, symbols_s, serdes_cd)
            symbols = symbols_s
        enable = Signal()
        self.comb += enable.eq(symbols & ~serdes.rx_idle)
        serdes.add_rx_errors_count(enable=enable)
        for name, value in serdes.rx_errors_counts.items():
            if serdes_cd != "sys":
                sync = BusSynchronizer(32, serdes_cd, "sys")
                self.submodules += sync
                self.comb += sync.i.eq(value)
                value = sync.o
            csr  = CSRStatus(32, name=f"{name}_count",
                description=f"{name.replace('_', ' ')} count (RX Symbols, since the last clear).")
            base = Signal(32)
            setattr(self, f"_{name}_count", csr)
            self.sync += If(self._clear.re, base.eq(value))
            self.comb += csr.status.eq(value - base)

# USB3 RX Errors Debug -----------------------------------------------------------------------------

class USB3RXErrorsDebug(LiteXModule):
    """USB3 RX Errors Debug (CSRs, hardware bring-up).

    Counts, in the RX clock domain, the received symbols and the 8b/10b errors per type:
    - decoder_invalid: LiteX Decoder invalid flags.
    - code_invalid:    RX8b10bChecker invalid codes.
    - disparity:       RX8b10bChecker disparity errors.
    - bursts:          Error bursts (error words following an error-free word).
    - max_good_run:    Longest error-free run (words).
    Counters are synchronized to the sys clock domain (BusSynchronizer) and cleared with `clear`.
    """
    def __init__(self, decoders, checker, clock_domain="rx"):
        self._clear = CSR() # Clear the RX counters (write).

        # # #

        n = len(decoders)

        # Clear (sys -> rx).
        self.clear_ps = clear_ps = PulseSynchronizer("sys", clock_domain)
        self.comb += clear_ps.i.eq(self._clear.re)
        clear   = clear_ps.o
        sync_rx = getattr(self.sync, clock_domain)

        # Counters (rx).
        events = {
            "symbols"         : [Constant(1, 1)]*n,
            "decoder_invalid" : [decoder.invalid for decoder in decoders],
            "code_invalid"    : [checker.invalid[i] for i in range(n)],
            "disparity"       : [checker.disparity_error[i] for i in range(n)],
        }
        # Error bursts / longest error-free run.
        error   = Signal()
        error_d = Signal()
        run     = Signal(32)
        bursts  = Signal(32)
        max_run = Signal(32)
        sync_rx += [
            error.eq(Reduce("OR",
                events["decoder_invalid"] + events["code_invalid"] + events["disparity"])),
            error_d.eq(error),
            If(clear,
                run.eq(0),
                bursts.eq(0),
                max_run.eq(0),
            ).Elif(error,
                run.eq(0),
                If(~error_d, bursts.eq(bursts + 1)),
            ).Else(
                run.eq(run + 1),
                If(run > max_run, max_run.eq(run)),
            )
        ]

        for name, flags in events.items():
            count     = Signal(32)
            increment = Signal(max=n + 1)
            sync_rx += increment.eq(Reduce("ADD", flags))
            sync_rx += If(clear,
                count.eq(0)
            ).Else(
                count.eq(count + increment)
            )
            csr  = CSRStatus(32, name=f"{name}_count", description=f"RX {name} count.")
            sync = BusSynchronizer(32, clock_domain, "sys")
            self.submodules += sync
            setattr(self, f"_{name}_count", csr)
            self.comb += [
                sync.i.eq(count),
                csr.status.eq(sync.o),
            ]
        for name, value, description in [
            ("bursts_count", bursts,  "RX error bursts count."),
            ("max_good_run", max_run, "RX longest error-free run (words)."),
            ]:
            csr  = CSRStatus(32, name=name, description=description)
            sync = BusSynchronizer(32, clock_domain, "sys")
            self.submodules += sync
            setattr(self, f"_{csr.name}", csr)
            self.comb += [
                sync.i.eq(value),
                csr.status.eq(sync.o),
            ]

# USB3 SerDes Debug --------------------------------------------------------------------------------

class USB3SerDesDebug(LiteXModule):
    """USB3 SerDes Debug (CSRs, hardware bring-up of the USB3 SerDes: A7/K7/USP).

    - TX polarity / TX inhibit controls (TX inhibit can be restricted to an LTSSM state, ex to
      isolate the partner's signal from crosstalk during training).
    - Transceiver loopback control (0b010: Near-End PMA).
    - TX/RX clocks frequency meters (100ms period): the RX clock is the recovered clock, its offset
      vs the TX clock shows the CDR frequency tracking of the partner (SSC: 0/-5000ppm).
    - RX vs TX clocks phase (rx_tx_phase, sys clock domain, for LiteScope): its slope is the
      instantaneous frequency offset of the recovered clock (SSC profile, CDR tracking limits).
    - Transceiver DRP access (attributes changes without rebuild, ex: RXCDR_CFG/LPM sweeps; to be
      followed by a SerDes RX re-initialization).
    - RX 8b/10b errors statistics (USB3RXErrorsDebug).
    """
    def __init__(self, serdes, sys_clk_freq, ltssm_state=None):
        self._tx_polarity      = CSRStorage(description="TX polarity.")
        self._tx_inhibit       = CSRStorage(description="TX inhibit.")
        self._tx_inhibit_state = CSRStorage(9, description="TX inhibit while in LTSSM state [7:0] "
                                                            "when enabled [8].")
        self._loopback         = CSRStorage(3,
            description="Transceiver loopback (0b010: Near-End PMA).")
        self.rx_tx_phase       = Signal(16) # o

        # # #

        gt = getattr(serdes, serdes.xcvr_name)

        # TX/Loopback controls.
        tx_inhibit_state = Signal()
        if ltssm_state is not None:
            self.comb += tx_inhibit_state.eq(self._tx_inhibit_state.storage[8] &
                (ltssm_state == self._tx_inhibit_state.storage[:8]))
        self.comb += [
            serdes.tx_polarity.eq(self._tx_polarity.storage),
            gt.tx_inhibit.eq(self._tx_inhibit.storage | tx_inhibit_state),
            gt.loopback.eq(self._loopback.storage),
        ]

        # DRP access (selected on the transceiver DRP mux during the accesses, the mux default is
        # the transceiver RX initialization on GTP, gt.drp is the only interface on GTY).
        self._drp_sel = CSRStorage(description="Select DRP access on the transceiver DRP mux.")
        self.drp      = DRPControl(gt.drp)
        drp_index     = gt.drp_mux.interfaces.index(gt.drp)
        self.comb += gt.drp_mux.sel.eq(Mux(self._drp_sel.storage, drp_index, 0))

        # RX vs TX clocks phase (gray counters).
        rx_count = ClockDomainsRenamer("rx")(GrayCounter(16))
        tx_count = ClockDomainsRenamer("tx")(GrayCounter(16))
        self.submodules += rx_count, tx_count
        self.comb += rx_count.ce.eq(1), tx_count.ce.eq(1)
        rx_gray = Signal(16)
        tx_gray = Signal(16)
        self.specials += [
            MultiReg(rx_count.q, rx_gray),
            MultiReg(tx_count.q, tx_gray),
        ]
        self.sync += self.rx_tx_phase.eq(gray_decode(rx_gray) - gray_decode(tx_gray))

        # Clocks frequency meters.
        self.tx_freq = FreqMeter(period=int(sys_clk_freq/10), clk=ClockSignal("tx"))
        self.rx_freq = FreqMeter(period=int(sys_clk_freq/10), clk=ClockSignal("rx"))

        # RX errors.
        self.rx_errors = USB3RXErrorsDebug(gt.decoders, serdes.rx_substitution.checker)

# Gen 2 RX Debug -----------------------------------------------------------------------------------

class Gen2RXDebug(LiteXModule):
    """Gen 2 RX Debug (CSRs, hardware bring-up of a Gen2RXDatapath).

    - status: aligned [0], locked [1], polarity [2], data_stream [3], link_config [15:8].
    - `{name}_count`: GEN2_RX_COUNTERS (blocks, header/alignment errors, SYNC/TSEQ/TS1/TS2/SDS/SKP
      Ordered Sets, unknown control blocks), synchronized to the sys clock domain (BusSynchronizer).
    - clear: clears the counters (write).
    LiteScope probes: gen2_rx_analyzer_signals().
    """
    def __init__(self, rx_datapath, clock_domain="rx"):
        self._clear  = CSR() # Clear the counters (write).
        self._status = CSRStatus(fields=[
            CSRField("aligned",     size=1, description="Block aligned."),
            CSRField("locked",      size=1, description="Block alignment locked."),
            CSRField("polarity",    size=1, description="RX polarity inverted."),
            CSRField("data_stream", size=1, description="Receiving the Data Stream."),
            CSRField("link_config", size=8, offset=8, description="Received TS2 Link Configuration."),
        ])

        # # #

        # Clear (sys -> rx).
        self.clear_ps = clear_ps = PulseSynchronizer("sys", clock_domain)
        self.comb += [
            clear_ps.i.eq(self._clear.re),
            rx_datapath.clear.eq(clear_ps.o),
        ]

        # Status (quasi-static, rx -> sys).
        status     = Cat(rx_datapath.aligned, rx_datapath.locked, rx_datapath.polarity,
            rx_datapath.data_stream, Constant(0, 4), rx_datapath.link_config)
        status_sys = Signal(16)
        self.specials += MultiReg(status, status_sys)
        self.comb += [
            self._status.fields.aligned.eq(status_sys[0]),
            self._status.fields.locked.eq(status_sys[1]),
            self._status.fields.polarity.eq(status_sys[2]),
            self._status.fields.data_stream.eq(status_sys[3]),
            self._status.fields.link_config.eq(status_sys[8:16]),
        ]

        # Counters (rx -> sys).
        for name, description in GEN2_RX_COUNTERS:
            csr  = CSRStatus(32, name=f"{name}_count", description=f"Gen 2 RX {description}")
            sync = BusSynchronizer(32, clock_domain, "sys")
            self.submodules += sync
            setattr(self, f"_{name}_count", csr)
            self.comb += [
                sync.i.eq(getattr(rx_datapath, f"{name}_count")),
                csr.status.eq(sync.o),
            ]

def gen2_rx_analyzer_signals(rx_datapath):
    """LiteScope probes of a Gen2RXDatapath (RX clock domain): status, aligner/receiver events and
    blocks."""
    aligner = rx_datapath.aligner
    rx      = rx_datapath.rx
    return [
        aligner.aligned, aligner.locked, aligner.polarity, aligner.error,
        aligner.skp, aligner.skp_count,
        aligner.source.valid, aligner.source.header, aligner.source.header_error,
        aligner.source.data,
        rx.rx_sync, rx.rx_sds, rx.tseq, rx.ts1, rx.ts2, rx.unknown,
        rx.rx_tseq, rx.rx_ts1, rx.rx_ts2, rx.link_config, rx.data_stream,
    ]

# USB3 Analyzer Groups -----------------------------------------------------------------------------

USB3_ANALYZER_GROUPS = ["link", "lfps", "ts", "datapath", "phase", "u3", "lanes", "realign", "warm", "script"]

def usb3_analyzer_groups(phy, serdes, serdes_debug=None):
    """LiteScope probes groups of a USB3PHY/USB3SerDes (bench/usb3_analyzer.py), returns a dict
    {name: signals}:
    - link     : LTSSM + TS/LFPS Polling detections/generation, RX idle/errors/polarity.
    - lfps     : LTSSM + LFPS TX/RX (Polling, Ping, U1/U2/U3 exit, Warm Reset).
    - ts       : LTSSM + TS detections/generation, SerDes RX/TX streams.
    - datapath : LTSSM + SerDes and PHY RX/TX streams, SKP removal.
    - phase    : LTSSM + RX vs TX clocks phase (requires serdes_debug: USB3SerDesDebug).
    - lanes    : LTSSM + Gen 1x2 lanes words at the deskew input, deskew pairing, destriped words,
                 lanes TX words to the SerDes.
    - realign  : LTSSM + Gen 1x2 lanes RX words at the deskew input, deskew pairing, lanes Recovery
                 triggers, both lanes SerDes RX status (comma realignments, elastic buffer errors,
                 decode errors, idle) and RX words before the word aligner (a lane losing symbols
                 at the end of a TS burst): a lane realigned in U0 (no TX/destriped words).
    - u3       : LTSSM + U3 exit: LFPS TX/RX, TS1 detection, SerDes RX stream, RX vs TX clocks phase
                 (requires serdes_debug).
    """
    pipe  = phy.pipes[0] # Configuration Lane (Lane 0) with 2 lanes.
    ltssm = phy.ltssm
    link_signals = [
        phy.ltssm_state,
        ltssm.u0,
        ltssm.recovery,
        ltssm.rx_ready,
        ltssm.tx_ready,
        ltssm.idle_handshake,
        ltssm.idle_handshake_done,
        ltssm.ts2_decode,
    ]
    groups = {
        "link" : link_signals + [
            pipe.ts_rx_ts1, pipe.ts_rx_ts1_inv, pipe.ts_rx_ts2, pipe.ts_tx_done,
            pipe.ts_tx_tseq, pipe.ts_tx_ts1, pipe.ts_tx_ts2,
            pipe.lfps_rx_polling, pipe.lfps_tx_polling, pipe.lfps_tx_count,
            serdes.rx_idle, serdes.rx_errors, serdes.rx_polarity,
        ],
        "lfps" : link_signals + [
            serdes.tx_idle, serdes.tx_lfps, serdes.tx_pattern,
            serdes.rx_idle, serdes.rx_errors,
            # Unfiltered transceiver idle detection (bursts split by the idle detection toggling).
            *([serdes.rx_idle_raw] if hasattr(serdes, "rx_idle_raw") else []),
            pipe.lfps_rx_polling, pipe.lfps_rx_ping, pipe.lfps_rx_exit_u1,
            pipe.lfps_rx_exit_u2, pipe.lfps_rx_wakeup_u3, pipe.lfps_rx_reset,
            pipe.lfps_tx_polling, pipe.lfps_tx_count,
        ],
        "ts" : link_signals + [
            pipe.ts_rx_ts1, pipe.ts_rx_ts1_inv, pipe.ts_rx_ts2, pipe.ts_tx_done,
            pipe.ts_tx_tseq, pipe.ts_tx_ts1, pipe.ts_tx_ts2,
            serdes.source, serdes.sink,
        ],
        "datapath" : link_signals + [
            serdes.rx_errors,
            serdes.rx_datapath.skip_remover.skip,
            serdes.source, serdes.sink,
            phy.source, phy.sink,
        ],
    }
    if hasattr(phy, "deskew"):
        # Gen 1x2 (lanes=2): both lanes words at the deskew input (after the per lane word alignment
        # and SKP removal), deskew pairing (heads: marker at the FIFOs outputs) and destriped words.
        deskew = phy.deskew
        groups["lanes"] = link_signals + [
            phy.x2, phy.lane_swap, deskew.aligned, deskew.clear, *deskew.heads,
            *[getattr(deskew.sinks[lane], name) for lane in range(2) for name in ["valid", "data", "ctrl"]],
            phy.source.valid, phy.source.data, phy.source.ctrl,
            # TX: both lanes words to the SerDes (TS/scrambled data, before SKP insertion/8b10b).
            pipe.ts_tx_ts1, pipe.ts_tx_ts2, phy.pipes[1].ts_tx_ts2,
            *[getattr(phy.lane_swap_unit.lanes[lane], name) for lane in range(2) for name in ["tx_idle"]],
            *[getattr(phy.lane_swap_unit.lanes[lane].sink, name) for lane in range(2)
                for name in ["valid", "ready", "data", "ctrl"]],
        ]
        # Lanes RX words at the deskew input, lanes Recovery triggers (U0 exits requested by the
        # lanes) and the physical SerDes RX status of both lanes (comma realignments, decode
        # errors, electrical idle): a lane realigned in U0 (usb3_analyzer.py --trigger lanes_realign).
        groups["realign"] = link_signals + [
            phy.x2, phy.lane_swap, deskew.aligned, deskew.clear, *deskew.heads,
            *[getattr(deskew.sinks[lane], name) for lane in range(2) for name in ["valid", "data", "ctrl"]],
        ] + [getattr(phy, name) for name in ["lanes_realign", "lanes_deskew_lost", "lanes_idle",
            "lanes_com_slip", "lanes_com_partial"]
            if hasattr(phy, name)] + [getattr(s, name) for s in getattr(phy, "lanes_phys_serdes", [])
            for name in ["rx_realign", "rx_buferror", "rx_errors", "rx_idle"] if hasattr(s, name)] + [
            # Physical lanes words before the word aligner (after the SKP removal and the CDC, sys):
            # a lane losing symbols at the end of a TS burst, before or in the RX word alignment.
            getattr(s.rx_datapath.cdc.source, name) for s in getattr(phy, "lanes_phys_serdes", [])
            if hasattr(s, "rx_datapath") for name in ["valid", "data", "ctrl"]]
    if hasattr(phy, "lanes_phys_serdes"):
        # Warm Reset detection per physical lane (levels: capture with litescope_cli --subsampling,
        # the LFPS lasts ~100ms): electrical idle (filtered/raw), decode errors, RX reset, the
        # Configuration Lane Warm Reset checker and the lanes swap.
        groups["warm"] = link_signals + [phy.lane_swap, pipe.lfps_rx_reset] + [
            getattr(s, name) for s in phy.lanes_phys_serdes
            for name in ["rx_idle", "rx_idle_raw", "rx_errors", "rx_errors_hold", "rx_reset",
                "rx_invalid", "rx_stall"]
            if hasattr(s, name)]
    if serdes_debug is not None:
        groups["phase"] = link_signals + [
            serdes_debug.rx_tx_phase,
            serdes.rx_idle, serdes.rx_errors,
        ]
        groups["u3"] = link_signals + [
            serdes.tx_idle, serdes.tx_lfps, serdes.rx_idle, serdes.rx_errors,
            pipe.lfps_rx_wakeup_u3, pipe.ts_rx_ts1, pipe.ts_tx_ts1,
            serdes.source.valid, serdes.source.data, serdes.source.ctrl,
            serdes_debug.rx_tx_phase,
        ] + [getattr(serdes, name) for name in ["rx_realign", "rx_buferror"]
            if hasattr(serdes, name)]
    return groups
