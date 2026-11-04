#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Dual-lane (Gen 1x2) building blocks (USB 3.2 6.13), see doc/gen2-x2-roadmap.md.

- LaneStriper   : 64-bit link words (8 symbols, symbol 0 on data[0:8]) striped on two 32-bit lanes,
                  aligned to Lane 0: even symbols on Lane 0, odd symbols on Lane 1 (6.13.4). A word
                  is given to both lanes in the same cycle (lanes ready independent of valid).
- LaneDestriper : two 32-bit lanes to 64-bit link words.
- LaneDeskew    : aligns two lanes on a marker word (ex: Ordered Set duplicated on both lanes,
                  6.13.6, first marker after a gap on both lanes), the lanes are then released in
                  lockstep (the two sources must be consumed together, ex: by a LaneDestriper).
- LaneSwap      : logical lanes on two physical SerDes (USB Type-C plug orientation), Configuration
                  Lane detection from the partner's Polling.LFPS.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from usb3_pipe.common import SHP, SDP, SLC, EPF

# Layouts ------------------------------------------------------------------------------------------

def lane_layout():
    return [("data", 32), ("ctrl", 4)]

def link_layout():
    return [("data", 64), ("ctrl", 8)]

# Lane Striper -------------------------------------------------------------------------------------

class LaneStriper(LiteXModule):
    def __init__(self):
        self.sink    = sink    = stream.Endpoint(link_layout())
        self.sources = sources = [stream.Endpoint(lane_layout()) for _ in range(2)]

        # # #

        # A word is given to both lanes or to none: presented only when both lanes are ready (the
        # lanes ready must not depend on valid).
        self.comb += sink.ready.eq(sources[0].ready & sources[1].ready)
        for lane, source in enumerate(sources):
            self.comb += [
                source.valid.eq(sink.valid & sink.ready),
                source.first.eq(sink.first), # Packets boundaries (TX SKP Ordered Sets between packets).
                source.last.eq(sink.last),
                source.data.eq(Cat(*[sink.data[8*(2*i + lane):8*(2*i + lane + 1)] for i in range(4)])),
                source.ctrl.eq(Cat(*[sink.ctrl[2*i + lane] for i in range(4)])),
            ]

# Lane Destriper -----------------------------------------------------------------------------------

class LaneDestriper(LiteXModule):
    def __init__(self):
        self.sinks  = sinks  = [stream.Endpoint(lane_layout()) for _ in range(2)]
        self.source = source = stream.Endpoint(link_layout())

        # # #

        self.comb += [
            source.valid.eq(sinks[0].valid & sinks[1].valid),
            sinks[0].ready.eq(source.valid & source.ready),
            sinks[1].ready.eq(source.valid & source.ready),
        ]
        for i in range(4):
            for lane in range(2):
                self.comb += [
                    source.data[8*(2*i + lane):8*(2*i + lane + 1)].eq(sinks[lane].data[8*i:8*(i+1)]),
                    source.ctrl[2*i + lane].eq(sinks[lane].ctrl[i]),
                ]

# Lane Deskew --------------------------------------------------------------------------------------

class LaneDeskew(LiteXModule):
    """Two lanes deskew (up to depth words of skew) on a marker word (ex: COM words of the TS1/TS2
    Ordered Sets, duplicated on both lanes, 6.13.6).

    The markers are paired independently of the lanes latencies (per lane word alignment, SKP removal
    and RX buffers fill levels: up to a few words, a periodic marker would be ambiguous): the search
    is armed after a gap of gap words without marker on both lanes (ex: TSEQ or Logical Idle before
    the TS1 Ordered Sets), then the first marker received on each lane are the same marker. The words
    before it are dropped, then both lanes are released together. A marker at the head of a single
    lane (lanes no longer paired: ex: word alignment of a lane changed after the pairing) restarts the
    search (armed on the next gap).

    The sinks are never held (continuous lanes streams, a held lane would overflow the SerDes RX
    buffers): words received with a full FIFO are dropped.
    """
    def __init__(self, marker_data, marker_ctrl, depth=8, gap=16):
        self.sinks   = sinks   = [stream.Endpoint(lane_layout()) for _ in range(2)]
        self.sources = sources = [stream.Endpoint(lane_layout()) for _ in range(2)]
        self.aligned = aligned = Signal() # o

        # # #

        self.fifos = fifos = [stream.SyncFIFO(lane_layout(), depth) for _ in range(2)]
        self.submodules += fifos
        heads = []
        gaps  = []
        for lane in range(2):
            head      = Signal()
            gap_count = Signal(max=gap + 1)
            marker_in = Signal()
            self.comb += [
                sinks[lane].connect(fifos[lane].sink, omit={"ready"}),
                sinks[lane].ready.eq(1),
                marker_in.eq((sinks[lane].data == marker_data) & (sinks[lane].ctrl == marker_ctrl)),
                head.eq(fifos[lane].source.valid &
                    (fifos[lane].source.data == marker_data) & (fifos[lane].source.ctrl == marker_ctrl)),
            ]
            # Words without marker received on the lane (saturated to gap).
            self.sync += If(sinks[lane].valid,
                If(marker_in,
                    gap_count.eq(0)
                ).Elif(gap_count != gap,
                    gap_count.eq(gap_count + 1)
                )
            )
            heads.append(head)
            gaps.append(gap_count == gap)
        self.heads = heads

        # Search armed after a gap on both lanes (no marker in the FIFOs, dropped while searching),
        # first markers paired; aligned until the markers are no longer paired.
        armed = Signal()
        both  = Signal()
        self.comb += both.eq(fifos[0].source.valid & fifos[1].source.valid)
        self.sync += [
            If(~aligned,
                If(gaps[0] & gaps[1],
                    armed.eq(1)
                ).Elif(armed & heads[0] & heads[1],
                    aligned.eq(1),
                    armed.eq(0)
                )
            ).Elif(both & (heads[0] != heads[1]),
                aligned.eq(0)
            )
        ]
        for lane in range(2):
            self.comb += [
                If(aligned,
                    sources[lane].valid.eq(both),
                    sources[lane].data.eq(fifos[lane].source.data),
                    sources[lane].ctrl.eq(fifos[lane].source.ctrl),
                    fifos[lane].source.ready.eq(both & sources[0].ready & sources[1].ready),
                ).Else(
                    # Searching: drop the words (armed: the words before the first marker).
                    fifos[lane].source.ready.eq(fifos[lane].source.valid & ~(armed & heads[lane])),
                )
            ]

# Lane Swap ----------------------------------------------------------------------------------------

# SerDes signals of the Gen 1 interface used by the USB3PIPE (sys clock domain): inputs (driven by the
# PIPE) and outputs, sink/source streams.
LANE_SWAP_INPUTS  = ["tx_idle", "tx_pattern", "tx_lfps", "tx_polarity", "rx_polarity",
    "tx_skp_enable", "rx_align"]
LANE_SWAP_OUTPUTS = ["ready", "rx_idle", "rx_errors"]

class LaneSerDes:
    """Logical lane SerDes (LaneSwap): the Gen 1 SerDes interface of a physical SerDes."""
    def __init__(self, serdes):
        for name in LANE_SWAP_INPUTS + LANE_SWAP_OUTPUTS:
            setattr(self, name, Signal.like(getattr(serdes, name), name=name))
        self.sink   = stream.Endpoint(serdes.sink.description)
        self.source = stream.Endpoint(serdes.source.description)
        self.rx_idle_stretch = serdes.rx_idle_stretch
        self.xcvr_name       = None
        self.gen2_capable    = False

class LaneSwap(LiteXModule):
    """Logical lanes (sources: Lane 0 = Configuration Lane, Lane 1) on two physical SerDes: logical
    Lane i on the physical SerDes i ^ swap (USB Type-C plug orientation, 6.13.1: a flipped plug swaps
    the lanes). The Gen 1 SerDes interface of the USB3PIPE is muxed (sys clock domain); swap is
    expected to change only while the lanes do not transmit data (Rx.Detect/Polling.LFPS).

    With detect, swap follows the lane receiving the partner's Polling.LFPS (sent on its Configuration
    Lane only, 6.13.12) while enable (ex: LTSSM in Polling.LFPS): LFPS activity (rx_idle de-asserted)
    for burst_cycles on a single physical lane selects it as Configuration Lane."""
    def __init__(self, serdes, detect=False, burst_cycles=16):
        assert len(serdes) == 2
        self.lanes  = lanes = [LaneSerDes(s) for s in serdes]
        self.swap   = swap  = Signal() # i (detect=False) / o (detect=True).
        self.enable = Signal()         # i: Detection enable (detect=True).

        # # #

        for p in range(2):
            phys = serdes[p]
            for name in LANE_SWAP_INPUTS:
                self.comb += getattr(phys, name).eq(
                    Mux(swap, getattr(lanes[1 - p], name), getattr(lanes[p], name)))
            for name in LANE_SWAP_OUTPUTS:
                self.comb += getattr(lanes[p], name).eq(
                    Mux(swap, getattr(serdes[1 - p], name), getattr(serdes[p], name)))
            # TX: logical lane sink -> physical SerDes sink (ready back).
            a, b = lanes[p].sink, lanes[1 - p].sink
            for name in [n for n, *_ in phys.sink.description.payload_layout] + ["valid", "first", "last"]:
                self.comb += getattr(phys.sink, name).eq(Mux(swap, getattr(b, name), getattr(a, name)))
            self.comb += lanes[p].sink.ready.eq(Mux(swap, serdes[1 - p].sink.ready, phys.sink.ready))
            # RX: physical SerDes source -> logical lane source (ready back).
            a, b = serdes[p].source, serdes[1 - p].source
            for name in [n for n, *_ in phys.source.description.payload_layout] + ["valid", "first", "last"]:
                self.comb += getattr(lanes[p].source, name).eq(Mux(swap, getattr(b, name), getattr(a, name)))
            self.comb += phys.source.ready.eq(Mux(swap, lanes[1 - p].source.ready, lanes[p].source.ready))

        # Configuration Lane detection -------------------------------------------------------------
        if detect:
            active = [Signal(max=burst_cycles + 1) for _ in range(2)]
            for p in range(2):
                self.sync += If(serdes[p].rx_idle,
                    active[p].eq(0)
                ).Elif(active[p] != burst_cycles,
                    active[p].eq(active[p] + 1)
                )
            self.sync += If(self.enable,
                If((active[1] == burst_cycles) & serdes[0].rx_idle,
                    swap.eq(1)
                ).Elif((active[0] == burst_cycles) & serdes[1].rx_idle,
                    swap.eq(0)
                )
            )

# Lanes Framing Aligner ----------------------------------------------------------------------------

class LanesFramingAligner(LiteXModule):
    """64-bit link words (destriped lanes, Symbol 0 on data[0:8]) re-aligned on the packets framing
    Ordered Sets: packets and Link Commands may start on either lane (6.13.4), at any symbol position
    of the 64-bit words. The words are shifted by 0-3 symbols for the framing (SHP/SDP/SLC marker run)
    to start on a 32-bit word boundary (as RXWordAligner for Gen 1x1): link words pairs for a Link
    Layer. The alignment is updated at the start of a marker run (12 Logical Idle symbols needed
    before a re-aligned framing, see below), the words are output with one word of latency."""
    def __init__(self, markers=(SHP, SDP, SLC)):
        self.sink   = sink   = stream.Endpoint(link_layout())
        self.source = source = stream.Endpoint(link_layout())

        # # #

        self.buf = buf = stream.Buffer(link_layout())
        self.comb += [
            sink.connect(buf.sink),
            source.valid.eq(sink.valid & buf.source.valid),
            buf.source.ready.eq(sink.valid & source.ready),
        ]

        def is_marker(data, ctrl):
            return ctrl & Reduce("OR", [data == m.value for m in markers])
        marker   = Signal(8)
        marker_d = Signal(8)
        for i in range(8):
            self.comb += marker[i].eq(is_marker(sink.data[8*i:8*(i+1)], sink.ctrl[i]))
            self.comb += marker_d[i].eq(is_marker(buf.source.data[8*i:8*(i+1)], buf.source.ctrl[i]))

        # Alignment: first marker of the word (modulo 4 symbols), updated at the start of a marker
        # run (no marker on the last symbol of the previous word). A run starting in the first half
        # of the word (symbols 0-3) is aligned on the output word of this cycle, in the second half
        # (symbols 4-7) on the next one: the symbols dropped/repeated by a re-alignment (up to 3)
        # are within the 11 symbols before the framing: a re-aligned framing needs 12 Logical Idle
        # symbols before it (packets of a partner keeping its packets on 64-bit boundaries, as
        # LanesTXPacker, are never re-aligned). Not supported yet: a framing right after a DPP of
        # a length not a multiple of 4 symbols without Logical Idle symbols between them (would need
        # the partial word completed with Logical Idle symbols instead).
        position      = Signal(3)
        run_start     = Signal()
        pending       = Signal()
        pending_al    = Signal(2)
        alignment_d   = Signal(2)
        alignment_sel = Signal(2)
        for i in reversed(range(8)):
            self.comb += If(marker[i], position.eq(i))
        self.comb += [
            run_start.eq((marker != 0) & ~marker_d[7]),
            alignment_sel.eq(Mux(pending, pending_al, alignment_d)),
            If(run_start & ~position[2],
                alignment_sel.eq(position[0:2])
            )
        ]
        self.sync += If(sink.valid & sink.ready,
            alignment_d.eq(alignment_sel),
            pending.eq(run_start & position[2]),
            pending_al.eq(position[0:2]),
        )

        # Data selection (previous word in the LSBs).
        data = Cat(buf.source.data, sink.data)
        ctrl = Cat(buf.source.ctrl, sink.ctrl)
        self.comb += Case(alignment_sel, {a: [
            source.data.eq(data[8*a:8*a + 64]),
            source.ctrl.eq(ctrl[a:a + 8]),
        ] for a in range(4)})

# Lanes Idle Filter --------------------------------------------------------------------------------

def link_pairs_layout():
    """Link words pairs (words: 1 or 2 valid words, word 0 first: data[0:32]/ctrl[0:4])."""
    return [("data", 64), ("ctrl", 8), ("words", 2)]

class LanesIdleFilter(LiteXModule):
    """64-bit link words (two link words, framing at 32-bit word boundaries: LanesFramingAligner) ->
    link words pairs without the Logical Idle words between the packets (as LogicalIdleFilter, two
    words per cycle): Header Packet: SHP framing word and 4 words, Link Command: SLC framing word and
    1 word, DPP: from the SDP framing word to the EPF of its END/EDB framing. Continuous input (no
    back-pressure), output registered."""
    def __init__(self):
        self.sink   = sink   = stream.Endpoint(link_layout())
        self.source = source = stream.Endpoint(link_pairs_layout())

        # # #

        OUT, HPLC, DPP = 0, 1, 2
        mode  = Signal(2)
        count = Signal(2)

        def flags(w):
            data, ctrl = sink.data[32*w:32*(w+1)], sink.ctrl[4*w:4*(w+1)]
            def has(symbol):
                return Reduce("OR", [ctrl[i] & (data[8*i:8*(i+1)] == symbol.value) for i in range(4)])
            return (data == 0) & (ctrl == 0), has(SHP), has(SLC), has(SDP), has(EPF)

        def step(m, c, w):
            """Word w with state (m, c): (keep, next mode, next count) signals."""
            idle, shp, slc, sdp, epf = flags(w)
            keep, nm, nc = Signal(), Signal(2), Signal(2)
            self.comb += [
                keep.eq(1), nm.eq(m), nc.eq(c),
                Case(m, {
                    OUT: [
                        keep.eq(~idle),
                        If(shp,    nm.eq(HPLC), nc.eq(4 - 1)
                        ).Elif(slc, nm.eq(HPLC), nc.eq(1 - 1)
                        ).Elif(sdp, nm.eq(DPP)),
                    ],
                    HPLC: If(c == 0, nm.eq(OUT)).Else(nc.eq(c - 1)),
                    DPP:  If(epf, nm.eq(OUT)),
                    "default": nm.eq(OUT),
                }),
            ]
            return keep, nm, nc

        keep0, m1, c1 = step(mode, count, 0)
        keep1, m2, c2 = step(m1, c1, 1)
        self.comb += sink.ready.eq(1)
        self.sync += [
            source.valid.eq(0),
            If(sink.valid,
                mode.eq(m2),
                count.eq(c2),
                source.valid.eq(keep0 | keep1),
                source.words.eq(keep0 + keep1),
                If(keep0,
                    source.data.eq(sink.data),
                    source.ctrl.eq(sink.ctrl),
                ).Else(
                    source.data.eq(sink.data[32:64]),
                    source.ctrl.eq(sink.ctrl[4:8]),
                )
            )
        ]

# Lanes TX Packer ----------------------------------------------------------------------------------

class LanesTXPacker(LiteXModule):
    """Link words pairs (1 or 2 words per entry, packets first/last, a pair never spans two packets)
    -> 64-bit link words for the striped lanes (two words per entry, packets first/last): a 64-bit
    word never holds words of two packets, the word after the last word of a packet is a Logical Idle
    word (both lanes end the packets together: SKP Ordered Sets inserted on both lanes between the
    packets, 6.4.3.2). Up to two words per cycle (pairs of two words, or a held word + one word)."""
    def __init__(self):
        self.sink   = sink   = stream.Endpoint(link_pairs_layout())
        self.source = source = stream.Endpoint(link_layout())

        # # #

        held       = Signal()
        held_first = Signal()
        held_last  = Signal()
        held_data  = Signal(32, reset_less=True)
        held_ctrl  = Signal(4,  reset_less=True)
        two = sink.words == 2

        # Outputs.
        self.comb += [
            If(held & held_last,
                # Held last word of a packet + Logical Idle word.
                source.valid.eq(1),
                source.data.eq(Cat(held_data, Constant(0, 32))),
                source.ctrl.eq(Cat(held_ctrl, Constant(0, 4))),
                source.first.eq(held_first),
                source.last.eq(1),
            ).Elif(held,
                # Held word + first word of the entry.
                source.valid.eq(sink.valid),
                source.data.eq(Cat(held_data, sink.data[0:32])),
                source.ctrl.eq(Cat(held_ctrl, sink.ctrl[0:4])),
                source.first.eq(held_first),
                source.last.eq(sink.last & ~two),
                sink.ready.eq(source.ready),
            ).Elif(two,
                source.valid.eq(sink.valid),
                source.data.eq(sink.data),
                source.ctrl.eq(sink.ctrl),
                source.first.eq(sink.first),
                source.last.eq(sink.last),
                sink.ready.eq(source.ready),
            ).Elif(sink.last,
                # Last word of a packet alone + Logical Idle word.
                source.valid.eq(sink.valid),
                source.data.eq(Cat(sink.data[0:32], Constant(0, 32))),
                source.ctrl.eq(Cat(sink.ctrl[0:4], Constant(0, 4))),
                source.first.eq(sink.first),
                source.last.eq(1),
                sink.ready.eq(source.ready),
            ).Else(
                # Word alone (not last): held.
                sink.ready.eq(1),
            )
        ]
        # Held word.
        self.sync += [
            If(source.valid & source.ready,
                held.eq(0)
            ),
            If(sink.valid & sink.ready,
                If(held & two,
                    held.eq(1),
                    held_first.eq(0),
                    held_last.eq(sink.last),
                    held_data.eq(sink.data[32:64]),
                    held_ctrl.eq(sink.ctrl[4:8]),
                ).Elif(~held & ~two & ~sink.last,
                    held.eq(1),
                    held_first.eq(sink.first),
                    held_last.eq(0),
                    held_data.eq(sink.data[0:32]),
                    held_ctrl.eq(sink.ctrl[0:4]),
                )
            )
        ]
