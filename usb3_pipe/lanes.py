#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Dual-lane (Gen 1x2) building blocks (USB 3.2 6.13), see doc/notes/gen2-x2-roadmap.md.

- LaneStriper   : 64-bit link words (8 symbols, symbol 0 on data[0:8]) striped on two 32-bit lanes,
                  aligned to Lane 0: even symbols on Lane 0, odd symbols on Lane 1 (6.13.4). A word
                  is given to both lanes in the same cycle (lanes ready independent of valid).
- LaneDestriper : two 32-bit lanes to 64-bit link words.
- LaneDeskew    : aligns two lanes on a marker word (ex: Ordered Set duplicated on both lanes,
                  6.13.6, first marker after a gap on both lanes), the lanes are then released in
                  lockstep (the two sources must be consumed together, ex: by a LaneDestriper).
- LaneSwap      : logical lanes on two physical SerDes (USB Type-C plug orientation), Configuration
                  Lane detection from the partner's Polling.LFPS.
- LanesPacketAligner : destriped 64-bit link words -> link words pairs of the packets (any packet
                  placement, each packet starting on a 32-bit word, Logical Idle removed).
- LanesTXPacker : link words pairs -> 64-bit link words for the striper (packets on 64-bit words).
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
    """TX data striping (6.13.4): sink (64-bit link words, link_layout) -> sources[0]/sources[1]
    (32-bit lane words, lane_layout): even symbols on Lane 0, odd symbols on Lane 1, both lanes
    accepting the words in lockstep (sink.ready = both sources ready)."""
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
                source.data.eq(Cat(*[sink.data[8*(2*i + lane):8*(2*i + lane + 1)]
                    for i in range(4)])),
                source.ctrl.eq(Cat(*[sink.ctrl[2*i + lane] for i in range(4)])),
            ]

# Lane Destriper -----------------------------------------------------------------------------------

class LaneDestriper(LiteXModule):
    """RX data destriping (6.13.4): sinks[0]/sinks[1] (32-bit lane words, deskewed: a word is
    consumed on both lanes together) -> source (64-bit link words, link_layout, Lane 0 symbols on
    the even positions)."""
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
    before it are dropped, then both lanes are released together. Markers at the head of a single lane
    twice without paired markers in between (lanes no longer paired: ex: word alignment of a lane
    changed after the pairing, a mismatch at each Ordered Set) restart the search (armed on the next
    gap), as clear (ex: a lane in electrical idle). A single mismatch is tolerated: the last markers of
    an Ordered Sets stream one word apart on the lanes (ex: a decode error substituted at the end of
    the TS2 Ordered Sets on one lane, Logical Idle after them: two Acorn Minis), the lanes still
    paired.

    The sinks are never held (continuous lanes streams, a held lane would overflow the SerDes RX
    buffers): words received with a full FIFO are dropped.
    """
    def __init__(self, marker_data, marker_ctrl, depth=8, gap=16):
        self.sinks   = sinks   = [stream.Endpoint(lane_layout()) for _ in range(2)]
        self.sources = sources = [stream.Endpoint(lane_layout()) for _ in range(2)]
        self.aligned = aligned = Signal() # o
        self.armed   = armed   = Signal() # o: Search armed (gap seen, pairing on the next markers).
        self.clear   = Signal()           # i: Pairing cleared (search re-armed on the next gap).

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
                    (fifos[lane].source.data == marker_data) &
                    (fifos[lane].source.ctrl == marker_ctrl)),
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
        # first markers paired; aligned until the markers are no longer paired (second mismatch
        # without paired markers in between).
        both     = Signal()
        mismatch = Signal()
        self.comb += both.eq(fifos[0].source.valid & fifos[1].source.valid)
        self.sync += [
            If(self.clear,
                aligned.eq(0),
                armed.eq(0),
                mismatch.eq(0)
            ).Elif(~aligned,
                mismatch.eq(0),
                If(gaps[0] & gaps[1],
                    armed.eq(1)
                ).Elif(armed & heads[0] & heads[1],
                    aligned.eq(1),
                    armed.eq(0)
                )
            ).Elif(both & (heads[0] != heads[1]),
                If(mismatch,
                    aligned.eq(0)
                ).Else(
                    mismatch.eq(1)
                )
            ).Elif(both & heads[0] & heads[1],
                mismatch.eq(0)
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

def link_pairs_layout():
    """Link words pairs (words: 1 or 2 valid words, word 0 first: data[0:32]/ctrl[0:4])."""
    return [("data", 64), ("ctrl", 8), ("words", 2)]

class LanesPacketAligner(LiteXModule):
    """64-bit link words (destriped lanes, Symbol 0 on data[0:8]) -> link words pairs of the
    packets only, each packet starting on a 32-bit word (as RXWordAligner + LogicalIdleFilter for
    Gen 1x1), for packets at any symbol position of the 64-bit words (they may start on either
    lane, 6.13.4) with any number of Logical Idle symbols between them (none included).

    Symbols parser (8 symbols per cycle): a packet starts on a SHP/SLC/SDP K-symbol outside of a
    packet: Header Packet: 20 symbols (framing, 12-byte header, CRC-16, Link Control Word), Link
    Command: 8 symbols, DPP: from the SDP framing to the EPF of its END/EDB framing (7.2.1,
    7.2.4). The packets symbols are packed (Logical Idle removed) in a symbols buffer, the last
    word of a packet completed with Logical Idle symbols (00h data, as received from a partner
    keeping its packets on 32-bit words): a packet always starts on a 32-bit word. Up to two words
    per cycle on the output (registered, no back-pressure: four cycles of latency); the completion
    of the DPPs adds up to 3 symbols per packet, absorbed by the symbols buffer (buffer_symbols,
    overflow: sticky flag, never with Logical Idle or a SKP Ordered Set every few packets).

    Not handled (as the Gen 1x1 path): a corrupted first framing symbol (the packet is then taken
    from the next symbol, misaligned: CRC error and retry by the Link Layer), a corrupted EPF at
    the end of a DPP (the DPP ends at the next EPF)."""
    def __init__(self, buffer_symbols=32):
        assert buffer_symbols % 4 == 0
        self.sink     = sink   = stream.Endpoint(link_layout())
        self.source   = source = stream.Endpoint(link_pairs_layout())
        self.overflow = Signal() # o: Symbols buffer overflow (sticky).

        # # #

        IDLE, FIXED, DPP_FRAMING, DPP = range(4)

        # Symbols parser (registered: symbol, keep, end of packet) ---------------------------------
        mode  = Signal(2)
        count = Signal(5)
        sym   = [Signal(9, name=f"sym{i}")  for i in range(8)] # {k, data}.
        keep  = [Signal(name=f"keep{i}")    for i in range(8)] # Packet symbol.
        last  = [Signal(name=f"last{i}")    for i in range(8)] # Last symbol of a packet.
        valid = Signal()
        self.comb += sink.ready.eq(1)

        # Input registered with the framing K-symbols decoded (timing: the 64-bit words come
        # straight from the lanes destriping/deskew FIFOs).
        in_valid = Signal()
        in_data  = Signal(64)
        in_ctrl  = Signal(8)
        in_k     = {s: [Signal(name=f"is_{n}{i}") for i in range(8)]
            for s, n in [(SHP, "shp"), (SLC, "slc"), (SDP, "sdp"), (EPF, "epf")]}
        self.sync += [
            in_valid.eq(sink.valid),
            in_data.eq(sink.data),
            in_ctrl.eq(sink.ctrl),
        ]
        for i in range(8):
            for s in in_k:
                self.sync += in_k[s][i].eq(sink.ctrl[i] & (sink.data[8*i:8*(i+1)] == s.value))

        m, c = mode, count
        for i in range(8):
            data, k = in_data[8*i:8*(i+1)], in_ctrl[i]
            def is_k(symbol):
                return in_k[symbol][i]
            _keep, _last = Signal(), Signal()
            nm, nc = Signal(2, name=f"mode{i}"), Signal(5, name=f"count{i}")
            self.comb += [
                _keep.eq(1), _last.eq(0), nm.eq(m), nc.eq(c - 1),
                Case(m, {
                    IDLE: [
                        _keep.eq(0),
                        If(is_k(SHP),
                            _keep.eq(1), nm.eq(FIXED), nc.eq(20 - 1),
                        ).Elif(is_k(SLC),
                            _keep.eq(1), nm.eq(FIXED), nc.eq(8 - 1),
                        ).Elif(is_k(SDP),
                            _keep.eq(1), nm.eq(DPP_FRAMING), nc.eq(4 - 1),
                        ),
                    ],
                    FIXED: If(c == 1,
                        _last.eq(1), nm.eq(IDLE),
                    ),
                    DPP_FRAMING: If(c == 1,
                        nm.eq(DPP),
                    ),
                    DPP: If(is_k(EPF),
                        _last.eq(1), nm.eq(IDLE),
                    ),
                }),
            ]
            self.sync += [
                sym[i].eq(Cat(data, k)),
                keep[i].eq(in_valid & _keep),
                last[i].eq(in_valid & _last),
            ]
            m, c = nm, nc
        self.sync += [
            valid.eq(in_valid),
            If(in_valid,
                mode.eq(m),
                count.eq(c),
            )
        ]

        # Symbols positions (registered, timing: independent of the buffer level) -----------------
        # Position of each packet symbol and position after the cycle, relative to the 32-bit word of
        # the buffer level, for the 4 offsets of the level in its word (the completion of the last
        # word of a packet depends on it): the buffer stage selects them with the level 2 LSBs and
        # adds the level word, instead of a chain of 8 dependent additions from the level.
        rel_w   = bits_for(3 + 4*8)
        rel     = [[Signal(rel_w, name=f"rel{r}_{i}") for i in range(8)] for r in range(4)]
        rel_end = [Signal(rel_w, name=f"rel_end{r}") for r in range(4)]
        for r in range(4):
            q = Constant(r, rel_w)
            for i in range(8):
                nq   = Signal(rel_w, name=f"relq{r}_{i}")
                end  = Signal(rel_w + 1, name=f"relend{r}_{i}")
                self.comb += [
                    end.eq(q + 4),
                    nq.eq(q + keep[i]),
                    # Last symbol of a packet: word completed (next packet on a 32-bit word).
                    If(last[i], nq.eq(Cat(Constant(0, 2), end[2:]))),
                ]
                self.sync += rel[r][i].eq(q)
                q = nq
            self.sync += rel_end[r].eq(q)
        sym_r  = [Signal(9, name=f"sym_r{i}")  for i in range(8)]
        keep_r = [Signal(name=f"keep_r{i}")    for i in range(8)]
        self.sync += [
            *[sym_r[i].eq(sym[i])   for i in range(8)],
            *[keep_r[i].eq(keep[i]) for i in range(8)],
        ]

        # Symbols buffer (packets symbols packed, last word of the packets completed) --------------
        n      = buffer_symbols + 16 # Buffer + one cycle of symbols (8) and completions (2x3).
        level  = Signal(max=n + 1)
        buf    = [Signal(9, name=f"buf{j}") for j in range(buffer_symbols)]
        base   = Signal(max=n + 1) # Level 32-bit word.
        self.comb += base.eq(Cat(Constant(0, 2), level[2:]))
        dest   = []
        for i in range(8):
            d = Signal(max=n + 1, name=f"dest{i}")
            self.comb += d.eq(base + Array(rel[r][i] for r in range(4))[level[:2]])
            dest.append(d)
        p = Signal(max=n + 1)
        self.comb += p.eq(base + Array(rel_end)[level[:2]])
        new = [Signal(9, name=f"new{j}") for j in range(n)]
        for j in range(n):
            cases = If(level > j, new[j].eq(buf[j]) if j < buffer_symbols else new[j].eq(0))
            for i in range(8):
                cases = cases.Elif(keep_r[i] & (dest[i] == j), new[j].eq(sym_r[i]))
            self.comb += [new[j].eq(0), cases]

        # Output: up to two complete words per cycle.
        words = Signal(2)
        self.comb += [
            If(p >= 8,
                words.eq(2)
            ).Elif(p >= 4,
                words.eq(1)
            ).Else(
                words.eq(0)
            )
        ]
        self.sync += [
            source.valid.eq(words != 0),
            source.words.eq(words),
            source.data.eq(Cat(*[new[j][:8] for j in range(8)])),
            source.ctrl.eq(Cat(*[new[j][8]  for j in range(8)])),
            level.eq(p - 4*words),
            Case(words, {w: [buf[j].eq(new[j + 4*w]) for j in range(buffer_symbols)] for w in range(3)}),
            If(p - 4*words > buffer_symbols,
                self.overflow.eq(1),
                level.eq(buffer_symbols),
            ),
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

# Lanes TX Symbol Shift ----------------------------------------------------------------------------

class LanesTXSymbolShift(LiteXModule):
    """64-bit link words delayed by shift symbols (1-7, Logical Idle symbols before the first word,
    the end of the last word of a burst flushed with Logical Idle symbols): packets starting at
    any symbol position of the 64-bit words (on Lane 1 with an odd shift), as from a partner not
    keeping its packets on 64-bit words. Test of the receivers (sim.py --lanes-tx-shift)."""
    def __init__(self, shift):
        assert 1 <= shift <= 7
        self.sink   = sink   = stream.Endpoint(link_layout())
        self.source = source = stream.Endpoint(link_layout())

        # # #

        prev_data = Signal(64)
        prev_ctrl = Signal(8)
        pending   = Signal() # End of the previous word not sent yet.
        cur_data  = Mux(sink.valid, sink.data, 0)
        cur_ctrl  = Mux(sink.valid, sink.ctrl, 0)
        data      = Cat(prev_data, cur_data)
        ctrl      = Cat(prev_ctrl, cur_ctrl)
        self.comb += [
            source.valid.eq(sink.valid | pending),
            source.data.eq(data[8*(8 - shift):8*(16 - shift)]),
            source.ctrl.eq(ctrl[8 - shift:16 - shift]),
            source.first.eq(sink.first),
            source.last.eq(~sink.valid | sink.last),
            sink.ready.eq(source.ready),
        ]
        self.sync += If(source.valid & source.ready,
            prev_data.eq(cur_data),
            prev_ctrl.eq(cur_ctrl),
            pending.eq(sink.valid),
        )
