## USB 3.2 Gen 1x2: results between two boards

Following the suggestion to explore 2 x 5Gbps in a fork first, here is where it stands. Everything
below is in the `usb3.2-gen1-x2` branch, with the procedure and the detailed results in
`doc/gen1x2-hardware-validation.md`.

### What is implemented

- PHY: `USB3PHY(lanes=2)`, two SerDes lanes in lockstep, SuperSpeedPlus Polling with the x2
  capability (SCD/LBPM), per lane scramblers and polarity, data striping, lanes deskew,
  Configuration Lane detection (lanes swap, as a flipped USB Type-C plug), single lane fallback to
  Gen 1x1.
- Link Layer/Device Core: SuperSpeedPlus operation at Gen 1x2 through `USB3PHYX2Link` (64-bit link
  words, packets at any symbol position), SuperSpeed at Gen 1x1 on the Configuration Lane.
- Simulation: `sim.py --lanes 2 [--lanes-core]` and `TestPHYX2`/`TestPHYX2Core` (crossed lanes,
  inverted TX lanes, packet placement, Hot Resets, Compliance exit, runtime Gen 1x1).

### Hardware validation (two Acorn Baseboard Minis + CLE-215+, SFP DAC cables)

One board in each role. The Host board runs the PRBS Link-Layer stand-ins or a scripted USB host in
gateware (the simulation host model: link initialization, enumeration-like control transfers, Bulk
loopback with the data checked). One Host and one Device bitstream cover Gen 1x2 and Gen 1x1 (the
x2 capability is a runtime control).

| Test | Result |
|------|--------|
| PHY, PRBS, Gen 1x2 | 610 MB/s per direction, 0 errors, retrains, lanes swap, unplug/replug |
| PHY, PRBS, Gen 1x1 (single lane fallback) | 10/10 loads, 303.9 MB/s per direction, 0 errors |
| Device Core, Gen 1x2, 20 bitstream loads x 20 runs | 400/400 runs |
| Device Core, Gen 1x1, 20 loads x 20 runs | 400/400 runs |
| Soak, one load, 10000 runs, Gen 1x2 | 10000/10000, 0 LBAD/retry; the link goes through Recovery during the runs (about 1.1 run restarts per run, 2641 Device Recovery requests) |
| Soak, one load, 10000 runs, Gen 1x1 | 10000/10000, no Recovery during the runs |

Each result is over many bitstream loads: on these boards the behavior changed a lot from one
load to the next until the GTP receiver LPM adaptation was held outside Polling.RxEQ (the default
for the Gen 1x2 builds); some variation remained from one build to another of the same source
(earlier Host builds: 371 to 400/400 runs at Gen 1x2).

### Fixes found on the way

Two general ones are now upstream (#174 Hot Reset exit, #175 RX idle filter spike rejection,
thanks for the split and the rework). The others are Gen 1x2 specific: Recovery on a lanes deskew
lost, a lane in electrical idle or a lane realigned in U0, a single deskew mismatch tolerated at the
end of an Ordered Sets stream, the Configuration Lane detection in Compliance, `LanesPacketAligner`
timing.

### Not done yet

- No USB host yet: a Gen 1x1 host through an SFP2USB adapter (both lane orientations), then a dual
  SFP to USB-C breakout with a Gen 1x2 capable host (in preparation), and the Gen 1x2 throughput.

### Could you try it with an SFP2USB adapter?

I don't have an SFP2USB adapter. If you have one and an Acorn Baseboard Mini, it would be the first
test of the Gen 1x2 Device with a real xHCI host (at Gen 1x1, the adapter carries a single lane),
procedure in `doc/gen1x2-hardware-validation.md` "Single Board With a USB 3 Host" (tests 11-13):

```sh
git clone -b usb3.2-gen1-x2 https://github.com/ohault/usb3_pipe && cd usb3_pipe
./bench/acorn.py --lanes 2 --lanes-core --example bench --with-jtagbone --output-dir build/acorn_x1_bench --build --load
./bench/acorn_ftdi.py server --port 1234 &        # litex_server (JTAGBone) on the baseboard FTDI.
# SFP2USB in SFP-0 (J3), then in SFP-1 (J8, lanes swap):
lsusb -t                                            # 5000M.
./bench/usb3_lanes.py --port 1234 --csr-csv build/acorn_x1_bench/csr.csv status   # U0, x2: 0, lane_swap: 0/1.
./bench/usb3_bench.py both --duration 60 --csr-csv build/acorn_x1_bench/csr.csv
```

Expected: enumerated at 5000M in both cages (`lane_swap` 0 in SFP-0, 1 in SFP-1), bench rates in
the range of the Gen 1x1 Acorn build, no data errors.

Happy to discuss whether and how this could fit upstream once it runs with a real Gen 1x2 host.
