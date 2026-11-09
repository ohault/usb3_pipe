#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2019-2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""USB3 SoC shared by the bench targets (acorn.py, kc705.py, alibaba_xcku3p.py,
sipeed_tang_mega_138k_pro.py), see doc/targets.md.

- USB3BaseSoC     : SoCCore (no CPU by default), UARTBone/JTAGBone.
- add_usb3_device : USB3PHY + debug (USB3PHYDebug, USB3SerDesDebug), USB3 Device Core example
                    design and LEDs.
- add_usb3_lanes_link : Gen 1x2 USB3PHY(lanes=2) (Host or Device role) + debug (USB3PHYDebug,
                    USB3LanesDebug) and PRBS Link-Layer stand-ins (hardware link tests between two
                    boards, no USB3 Device Core).
- usb3_analyzer   : LiteScope analyzer (usb3_pipe.debug.usb3_analyzer_groups).
- usb3_soc_args/usb3_soc_argdict/usb3_soc_build: common target arguments and build/load.

The targets only provide their CRG, IOs and USB3 SerDes (+ board specifics).
"""

import os

import common # Repository root on the path.

from migen import *
from migen.genlib.cdc import MultiReg, PulseSynchronizer, BusSynchronizer

from litex.gen import *

from litex.soc.interconnect.csr     import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder  import *

from litescope import LiteScopeAnalyzer

from usb3_pipe.phy      import USB3PHY, USB3PHYX1Link, USB3PHYX2Link
from usb3_pipe.prbs     import PRBSLinkTester
from usb3_pipe.datapath import Gen2RXDatapath
from usb3_pipe.debug    import USB3PHYDebug, USB3LanesDebug, USB3SerDesDebug, Gen2RXDebug
from usb3_pipe.debug    import usb3_analyzer_groups, USB3_ANALYZER_GROUPS

from usb3_core.examples import add_usb3_example, USB3_EXAMPLES

# USB3 SoC -----------------------------------------------------------------------------------------

class USB3BaseSoC(SoCCore):
    """SoCCore with Wishbone bridges (UARTBone/JTAGBone), USB3 device added with add_usb3_device.

    No CPU by default (bridges only), CPU with the console/composite examples (BIOS on the USB3
    CDC-ACM) or for the DRAM initialization. with_uart: stub UART (BIOS console when the console is
    not on the USB3 CDC-ACM).
    """
    def __init__(self, platform, sys_clk_freq, cpu_type=None, with_uart=False,
        with_uartbone=True, with_jtagbone=False):
        # SoCCore ----------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq,
            ident                = "USB3SoC",
            ident_version        = True,
            cpu_type             = cpu_type,
            integrated_rom_size  = 0x10000 if cpu_type is not None else 0,
            integrated_sram_size = 0x2000  if cpu_type is not None else 0,
            with_uart            = with_uart,
            uart_name            = "stub",
            with_timer           = cpu_type is not None,
        )

        # UARTBone / JTAGBone ----------------------------------------------------------------------
        if with_uartbone:
            self.add_uartbone(baudrate=115200)
        if with_jtagbone:
            self.add_jtagbone()

# USB3 Device --------------------------------------------------------------------------------------

class RXRawSnapshot(LiteXModule):
    """Raw RX words snapshot (bring-up): circular capture of the raw words (rx_nr: reset-less rx
    clock, kept across RX re-initializations) with their flags, stopped `depth//2` words after a
    trigger (flags bit selected by the trigger CSR) once armed; read back with index/data CSRs
    (oldest word at index 0, 40-bit word in data0/data1[:8], flags in data1[8:])."""
    def __init__(self, rx_raw, flags, depth=1024, clock_domain="rx_nr", write_enable=1, post=None):
        self._arm     = CSR() # Write: arm the capture (stopped depth//2 words after the trigger).
        self._trigger = CSRStorage(bits_for(len(flags) - 1),
            description="Trigger: flags bit index.")
        self._done    = CSRStatus(description="Capture done (triggered after arm, post-trigger "
            "entries stored).")
        self._index   = CSRStorage(bits_for(depth - 1),
            description="Entry to read (0: oldest): the raw word then the flags, in data0..data4.")
        self._data0   = CSRStatus(32, description="Entry bits [31:0].")
        self._data1   = CSRStatus(32, description="Entry bits [63:32].")
        wide = (len(rx_raw) + len(flags)) > 64
        if wide:
            self._data2 = CSRStatus(32, description="Entry bits [95:64].")
            self._data3 = CSRStatus(32, description="Entry bits [127:96].")
            self._data4 = CSRStatus(32, description="Entry bits [159:128].")

        # # #

        post_count = post

        mem = Memory(len(rx_raw) + len(flags), depth)
        wr  = mem.get_port(write_capable=True, clock_domain=clock_domain)
        rd  = mem.get_port(clock_domain="sys")
        self.specials += mem, wr, rd
        arm_ps = PulseSynchronizer("sys", clock_domain)
        self.submodules += arm_ps
        sel  = Signal(len(self._trigger.storage))
        done = Signal()
        self.specials += [
            MultiReg(self._trigger.storage, sel, clock_domain),
            MultiReg(done, self._done.status),
        ]
        armed = Signal()
        post  = Signal(max=depth)
        adr   = Signal(max=depth)
        start = Signal(max=depth)
        self.comb += arm_ps.i.eq(self._arm.re)
        sync = getattr(self.sync, clock_domain)
        sync += [
            If(arm_ps.o,
                armed.eq(1), done.eq(0), post.eq(0)
            ).Elif(~done & write_enable,
                adr.eq(adr + 1),
                If(armed & (flags >> sel)[0],
                    armed.eq(0), post.eq(depth//2 if post_count is None else post_count)
                ).Elif(post != 0,
                    post.eq(post - 1),
                    If(post == 1, done.eq(1), start.eq(adr + 1))
                )
            )
        ]
        self.comb += [
            wr.adr.eq(adr),
            wr.dat_w.eq(Cat(rx_raw, flags)),
            wr.we.eq(~done & write_enable),
            rd.adr.eq(start + self._index.storage),
            self._data0.status.eq(rd.dat_r[:32]),
            self._data1.status.eq(rd.dat_r[32:64]),
        ]
        if wide:
            self.comb += [
                self._data2.status.eq(rd.dat_r[64:96]),
                self._data3.status.eq(rd.dat_r[96:128]),
                self._data4.status.eq(rd.dat_r[128:]),
            ]

class CountSync(LiteXModule):
    """Counter of another clock domain read from sys: BusSynchronizer (a MultiReg on a changing
    counter gives torn reads)."""
    def __init__(self, i, o, idomain):
        self.bs = bs = BusSynchronizer(len(o), idomain, "sys")
        self.comb += [bs.i.eq(i), o.eq(bs.o)]

def add_usb3_gen2_rx(soc, serdes, phy):
    """Gen 2 bring-up: Gen 2 RX monitor on the raw transceiver symbols (the PHY switches to 10Gbps
    once Gen 2 is negotiated in SuperSpeedPlus Polling, USB3PHY.add_gen2) with its debug CSRs
    (usb3_gen2_rx_*: alignment status, blocks/Ordered Sets counters) and a raw RX snapshot."""
    # Gen 2 RX datapath/counters in a reset-less RX clock domain: kept across the RX
    # re-initializations (rate changes), counters accumulated over the 10Gbps periods.
    soc.cd_rx_nr = ClockDomain(reset_less=True)
    soc.comb += soc.cd_rx_nr.clk.eq(ClockSignal("rx"))
    gen2_rx = ClockDomainsRenamer("rx_nr")(Gen2RXDatapath())
    soc.usb3_gen2_rx_datapath = gen2_rx
    soc.comb += [
        gen2_rx.sink.valid.eq(1),
        gen2_rx.sink.data.eq(serdes.gen2_rx_data),
        gen2_rx.source.ready.eq(1),
    ]
    soc.usb3_gen2_rx = Gen2RXDebug(gen2_rx, clock_domain="rx_nr")
    aligner = gen2_rx.aligner
    soc.usb3_gen2_snapshot = RXRawSnapshot(serdes.gen2_rx_data, flags=Cat(
        aligner.source.valid & aligner.source.header_error,                 # 0: Header error.
        aligner.source.valid & aligner.source.header_error & aligner.locked, # 1: Header error (locked).
        aligner.error,                                                      # 2: Alignment error.
        aligner.aligned,                                                    # 3.
        aligner.locked,                                                     # 4.
        aligner.polarity,                                                   # 5.
        aligner.source.valid,                                               # 6.
    ))
    # TX raw words snapshot (tx_nr: reset-less tx clock), trigger 0: Data Block with Link Layer data
    # sent, 1: Gen 2 TX enabled.
    if hasattr(phy, "gen2_pipe"):
        soc.cd_tx_nr = ClockDomain(reset_less=True)
        soc.comb += soc.cd_tx_nr.clk.eq(ClockSignal("tx"))
        blocks = phy.gen2_pipe.tx_blocks
        soc.usb3_gen2_tx_snapshot = RXRawSnapshot(phy.gen2_pipe.tx_data, clock_domain="tx_nr",
            flags=Cat(blocks.valid & blocks.ready, blocks.last))
    # PHY Gen2PIPE events (sys): TS1/TS2 (8 consecutive) pulses at the Gen2PIPE and LTSSM inputs,
    # PHY Gen 2 RX aligner status.
    if hasattr(phy, "gen2_pipe"):
        gp = phy.gen2_pipe
        soc.usb3_gen2_events = CSRStatus(32*5, description="In U0: ts_rx_ts1 (LTSSM), ts_rx_ts2, "
            "ts_rx_ts2_reset cycles, PHY Gen2RX TS1 blocks, monitor TS1 blocks.")
        counts = [Signal(32) for _ in range(5)]
        u0 = phy.ltssm.u0
        for c, e in zip(counts[:3], [
            phy.ltssm.ts_rx_ts1,
            phy.ltssm.ts_rx_ts2,
            phy.ltssm.ts_rx_ts2_reset,
        ]):
            soc.sync += If(u0 & e, c.eq(c + 1))
        u0_rx = Signal()
        soc.specials += MultiReg(u0, u0_rx, "rx_nr")
        for c, e in zip(counts[3:], [gp.rx.rx.ts1, gen2_rx.rx.ts1]):
            c_rx = Signal(32)
            soc.sync.rx_nr += If(u0_rx & e, c_rx.eq(c_rx + 1))
            soc.submodules += CountSync(c_rx, c, "rx_nr")
        soc.comb += soc.usb3_gen2_events.status.eq(Cat(*counts))
        # PHY Gen 2 RX Link Layer path: RX blocks buffer overflow (sticky), framing errors (unknown
        # packet starts).
        soc.usb3_gen2_rx_link = CSRStatus(32,
            description="RX overflow [0], framing errors [31:16].")
        soc.specials += MultiReg(Cat(gp.rx_overflow, C(0, 15), gp.rx_framing.errors),
            soc.usb3_gen2_rx_link.status)
        aligner = gp.rx.aligner
        soc.usb3_gen2_phy_rx_status = CSRStatus(8,
            description="PHY Gen 2 RX: aligned, locked, polarity, data_stream.")
        soc.specials += MultiReg(
            Cat(aligner.aligned, aligner.locked, aligner.polarity, gp.rx.data_stream),
            soc.usb3_gen2_phy_rx_status.status[0:4])
    # RX Data Blocks snapshot (monitor, descrambled, rx_nr): trigger 0: Link Layer Recovery request.
    link = getattr(getattr(soc, "usb3_core", None), "link", None)
    if link is not None:
        # Trigger: LCRD_x received out of order (sys pulse stretched for the rx_nr domain).
        lcrd_err    = Signal()
        lcrd_err_rx = Signal()
        lcrd_count  = Signal(3)
        soc.sync += If(link.dbg_recovery_cause[2], lcrd_count.eq(7)).Elif(lcrd_count != 0,
            lcrd_count.eq(lcrd_count - 1))
        soc.comb += lcrd_err.eq(lcrd_count != 0)
        soc.specials += MultiReg(lcrd_err, lcrd_err_rx, "rx_nr")
        # Link Commands counts along the RX path (frozen on a LCRD_x out of order, rearm with the
        # CSR): framing output / words buffer writes (rx), words buffer reads / Link Layer input /
        # checked (sys).
        lrx   = phy.gen2_pipe.link_rx
        fr    = lrx.framing.source
        bsink = lrx.buffer.sink
        bsrc  = lrx.buffer.source
        src   = phy.source # PHY order: Symbol 0 on data[24:32].
        soc.usb3_gen2_lc_rearm = CSR() # Write: counts running again after a LCRD_x out of order.
        stop    = Signal()
        stop_rx = Signal()
        soc.sync += If(soc.usb3_gen2_lc_rearm.re,
            stop.eq(0)
        ).Elif(link.dbg_recovery_cause[2],
            stop.eq(1)
        )
        soc.specials += MultiReg(stop, stop_rx, "rx_nr")
        def is_lc(ep, swap=False):
            return ep.valid & ep.ready & (ep.ctrl[0:4] == 0b1111) & (
                (ep.data[24:32] if swap else ep.data[0:8]) == 0xfe)
        rx_events  = [is_lc(fr), is_lc(bsink), bsink.valid & bsink.ready]
        sys_events = [is_lc(bsrc), bsrc.valid & bsrc.ready, is_lc(src, swap=True) & phy.u0,
            link.dbg_rx_lc]
        counts = []
        for e in rx_events:
            c_rx = Signal(32)
            soc.sync.rx_nr += If(~stop_rx & e, c_rx.eq(c_rx + 1))
            c = Signal(32)
            soc.submodules += CountSync(c_rx, c, "rx_nr")
            counts.append(c)
        for e in sys_events:
            c = Signal(32)
            soc.sync += If(~stop & e, c.eq(c + 1))
            counts.append(c)
        soc.usb3_gen2_lc_counts = CSRStatus(32*7, description="rx: LC framing, LC buffer written, "
            "entries written; sys: LC buffer read, entries read, LC Link Layer input, LC checked.")
        soc.comb += soc.usb3_gen2_lc_counts.status.eq(Cat(*counts))

        # PHY Gen 2 RX Data Blocks (Gen2PIPE), flags: trigger, PHY data_stream, framing output.
        mon = phy.gen2_pipe.rx.rx.source
        lrx = phy.gen2_pipe.link_rx
        # Valid Data Blocks only (~6.8us of Data Blocks).
        soc.usb3_gen2_blocks_snapshot = RXRawSnapshot(Cat(mon.data, mon.valid),
            flags=Cat(lcrd_err_rx, phy.gen2_pipe.rx.rx.data_stream, lrx.framing.source.valid),
            depth=512, clock_domain="rx_nr",
            write_enable=mon.valid | lcrd_err_rx | ~phy.gen2_pipe.rx.rx.data_stream)
    # TX Data Blocks snapshot (unscrambled, Gen2LinkTX packer -> Gen2TX, blocks sent), stopped right
    # after a U0 exit (the last ~1000 blocks before it).
    if hasattr(phy, "gen2_pipe"):
        u0_exit    = Signal()
        u0_d       = Signal()
        u0_exit_tx = Signal()
        u0_count   = Signal(3)
        soc.sync += [
            u0_d.eq(phy.u0),
            If(u0_d & ~phy.u0, u0_count.eq(7)).Elif(u0_count != 0, u0_count.eq(u0_count - 1)),
        ]
        # Optional trigger: LBAD received (Header Packet received with errors by the partner).
        if link is not None:
            soc.usb3_gen2_txblocks_lbad = CSRStorage(1, description="TX Data Blocks snapshot also "
                "stopped on a LBAD received.")
            soc.sync += If(soc.usb3_gen2_txblocks_lbad.storage & link.dbg_lbad_rx, u0_count.eq(7))
        soc.comb += u0_exit.eq(u0_count != 0)
        soc.specials += MultiReg(u0_exit, u0_exit_tx, "tx_nr")
        # Gen2TX blocks: data (sink data blocks), idle (Logical Idle blocks) and SKP Ordered Sets,
        # with the unscrambled sink data.
        g2tx = phy.gen2_pipe.tx.tx
        pk   = phy.gen2_pipe.tx_blocks
        soc.usb3_gen2_txblocks_snapshot = RXRawSnapshot(
            Cat(pk.data, pk.last, g2tx.tx_data_blk, g2tx.tx_idle, g2tx.tx_skp),
            flags=Cat(u0_exit_tx), depth=1024, clock_domain="tx_nr",
            write_enable=g2tx.tx_data_blk | g2tx.tx_idle | g2tx.tx_skp | u0_exit_tx, post=8)
    # Transceiver electrical controls (Gen 2 signal integrity bring-up): TX swing/pre/post cursors,
    # RX equalizer (RXLPMEN: 1 LPM, 0 DFE).
    xcvr = getattr(serdes, serdes.xcvr_name)
    if hasattr(xcvr, "add_electrical_control"):
        xcvr.add_electrical_control()
        soc.usb3_gen2_rx_lpmen = CSRStorage(1, reset=1, description="RX equalizer: 1 LPM, 0 DFE.")
        xcvr.gty_params.update(i_RXLPMEN=soc.usb3_gen2_rx_lpmen.storage)
    # Link Layer max durations (sys cycles): LGOOD_n pending, LCRD_x pending, TX DPP data stall.
    if link is not None:
        soc.usb3_gen2_link_max = CSRStatus(32*3,
            description="Max cycles: LGOOD pending, LCRD pending, DPP stall.")
        soc.usb3_gen2_link_max_clear = CSR() # Write: clear the maximums.
        maxes = []
        for e in [link.dbg_lgood_pending, link.dbg_lcrd_pending, link.dbg_dpp_stall]:
            cnt = Signal(32)
            mx  = Signal(32)
            soc.sync += [
                If(e, cnt.eq(cnt + 1)).Else(cnt.eq(0)),
                If(soc.usb3_gen2_link_max_clear.re, mx.eq(0)).Elif(cnt > mx, mx.eq(cnt)),
            ]
            maxes.append(mx)
        soc.comb += soc.usb3_gen2_link_max.status.eq(Cat(*maxes))
    # Gen 2 capability advertised in SuperSpeedPlus Polling (0: Gen 1 operation, test of the Gen 1
    # datapath/fallback; applied at the next link training, ex: usb3_debug phy_reset).
    soc.usb3_gen2_capable = CSRStorage(1, reset=1, description="Gen 2 capability advertised.")
    soc.comb += phy.ssp.gen2_capable.eq(soc.usb3_gen2_capable.storage)
    soc.usb3_gen2_status = CSRStatus(2, description="Gen 2 negotiated [0], 10Gbps rate [1].")
    soc.comb += soc.usb3_gen2_status.status.eq(Cat(phy.gen2, serdes.rate_10g))

USB3_PROFILE_EVENTS = [
    "cycles", "u0",
    "link_tx_words", "link_tx_stall",                             # PHY sink: words, back-pressure.
    "link_tx_idle", "link_tx_full", "link_tx_credit", "link_dpp_stall",
    "in_dps", "in_no_data", "in_no_win", "in_fc", "in_hp_wait", "in_slots_full",
    "out_words",
    "hp_push", "hp_occupancy",                                     # Tx Header Buffers: pushes, sum of the count.
    "lgood_count", "lgood_rtt_sum", "lgood_rtt_max",               # Header Packet sent -> LGOOD_n received.
    "in_inflight_sum",                                             # Bulk IN: sum of the sent not acknowledged DPs.
]

def add_usb3_profile(soc, phy):
    """Throughput profile: cycles counters (sys) of the Link Layer TX and of the bench Bulk IN
    endpoint states (USB3_PROFILE_EVENTS), cleared/frozen by usb3_profile_control (clear, run)."""
    link = soc.usb3_core.link
    ep_in, ep_out = soc.usb3_core.endpoints[0:2]
    events = {
        "cycles"         : 1,
        "u0"             : phy.u0,
        "link_tx_words"  : phy.sink.valid & phy.sink.ready,
        "link_tx_stall"  : phy.sink.valid & ~phy.sink.ready,
        "link_tx_idle"   : link.dbg_tx_idle,
        "link_tx_full"   : link.dbg_tx_full,
        "link_tx_credit" : link.dbg_tx_credit,
        "link_dpp_stall" : link.dbg_dpp_stall,
        "in_dps"         : ep_in.jobs.sink.valid & ep_in.jobs.sink.ready,
        "in_no_data"     : ep_in.dbg_no_data,
        "in_no_win"      : ep_in.dbg_no_win,
        "in_fc"          : ep_in.dbg_fc,
        "in_hp_wait"     : ep_in.dbg_hp_wait,
        "in_slots_full"  : ep_in.dbg_inflight == ep_in.max_burst,
        "out_words"      : ep_out.slots.wr_port.we,
        "hp_push"        : link.dbg_tx_push,
        "hp_occupancy"   : link.dbg_tx_count,
        "in_inflight_sum": ep_in.dbg_inflight,
    }
    # Header Packet round trip: transmission start (send_seq) -> LGOOD_n received (per sequence
    # number timestamps, retransmissions overwrite them).
    time   = Signal(32)
    stamps = Array(Signal(32) for _ in range(16))
    rtt    = Signal(32)
    soc.sync += [
        time.eq(time + 1),
        If(link.dbg_tx_hp, stamps[link.dbg_tx_hp_info[0:4]].eq(time)),
    ]
    soc.comb += rtt.eq(time - stamps[link.dbg_lgood_seq])
    events["lgood_count"]   = link.dbg_lgood_rx
    events["lgood_rtt_sum"] = Mux(link.dbg_lgood_rx, rtt, 0)
    soc.usb3_profile_control = CSRStorage(fields=[
        CSRField("clear", size=1, offset=0, pulse=True, description="Clear the counters."),
        CSRField("run",   size=1, offset=1, reset=1,    description="Counting."),
    ])
    soc.usb3_profile = CSRStatus(32*len(USB3_PROFILE_EVENTS), description="Profile counters: " +
        ", ".join(USB3_PROFILE_EVENTS) + ".")
    ctrl   = soc.usb3_profile_control.fields
    counts = []
    for name in USB3_PROFILE_EVENTS:
        c = Signal(32, name=f"usb3_profile_{name}")
        if name == "lgood_rtt_max":
            soc.sync += If(ctrl.clear,
                c.eq(0)
            ).Elif(ctrl.run & link.dbg_lgood_rx & (rtt > c),
                c.eq(rtt)
            )
        else:
            # Counts (1-bit events) or sums (values), sized first (Verilog: operands extended to the
            # sum width before the event logic).
            e = Signal(max(len(Cat(events[name])), 1), name=f"usb3_profile_{name}_event")
            soc.comb += e.eq(events[name])
            soc.sync += If(ctrl.clear, c.eq(0)).Elif(ctrl.run, c.eq(c + e))
        counts.append(c)
    soc.comb += soc.usb3_profile.status.eq(Cat(*counts))

def add_usb3_device(soc, serdes, leds=[], leds_inverted=False,
    with_serdes_debug = False,
    with_core         = True,
    example           = "loopback",
    with_lpm          = False,
    max_burst         = 8,
    link_words        = 1,
    with_debug        = True,
    with_profile      = True,
    with_trace        = True,
    phy_cd            = None,
    phy_clk_freq      = None):
    """Add a USB3 device on serdes to soc: USB3PHY + debug, USB3 Device Core example design
    (with_core) and LEDs (SerDes ready, U0, Recovery).

    phy_cd: USB3PIPE (and serdes, renamed by the caller) in the phy_cd clock domain at phy_clk_freq,
    LTSSM/Link Layer/Core in sys (USB3PHY pipe_cd, ex: PIPE at 125MHz, Core at 62.5MHz with
    link_words=2), without PHY/SerDes debug.

    Note: a function (as add_usb3_example), not a USB3BaseSoC method, and the debug modules (XADC,
    LiteScope analyzer: usb3_analyzer) assigned from the target __init__: Migen signal names follow
    the instantiation stack (gateware/analyzer.csv names kept)."""
    sys_clk_freq = soc.sys_clk_freq

    # USB3 SerDes ----------------------------------------------------------------------------------
    soc.usb3_serdes = serdes

    # USB3 PHY (PIPE + LTSSM) ----------------------------------------------------------------------
    gen2_capable = getattr(serdes, "gen2_capable", False)
    assert (phy_cd is None) or not (with_serdes_debug or with_profile)
    soc.usb3_phy = usb3_phy = USB3PHY(
        serdes        = serdes,
        sys_clk_freq  = sys_clk_freq,
        role          = "device",
        gen2_capable  = gen2_capable,
        link_words    = link_words,
        pipe_cd       = phy_cd,
        pipe_clk_freq = phy_clk_freq,
        with_u1u2     = with_lpm or (phy_cd is None)) # U1/U2 only with LPM on slow fabrics.
    if (phy_cd is not None) and not with_debug:
        # Minimal PHY status (no USB3PHYDebug): LTSSM state (get_ltssm_states), U0, SerDes ready.
        usb3_phy.status = CSRStatus(fields=[
            CSRField("ltssm_state", size=len(usb3_phy.ltssm_state),
                description="LTSSM state (usb3_pipe.gen.get_ltssm_states)."),
            CSRField("u0",          size=1, offset=8, description="LTSSM in U0."),
            CSRField("ready",       size=1, offset=9, description="SerDes ready."),
        ])
        soc.comb += [
            usb3_phy.status.fields.ltssm_state.eq(usb3_phy.ltssm_state),
            usb3_phy.status.fields.u0.eq(usb3_phy.u0),
            usb3_phy.status.fields.ready.eq(usb3_phy.ready),
        ]

    # USB3 PHY/SerDes Debug ------------------------------------------------------------------------
    if with_debug:
        soc.usb3_debug = USB3PHYDebug(usb3_phy, serdes, sys_clk_freq)
    if with_serdes_debug:
        soc.usb3_serdes_debug = USB3SerDesDebug(serdes, sys_clk_freq,
            ltssm_state = usb3_phy.ltssm_state)

    # USB3 Core (Example design) -------------------------------------------------------------------
    if with_core:
        add_usb3_example(soc, usb3_phy, sys_clk_freq, example=example, with_lpm=with_lpm,
            max_burst=max_burst, with_trace=with_trace)
    else:
        soc.comb += usb3_phy.source.ready.eq(1)

    # Gen 2 bring-up debug (after the core: Link Layer probes). With phy_cd (slow fabrics): Gen 2
    # capability/status only.
    if gen2_capable and phy_cd is None:
        add_usb3_gen2_rx(soc, serdes, usb3_phy)
    elif gen2_capable:
        soc.usb3_gen2_capable = CSRStorage(1, reset=1, description="Gen 2 capability advertised.")
        soc.comb += usb3_phy.ssp.gen2_capable.eq(soc.usb3_gen2_capable.storage)
        soc.usb3_gen2_status = CSRStatus(2, description="Gen 2 negotiated [0], 10Gbps rate [1].")
        soc.comb += soc.usb3_gen2_status.status.eq(Cat(usb3_phy.gen2, serdes.rate_10g))

    # Throughput profile (Bulk IN/Link Layer TX cycles).
    if with_core and with_profile and hasattr(soc, "usb3_bench"):
        add_usb3_profile(soc, usb3_phy)

    # Leds -----------------------------------------------------------------------------------------
    for led, signal in zip(leds, [serdes.ready, usb3_phy.u0, usb3_phy.recovery]):
        soc.comb += led.eq(~signal if leds_inverted else signal)

# USB3 Gen 1x2 Link (PRBS) -------------------------------------------------------------------------

def add_usb3_lanes_link(soc, serdes, role="device", x2_capable=True, leds=[], leds_inverted=False,
    with_core = False,
    example   = "loopback",
    with_lpm  = False,
    max_burst = 8):
    """Add a Gen 1x2 link on serdes (2 lanes, Lane 0: Configuration Lane) to soc: USB3PHY(lanes=2) in
    the Host or Device role + debug (USB3PHYDebug on Lane 0, USB3LanesDebug), PRBS Link-Layer stand-ins
    (PRBSLinkTester on the 64-bit link words) and LEDs (SerDes ready, U0, x2 negotiated).

    The link is tested between two boards (one in each role, as sim.py --lanes 2,
    doc/gen1x2-hardware-validation.md). x2_capable=False: Gen 1x1 negotiated with the partner
    (single lane fallback on Lane 0, as sim.py --dev-mode x1).

    with_core (Host role): scripted USB host (USB3HostScript: USB3HostModel running the Gen 1x2
    enumeration + Bulk loopback script with the data checks, on a USB3PHYX2Link) for a Device board
    running the loopback example: the Gen 1x2 Device Core tested between two boards. Host not x2
    capable: SuperSpeed script, Gen 1x1 negotiated (the Device Core at Gen 1x1, as with a Gen 1x1
    USB host).

    with_core (Device role): USB3 Device Core example design instead of the PRBS stand-ins, through a
    dual SFP to USB-C breakout, Configuration Lane (plug orientation) detected (as sim.py --lanes 2
    --lanes-core), soc.usb3_link:
    - examples with 64-bit endpoints (loopback, wishbone, bench): USB3PHYX2Link, SuperSpeedPlus at
      Gen 1x2 with a Gen 1x2 host, SuperSpeed at Gen 1x1 otherwise.
    - other examples (32-bit endpoints): USB3PHYX1Link, the PHY not x2 capable: Gen 1x1.
    LEDs: SerDes ready, U0, lanes swapped."""
    sys_clk_freq = soc.sys_clk_freq
    assert len(serdes) == 2
    host_script = with_core and (role == "host")
    lanes_x2    = host_script or (with_core and (example in ["loopback", "wishbone", "bench"]))
    if with_core and not lanes_x2:
        x2_capable = False # Gen 1 Link Layer on 32-bit words: Gen 1x1 only.

    # USB3 SerDes ----------------------------------------------------------------------------------
    soc.usb3_serdes  = serdes[0]
    soc.usb3_serdes1 = serdes[1]

    # USB3 PHY (PIPEs + LTSSM) ---------------------------------------------------------------------
    soc.usb3_phy = usb3_phy = USB3PHY(
        serdes               = serdes,
        sys_clk_freq         = sys_clk_freq,
        role                 = role,
        with_endianness_swap = False,
        lanes                = 2,
        x2_capable           = x2_capable)
    if (not with_core) or host_script:
        soc.comb += usb3_phy.link_activity.eq(1) # No (native) Link Layer: no PM activity.

    # USB3 PHY/Lanes Debug -------------------------------------------------------------------------
    soc.usb3_debug = USB3PHYDebug(usb3_phy, serdes[0], sys_clk_freq)

    usb3_link = None
    if host_script:
        # Scripted USB Host ------------------------------------------------------------------------
        # RX buffer: a Device 1024-byte DPP (128 pairs at two words per cycle) taken by the script at
        # one word per cycle.
        soc.usb3_link   = usb3_link = USB3PHYX2Link(usb3_phy, rx_buffer_depth=512)
        # SuperSpeedPlus script at Gen 1x2, SuperSpeed script when the Host is not x2 capable (Gen 1x1
        # negotiated: as a Gen 1x1 USB host with the Device).
        soc.usb3_script = USB3HostScript(usb3_link, sys_clk_freq=sys_clk_freq)
    elif with_core:
        # USB3 Device Core -------------------------------------------------------------------------
        if lanes_x2:
            soc.usb3_link = usb3_link = USB3PHYX2Link(usb3_phy)
        else:
            soc.usb3_link = usb3_link = USB3PHYX1Link(usb3_phy)
        add_usb3_example(soc, usb3_link, sys_clk_freq, example=example, with_lpm=with_lpm,
            max_burst=max_burst)
    else:
        # PRBS Link-Layer Stand-Ins ----------------------------------------------------------------
        soc.usb3_prbs = PRBSLinkTester(usb3_phy, data_width=64)

    # Lanes Debug (with the USB3PHYX2Link RX buffer overflow/drops) --------------------------------
    soc.usb3_lanes_debug = USB3LanesDebug(usb3_phy, serdes, link=usb3_link)

    # Host Port Reset (Host role: Warm Reset when U0 is not reached, as the host software) --------
    if role == "host":
        soc.usb3_port_reset = USB3HostPortReset(usb3_phy, sys_clk_freq=sys_clk_freq)

    # Leds -----------------------------------------------------------------------------------------
    status = usb3_phy.lane_swap if (with_core and not host_script) else usb3_phy.x2
    for led, signal in zip(leds, [usb3_phy.ready, usb3_phy.u0, status]):
        soc.comb += led.eq(~signal if leds_inverted else signal)

# USB3 Host Port Reset ----------------------------------------------------------------------------

class USB3HostPortReset(LiteXModule):
    """Host port reset policy (as the host software resetting its port, xHCI PORTSC Warm Port
    Reset): a Warm Reset directed to the LTSSM (Downstream Port) when U0 is not reached for timeout
    seconds, the request held until the WarmReset state (or dropped on U0: a link in U0 is never
    reset). A Device left in Compliance (Polling.LFPS timeout before the Host started, ex: the
    Device board loaded first) only leaves it on a Warm Reset (7.5.5.2)."""
    def __init__(self, phy, sys_clk_freq=125e6, timeout=0.5):
        from litex.soc.interconnect.csr import CSRStorage, CSRStatus, CSRField
        from migen.genlib.misc import WaitTimer
        self._control = CSRStorage(fields=[
            CSRField("enable", size=1, offset=0, reset=1, description="Warm Reset when U0 is not reached."),
        ])
        self._count = CSRStatus(32, description="Warm Resets requested count.")

        # # #

        timer      = WaitTimer(int(timeout*sys_clk_freq))
        requesting = Signal()
        in_warm    = Signal()
        self.submodules += timer
        self.comb += in_warm.eq(phy.ltssm_state == phy.ltssm_states["WarmReset"])
        self.comb += [
            timer.wait.eq(self._control.fields.enable & ~phy.u0 & ~requesting & ~in_warm),
            phy.warm_reset_req.eq(requesting),
        ]
        self.sync += [
            If(phy.u0 | in_warm | ~self._control.fields.enable,
                requesting.eq(0)
            ).Elif(timer.done & ~requesting,
                requesting.eq(1),
                self._count.status.eq(self._count.status + 1),
            )
        ]

# USB3 Scripted Host -------------------------------------------------------------------------------

def usb3_host_idle_script(ssp=True):
    """Scripted USB host idle script (USB3HostScript out of the test runs): link initialization
    (Advertisements, Port Capability/Configuration LMPs), then the reactive acknowledges of the
    Device Header Packets (no Device Recovery on PENDING_HP_TIMER while the host is idle)."""
    from usb3_core.host_model import HostScript
    s = HostScript(ssp=ssp)
    s.link_init()
    s.auto_ack()
    s.end()
    return s

def usb3_host_script(ssp=True):
    """Scripted USB host script for the hardware tests (USB3HostScript, bench/usb3_lanes.py script):
    link initialization, enumeration-like control transfers and Bulk loopback (EP2 OUT -> EP1 IN) with
    the Bulk IN data checked, SuperSpeedPlus (Gen 1x2) or SuperSpeed (Gen 1x1) operation."""
    from usb3_core.host_model import enumeration_script
    return enumeration_script(skp=False, ssp=ssp, check_data=True)

class USB3HostScript(LiteXModule):
    """Scripted USB host (USB3HostModel) on a USB3PHYX2Link with CSRs: the script runs in U0 when
    enabled (restarted when disabled or out of U0), done/error/step status, passes/fails counters.

    Each run starts after a Hot Reset directed by the host (7.5.12, as a host resetting its port):
    the Header Sequence Numbers of both Link Layers are reset (the script is built with sequence
    numbers from 0); a U0 exit during a run (Recovery) restarts it with a new Hot Reset, a U0 exit
    after a run holds its result until disabled (one run per enable). Out of the
    script runs, a LUP keep-alive Link Command is sent every 10us in U0 (as a host, 7.5.6.1: the
    Device does not enter Recovery for a lack of link activity, 1ms) and, after a run, the model
    reactive acknowledges (LGOOD_n/LCRD_x of the Device Header Packets) are still sent: no Device
    Recovery for unacknowledged Header Packets between the runs (PENDING_HP_TIMER).

    Both scripts in the model ROM (SuperSpeedPlus, then SuperSpeed from step ss_start), the run
    starting on the one of the negotiated link (Gen 1x2: SuperSpeedPlus, Gen 1x1: SuperSpeed),
    latched at the run start (usb3_script_ssp)."""
    def __init__(self, link, sys_clk_freq=125e6, idle_delay=10e-3):
        from litex.soc.interconnect.csr import CSRStorage, CSRStatus, CSRField
        from litex.soc.interconnect import stream
        from usb3_pipe.framing  import WordsToPairs, PairsToWords
        from usb3_core.host_model import USB3HostModel
        self._control = CSRStorage(fields=[
            CSRField("enable", size=1, offset=0, reset=0, description="Run the script (in U0, restarted on 0 -> 1)."),
            CSRField("idle_init", size=1, offset=1, reset=1, description="Out of the runs, link initialization and acknowledges of the Device Header Packets (after a Hot Reset, on each U0 entry)."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("done",    size=1, offset=0, description="Script done (all the steps matched)."),
            CSRField("error",   size=1, offset=1, description="Script error (mismatch or timeout at step)."),
            CSRField("running", size=1, offset=2, description="Script running."),
        ])
        self._step   = CSRStatus(32, description="Current script step (failing step on error).")
        self._passes = CSRStatus(32, description="Scripts done count.")
        self._fails  = CSRStatus(32, description="Scripts errors count.")
        self._resets = CSRStatus(32, description="Hot Resets directed before the runs count.")
        self._ssp    = CSRStatus(description="Script of the current/last run: SuperSpeedPlus (Gen 1x2), SuperSpeed (Gen 1x1) otherwise.")

        # # #

        from migen.genlib.misc import WaitTimer
        from migen.genlib.fsm import FSM, NextState, NextValue
        from usb3_core.host_model import link_command, LUP
        from usb3_core.host_model import OP_END
        ssp_steps = usb3_host_script(ssp=True).steps
        ss_steps  = usb3_host_script(ssp=False).steps
        ss_start  = len(ssp_steps) + 1
        ssp_idle_steps = usb3_host_idle_script(ssp=True).steps
        ss_idle_steps  = usb3_host_idle_script(ssp=False).steps
        ssp_idle_start = ss_start + len(ss_steps) + 1
        ss_idle_start  = ssp_idle_start + len(ssp_idle_steps) + 1
        end = [(OP_END, 0, 0, 0, 0, 0)]
        self._ss_start = CSRStatus(32, reset=ss_start, description="First step of the SuperSpeed script (steps of the SuperSpeedPlus script before).")
        self.model = model = USB3HostModel(ssp_steps + end + ss_steps + end + ssp_idle_steps + end +
            ss_idle_steps)
        ssp  = Signal(reset=1) # Script of the run: the negotiated link out of the runs, kept during a
                               # run (the model step loaded from model.start while it is disabled).
        test = Signal()        # Run kind: test run (enable), else idle link initialization.
        self.comb += [
            model.start.eq(Mux(test, Mux(ssp, 0, ss_start), Mux(ssp, ssp_idle_start, ss_idle_start))),
            self._ssp.status.eq(ssp),
        ]
        self.pairs = pairs = WordsToPairs()
        self.words = words = PairsToWords()
        # RX words registered before the model (timing: the script steps compare them).
        self.rx_buffer = rx_buffer = stream.Buffer([("data", 32), ("ctrl", 4)], pipe_valid=True)

        # LUP keep-alive (out of the script runs).
        lup       = link_command(LUP())
        lup_timer = WaitTimer(int(10e-6*sys_clk_freq))
        lup_busy  = Signal()
        lup_word  = Signal()
        run       = Signal() # Script enabled (started between two LUPs, after a Hot Reset).
        active    = Signal() # Script running.
        model_tx  = Signal() # Model words to send (script, or acknowledges after the script).
        self.submodules += lup_timer

        # Runs: Hot Reset (Header Sequence Numbers reset on both sides), U0, script. Test runs when
        # enabled; out of them, an idle link initialization (idle_init, once per U0 entry).
        enable    = self._control.fields.enable
        idle_init = self._control.fields.idle_init
        idle_done = Signal() # Idle link initialization done since the U0 entry.
        abort     = Signal() # Run kind no longer wanted (test run disabled, or idle run superseded).
        self.comb += abort.eq(Mux(test, ~enable, enable | ~idle_init))
        # Idle link initialization after 10ms without a test run in U0 (not between two runs of a
        # client toggling enable: an idle Hot Reset then superseded in Recovery left the two sides
        # out of step, runs restarted).
        idle_timer = WaitTimer(max(1, int(idle_delay*sys_clk_freq)))
        self.submodules += idle_timer
        self.run_fsm = run_fsm = FSM(reset_state="IDLE")
        # Time without a test run (not U0 time: without the acknowledges of the idle initialization,
        # the Device leaves U0 every PENDING_HP_TIMER, the timer would never complete).
        self.comb += idle_timer.wait.eq(run_fsm.ongoing("IDLE") & ~enable & idle_init & ~idle_done)
        run_fsm.act("IDLE",
            If(link.u0 & ~lup_busy,
                If(enable,
                    NextValue(test, 1),
                    NextState("HOT-RESET")
                ).Elif(idle_timer.done,
                    NextValue(test, 0),
                    NextState("HOT-RESET")
                )
            )
        )
        run_fsm.act("HOT-RESET",
            # A Hot Reset once requested is not aborted (a request dropped in Recovery leaves the two
            # sides out of step): only a disabled test run returns to IDLE here.
            link.hot_reset_req.eq(1),
            If(test & ~enable,
                NextState("IDLE")
            ).Elif(link.hot_reset | link.polling_idle,
                NextState("WAIT-U0")
            )
        )
        run_fsm.act("WAIT-U0",
            If(abort,
                NextState("IDLE")
            ).Elif(link.u0 & ~lup_busy,
                NextState("RUN")
            )
        )
        self.sync += If(~run, ssp.eq(link.x2))
        held_done  = Signal() # Run result held out of U0 until disabled (one run per enable).
        held_error = Signal()
        self.sync += If(~link.u0 & ~run_fsm.ongoing("RUN"),
            idle_done.eq(0)
        ).Elif(run_fsm.ongoing("RUN") & ~test & model.done,
            idle_done.eq(1)
        )
        run_fsm.act("RUN",
            run.eq(1),
            If(abort,
                NextState("IDLE")
            ).Elif(~link.u0,
                If(test & (model.done | model.error),
                    NextValue(held_done,  model.done),
                    NextValue(held_error, model.error),
                    NextState("HELD")
                ).Else(
                    NextState("IDLE") # Run restarted with a new Hot Reset.
                )
            )
        )
        run_fsm.act("HELD",
            If(~enable,
                NextValue(held_done,  0),
                NextValue(held_error, 0),
                NextState("IDLE")
            )
        )
        resets_d = Signal()
        self.sync += [
            resets_d.eq(run_fsm.ongoing("HOT-RESET") & test),
            If(run_fsm.ongoing("HOT-RESET") & test & ~resets_d, self._resets.status.eq(self._resets.status + 1)),
        ]

        self.comb += [
            active.eq(run & ~model.done & ~model.error),
            model_tx.eq(active | (run & model.done & model.source.valid)),
            lup_timer.wait.eq(link.u0 & ~active & ~lup_busy),
            If(lup_busy,
                pairs.sink.valid.eq(1),
                pairs.sink.first.eq(~lup_word),
                pairs.sink.last.eq(lup_word),
                pairs.sink.data.eq(Mux(lup_word, lup[1][0], lup[0][0])),
                pairs.sink.ctrl.eq(Mux(lup_word, lup[1][1], lup[0][1])),
            ).Elif(model_tx,
                model.source.connect(pairs.sink),
            ),
        ]
        self.sync += [
            # LUP between two model words only (not inside a Link Command of the acknowledges).
            If(lup_timer.done & ~lup_busy & ~active & ~model.source.valid,
                lup_busy.eq(1),
                lup_word.eq(0),
            ).Elif(lup_busy & pairs.sink.ready,
                lup_word.eq(1),
                If(lup_word, lup_busy.eq(0)),
            ),
        ]
        self.comb += [
            pairs.source.connect(link.sink),
            link.source.connect(words.sink),
            words.source.connect(rx_buffer.sink),
            rx_buffer.source.connect(model.sink),
            model.enable.eq(run),
            model.u0.eq(link.u0),
            self._status.fields.done.eq((test & model.done) | held_done),
            self._status.fields.error.eq((test & model.error) | held_error),
            self._status.fields.running.eq(test & model.enable & ~model.done & ~model.error),
            self._step.status.eq(model.step),
        ]
        for name, signal in [("passes", test & run & model.done), ("fails", test & run & model.error)]:
            csr = getattr(self, f"_{name}")
            signal_d = Signal()
            self.sync += [
                signal_d.eq(signal),
                If(signal & ~signal_d, csr.status.eq(csr.status + 1)),
            ]

# USB3 Analyzer ------------------------------------------------------------------------------------

def usb3_analyzer(soc, group="link", csv="analyzer.csv"):
    """LiteScope analyzer on the soc USB3 PHY/SerDes (usb3_analyzer_groups group), to be assigned by
    the SoC: soc.analyzer = usb3_analyzer(soc, ...)."""
    groups = usb3_analyzer_groups(soc.usb3_phy, soc.usb3_serdes,
        serdes_debug = getattr(soc, "usb3_serdes_debug", None))
    assert group in groups, f"{group} group requires --with-serdes-debug."
    return LiteScopeAnalyzer(groups[group],
        depth        = 4096,
        clock_domain = "sys",
        register     = True,
        csr_csv      = csv
    )

# Arguments / Build --------------------------------------------------------------------------------

def usb3_soc_args(parser, output_dir, with_uartbone=True):
    """Common bench target arguments (with_uartbone: target with a UART,
    --no-uartbone/--with-jtagbone; JTAGBone only otherwise)."""
    parser.add_argument("--build",             action="store_true", help="Build bitstream.")
    parser.add_argument("--load",              action="store_true", help="Load bitstream.")
    parser.add_argument("--output-dir",        default=output_dir,  help=f"Build directory (default: {output_dir}).")
    if with_uartbone:
        parser.add_argument("--no-uartbone",   action="store_true", help="Disable UARTBone.")
        parser.add_argument("--with-jtagbone", action="store_true", help="Enable JTAGBone.")
    parser.add_argument("--cpu-type",          default=None,        help="CPU (console/composite examples, ex: vexriscv).")
    parser.add_argument("--no-core",           action="store_true", help="Build without the USB3 Core (PHY only).")
    parser.add_argument("--example",           default="loopback",  help="USB3 Device Core example design.", choices=USB3_EXAMPLES)
    parser.add_argument("--with-lpm",          action="store_true", help="U1/U2 Link Power Management (loopback/bench examples).")
    parser.add_argument("--lean",              action="store_true", help="No PHY debug, throughput profile and core trace (timings).")
    parser.add_argument("--max-burst",         default=8, type=int, help="Bulk endpoints Max Burst (loopback/bench examples).", choices=[2, 4, 8, 16])
    parser.add_argument("--link-words",        default=1, type=int, help="Link Layer words: 1 (32-bit), 2 (64-bit) or 4 (128-bit, Gen 2 with wide SerDes words), loopback/bench examples: Gen 2 bandwidth.", choices=[1, 2, 4])
    parser.add_argument("--with-serdes-debug", action="store_true", help="Enable SerDes debug (TX/loopback controls, clocks/RX errors measurements).")
    parser.add_argument("--with-analyzer",     action="store_true", help="Enable LiteScope Analyzer.")
    parser.add_argument("--analyzer-group",    default="link",      help="LiteScope probes group (phase: requires --with-serdes-debug, lanes/realign: --lanes 2).", choices=USB3_ANALYZER_GROUPS)

def usb3_soc_argdict(args):
    """Target SoC arguments from the common bench target arguments: USB3BaseSoC (bridges, CPU),
    analyzer (usb3_analyzer) and usb3_kwargs (add_usb3_device)."""
    return {
        "with_uartbone"     : not getattr(args, "no_uartbone", True),
        "with_jtagbone"     : getattr(args, "with_jtagbone", True),
        "cpu_type"          : args.cpu_type,
        "with_analyzer"     : args.with_analyzer,
        "analyzer_group"    : args.analyzer_group,
        "analyzer_csv"      : os.path.join(args.output_dir, "analyzer.csv"),
        "usb3_kwargs"       : {
            "with_serdes_debug" : args.with_serdes_debug,
            "with_core"         : not args.no_core,
            "example"           : args.example,
            "with_lpm"          : args.with_lpm,
            "max_burst"         : args.max_burst,
            "link_words"        : args.link_words,
            "with_debug"        : not args.lean,
            "with_profile"      : not args.lean,
            "with_trace"        : not args.lean,
        },
    }

def usb3_soc_build(parser, args, soc, **kwargs):
    """Build (--build, kwargs: toolchain arguments) and load (--load) soc."""
    if not args.build and not args.load:
        parser.print_help()
    builder = Builder(soc,
        output_dir = args.output_dir,
        csr_csv    = os.path.join(args.output_dir, "csr.csv"))
    builder.build(run=args.build, **kwargs)
    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(os.path.join(builder.gateware_dir, soc.build_name + ".bit"))
