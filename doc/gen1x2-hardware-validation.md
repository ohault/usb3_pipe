# Gen 1x2 Hardware Validation: LiteX Acorn Baseboard Mini (Two Boards, SFP2USB, Gen 1x2 Host)

Hardware validation of the USB 3.2 Gen 1x2 PHY (`USB3PHY(lanes=2)`), first between two boards, one
in the Host role and one in the Device role, without a Gen 1x2 USB host or a USB Type-C breakout
([Gen 1x2 hardware milestones](notes/gen2-x2-roadmap.md#gen-1x2-hardware-milestones), M0), then with USB hosts through
the SFP2USB adapter and the dual SFP to USB-C breakout. The two boards tests run in simulation with
`sim.py --lanes 2` (`test/test_phy.py` `TestPHYX2`).

Each board runs `bench/acorn.py --lanes 2`: `USB3PHY(lanes=2)` on SFP-0 (Lane 0, Configuration Lane)
and SFP-1 (Lane 1), `USB3PHYDebug` (Lane 0), `USB3LanesDebug` (x2/deskew/lanes swap status, per lane
counters) and the PRBS Link-Layer stand-ins (`PRBSLinkTester`: PRBS packets sent and checked in U0,
64-bit link words with Gen 1x2, 32-bit words on Lane 0 when Gen 1x1 is negotiated). Between two
boards the link is first tested with PRBS packets, then the SuperSpeedPlus Link Layer/Device Core
at Gen 1x2 with a scripted USB host on the Host board (second part), finally with real USB hosts.

What is validated:
- SuperSpeedPlus Polling (SCD1/SCD2, LBPM PHY Capability/Ready) with Gen 1x2 negotiated.
- Link training to U0 on both lanes, lanes deskew, per lane polarity/scrambling, data striping.
- PRBS packets without errors in both directions, link retrains.
- Lanes swap (Configuration Lane detection, as a flipped USB Type-C plug) with crossed cables.
- Single lane fallback (Gen 1x1 negotiated) with a board built without the x2 capability.
- LFPS/electrical idle through the SFP DAC cables, and the Host role (first time on hardware).

A second part, with the same two boards and DAC cables, runs the USB3 Device Core at Gen 1x2
(SuperSpeedPlus, `loopback` example) on the Device board, driven by a scripted USB host on the Host
board: link initialization, enumeration-like control transfers and Bulk loopback with the Bulk IN
data checked ([Two Boards: Gen 1x2 Device Core With the Scripted Host](#two-boards-gen-1x2-device-core-with-the-scripted-host)).

A third, single board test runs the USB3 Device Core on the Gen 1x2 PHY with a USB 3 host through
the single lane SFP2USB adapter ([Single Board With a USB 3 Host](#single-board-with-a-usb-3-host-sfp2usb-adapter)):
enumeration and transfers at Gen 1x1, with the host Configuration Lane on SFP-0 and then on SFP-1
(lanes swap), as with the dual SFP to USB-C breakout in both plug orientations. It needs only one
board and no DAC cable, and can be run first.

A fourth part runs the same Device Core at Gen 1x2 (SuperSpeedPlus, both lanes) with a Gen 1x2
capable host through the dual SFP to USB-C breakout
([Gen 1x2 Device Core With a Gen 1x2 Host](#gen-1x2-device-core-with-a-gen-1x2-host-dual-sfp-to-usb-c-breakout)):
it needs the breakout (in preparation) and such a host.

| Part | Boards | Link partner | Link Layer | Simulation |
|------|--------|--------------|------------|------------|
| Two boards (tests 1-6) | 2 | Acorn Mini, Host role, 2 DAC cables | PRBS stand-ins | `sim.py --lanes 2` (`TestPHYX2`) |
| Two boards, core (tests 7-10b) | 2 | Acorn Mini, scripted USB host, 2 DAC cables | Device Core, SuperSpeedPlus at Gen 1x2 (SuperSpeed at Gen 1x1: 10b) | `sim.py --lanes 2 --lanes-core [--dev-mode x1]` (`TestPHYX2Core`) |
| Single board (tests 11-13) | 1 | USB 3 host, SFP2USB adapter (1 lane) | Device Core, Gen 1x1 | `sim.py --lanes 2 --lanes-core --dev-mode x1` (`TestPHYX2Core`) |
| Gen 1x2 host (tests 14-18) | 1 | Gen 1x2 host, dual SFP to USB-C breakout | Device Core, SuperSpeedPlus at Gen 1x2 | `sim.py --lanes 2 --lanes-core` (`TestPHYX2Core`) |

Hardware needed per part: two Acorn Minis and two SFP DAC cables run the first two parts (tests 1-10:
the PHY, then the Device Core at Gen 1x2); the SFP2USB adapter (tests 11-13) and the dual SFP to
USB-C breakout with a Gen 1x2 host (tests 14-18) come next.

## Hardware

- 2x LiteX Acorn Baseboard Mini, each with a SQRL Acorn CLE-215+ (Artix7 GTP) in the M.2 socket.
- 2x passive SFP+ DAC cables. The SFP lanes are DC coupled on the Minis (AC coupling is expected in
  the SFP modules): whether the DAC cables provide the AC coupling required by USB3 is part of what
  this validation checks.
- Per board: power on USB-C J9 (USB Power Delivery input) or a PCIe slot, USB-C J7 (baseboard FTDI:
  FT2232H or FT4232H depending on the revision, JTAG on channel A, UART) to the PC, and the
  Pico-EZmate cable from J10 to the Acorn JTAG connector (without it, the JTAG does not reach the
  FPGA).

Cabling (straight): SFP-0 <-> SFP-0 and SFP-1 <-> SFP-1. SFP-0 is J3, the cage closest to the M.2
socket; SFP-1 is J8, the cage closest to the SATA connector
([Mini connectors](https://github.com/enjoy-digital/litex-acorn-baseboard/tree/master/hardware)).
Both cages are in the same GTP quad: Lane 1 runs on the Lane 0 Quad PLL and TX clock (lanes TX in
lockstep, as required by `USB3PHY(lanes=2)`).

LEDs (each board): SerDes ready, U0, x2 negotiated.

## Build

One bitstream per role (Vivado), JTAGBone for the CSRs:

```sh
./bench/acorn.py --lanes 2 --role host   --with-jtagbone --output-dir build/acorn_x2_host   --build
./bench/acorn.py --lanes 2 --role device --with-jtagbone --output-dir build/acorn_x2_device --build
```

The same bitstreams run at Gen 1x1: the Gen 1x2 capability advertised in the SuperSpeedPlus Polling
is a runtime control (`usb3_lanes.py x2-disable`/`x2-enable`, then retrain), `--no-x2` (built not x2
capable) is not needed for the tests.

`--lpm-hold rxeq` (GTP LPM adaptation only in Polling.RxEQ, on the partner's TSEQ) is the default
with `--lanes 2`: with a continuous adaptation the receive quality of a lane changed from one
bitstream load to the next (`--lpm-hold none` to compare). Optional: `--with-analyzer
--analyzer-group link` (LiteScope probes on Lane 0).

## Select Each Board

Both boards expose the same FTDI chip (FT2232H "Dual RS232-HS" or FT4232H "Quad RS232-HS", depending
on the baseboard revision): the default programmer (`--load`) and `litex_server --jtag` take the
first FTDI found. Always select each board explicitly, by the USB location of its FTDI, with
`bench/acorn_ftdi.py` (it picks the openFPGALoader cable, `ft2232`/`ft4232`, and the OpenOCD config,
USB PID 0x6010/0x6011 and location, for the chip of each board):

```sh
./bench/acorn_ftdi.py list
# ex: {"location": "1-2", "chip": "FT2232H", ...} (board A), {"location": "1-4", "chip": "FT2232H", ...} (board B)
```

To know which board is which, unplug the J7 cable of one board and run `list` again. Below,
`<host_location>` is the board in the Host role and `<dev_location>` the board in the Device role
(other FT2232H/FT4232H boards connected to the PC are also listed: select by location).

## Load

Load each bitstream in SRAM through its own FTDI (the load order does not matter: Rx.Detect is not
modelled by the LTSSM, both boards start in Polling and retry until the partner is present):

```sh
./bench/acorn_ftdi.py --location <host_location> load build/acorn_x2_host/gateware/sqrl_acorn.bit
./bench/acorn_ftdi.py --location <dev_location>  load build/acorn_x2_device/gateware/sqrl_acorn.bit
```

(`openFPGALoader -c ft2232 --busdev-num <bus>:<dev> --write-sram <bitstream>` with an FT2232H,
`-c ft4232` with an FT4232H, bus/dev from `list`.)

## litex_server (One Per Board)

One `litex_server` (JTAGBone) per board on dedicated ports (not the LiteX default 1234: a client
could talk to another board/bridge), each with the OpenOCD config of its FTDI (channel A, USB PID
of the chip, `ftdi_location` as `bus:ports`, ex: `1:2`), then check the identifiers:

```sh
./bench/acorn_ftdi.py --location <host_location> server --port 1240   # (one terminal each)
./bench/acorn_ftdi.py --location <dev_location>  server --port 1241
litex_cli --port 1240 --csr-csv build/acorn_x2_host/csr.csv   --ident # USB3SoC <build date>
litex_cli --port 1241 --csr-csv build/acorn_x2_device/csr.csv --ident # USB3SoC <build date>
```

Restart the `litex_server` of a board after loading it. `./bench/acorn_ftdi.py --location
<location> openocd-cfg board.cfg` writes the OpenOCD config only (`litex_server --jtag --jtag-config
board.cfg`).

Client shorthands used below:

```sh
H="--port 1240 --csr-csv build/acorn_x2_host/csr.csv"
D="--port 1241 --csr-csv build/acorn_x2_device/csr.csv"
```

`bench/usb3_lanes.py` commands: `status` (JSON status and counters), `clear` (PHY/lanes counters),
`retrain` (PHY reset: link retraining, status and LTSSM state history), `watch` (status on changes), `prbs`
(PRBS packets rate/errors over `--duration` seconds), `prbs-enable`/`prbs-disable`.

## Tests

### 1. Link up (Gen 1x2)

```sh
./bench/usb3_lanes.py $H status
./bench/usb3_lanes.py $D status
```

Pass, on both boards: `ltssm_state` U0, `x2: 1`, `deskew_aligned: 1`, `ready: [1, 1]`,
`rx_idle: [0, 0]`, `lane_swap: 0`, the 3 LEDs on.

### 2. PRBS

```sh
./bench/usb3_lanes.py $D prbs --duration 60
./bench/usb3_lanes.py $H prbs --duration 60
```

Pass: `rx_errors: 0`, `recoveries: 0`, `x2: 1`. The rate is a few hundred MB/s per direction
(64-bit link words at 125MHz: 1GB/s max, less the PRBS packets markers and the 0-15 cycles Logical
Idle gaps between packets, not characterized on hardware yet): the errors are the criterion.

### 3. Retrains

`retrain` resets the PHY of a board. With the PRBS stand-ins (no Link Layer), the partner of a
board retrained alone stays in U0 (nothing detects the lost link) and the retrained board ends in
Compliance (Polling.LFPS timeout without the partner LFPS): always retrain both boards together.

```sh
for i in $(seq 10); do ./bench/usb3_lanes.py $H retrain --wait 2 & ./bench/usb3_lanes.py $D retrain --wait 2; wait; done
./bench/usb3_lanes.py $D prbs --duration 30
```

Pass: U0 with `x2: 1` and `deskew_aligned: 1` after each retrain on both boards, PRBS still without
errors. A deskew lost during the TS1/TS2 Ordered Sets (`deskew` counter > 0 with `deskew_aligned:
0`) is recovered by a Recovery (`recovery_count` + 1).

### 4. Lanes swap (crossed cables)

Cross the DAC cables: Host SFP-0 <-> Device SFP-1 and Host SFP-1 <-> Device SFP-0 (as a flipped USB
Type-C plug on the dual SFP to USB-C breakout), then:

```sh
./bench/usb3_lanes.py $H retrain --wait 2 & ./bench/usb3_lanes.py $D retrain --wait 2; wait
./bench/usb3_lanes.py $D status
./bench/usb3_lanes.py $D prbs --duration 60
```

Pass: Device `lane_swap: 1` (Configuration Lane detected on SFP-1 from the Host Polling.LFPS), Host
`lane_swap: 0` (the Host keeps its lanes), `x2: 1`, deskewed, PRBS without errors. Put the cables
back straight after this test.

### 5. Single lane fallback (Gen 1x1 negotiated)

Gen 1x2 not advertised by the Device (runtime control, then retrain), PRBS at Gen 1x1:

```sh
./bench/usb3_lanes.py $D x2-disable --wait 2
./bench/usb3_lanes.py $D prbs --duration 60
./bench/usb3_lanes.py $H status
./bench/usb3_lanes.py $D x2-enable --wait 2       # Back to Gen 1x2.
```

Pass: `x2: 0` on both boards (Gen 1x1 negotiated in the LBPM PHY Capability exchange), U0 on SFP-0
only, SFP-1 in electrical idle (`rx_idle: [0, 1]`), PRBS without errors (32-bit link words: about
half the Gen 1x2 rate). With crossed cables (test 4), the same on the Device SFP-1.

A Device loaded seconds before the Host times out of Polling.LFPS to Compliance (360ms) and only
leaves it on a Warm Reset: the Host board directs one when U0 is not reached for 0.5s
(`USB3HostPortReset`, `usb3_port_reset_count`), the Device detects it on either physical lane
(lanes swap in Compliance). Without them (builds before `daa2451`): retrain both boards together
after the loads (`usb3_debug_phy_reset` of both boards set, then released).

### 6. Unplug/replug (optional)

```sh
./bench/usb3_lanes.py $D watch
```

Unplug and replug a DAC cable: the link leaves U0, then retrains (the LTSSM exits to Rx.Detect on
the training failures and restarts the Polling) and the lanes are deskewed again.

## Two Boards: Gen 1x2 Device Core With the Scripted Host

Same boards and DAC cables (straight cabling), the PRBS stand-ins replaced by USB Link Layers:
- Device board: `--role device --lanes-core --example loopback`: the USB3 Device Core on a
  `USB3PHYX2Link` (SuperSpeedPlus at Gen 1x2, 64-bit endpoints), vendor class Bulk loopback (EP2
  OUT -> EP1 IN).
- Host board: `--role host --lanes-core`: a scripted USB host (`USB3HostScript`: the
  `USB3HostModel` of the simulations, in gateware, on a `USB3PHYX2Link`), running the script of
  `sim.py --lanes 2 --lanes-core`: link initialization (Advertisements, Port Capability/Configuration
  LMPs), enumeration-like control transfers (GET_DESCRIPTOR device/configuration/string,
  SET_CONFIGURATION), Bulk OUT (64 and 1024 bytes) then Bulk IN with the looped back data checked
  by the script (DPH, SDP framing, data, CRC-32, END framing: 286 words), in SuperSpeedPlus operation
  (4-bit Header Sequence Numbers, Type 1/Type 2 credits). A script step not matched (or a timeout)
  is a script error with its step. Out of the script runs, the scripted host sends LUP keep-alives.

It validates the Gen 1x2 Device Core and Link interface on hardware between the two boards; it does
not replace a real xHCI host (interoperability: tests 11-18).

### Build and load

```sh
./bench/acorn.py --lanes 2 --role host   --lanes-core --with-jtagbone --output-dir build/acorn_x2_host_script --build
./bench/acorn.py --lanes 2 --role device --lanes-core --example loopback --with-jtagbone --output-dir build/acorn_x2_device_core --build
./bench/acorn_ftdi.py --location <host_location> load build/acorn_x2_host_script/gateware/sqrl_acorn.bit
./bench/acorn_ftdi.py --location <dev_location>  load build/acorn_x2_device_core/gateware/sqrl_acorn.bit
H2="--port 1240 --csr-csv build/acorn_x2_host_script/csr.csv"
D2="--port 1241 --csr-csv build/acorn_x2_device_core/csr.csv"
```

The `litex_server`s as above (one per board, restarted after a load). LEDs: Host board: SerDes
ready, U0, x2; Device board: SerDes ready, U0, lanes swapped.

### 7. Link up with the Link Layers

```sh
./bench/usb3_lanes.py $H2 status
./bench/usb3_lanes.py $D2 status
```

Pass: U0 reached with `x2: 1`, `deskew_aligned: 1` on both boards, `rx_overflow: 0`. Out of the
script runs, the scripted host sends LUP keep-alives and, after a run, the acknowledges of the
Device Header Packets (LGOOD_n/LCRD_x); before the first run it does not acknowledge them, so the
Device Link Layer may request Recoveries on PENDING_HP_TIMER (`usb3_core_recovery_cause`:
`pending_hp`). Each script run starts after a Hot Reset directed by the host (Header Sequence
Numbers of both Link Layers reset: no `lgood`/`hp_seq` Recovery per run) and is restarted with a
new Hot Reset on a U0 exit. Test 8 is the criterion.

### 8. Scripted host runs

```sh
./bench/usb3_lanes.py $H2 script --runs 100
./bench/usb3_lanes.py $D2 status
litex_cli --port 1241 --csr-csv build/acorn_x2_device_core/csr.csv --regs | grep usb3_core  # Device Link Layer counters.
```

Pass: `done` for each run (one JSON line per run with its duration), final line with `done: 100`,
`error: 0`, `timeout: 0`, `x2: 1`, `rx_overflow: 0` on both boards, `recovery_count` stable, no
LBAD/retries in the Device Link Layer counters (`usb3_core_rx_lbad`, `usb3_core_tx_retry`,
`usb3_core_recovery_req`). An `error` gives the failing step and script section (`link_init`,
`get_device_descriptor`... `bulk_in_1`): report them; a `timeout` is a link not in U0. The
final line also gives `resets_csr` (Hot Resets directed before the runs, restarts included).

A single bitstream load proves little (the behavior of a Gen 1x2 build changes from one load to
the next): run ~20 loads, both boards loaded on each (servers restarted, counters cleared, Device
Core counters read before and after the runs, summary with the bad loads apart):

```sh
./bench/acorn_x2_loads.py --host-build build/acorn_x2_host_script --device-build build/acorn_x2_device_core \
    --loads 20 --runs 20 --out build/hw_runs/<name>/loads.jsonl
./bench/acorn_x2_loads.py --summary build/hw_runs/<name>/loads.jsonl
```

### 9. Crossed cables (lanes swap with the core)

Cross the DAC cables (Host SFP-0 <-> Device SFP-1, Host SFP-1 <-> Device SFP-0), retrain, run the
script:

```sh
./bench/usb3_lanes.py $D2 retrain --wait 2
./bench/usb3_lanes.py $H2 script --runs 100
./bench/usb3_lanes.py $D2 status
```

Pass: as test 8, Device `lane_swap: 1`. Put the cables back straight after this test.

### 10. Retrains and soak (optional)

```sh
for i in $(seq 20); do ./bench/usb3_lanes.py $D2 retrain --wait 2; ./bench/usb3_lanes.py $H2 script --runs 10; done
./bench/usb3_lanes.py $H2 script --runs 10000 --timeout 5
```

Pass: all the runs `done` after each retrain (the script restarts from the link initialization on
each run), no `rx_overflow`.

### 10b. Gen 1x1 Device Core

The same bitstreams, Gen 1x2 not advertised (runtime control on both boards, `--x1`): Gen 1x1
negotiated in the SuperSpeedPlus Polling (as with a Gen 1x1 USB host), the Device Core in SuperSpeed
operation on its Configuration Lane, the scripted host running its SuperSpeed script (3-bit Header
Sequence Numbers, `usb3_script_ssp: 0`; both scripts are in the scripted host, the run uses the one
of the negotiated link):

```sh
./bench/acorn_x2_loads.py --x1 --host-build build/acorn_x2_host_script --device-build build/acorn_x2_device_core \
    --loads 20 --runs 20 --out build/hw_runs/<name>/loads.jsonl
```

Pass: as test 8, `x2: 0` on both boards (`sim.py --lanes 2 --lanes-core --dev-x2-disable
--no-host-skp`, `TestPHYX2Core.test_core_x1_runtime`).

## Single Board With a USB 3 Host (SFP2USB Adapter)

One Acorn Mini built with `--lanes 2 --lanes-core`: `USB3PHY(lanes=2)` on SFP-0/SFP-1 and the USB3
Device Core example design (`bench`: `USB3PHYX2Link`, Gen 1x2 capable; a Gen 1x1 host through the
single lane adapter negotiates Gen 1x1 on the Configuration Lane, SuperSpeed operation). The SFP2USB
adapter carries a single lane: in SFP-0, the host Configuration Lane is on SFP-0 (`lane_swap: 0`); in
SFP-1, the Device detects it from the host Polling.LFPS and swaps its lanes (`lane_swap: 1`), as for
a flipped plug on the dual SFP to USB-C breakout. Simulation: `sim.py --lanes 2 --lanes-core
--dev-mode x1 [--lanes-crossed]` (`test/test_phy.py` `TestPHYX2Core` `core_x1`/`core_x1_crossed`).

Hardware: one Acorn Mini (power, J7 to the PC, J10 Pico-EZmate as above), the SFP2USB adapter and a
USB 3 cable to the host (xHCI, Linux: `bench/99-usb3-pipe.rules` for user access to the vendor
class examples). The device is `1d50:605a`.

### Build and load

```sh
./bench/acorn.py --lanes 2 --lanes-core --example bench --with-jtagbone --output-dir build/acorn_x1_bench --build --load
./bench/acorn_ftdi.py server --port 1240     # --location <location> with several boards connected.
B="--port 1240 --csr-csv build/acorn_x1_bench/csr.csv"
```

With a single Acorn connected, `--load` (FT2232H/FT4232H detected) can be used; select the board by
its USB location as above when the other board is also connected. Other examples:
`--example loopback` (`bench/usb3_bulk.py loopback`), `cdc_uartbone`, `uvc`... (the examples
without CPU/DRAM). LEDs: SerDes ready, U0, lanes swapped.

### 11. SFP2USB in SFP-0 (no lanes swap)

```sh
lsusb -d 1d50:605a -v | grep -i bcdUSB                          # Enumerated (USB 3).
lsusb -t                                                         # 5000M.
./bench/usb3_lanes.py $B status                                  # U0, x2: 0, lane_swap: 0.
./bench/usb3_bench.py in   --duration 30                         # IN data checked.
./bench/usb3_bench.py out  --duration 30 $B                      # OUT, device checker errors.
./bench/usb3_bench.py both --duration 60 $B
```

Pass: enumerated at 5000M, `ltssm_state` U0, `x2: 0`, `lane_swap: 0`, `rx_idle: [0, 1]` (SFP-1
without signal), no IN/OUT data errors, `recovery_count` stable; rates in the range of the Gen 1x1
Acorn build ([Examples](manual/12_examples.md): ~450MB/s IN/OUT).

### 12. SFP2USB in SFP-1 (lanes swap)

Unplug the USB cable, move the SFP2USB adapter to SFP-1, plug the USB cable (the PHY retrains:
Polling from Rx.Detect, or `./bench/usb3_lanes.py $B retrain --wait 2`), then the same commands as
test 11.

Pass: the same results with `lane_swap: 1` (third LED on) and `rx_idle: [1, 0]`; moved back to SFP-0:
`lane_swap: 0` again.

### 13. Host reconnections (optional)

Unplug/replug the USB cable and the adapter a few times in both cages (`./bench/usb3_lanes.py $B
watch` running), suspend/resume or unbind/bind the device on the host: enumerated again each time,
with the lanes swap following the adapter cage.

## Gen 1x2 Device Core With a Gen 1x2 Host (Dual SFP to USB-C Breakout)

The `--lanes-core` build of the single board part (`bench` example: `USB3PHYX2Link`, Gen 1x2 capable)
with both lanes connected to a USB 3.2 x2 capable host: SuperSpeedPlus Polling with Gen 1x2
negotiated, then the SuperSpeedPlus Link Layer (4-bit Header Sequence Numbers, Type 1/Type 2
credits) on the striped lanes, 64-bit Bulk endpoints. Simulation: `sim.py --lanes 2 --lanes-core`
(`--lanes-crossed`, `--host-lpm`; `test/test_phy.py` `TestPHYX2Core` `core_x2`/`core_x2_crossed`/
`core_x2_lpm`).

Hardware:
- The Acorn Mini with the dual SFP to USB-C breakout: Lane 0 on SFP-0 (TX1/RX1, CC1 orientation),
  Lane 1 on SFP-1, Rd on CC1/CC2 (Device), no USB 2.0.
- A USB 3.2 x2 capable host (ex: ASMedia ASM3242 based Gen 2x2 PCIe card; Gen 1x2 support to check
  in its specification), a USB-C to USB-C cable rated for USB 3.2 x2 (both SuperSpeed pairs wired,
  ex: USB 3.2 Gen 2x2/20Gbps or USB4 cable), Linux (the negotiated lanes are in the sysfs).
- Optional: a Gen 1x1/Gen 2x1 host with a USB-C port (fallback test).

Build and load as in the single board part (the same bitstream: `build/acorn_x1_bench`, `$B`).

### 14. Enumeration at Gen 1x2

```sh
lsusb -t                                                          # Device under the x2 host port.
S=$(grep -l 605a /sys/bus/usb/devices/*/idProduct | xargs -n1 dirname | head -1)
cat $S/speed $S/rx_lanes $S/tx_lanes                              # Negotiated speed/lanes.
./bench/usb3_lanes.py $B status                                   # U0, x2: 1, deskew_aligned: 1.
./bench/usb3_debug.py host                                        # SuperSpeed devices (speed).
```

Pass: enumerated, `rx_lanes`/`tx_lanes` = 2 (`speed`: 10000, SuperSpeedPlus), `x2: 1`,
`deskew_aligned: 1`, `rx_idle: [0, 0]`, `recovery_count` stable. With `x2: 0` the host negotiated
Gen 1x1 (see Troubleshooting).

### 15. Bulk transfers at Gen 1x2

```sh
./bench/usb3_bench.py in   --duration 30 --transfer-size 65536            # IN data checked.
./bench/usb3_bench.py out  --duration 30 --transfer-size 65536 $B         # OUT, device checker.
./bench/usb3_bench.py both --duration 60 --transfer-size 65536 $B
./bench/usb3_soak.py --bench 20 --duration 300 $B                         # Soak (optional).
```

Pass: no IN/OUT data errors, no LBAD/retries growing, `recovery_count` stable, `rx_overflow: 0`/
`rx_drop: 0` in `usb3_lanes.py $B status` (no RX words dropped by the Gen 1x2 RX buffer). Rates:
above the Gen 1x1 build (~450MB/s), up to ~1GB/s for 64-bit link words at 125MHz (the Gen 1x2
throughput has not been characterized yet: report the rates, they are a result).

### 16. Plug orientations

Unplug the USB-C cable at the breakout, flip it, plug it back; then tests 14 and 15 again.

Pass: the same results in both orientations, `lane_swap` changing with the orientation (`0`: host
Configuration Lane on SFP-0, `1`: on SFP-1).

### 17. Gen 1x1 host (fallback, optional)

Connect the breakout to a Gen 1x1/Gen 2x1 host USB-C port: enumerated at 5000M, `x2: 0` (single
lane on the Configuration Lane, SuperSpeed operation), test 15 rates in the range of the Gen 1x1
build, in both plug orientations.

### 18. Reconnections and power management (optional)

Unplug/replug, flip, suspend/resume, unbind/bind on the host (`./bench/usb3_lanes.py $B watch`
running): enumerated again at Gen 1x2 each time. U1/U2 (only if the host enables them: x2 Link flow
control timers): entries/exits in the `usb3_debug.py` counters, transfers still without errors.

## Report

Results to report, per test and per board:
- `status` JSON (LTSSM state, x2, deskew/lanes swap, per lane ready/RX idle/RX polarity, counters,
  `rx_overflow`/`rx_drop` with the `--lanes-core` Gen 1x2 builds).
- `prbs` final JSON (rates, errors, recoveries).
- Two boards, core: `script` output (per run results, final line), failing step/section on an
  error, Device `usb3_core` counters.
- Single board: `lsusb -t` line of the device, `status` JSON, `usb3_bench.py` results, host
  controller (`lspci`), SFP2USB cage.
- Gen 1x2 core: `speed`/`rx_lanes`/`tx_lanes`, `status` JSON, `usb3_bench.py` results per plug
  orientation, host controller and cable references, `dmesg` lines of the enumeration.
- On a failure: `retrain` output (LTSSM state history), per lane counters (`lane0/1_ts1`,
  `ts1_inv`, `ts2`, `rx_errors_cycles`, `deskew`), DAC cables references/lengths.

## Results (Two Boards, 2026-11-08)

Summary (latest builds, crossed cables, one Host and one Device bitstream for Gen 1x2 and Gen 1x1):

| Part | Status |
|------|--------|
| PHY, PRBS (tests 1-6) | Validated: 610MB/s per direction without errors, retrains, lanes swap, unplug/replug, 20/20 bitstream loads good. Single lane fallback (test 5): with both PHYs retrained together (a Device not x2 capable starting alone times out to Compliance: open). |
| Device Core at Gen 1x2, scripted host (tests 7-9) | Validated: 400/400 runs over 20 bitstream loads (with `--lpm-hold rxeq`, the default with `--lanes 2`), again after the upstream merge (`cb7efab`). |
| Device Core at Gen 1x1 (test 10b) | Validated: 400/400 runs over 20 bitstream loads, same bitstreams (runtime Gen 1x2 control). |
| Soak (test 10, one load, 10000 runs, Host `cb7efab`, Device `32dd75c`) | Gen 1x2: 10000/10000, 0 LBAD/retry (21221 Hot Resets: about 1.1 run restarts per run after a U0 exit; Device Link Layer 2641 Recovery requests during the runs: `pending_hp`, following the lanes events, see the Device Recovery causes results). Gen 1x1 (`--x1`): 10000/10000, one Hot Reset per run, no Device Recovery request. One Warm Reset at the start of each. |
| USB hosts (tests 11-18) | Not run: SFP2USB adapter, dual SFP to USB-C breakout and Gen 1x2 host needed. |

Results after each fix (two Acorn Minis, crossed cables, 20 loads x 20 scripted runs unless noted):

| Change | Results |
|--------|---------|
| Single lane fallback (test 5), `50681d4` | Before the Compliance fix: 6/10 loads (both boards retrained together), PRBS 303MB/s per direction without errors; 4/10 Device in Compliance. |
| Soak, `50681d4` | Inconclusive: ~4970 runs, then the Host FPGA reconfigured from its flash (no USB event: power?). `bench/acorn_x2_loads.py` now checks the boards identifiers before and after the runs. |
| Device Core at Gen 1x2, Compliance exit (`daa2451`) | 400/400 runs over 20 loads; Host port resets (Warm Reset, Device out of Compliance) on 2 loads. |
| Device Core at Gen 1x1 (test 10b, `daa2451`) | 349/400 runs: 16/20 loads 20/20 (2 Warm Resets each: Device out of Compliance), 2 loads 14-15/20, 2 loads without U0 after 74 Warm Resets (open). Before the Compliance fix (`50681d4`): 200/400, alternating loads. |
| One Host/one Device bitstream (`3a208f9`, Gen 1x1 by the runtime control) | Gen 1x2: 340/400 (17/20 loads 20/20); Gen 1x1 (`--x1`): 280/400 (14/20 loads 20/20). The other loads never reach U0, both modes (open): the Host Configuration Lane receives the Device Polling LFPS chopped (counted as Ping/U1 exit LFPS, its electrical idle detection toggling: 358106 transitions in 3s), the Device hears the Host; the Warm Resets loop every 600ms (Device Polling.LFPS -> Compliance -> Warm Reset). Load and build dependent (Host build WNS +0.002ns). |
| RX idle filter spikes rejection (`90220e2`, one Host/Device bitstream) | Gen 1x1 (`--x1`): 400/400 runs, 20/20 loads (1-2 Warm Resets per load: Device out of Compliance). Gen 1x2: all 20 loads train (no stuck load, no Warm Reset needed), 338/400 runs: 15/20 loads 20/20, 5 loads with `link_init` errors/timeouts at Gen 1x2 (Host build WNS +0.009ns: scripted host model step -> script ROM path, open). |
| Scripted host ROM registered (Host `1e04ceb`, WNS +0.247ns; Device `90220e2`) | Gen 1x2: 330/400 (15/20 loads 20/20, all loads train); Gen 1x1: 300/400 (15/20 loads 20/20, 5 loads stuck again: the spike rejection is not enough on every build/load). The failing loads in both modes are Host Lane 0 (SFP-0) receive quality: on the Gen 1x2 ones 1.2-3.1 million comma realignments (<= 90000 on the good loads), on the stuck ones the LFPS idle detection spikes: load dependent, GTP RX adaptation or the channel (open). Not the scripted host timing. |
| GTP LPM adaptation hold (`--lpm-hold rxeq`, `885d9f1`) | **Gen 1x2: 400/400** runs (20/20 loads), **Gen 1x1 (`--x1`): 400/400** (20/20 loads, 20 Recoveries per load: the runs Hot Resets only). The receive quality changes from one load to the next came from the continuous GTP LPM adaptation (Host Lane 0): adaptation only in Polling.RxEQ, now the default with `--lanes 2`. |
| Test 5 rerun, PRBS bitstreams `4d6d82d` (runtime Gen 1x2 control on the Device, Host port reset, LPM hold) | 10/10 loads: Gen 1x1 on both boards, Device SFP-1 (lanes swap), PRBS 303.9 MB/s per direction, 0 errors, 0 Recovery. |
| Scripted host idle link initialization (Host `4d6d82d`, `edf05ce`; Device `885d9f1`) | Out of the runs: Host Recoveries per load 20-167 (40-3400 before), Device Recovery requests before the first run 0-8 (median 32-193 before). Runs: Host `4d6d82d` 399/400 (20 loads), soak 10000/10000; Host `edf05ce` 371/400 (2 loads with Hot Reset storms), soak 9987/10000 (11 LBAD). The idle initialization was off during these runs (`usb3_lanes.py script` cleared its control bit, fixed): the differences are Host build to build variations (open). |
| Upstream merge (Host `cb7efab`, Device `32dd75c`: upstream RX idle filter with `rx_idle_min_burst=40e-9` on the Gen 1x2 builds) | **Gen 1x2: 400/400**, **Gen 1x1 (`--x1`): 400/400** (20 loads each, no failed run). The scripted host idle initialization is optional (off by default: an idle Hot Reset not completing blocked the runs on 4/20 Gen 1x2 loads with `84b4965`), a Hot Reset not completed in 20ms is abandoned. |
| Device Recovery causes (Host/Device `e2f900d`, WNS +0.253/+0.152ns, 5 loads x 200 runs) | **1000/1000** runs, no bad load. Device Link Layer Recovery requests during the runs: 11, 174, 18, 11, 9 per load (0.05-0.09 per run on 4 loads), almost all `pending_hp` (LGOOD_n not received in time), `lcrd` 28 on load 2 and 1 on load 5, `lgood`/`hp_seq`/`credit_hp` 0. They follow the lanes events: load 2 (bad receive) has Host `deskew_lost_u0` 321 and Device `realign_u0` 141 (15-24 on the other loads). Host Lane 0 (SFP-0) comma realignments 101580 vs 2374-7195 on the other receivers. More `pending_hp` before the runs (57-231 per load: the scripted host does not acknowledge before the first run, expected). Open: the Host Lane 0 receive (cable, cage or board). |
| Device Recovery causes, straight cables (same bitstreams, SFP-0/SFP-0, SFP-1/SFP-1) | **1000/1000** runs, `lane_swap` 0 on both boards. Good loads (1-3): 13-16 Device Recovery requests per 200 runs, `pending_hp`. Bad loads 4-5: 231/306 requests (`pending_hp`, `lcrd` 45/52; the per cause counters are 8-bit and saturate at 255 with the requests before the runs: the requests not attributed are `pending_hp`), Host `deskew_lost_u0` 247/290. Comma realignments (median): Host SFP-0 19316, Host SFP-1 76258 (the Host receiver fed by the Device SFP-1 is the worst in both cablings: 101580 crossed), Device SFP-1 19986 (1.2-1.9 million on the bad loads). The bad link follows the Device SFP-1 path (cable or cage: cables exchanged next). |
| Device Recovery causes, straight cables, the two DAC cables exchanged (same bitstreams) | **759/1000** runs (241 `link_init` timeouts/errors): load 2 0/200 (Host in eSS.Inactive, deskew lost, 29348 resets), load 3 159/200, loads 1, 4, 5 200/200. The SFP-1 receivers stay the worst on both boards with either cable (Host SFP-1/SFP-0 realignments about 3.5x, as before the exchange; Device SFP-1 up to 5.1 million), and this cable pairing is worse overall. With the crossed run (the Host receiver fed by the Device SFP-1 worst): the receivers fed by an SFP-1 transmitter are the weak ones, on both boards (SFP-1 channel of the Acorn Mini, not one board or one cable). Next: GTP TX pre-emphasis/swing A/B (`--gtp-param i_TXPOSTCURSOR=...`). |
| GTP TX post-cursor pre-emphasis (`--gtp-param i_TXPOSTCURSOR=0b00110` on both boards, `36ad31d`, WNS +0.213/+0.245ns), same cabling as the previous row | **998/1000** runs (759 without): no collapsed load (worst 198/200, 800 resets; 0/200 and 29348 resets without). Host SFP-1 (fed by the Device SFP-1) 21k-55k comma realignments on 3 loads (~114k without), Device SFP-1 38-228k (54k-5.1M without). 10-38 Device Recovery requests per 200 runs (`pending_hp` first, `lcrd` on the worse loads). Load to load variation remains: 2 loads with 340k-600k Host realignments on both lanes. |
| GTP TX post-cursor pre-emphasis 10 (`i_TXPOSTCURSOR=0b01010`, `36ad31d`, Host WNS +0.008ns, Device +0.431ns), same cabling | **974/1000** runs: loads 1-4 800/800 and the cleanest so far (Device comma realignments 26-685 per lane, Host lanes balanced, 206-220 resets), load 5 collapsed (174/200, 15137 resets, Host Lane 1 9.3 million realignments, first `rx_lbad`: 16). 5 loads do not separate 6 from 10 on the bad load rate; 6 kept as the `--lanes 2` default (more margin: Host WNS +0.213ns vs +0.008ns). The bad loads are not cured by the TX pre-emphasis (receive side, load dependent). |
| Reference rerun with the defaults (`3bb7f88`: pre-emphasis 6, 16-bit Recovery cause counters; WNS +0.223/+0.231ns), crossed cables, 20 loads x 20 runs | **400/400** runs, 20/20 loads, `lane_swap` Device 1/Host 0. Device receive much cleaner than without pre-emphasis (comma realignments median 50/72 per lane vs 2374/7195). Host Lane 0 (fed by the Device SFP-1) unchanged: median 110k (101k without). Device Recovery requests during the runs 7-33 per 20 runs (173 on one load), all `pending_hp` (`lcrd` 4 and 1 on two loads); before the runs 170-350 per load (5283 on one load). The earlier "`pending_hp` 0 during the runs" was read on the 8-bit counters, already saturated by the requests before the runs: not comparable. |
| Pre-emphasis per SFP cage, `--tx-postcursor 6,10` (`f7a86af`, Host WNS +0.001ns, Device +0.134ns), crossed cables, 20 loads x 20 runs | **399/400** runs (1 `link_init` error). Host Lane 0 (fed by the Device SFP-1) median 77k comma realignments (110k with 6 on both cages), Device unchanged (44/73). Device Recovery requests during the runs median 8.5 per 20 runs (15), but less steady links: Hot Resets median ~33 (20), Host `deskew_lost_u0` 44-153 on 7 loads (at most 45), `lcrd` Recoveries on 7 loads (2). Not adopted: 6 on both cages stays the default. The Host builds' timing margin varies a lot between builds (+0.223, +0.008, +0.001ns): to watch. |
| Scripted host idle link initialization on by default + timing register stages (Host `5eefc1e`, sys WNS +0.123ns, design WNS +0.084ns in the Lane 1 TX clock domain; reference Device build), crossed cables, 20 loads x 20 runs | **398/400** runs (1 `ss:end` and 1 `link_init` error on two noisy loads). Device Recovery requests before the runs 1-27 per load (170-350 with the reference Host, 65535 with the register stages alone: the idle host now acknowledges the Device), Host Recoveries 40-283 per load (55-371), Device requests during the runs median 3.5 per 20 runs (15). Receive quality varies more between these loads (Hot Resets median ~46, Host Lane 0 rx_errors_cycles up to 228M); 5 loads near-perfect. |
| `LanesPacketAligner` parser without the 8-step chain (t3: Host + Device built at `1192007`; Host design WNS +0.315ns, Device +0.236ns in the GTP domains, sys WNS +0.602/+0.679ns, aligner worst path +1.008/+0.959ns), crossed cables, 20 loads x 20 runs | **398/400** runs (1 `ss:end` and 1 `link_init` timeout, both on load 10: 8 Hot Resets, rx_errors_cycles ~690M per lane, about 10x any other load; runs 13-20 of that load passed). Hot Resets median 23.5 per load (20-66; t2 ~46, reference ~20), 8 loads near-perfect (20-22 resets). Device Recovery requests before the runs 0-12 (median 2; t2 1-27), Host Recoveries 40-168 (median 60; t2 40-283, median 109.5), deskew lost in U0 median 6 Host/5 Device (t2 10/28.5), Host Lane 0 rx_realign median 23.7k (t2 73k, reference 110k), Lane 1 1.5k (t2 21.8k). Unchanged: Device requests during the runs median 3.5 per 20 runs, all `pending_hp`/`recovery_req` (bursts with `lcrd` on loads 9, 11, 18). |

The sections below are in chronological order: first results, what was found on hardware and fixed
(each reproduced in simulation first), and the results after each fix.

Two LiteX Acorn Baseboard Minis (FT2232H) + SQRL Acorn CLE-215+, two passive SFP DAC cables,
Vivado 2023.2 (all builds timing met unless noted). The first results (tests 1-10 passed) were obtained on
bitstream loads that happened to be good: about half of the loads were not, until the fixes below
(found with `--analyzer-group lanes` captures and the `USB3LanesDebug` counters).

PHY with the PRBS stand-ins (`acorn_x2_host`/`acorn_x2_device`, all the fixes):

| Test | Result |
|------|--------|
| 1. Link up (straight) | U0, `x2: 1`, deskewed, `lane_swap: 0` on both boards. |
| 2. PRBS | 60s, 0 errors/0 recoveries in both directions, 610MB/s per direction (straight and crossed). |
| 3. Retrains | 10 double retrains: deskewed on both boards, PRBS 5s after each without errors. |
| 4. Lanes swap (crossed) | Device `lane_swap: 1`, Host `lane_swap: 0`, PRBS 0 errors. |
| 5. Single lane fallback | `x2: 0` on both boards, U0 on the Configuration Lane (Device SFP-1 with crossed cables), PRBS 0 errors, 305MB/s. |
| 6. Unplug/replug | Link out of U0 on the unplug, Polling retries, U0 deskewed on the replug, PRBS 30s 0 errors. |
| Bitstream loads | 20/20 loads good (crossed cables), the Recovery on a lane realignment in U0 used on 11 of them. |

Device Core with the scripted host (`acorn_x2_host_script`/`acorn_x2_device_core`), first results
(before the fixes below):

| Test | Result |
|------|--------|
| 7. Link up, core | U0 at Gen 1x2, deskewed; not stable (Recoveries in and out of the script runs). |
| 8/9. Scripted host | 100/100 runs on a first build, but 35-60% of the runs done on every load of later builds, including a rebuild of the same commit (`d32dd6f`): not a regression of the fixes, a build/load dependent behavior. ~3 Recoveries per run: mostly Host U0 entries without the lanes deskewed (`deskew_lost_u0`), Host lanes comma realignments (`lane0/1_rx_realign`, 10^5 per 20 runs), a few Device Link Layer Recoveries (`lgood`, `pending_hp`). Device LBAD 0-2, retries 0. |
| 10. Soak | 10200 runs done on the first build only. |

Found on hardware:
- All the Acorn Mini SFP RX polarities are inverted (flipped at the end of Polling.Active on the 4
  receivers, `sim.py --lanes-tx-inverted`).
- Fixed: the lanes deskew acquired on the first TS1 lost before U0 (U0 without data): Recovery on a
  deskew lost in U0 at Gen 1x2.
- Fixed: a lane in electrical idle in U0 (cable unplugged): Recovery on a lane idle for 10us.
- Fixed: a lane words alignment changed in U0 (GTP comma realignment or RX re-initialization: the
  lanes are only re-aligned on COM, none in U0): the link flapped, stayed in Polling or stayed in
  U0 with every x2 word corrupted (symbols rotated by 2, lanes paired one word apart), until the
  next bitstream load (PHY retrains did not help, a RX reset in U0 reproduces it): Recovery on a
  comma realignment/RX re-initialization in U0 at Gen 1x2 (`realign_u0`), RX re-initialization of a
  lane with continuous decode errors (`rx_errors_reinit`).
- Ruled out: RX elastic buffer errors (`rx_buferror` always 0), the GTP CDR hold during electrical
  idle (raw idle detection vs filtered idle: no difference), unconstrained paths (only the JTAGBone
  and the LEDs, `check_timing`), the Recovery on a lane idle (counters at 0 on the bad loads).
- Open (Device Core pair): Recoveries during the script runs (Host U0 entries without deskew,
  continuous Host comma realignments), build dependent (see below).

Scripted host with a Hot Reset before each run (Device `acorn_x2_device_core` built after `88049cc`
for all, crossed cables, 20 loads x 20 runs per host build, both boards loaded on each load,
`--analyzer-group` none):

| Host build | Runs done | Bad loads | Host `realign_u0` (median) | Host Recoveries (median) | Device Recovery causes (median per load) | Script errors |
|------------|-----------|-----------|----------------------------|--------------------------|------------------------------------------|---------------|
| `3fe469f` (no Hot Reset) | 246/400 (62%) | 0/20 | 72 | 90 | `pending_hp` 77, `lgood` 12, `hp_seq` 2 | 154, `link_init` |
| Hot Reset, build A | 256/400 (64%) | 2/20 | 71 | 114 | `pending_hp` 84 | 144, `link_init` |
| Hot Reset, build B (same source as A) | 340/400 (85%), 340/340 on the good loads | 3/20 | 14 | 89 | `pending_hp` 220 | 60, on the bad loads |

- The Hot Reset removes the `lgood`/`hp_seq` Device Recoveries (Header Sequence Numbers in step at
  each run start), with little effect on the runs done (62% to 64% on build A).
- The runs done follow the build: two builds of the same source, 64% and 85%, build B with ~5x
  fewer Host lanes realignments in U0. The `link_init` script errors are not U0 exits (restarted
  with a Hot Reset): words corrupted around the lanes realignments in U0 (PHY, build dependent).
- Bad loads (Host lanes flapping: 10^6 comma realignments, Device in Polling.LFPS/eSS.Inactive): 0/20
  without the Hot Reset, 5/40 with it (not significant on these samples; a Hot Reset requested at
  each U0 entry of a flapping link not ruled out).
- `pending_hp` Device Recoveries remain on all builds (not removed by the acknowledges after the
  runs: before the first run, during the Hot Resets/link initializations or the script restarts by
  the client, not separated: the Device Core counters are not cleared before the runs).

Host lanes realignments in U0 captured (`--analyzer-group realign`, `usb3_analyzer.py capture
--trigger lanes_realign --no-retrain` during scripted runs, a realign prone load: 122 `realign_u0`
per 20 runs) and frozen LTSSM histories of both boards (first 32 transitions after a clear, around
a Host realignment): the realignments are a consequence, not the cause.
- On the 3 captures, the Host is in U0, deskewed, when both lanes get continuous decode errors then
  electrical idle at once (2-8us before the trigger), followed on lane 0 by ~1us bursts every
  6-11us (the Device Polling.LFPS): the comma realignments are on these bursts. The Device has left
  U0 while the Host stays in it.
- The histories show how the Device leaves: Hot Reset handshakes not converging (Device
  HotReset.Active -> HotReset.Exit in ~2us, then tHotResetExitTimeout 2ms -> eSS.Inactive -> Polling,
  while the Host stays in HotReset.Active until tHotResetActiveTimeout 12ms: 4 Host HotReset.Active
  entries, 2 exits; 5/5 Device exits), and Recovery.Idle timeouts (2ms -> eSS.Inactive). The Host
  also re-enters HotReset.Active from Polling.Idle (scripted host Hot Reset request still asserted).
- Reproduced in simulation (`sim.py --lanes 2 --lanes-core --host-hot-reset 4 --lanes-crossed
  --lanes-tx-inverted`: Hot Resets back to back, each one at the U0 entry after the previous one):
  HotReset.Active entries skewed (121 cycles, Device later), a side left HotReset.Active on the
  partner Reset bit fall without having sent any Reset=0 TS2, the partner then stuck in
  HotReset.Active (12ms) while the side timed out in HotReset.Exit (2ms), both to eSS.Inactive.
  Fixed in the LTSSM: HotReset.Active exit at the end of a full TS2 burst with Reset=0 sent after
  the partner Reset bit fell (7.5.12.2), `TestPHYX2Core.test_core_x2_hot_resets`.
- With the Hot Reset fix (`bcd01c5`, 20 loads x 20 runs): 313/400 runs done, 300/300 on the 15
  good loads, Device `pending_hp` during the runs median 5 per load; 5 bad loads: both sides
  re-entering U0 thousands of times, each U0 entry without deskew (`deskew_lost_u0` ~ `u0_count`),
  the Hot Resets themselves completing (HotReset.Exit -> U0 in ~3us).
- Deskew lost in U0 captured (`--trigger lanes_deskew_lost,ltssm_u0`, bad load): the deskew dropped
  at the end of the Recovery TS2, the Device last TS2 COM words one word apart on the lanes (a decode
  error substituted, K28.4, at the end on Lane 0), Logical Idle after them still paired (both lanes
  descrambled to zeros): a false loss. The Host then entered U0 without deskew and went back to
  Recovery.Active at once (TS1) while the Device was still in Recovery.Idle (idle handshake, no exit
  on TS1): Device tRecoveryIdleTimeout (2ms) -> eSS.Inactive, Host tRecoveryActiveTimeout (12ms), and
  a Recovery without a Logical Idle gap does not re-arm the deskew (the U0 entries/Recoveries loop).
- Fixed: the deskew pairing is lost on a second mismatch without paired markers in between (a single
  mismatch tolerated: end of an Ordered Sets stream), and the Recovery on a deskew lost in U0 waits
  for the deskew search armed (Logical Idle gap: the partner in U0, the deskew re-acquired on the
  Recovery TS1). `test_lanes` deskew mismatch tests, `TestPHYX2Core.test_core_x2_deskew_lost`
  (`sim.py --host-recovery --host-deskew-clear`).

Results with the fixes (Device `cb0bfb6`, 20 loads x 20 runs, crossed cables):

| Host build | Runs done | Loads all done | Loads none done | Timing (Host WNS) |
|------------|-----------|----------------|-----------------|-------------------|
| `3fe469f` (no Hot Reset) | 246/400 (62%) | 1 | 0 | met |
| `bcd01c5` (Hot Reset fix) | 313/400 (78%) | 15 | 4 | met |
| `cb0bfb6` (deskew fixes) | 385/400 (96%) | 18 | 0 | -0.548ns (`LanesPacketAligner`) |
| `LanesPacketAligner` positions pipelined | **400/400** | **20** | 0 | +0.172ns |

- Device Core counters during the runs: no Recovery request (`pending_hp` 0 on every load), no
  LBAD/retry; one Hot Reset per run on most loads (no run restarted).
- Host Recoveries outside the runs remain (40-3400 per load: before the first run, the Device
  `pending_hp` Recoveries while the scripted host is idle), Host lanes realignments in U0 20-470 per
  load: Recoveries the link recovers from.
- `LanesPacketAligner` (Host Link Layer RX) was the critical path of the Host builds (a chain of 8
  additions from the buffer level): the symbols positions are now computed one cycle earlier for
  the 4 offsets of the level in its word (one more cycle of latency).
- Next: the Host Recoveries outside the runs (scripted host idle: acknowledges before the first
  run), the Device Core with a USB 3 host (tests 11-13). Tools: `bench/acorn_x2_loads.py`.

Debug controls (`usb3_lanes_debug_control`, A/B tests on a loaded bitstream): bit 0 Recovery on a
lane idle, bit 1 RX re-initialization on continuous errors, bit 2 Recovery on a lane realignment in
U0, bit 4 Recovery on an odd SKP run in U0 (all set by default; `usb3_lanes.py
idle-recovery-*`/`rx-reinit-*`/`skp-recovery-*`). Counters in `usb3_lanes.py status`:
`deskew_lost_u0`, `lane_idle_u0`, `realign_u0`, `skp_odd_u0`, per lane `rx_buferror`, `rx_realign`,
`rx_skp_odd`, `rx_errors_reinit`, `rx_idle_u0_cycles`, `rx_idle_raw_u0_cycles`.

### Device `pending_hp` during the runs: a lane one Symbol off after a SKP error (2026-11-14)

On the t3 run (20 loads x 20 runs), the Device Link Layer Recovery requests during the runs follow
the Host `deskew_lost_u0` almost one to one (Spearman 0.95 over the loads, `deskew_lost_u0` >= the
requests on 19/20 loads) and the Device lanes comma realignments (0.9, with the `lcrd` causes on the
same loads: Link Commands lost on the Device receive side). The scripted host acknowledges every
Header Packet start it sees (no LBAD, no timer): a `pending_hp` is a Device Header Packet or its
LGOOD_n not received, then 10us of no acknowledge.

Cause found in the RX path: the 8b/10b errors are substituted (K28.4) before the per lane SKP
removal, and the lanes deskew is only checked on the TS1/TS2 COM words. A SKP Symbol received with
an error is not removed: that lane is one Symbol off the other lane, every destriped word is
corrupted, and nothing in U0 detects it until a Link Layer timeout (Device PENDING_HP_TIMER). The
Device Recovery TS1 then shows the lanes unpaired on the Host side (`deskew_lost_u0` counted after
the fact). Reproduced with `sim.py --lanes 2 --lanes-core --host-script 900000 --lane-skp-error
303000,DIR,LANE` (one SKP Symbol error on one lane during the run): any direction/lane gives a Device
`pending_hp` Recovery ~1600 cycles later, then the run restarted.

Fix (`RXSKPParityCheck`, `USB3PHY(lanes=2)` only, single lane Verilog unchanged): Gen 1 SKP Ordered
Sets are 2 Symbols, added/removed whole (per lane SKP counts may differ, always even): a SKP run of
odd length on a lane in U0 is a lane realignment (deskew cleared, Recovery at once). In the same
simulations: Recovery ~10 cycles after the error, no Device Link Layer Recovery request
(`TestPHYX2Core.test_core_x2_skp_error`); no odd run on the PRBS/core simulations with per lane SKP
differences, +/-300ppm, crossed lanes. Hardware run pending: `skp_odd_u0`/`lane*_rx_skp_odd` against
the Device `pending_hp` (`usb3_lanes.py skp-recovery-disable` for the A/B on one load).

Also seen in these simulations (separate, open): after the Host Recovery and the run restart Hot
Reset, the Host enters U0 24 cycles before the Device and its Header Sequence Number Advertisement
(LGOOD_n) can be lost (Device in HotReset.Exit): one Device `pending_hp` Recovery (the Device waits
for the Advertisement), then the run restarted (`--lane-skp-error 303000,d2h,0`).

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `litex_cli --ident` fails or returns another design | `--location` of the board (`acorn_ftdi.py list`), J10 Pico-EZmate cable, `--bind-port`/`--port`, `litex_server` restarted after the load. |
| No U0, `rx_idle: [1, x]` | No signal on Lane 0: SFP-0 cable seated, the partner bitstream loaded. |
| Stuck in Polling, `rx_errors_cycles` increasing | Receiver equalization through the DAC cable: `--lpm-hold rxeq` (default with `--lanes 2`), a shorter cable. |
| U0 with `x2: 0` and straight cables (x2 bitstreams) | Lane 1: `lane1_ts1` stays at 0 or `rx_idle[1]` stays at 1 (SFP-1 cable), `--no-x2` bitstream loaded by mistake. |
| U0 but `deskew_aligned: 0`, or PRBS errors in one direction only | `retrain` output of both boards (history), `deskew` counter. |
| Link flapping, stuck in Polling or no PRBS words after a load (retrains do not help) | `lane0/1_rx_realign`, `realign_u0`, `deskew_lost_u0` counters; reload the bitstreams; `--analyzer-group lanes` capture. |
| PRBS errors increasing slowly | `rx_errors_cycles` per lane (link quality), `recovery_count`, cable length. |
| `lane_swap: 1` with straight cables | Cables swapped (SFP-0/SFP-1 cages). |
| Two boards, core: script `timeout` | Link not in U0 (`status` of both boards, test 1 with the PRBS bitstreams), Host board `--lanes-core` bitstream loaded. |
| Two boards, core: script `error` at `link_init` | Advertisements/LMPs not exchanged: Device board bitstream (`--lanes-core --example loopback`), `x2: 1` on both (SuperSpeedPlus script: a Gen 1x1 link is SuperSpeed), Device `usb3_core` state. |
| Two boards, core: script `error` at `bulk_in_*` | Data check failed: step offset in the section (DPH words, SDP, data word, CRC-32, END), `rx_overflow`, Device LBAD/retries; the same with `--runs` repeated (systematic or random). |
| Single board: not enumerated, U0 not reached | `status`/`retrain` history, the same SFP2USB/host/cable with the Gen 1x1 build (`bench/acorn.py` without `--lanes`) for a reference. |
| Single board: enumerated in one cage only | `lane_swap` and `rx_idle` per cage, `retrain` history in the failing cage. |
| Gen 1x2 core: `x2: 0` with a x2 host | Host x2 support (port, `rx_lanes`), cable with both SuperSpeed pairs, Lane 1 signal (`rx_idle[1]`, `lane1_ts1`), the two boards part (tests 1-4) for the lanes themselves. |
| Gen 1x2 core: U0 at x2 but not enumerated/transfer errors | `usb3_debug.py` Link Layer counters (LBAD/retries, recovery causes), `retrain` history; RX buffer overflow (`rx_overflow`/`rx_drop` in `usb3_lanes.py status`: dropped RX words, the Link Layer too slow); `rx_overflow` also set by a `LanesPacketAligner` symbols buffer overflow (host packets back to back right after short DPPs, [gen2-x2-roadmap.md](notes/gen2-x2-roadmap.md)). |
| Gen 1x2 core: works in one plug orientation only | `lane_swap` per orientation, CC/lane routing of the breakout (TX1/RX1 on SFP-0). |

## References

- [gen2-x2-roadmap.md](notes/gen2-x2-roadmap.md): Gen 1x2 PHY (`USB3PHY(lanes=2)`), simulation coverage,
  hardware milestones.
- [Debugging](manual/14_debugging.md): JTAG/`litex_server` setup, CSRs, LiteScope.
- `usb3_pipe/phy.py` (`USB3PHYX2Link`), `usb3_pipe/lanes.py` (`LanesTXPacker`,
  `LanesPacketAligner`): the Gen 1x2 Link interface.
- `bench/acorn.py` (`--lanes 2`, `--role`, `--no-x2`, `--lanes-core`), `bench/usb3_soc.py` (`add_usb3_lanes_link`),
  `bench/usb3_lanes.py` (client), `bench/acorn_ftdi.py` (FT2232H/FT4232H boards selection: list, load,
  litex_server).
