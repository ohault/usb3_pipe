#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from usb3_pipe.lanes import *

MARKER = (0xbcbcbcbc, 0b1111) # COM x4.

class DUT(LiteXModule):
    def __init__(self):
        self.striper   = LaneStriper()
        self.deskew    = LaneDeskew(*MARKER)
        self.destriper = LaneDestriper()
        for lane in range(2):
            self.comb += self.deskew.sources[lane].connect(self.destriper.sinks[lane])

class TestLanes(unittest.TestCase):
    def test_striping(self):
        # Even symbols on Lane 0, odd symbols on Lane 1 (aligned to Lane 0).
        dut = LaneStriper()
        def generator(dut):
            yield dut.sink.valid.eq(1)
            yield dut.sink.data.eq(0x0706050403020100)
            yield dut.sink.ctrl.eq(0b00000101)
            yield dut.sources[0].ready.eq(1)
            yield dut.sources[1].ready.eq(1)
            yield
            self.assertEqual((yield dut.sources[0].data), 0x06040200)
            self.assertEqual((yield dut.sources[1].data), 0x07050301)
            self.assertEqual((yield dut.sources[0].ctrl), 0b0011)
            self.assertEqual((yield dut.sources[1].ctrl), 0b0000)
        run_simulation(dut, generator(dut))

    def test_striping_lockstep(self):
        # Lanes ready randomly: a word is given to both lanes in the same cycle, never to a single
        # lane (a lane held must hold the other one, the lanes would get out of step).
        rng   = random.Random(1)
        words = [rng.getrandbits(64) for _ in range(64)]
        dut   = LaneStriper()
        got   = [[], []]
        def generator(dut):
            yield dut.sink.valid.eq(1)
            i = 0
            while i < len(words):
                yield dut.sink.data.eq(words[i])
                for lane in range(2):
                    yield dut.sources[lane].ready.eq(rng.random() < 0.7)
                yield
                valid = []
                for lane in range(2):
                    valid.append((yield dut.sources[lane].valid) & (yield dut.sources[lane].ready))
                self.assertEqual(valid[0], valid[1])
                for lane in range(2):
                    if valid[lane]:
                        got[lane].append((yield dut.sources[lane].data))
                if (yield dut.sink.ready):
                    i += 1
        run_simulation(dut, generator(dut))
        for lane in range(2):
            self.assertEqual(got[lane], [
                sum(((w >> (8*(2*k + lane))) & 0xff) << (8*k) for k in range(4)) for w in words])

    def test_stripe_skew_deskew_destripe(self):
        # Link words striped, lanes skewed (Lane 1 delayed by 3 words, different garbage before the
        # marker, longer than the deskew gap), deskewed on the marker, destriped: link words recovered.
        rng   = random.Random(0)
        words = [(rng.getrandbits(64), rng.getrandbits(8)) for _ in range(64)]
        # Marker on both lanes (as duplicated Ordered Sets): striped from a link word.
        marker_word = (0xbcbcbcbcbcbcbcbc, 0xff)
        striper = LaneStriper()
        lanes = [[], []]
        def strip_gen(dut):
            for lane in range(2):
                yield dut.sources[lane].ready.eq(1)
            for data, ctrl in [marker_word] + words:
                yield dut.sink.valid.eq(1)
                yield dut.sink.data.eq(data)
                yield dut.sink.ctrl.eq(ctrl)
                yield
                for lane in range(2):
                    lanes[lane].append(((yield dut.sources[lane].data), (yield dut.sources[lane].ctrl)))
        run_simulation(striper, strip_gen(striper))
        lanes[0] = [(rng.getrandbits(32), 0) for _ in range(17)] + lanes[0]
        lanes[1] = [(rng.getrandbits(32), 0) for _ in range(20)] + lanes[1]

        dut = DUT()
        out = []
        def lane_gen(dut, lane):
            for data, ctrl in lanes[lane]:
                yield dut.deskew.sinks[lane].valid.eq(1)
                yield dut.deskew.sinks[lane].data.eq(data)
                yield dut.deskew.sinks[lane].ctrl.eq(ctrl)
                yield
                while not (yield dut.deskew.sinks[lane].ready):
                    yield
            yield dut.deskew.sinks[lane].valid.eq(0)
        def checker(dut):
            yield dut.destriper.source.ready.eq(1)
            for _ in range(300):
                if (yield dut.destriper.source.valid):
                    out.append(((yield dut.destriper.source.data), (yield dut.destriper.source.ctrl)))
                yield
        run_simulation(dut, [lane_gen(dut, 0), lane_gen(dut, 1), checker(dut)])
        self.assertEqual(out, [marker_word] + words)

    def run_deskew(self, lanes, cycles=300):
        class DUT(LiteXModule):
            def __init__(self):
                self.deskew    = LaneDeskew(0xbcbcbcbc, 0b1111)
                self.destriper = LaneDestriper()
                for lane in range(2):
                    self.comb += self.deskew.sources[lane].connect(self.destriper.sinks[lane])
        dut = DUT()
        out = []
        def lane_gen(dut, lane):
            for data, ctrl in lanes[lane]:
                yield dut.deskew.sinks[lane].valid.eq(1)
                yield dut.deskew.sinks[lane].data.eq(data)
                yield dut.deskew.sinks[lane].ctrl.eq(ctrl)
                yield
            yield dut.deskew.sinks[lane].valid.eq(0)
        def checker(dut):
            yield dut.destriper.source.ready.eq(1)
            for _ in range(cycles):
                if (yield dut.destriper.source.valid):
                    out.append(((yield dut.destriper.source.data), (yield dut.destriper.source.ctrl)))
                yield
        run_simulation(dut, [lane_gen(dut, 0), lane_gen(dut, 1), checker(dut)])
        return out

    @staticmethod
    def stripe(word, lane):
        data, ctrl = word
        return (sum(((data >> (8*(2*i + lane))) & 0xff) << (8*i) for i in range(4)),
                sum(((ctrl >> (2*i + lane)) & 0x1) << i for i in range(4)))

    def test_deskew_first_marker_after_gap(self):
        # Gap without marker (TSEQ), then periodic marker (TS1/TS2 COM words, every 4 words), lanes
        # skewed by up to 3 words in either direction (more than half the marker period): the first
        # markers after the gap are paired, the link words are recovered from the first marker.
        rng    = random.Random(1)
        marker = (0xbcbcbcbcbcbcbcbc, 0xff)
        tseq   = [(rng.getrandbits(64), 0) for _ in range(24)]
        ts     = []
        for _ in range(8):
            ts += [marker] + [(rng.getrandbits(64), 0) for _ in range(3)]
        data   = [(rng.getrandbits(64), rng.getrandbits(8) & 0x7f) for _ in range(32)]
        stream = tseq + ts + data
        for skew in [-3, -2, -1, 0, 1, 2, 3]:
            # Lane late by skew words: extra garbage words before its stream.
            lanes = [
                [(0, 0)]*max(0,  skew) + [self.stripe(w, 0) for w in stream],
                [(0, 0)]*max(0, -skew) + [self.stripe(w, 1) for w in stream],
            ]
            out = self.run_deskew(lanes)
            self.assertEqual(out, ts + data, f"skew={skew}")

    def test_deskew_no_gap(self):
        # Deskew started in the middle of periodic markers (no gap): no pairing (ambiguous), until a
        # gap followed by markers.
        rng    = random.Random(2)
        marker = (0xbcbcbcbcbcbcbcbc, 0xff)
        def ts(n):
            r = []
            for _ in range(n):
                r += [marker] + [(rng.getrandbits(64), 0) for _ in range(3)]
            return r
        first = ts(6)
        idle  = [(0, 0)]*20
        last  = ts(4)
        stream = first + idle + last
        lanes = [[self.stripe(w, 0) for w in stream], [(0, 0)]*2 + [self.stripe(w, 1) for w in stream]]
        out = self.run_deskew(lanes)
        self.assertEqual(out, last)

    def test_lane_swap(self):
        # Logical lanes on the physical SerDes (lane i on SerDes i ^ swap), swap detected from the
        # partner's LFPS on a single physical lane (detection enabled only).
        class SerDes:
            def __init__(self):
                for name in ["tx_idle", "tx_lfps", "tx_polarity", "rx_polarity", "tx_skp_enable",
                    "rx_align", "ready", "rx_idle", "rx_errors"]:
                    setattr(self, name, Signal())
                self.tx_pattern = Signal(20)
                self.sink   = stream.Endpoint(lane_layout())
                self.source = stream.Endpoint(lane_layout())
                self.rx_idle_stretch = 0
        serdes = [SerDes(), SerDes()]
        dut    = LaneSwap(serdes, detect=True, burst_cycles=4)
        lanes  = dut.lanes
        def generator():
            for p in range(2):
                yield serdes[p].rx_idle.eq(1)
                yield serdes[p].source.valid.eq(1)
                yield serdes[p].source.data.eq(0x100 + p)
                yield serdes[p].ready.eq(p)
            yield lanes[0].tx_idle.eq(1)
            yield lanes[0].sink.valid.eq(1)
            yield lanes[0].sink.data.eq(0xaa)
            yield
            # Not swapped: lane i on SerDes i.
            self.assertEqual((yield serdes[0].tx_idle), 1)
            self.assertEqual((yield serdes[1].tx_idle), 0)
            self.assertEqual((yield serdes[0].sink.data), 0xaa)
            self.assertEqual((yield lanes[0].source.data), 0x100)
            self.assertEqual((yield lanes[1].ready), 1)
            # LFPS on SerDes 1 only, detection disabled: no swap.
            yield serdes[1].rx_idle.eq(0)
            for _ in range(8):
                yield
            self.assertEqual((yield dut.swap), 0)
            # Detection enabled: swapped (Lane 0 on SerDes 1).
            yield dut.enable.eq(1)
            for _ in range(8):
                yield
            self.assertEqual((yield dut.swap), 1)
            self.assertEqual((yield serdes[1].tx_idle), 1)
            self.assertEqual((yield serdes[0].tx_idle), 0)
            self.assertEqual((yield serdes[1].sink.data), 0xaa)
            self.assertEqual((yield serdes[1].sink.valid), 1)
            self.assertEqual((yield serdes[0].sink.valid), 0)
            self.assertEqual((yield lanes[0].source.data), 0x101)
            self.assertEqual((yield lanes[0].ready), 1)
            # Both lanes active (data): kept. LFPS on SerDes 0 only: back to not swapped.
            yield serdes[0].rx_idle.eq(0)
            for _ in range(8):
                yield
            self.assertEqual((yield dut.swap), 1)
            yield serdes[1].rx_idle.eq(1)
            for _ in range(8):
                yield
            self.assertEqual((yield dut.swap), 0)
        run_simulation(dut, generator())

    # x2 Link interface building blocks --------------------------------------------------------------

    @staticmethod
    def x2_packets(rng, n=24):
        """Gen 1 Link Layer packets as lists of (word, ctrl) link words (Symbol 0 in the LSBs):
        Header Packets (SHP + 4 words), Link Commands (SLC + 1 word), DPHs + DPPs (zero data words
        included, END framing)."""
        def framing(k):
            return (k | (k << 8) | (k << 16) | (0xf7 << 24), 0b1111) # 3 K Symbols + EPF.
        SHP, SLC, SDP, END = 0xfb, 0xfe, 0x5c, 0xfd # K27.7, K30.7, K28.2, K29.7.
        packets = []
        for _ in range(n):
            kind = rng.choice(["hp", "lc", "dp"])
            if kind == "hp":
                packets.append([framing(SHP)] + [(rng.getrandbits(32) | 1, 0) for _ in range(4)])
            elif kind == "lc":
                packets.append([framing(SLC), (rng.getrandbits(32) | 1, 0)])
            else:
                dpp = [(rng.choice([0, rng.getrandbits(32)]), 0) for _ in range(rng.randint(1, 12))]
                packets.append([framing(SHP)] + [(rng.getrandbits(32) | 1, 0) for _ in range(4)] +
                    [framing(SDP)] + dpp + [framing(END)])
        return packets

    def test_tx_packer(self):
        # Packets as link words pairs (1 or 2 words, a pair never spans two packets), random gaps on
        # both sides: 64-bit words with the packets words in order, never two packets in a word, a
        # Logical Idle word only after the last word of a packet, first/last on the packets words.
        rng     = random.Random(3)
        packets = self.x2_packets(rng)
        pairs   = []
        for p in packets:
            i = 0
            while i < len(p):
                n = 2 if (i + 1 < len(p)) and rng.random() < 0.6 else 1
                pairs.append((p[i:i+n], i == 0, i + n == len(p)))
                i += n
        dut = LanesTXPacker()
        out = []
        def source_gen():
            for words, first, last in pairs:
                while rng.random() < 0.3:
                    yield dut.sink.valid.eq(0)
                    yield
                yield dut.sink.valid.eq(1)
                yield dut.sink.data.eq(sum(w << (32*i) for i, (w, c) in enumerate(words)))
                yield dut.sink.ctrl.eq(sum(c << (4*i) for i, (w, c) in enumerate(words)))
                yield dut.sink.words.eq(len(words))
                yield dut.sink.first.eq(first)
                yield dut.sink.last.eq(last)
                yield
                while not (yield dut.sink.ready):
                    yield
            yield dut.sink.valid.eq(0)
        def sink_gen():
            for _ in range(2000):
                ready = rng.random() < 0.7
                yield dut.source.ready.eq(ready)
                yield
                if ready and (yield dut.source.valid):
                    out.append(((yield dut.source.data), (yield dut.source.ctrl),
                        (yield dut.source.first), (yield dut.source.last)))
        run_simulation(dut, [source_gen(), sink_gen()])
        got, current = [], None
        for data, ctrl, first, last in out:
            words = [(data & 0xffffffff, ctrl & 0xf), (data >> 32, ctrl >> 4)]
            if first:
                self.assertIsNone(current)
                current = []
            self.assertIsNotNone(current)
            current.append(words[0])
            if last:
                # Second word: last word of the packet or a Logical Idle word after it.
                if words[1] != (0, 0) or len(current) + 1 <= len(packets[len(got)]) and \
                    packets[len(got)][len(current)] == (0, 0):
                    current.append(words[1])
                if current[-1] == (0, 0) and len(current) > len(packets[len(got)]):
                    current.pop()
                got.append(current)
                current = None
            else:
                current.append(words[1])
        self.assertEqual(got, packets)

    def test_idle_filter(self):
        # Packets with Logical Idle words between them (packets starting on both 32-bit words of the
        # 64-bit words): the packets words only, in order (zero DPP data words kept).
        rng     = random.Random(4)
        packets = self.x2_packets(rng)
        words   = []
        for p in packets:
            words += [(0, 0)]*rng.randint(0, 5) + p
        words += [(0, 0)]*(len(words) % 2)
        dut = LanesIdleFilter()
        out = []
        def gen():
            yield dut.source.ready.eq(1)
            for i in range(0, len(words), 2):
                yield dut.sink.valid.eq(1)
                yield dut.sink.data.eq(words[i][0] | (words[i+1][0] << 32))
                yield dut.sink.ctrl.eq(words[i][1] | (words[i+1][1] << 4))
                yield
                if (yield dut.source.valid):
                    n = (yield dut.source.words)
                    data, ctrl = (yield dut.source.data), (yield dut.source.ctrl)
                    out.extend([((data >> (32*k)) & 0xffffffff, (ctrl >> (4*k)) & 0xf) for k in range(n)])
            yield dut.sink.valid.eq(0)
            for _ in range(2):
                yield
                if (yield dut.source.valid):
                    n = (yield dut.source.words)
                    data, ctrl = (yield dut.source.data), (yield dut.source.ctrl)
                    out.extend([((data >> (32*k)) & 0xffffffff, (ctrl >> (4*k)) & 0xf) for k in range(n)])
        run_simulation(dut, gen())
        self.assertEqual(out, [w for p in packets for w in p])

    def test_framing_aligner(self):
        # Packets starting at any symbol position (6.13.4), 12+ Logical Idle symbols between them:
        # every framing word re-aligned on a 32-bit word boundary, non idle symbols unchanged.
        rng     = random.Random(5)
        packets = self.x2_packets(rng)
        symbols = [] # (byte, k).
        for p in packets:
            symbols += [(0, 0)]*rng.randint(12, 19)
            for w, c in p:
                symbols += [((w >> (8*i)) & 0xff, (c >> i) & 1) for i in range(4)]
        symbols += [(0, 0)]*(16 - len(symbols) % 8)
        dut = LanesFramingAligner()
        out = []
        def gen():
            yield dut.source.ready.eq(1)
            for i in range(0, len(symbols), 8):
                yield dut.sink.valid.eq(1)
                yield dut.sink.data.eq(sum(symbols[i+k][0] << (8*k) for k in range(8)))
                yield dut.sink.ctrl.eq(sum(symbols[i+k][1] << k for k in range(8)))
                yield
                if (yield dut.source.valid):
                    data, ctrl = (yield dut.source.data), (yield dut.source.ctrl)
                    out.extend([((data >> (8*k)) & 0xff, (ctrl >> k) & 1) for k in range(8)])
        run_simulation(dut, gen())
        starts = {0xfb, 0xfe, 0x5c} # SHP, SLC, SDP.
        for i, (b, k) in enumerate(out):
            if k and b in starts and not (i > 0 and out[i-1] == (b, k)):
                self.assertEqual(i % 4, 0, f"framing at symbol {i}")
        self.assertEqual([s for s in out if s != (0, 0)], [s for s in symbols if s != (0, 0)])

if __name__ == "__main__":
    unittest.main()
