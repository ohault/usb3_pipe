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
| SKP run parity Recovery (t4: Host + Device built at `047511e`; Host sys WNS +0.316ns, design +0.247ns, Device sys +0.513ns, design +0.361ns, both in `usb3_serdes1_tx_clk`; the parity check reset fan-out is the Host `serdes_rx` worst path, +0.344ns), crossed cables, 20 loads x 20 runs | **386/400** runs: loads 2-20 380/380, load 1 never recovered (6/20, 14 `link_init` timeouts, ~1.9M Recoveries, 1.19M of them Host `deskew_lost_u0`, ended in Recovery.Configuration; `skp_odd_u0` 8562 Host/3557 Device, <1% of them). Loads 2-20: resets median 20 (11 loads at 20), Recoveries median 40/40, Host Lane 0 realign median 5, Device `pending_hp` during the runs median 0 (15-38 on the noisy loads 3, 7, 13, 20). `skp_odd_u0` 0 on the Device for every load but load 1, 0-2 on the Host: the odd SKP runs counted per lane (hundreds to tens of thousands on the noisy loads) are almost all out of U0. A/B on one noisy load (20 runs each): `pending_hp` 915 with the SKP Recovery, 664 without, Device `skp_odd_u0` 0 in both. The SKP slip is real (simulation) but rare on hardware: not the cause of the `pending_hp`; the lower median is load to load variation (Host Lane 0 realign also fell, which the check cannot change). Device `pending_hp` before the runs 109-365 on 4 clean loads (t3: 12 max), not explained. |
| Scripted host fixes (t5: Host `99ba623`, sys WNS +0.244ns, design +0.205ns in `usb3_serdes1_tx_clk`; Device: the t4 bitstream, its Verilog identical at `99ba623`), crossed cables, 20 loads x 20 runs | **387/400** runs: 12 `link_init` timeouts on load 14 (looping: 3725 resets, Host `deskew_lost_u0` 2749, Host ended in Recovery.Active), 1 `ss:end` error on load 18. Device Recoveries before the runs median 4, max 16 outside load 14 (t4: 109-365 on 4 loads): the Advertisement on the U0 re-entries works; idle 60s on 9 loads: 0 Device Recoveries. In-run Device `pending_hp` median 2 (0-16, 1566 on load 14), resets median 27. Looping loads remain about 1 in 20 (t4 load 1, t5 load 14, a probe load): Device Link trace on a probe looping load (3 captures): Device LMP sent after the Host Advertisement, Host LMP received and acknowledged by the Device, then nothing from the Host for 12.18us (Device LMP never acknowledged) with Host lane 0 ~255-299k comma realignments and Host `deskew_lost_u0` 103-157 per run: the Host receive path, not the `link_init` race. |
| Lane slip/TX flush/RX keep fixes (t6: Host + Device built at `30aab10`; Host design WNS +0.064ns in `serdes1_tx` (multireg -> GTP TXDATA), sys +0.239ns; Device design +0.309ns, sys +0.343ns), crossed cables, 20 loads x 20 runs | **314/400** runs (63 `link_init`, 23 `ss:end` errors, 10 loads with failures, loads 3 and 14 0/20): a regression, every load storms (resets median 848.5, t5 27; Host Recoveries median 1254, Device in-run `pending_hp` median 177). Cause: the new `com_slip` deskew clear fires on nearly every TS burst (median 1636 Host, 1307 Device per load); A/B on one load, `com-recovery-disable`: 20/20, 20 resets, Recoveries 40/40 (the minimum), 0 Device Recovery requests (19/20, 682 resets with it). LiteScope: see "Looping loads" (the first COM Symbols of an Ordered Set received as K28.4, the word aligner moved to the first intact COM). |
| Word aligner kept on K28.4 before a COM run, `com_slip` on lanes disagreement (t7: Host + Device built at `ec85995`; Host design WNS +0.250ns, `serdes1_tx` +0.421ns; Device design +0.239ns in `serdes1_rx`, sys +0.291ns), crossed cables, screen 1 load x 20 runs | **20/20** runs but 258 resets, Host/Device `com_slip` 118/320, Host Recoveries 477: over the screen limits, no 20x20. A/B on the same load: `com-recovery-enable` 19/20, 248 resets, 21 Device `pending_hp`, Recoveries 429/286; `-disable` 20/20, 29 resets, 7 `pending_hp`, Recoveries 55/67, Host `com_slip` 343000 (counted: the TSEQ words, one COM, with a deskew left aligned from before the Polling). t6 captures: no SKP removal before the corrupted COM words (0/38); 25/38 without a decoder `invalid` (most likely running disparity errors), 13 inconclusive. |
| Word aligner kept on any shortened COM run, `com_slip` on cut COM words (t8: Host + Device built at `2601dc1`; Host design/sys WNS +0.388ns (scripted host `model_step`, 14 levels); Device design +0.191ns in `serdes1_tx` (multireg -> GTP TXDATA), sys +0.222ns), crossed cables, 20 loads x 20 runs | **397/400** runs (2 `link_init`, 1 `ss:end`, one run each on loads 5, 11, 16, all ending U0/U0), no looping or stuck load. `com_slip` median 1 Host / 22.5 Device (t7 screen 118/320, t6 1636/1307), `rx_com_partial` tens per lane (t7 ~10M). Resets median 61 (t5 27), Host Recoveries 157.5 (t5 60), Host `deskew_lost_u0` 24, Device in-run `pending_hp` median 8 (max 156; screen load 267); 6 loads at or near the minimum (20-24 resets). A/B on a noisy load (133 resets per 20 runs): `com-recovery-enable` 54 resets, Recoveries 166/136; `-disable` 67 resets, 137/96: the check is neutral. The noisy loads have high `rx_realign`/`rx_errors_cycles` (receive quality). |
| t5 vs t8 A/B (no new build: A = t5 Host `99ba623` + t4 Device `047511e`, B = t8 pair `2601dc1`; builds matched by build time, idents and CSRs), crossed cables, 20 rounds alternating A/B order, 20 runs per load | **A 399/400** (1 `link_init` error, Host left in Polling.RxEQ), **B 400/400** (every load ending U0/U0). Clean loads (resets <= 24) 11/20 vs 10/20. Medians A/B (Mann-Whitney p): resets 23/24.5 (0.65), Host Recoveries 63.5/53.5 (0.65), Device Recoveries 62/47.5 (0.70), Device in-run `pending_hp` 1.5/3 (0.47); deskew_lost_u0, realign_u0, Host lane rx_realign/rx_errors_cycles p 0.57-0.95; worst load an A load (710 resets). Device Recovery requests before the runs 2/4.5 (p 0.047, not significant over 15 metrics). The t8 noise baseline was load variance/bench drift, not the gateware changes since t5. |
| RX error type counters (t9: Host + Device built at `473b81f`; Host design WNS +0.095ns in the Lane 0 RX domain (t8 +0.626ns: the RX reset fan-out, larger with the counters), Device +0.171ns), crossed cables, 20 loads x 20 runs | **360/400** runs: 18 loads 360/360, loads 4 and 15 stuck in Polling.LFPS on both boards (0 runs; seen before at 1-3 per 20 loads, 0 in t8 and the A/B: p 0.06). Good loads: resets median 33.5, Host Recoveries 92, Device in-run `pending_hp` 6.5, clean loads 7/18 (within the t8/A/B spread, p 0.07-0.92). The new counters were unusable: counted in the SerDes RX clock domain, reset with each transceiver RX reset, the clear snapshot then gave wrapped readings (18/20 loads). 60s idle in U0 on a noisy load: no error on any counter, no Recovery (below ~1e-10 per lane): the errors come with the resets, training and Recoveries. |
| RX error type counters fixed (t10: Host + Device built at `2ec7f82`; Host design WNS +0.326ns, Lane 0 RX +0.456ns (t9 +0.095ns); Device +0.181ns), crossed cables, 20 loads x 20 runs | **394/400** runs (6 `link_init` errors on loads 4, 8, 15), no load stuck in Polling.LFPS. Resets median 89.5, Host Recoveries 217.5, Device in-run `pending_hp` 3.5, clean loads 2/20: noisier than t9 (p 0.001), but a 10-round interleaved t9 vs t10 A/B shows no significant difference (resets 40.5 vs 78, p 0.27; t9 itself noisier than in its run): bench drift over the evening. Counters: cleared to 0, only increasing across Hot Reset, SerDes RX resets, PHY retrains. Decode errors 98-99.7% of all errors, mostly training/Recovery activity (Host decode totals vs Host Recoveries rho 0.92; ~43k per Host lane on clean loads); disparity errors the line quality signal (~80 per Host lane on clean loads, 860-1280 on noisy loads); errors before a COM 0.009% of all, on the Host lanes more often disparity than decode (1.4-1.6x). Device RX Lane 1 has 46% of all errors and most disparity errors (~661 per reset vs 7-13 on the other lanes), Host RX Lane 0 22%; worst lane per load: Host L0 on 10 loads, Device L1 on 10; Device RX decode errors track the Device in-run `pending_hp` (rho 0.85/0.79). |
| TX post-cursor sweep (t11: Host + Device built at `a1a1784`, runtime TXPOSTCURSOR; Host design WNS +0.214ns, Device +0.079ns: sys reset fan-out to the error counters accumulators), crossed cables, 10 loads x 14 settings x 10 runs, paired per load, random order, retrain before each setting | Sweep A (Host SerDes 0 TX, feeding Device RX SerDes 1 per the cabling) and B (Device SerDes 1 TX, feeding Host RX SerDes 0, confirmed: at 31 the Host RX SerDes 0 disparity errors go from ~5 to 37.7 per reset) at 0, 3, 6, 9, 12, 16, 20: **no value better than 6** (paired p >= 0.08 for every value, loads split evenly), no effect on the other lanes. The load explains the variance (p 1e-9 to 1e-20), the setting none (p 0.29-0.96): load 10 ~390 resets per 10 runs at all 14 settings (23 failed runs, all on it), loads 5 and 9 clean at all; the Device RX errors come in random bursts at any setting. Keep `--tx-postcursor 6`. |
| Transceivers re-initialization at runtime (t12: Host + Device built at `93ea941`, `xcvr_reinit`: both GTP channels TX/RX and the shared Quad PLL reset 10us, then initialized as at the load; Host design WNS +0.066ns (Lane 0 RX +0.093ns), Device +0.077ns), crossed cables, 20 loads x 14 rounds x 10 runs (per load: baseline retrain, then in random order 5 re-inits of both boards, 2 retrains, 3 Device-only and 3 Host-only re-inits) | **2800/2800** runs; 3 of 220 re-inits needed a retrain to be in U0 x2 within 1s. **The re-init re-draws a load's noise**: share of the variance between loads, resets 0.95 with retrains only (t11) vs -0.15 with re-inits of both boards (p 0.99), Host Recoveries 0.95 vs -0.16; the reset class (> 15 resets per 10 runs) changed vs the load baseline in 29 of 100 both-board re-inits (12 clean to noisy, 17 noisy to clean) vs 6 of 40 retrains, larger within-load spread after re-inits (resets p 0.048); a re-init draw is kept by the next retrain (10 of 14). Resets/Host Recoveries re-drawn by either board's re-init; the Device RX SerDes 1 disparity stays with the load when only the Device is re-initialized (0.51, p 9e-5) and changes with a Host re-init: set by the Host SerDes 0 transmitter start-up. Bench noisier this session (34/40 retrain rounds reset-noisy). |
| Transceivers status/DRP and re-initialization until clean (t13: Host + Device built at `35be39a`: per SerDes status (TX/RX ready, Quad PLL lock/refclk lost, TX/RX buffer status, CDR lock), Quad PLL lock lost/TX buffer error counters, DRP access; Host design WNS +0.149ns, Device +0.135ns), crossed cables. A: 8 loads x 6 draws (both boards re-initialized per draw, status + DRP 0x000-0x0ff of the 4 channels, 10 runs). Onset: 10 loads x 40 bursts of 5 runs (~65s). B: 20 + 20 interleaved loads x 20 runs, `--reinit-until-clean 5 --check-runs 5 --clean-disparity 25` vs without | A: 480/480 runs, 48/48 draws in U0 x2. **Two noise levels**: worst lane disparity per reset <= 11.9 (24 draws, Host Recoveries exactly 2 per reset) or >= 33.9 (24), nothing between; 6 noisy draws with only 10-13 resets. **No status bit, counter or DRP address separates them**: DRP 0x000-0x0ff identical on all draws and lanes; Quad PLL lock lost only at the start-up; refclk lost constant (Lane 0 1, Lane 1 0: not a real loss); TX buffer error on 2 clean draws; Lane 1 TX buffer half-full varies, unrelated (Fisher p >= 0.52). Onset: no settling time (early vs late bursts rho -0.06); a draw sets the rate of short noise episodes (2 loads noisy in 95-100% of the bursts, 3 in 40-55%, 5 in 2-17%); after 1-4 clean check bursts the next 20 runs are clean 55-64%. B: **400/400 + 400/400** runs; first check clean on 11/20 loads, all 20 ended clean (re-inits 0 x11, 1 x6, 2 x1, 3 x2, budget never reached), +2s per load (median 18 vs 16s); reset-noisy loads 1/20 vs 7/20 (Fisher p 0.044), resets max 26 vs 156 (median 20.5 vs 22.5, p 0.059); disparity per reset, Host Recoveries, Device pending_hp unchanged (p 0.52-0.98, disparity-noisy loads 9/20 both): a screen for the reset-heavy draws, not a fix. |
| Lanes noise monitor (t14: Host + Device built at `fc9cc51`, `LanesNoiseMonitor`; Host design WNS +0.214ns, Device +0.081ns: sys reset fan-outs), crossed cables. Calibration: 8 loads, monitor measuring only, 0.5s windows logged, 30s idle U0 then 40 bursts of 5 runs. A/B: 30 interleaved loads x 20 bursts of 5 runs, monitor enabled on both boards (2s windows, 2 noisy windows, holdoff 2, disparity 200/lane, 30 Recovery entries, budget 8) vs measuring only; then 10 + 10 loads Host-only vs Device-only monitor | Calibration: 1593/1599 runs (noisy bench: 175/320 bursts noisy); window sums = status counters; idle U0 windows: 0 errors, 0 Recoveries; a burst's errors land in one 0.5s window (0.5-1s windows with 2 in a row catch ~20% of the noisy bursts, 2s windows work); per burst: Host Recoveries > 30 detect 69% (6.6% false), Host disparity > 150 55% (4.4%), Device disparity high on clean bursts too. A/B: **1498/1500 enabled, 1496/1497 off** (no failure in a re-init burst); noisy bursts per load 0.35 vs 0.64 (p 0.008), last 10 bursts 0.21 vs 0.61 (p 0.001), pooled 105/300 vs 191/300 (p 3e-12); resets per run median 1.89 vs 3.69 (p 0.12), Host Recoveries per run 5.3 vs 10.2 (p 0.20), pending_hp n.s.; re-inits 0 on the 5 clean loads, 2-10 on the others (budget never reached); a single re-init does not quiet a load (3 bursts before/after 0.69 to 0.66): re-drawn until a clean draw holds (6/10 re-initialized loads end with 8-12 clean bursts in a row, no off load). **Host-only vs Device-only**: noisy bursts 43/200 vs 99/200 (p 6.5e-9), re-inits 0-2 vs 0-6 per load, after a Host re-init 0.81 to 0.29 (p 0.042), after a Device re-init 0.71 to 0.68: only the Host transceivers start-up matters (as t12). |
| Monitor disparity per training (t15: Host + Device built at `b61d37c`; Host design WNS +0.190ns, Device +0.088ns), crossed cables. Calibration: 8 loads, measuring only, 20 dense (~1.8 runs/s) + 20 sparse (~0.3 runs/s) bursts of 5 runs. A/B: 30 interleaved loads x 20 bursts (dense/sparse alternating), Host ratio monitor (> 3 per training, min 2, Hot Resets counted, 1 window) vs measuring only; 10 + 10 loads Host ratio vs Host absolute (t14) at the sparse density | Calibration: 1516/1600 (84 failures on one looping load), 84/320 bursts noisy; clean run = 2 Recovery + 2 Hot Reset entries per board; worst lane disparity per training noisy/clean: Host 2.2/0.8, Device 8.1/1.1, the same at both densities (traffic independent); with Recovery entries only the Host ratio loses it (the Host noise is mostly extra Recoveries); Host ratio > 3: detection 0.41-0.43, false 6-7%; Device ratio > 8: 0.49-0.50, 6%; t14 data re-analysed: absolute thresholds 28%/46% false (Host/Device) at 2.5 runs/s. A/B: **3000/3000** runs, quiet bench (off loads 0.13 noisy vs 0.64 in t14): 37/300 vs 38/300 noisy bursts (p 1), 6 re-inits; the Host ratio misses the Device RX noise (load 19: Device RX SerDes 1 1264 disparity per reset, no trigger). Ratio vs absolute: 38/200 vs 44/200 (n.s.); the absolute N=2 almost never fires at the sparse density. Best detector on the Device, the cure on the Host. |

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
differences, +/-300ppm, crossed lanes. Hardware (t4 row of the results table): odd SKP runs in U0
are rare (Device `skp_odd_u0` 0 on 19/20 loads, Host 0-2) and the A/B shows no `pending_hp`
reduction: the check stays (a real slip is otherwise silent) but the `pending_hp` during the runs
have another cause, found with the Device Link trace below.

### Device `pending_hp`: the scripted host after a Recovery (Link trace, 2026-11-14)

Device Link trace stopped on the Recovery requests (t4 bitstreams, `usb3_trace.py link-clear
--circular --filter [--skip N]`, the trace stopped before its dump; files on the PC in
`build/hw_runs/crossed_t4/trace/`): 204 Device Recovery requests captured (idle: load 2, in-run:
load 5), all `pending_hp`, 12.18us after the last Device Header Packet or the U0 entry (the
SuperSpeedPlus PENDING_HP_TIMER: 10us + 1088 bytes/4/125MHz). None with an acknowledge lost on the
Device RX side (later Host Link Commands received but not the LGOOD_n: 0), Device `lc_bad` 0 during
the in-run captures. Two classes, both in the scripted host (bench gateware, a reaction to the
Recoveries of the noisy loads):

- B (58, 49 of them in-run): right after a link initialization (Hot Reset), the Device Port
  Capability LMP is sent 0.22us after its U0 entry, while the Host Advertisement is still arriving;
  the Host LMP is received, then nothing from the Host (no LGOOD_0, no LCRD). `HostScript.link_init`
  sends the Advertisement and its LMP before its `OP_WAIT` for the Device HPSTART, and
  `USB3HostModel` only matches the words received during an `OP_WAIT` step (RX always ready): a
  Device LMP received before it is missed, the run waits in `link_init` (the `link_init` timeouts of
  the bad loads).
- C (146, 138 of them idle): no Host Advertisement after the U0 entry, only LUP keep-alives. Out of a
  test run, `USB3HostScript` leaves its idle run on a U0 exit (model disabled, no Advertisement on the
  next U0 entry) and starts the next idle link initialization 10ms later: meanwhile the Device
  requests a Recovery every 12.18us (~800 per 10ms, the Recovery storms of the noisy loads).

The U0 exits not requested by the Device are 0.1-0.5us U0 periods (the lanes events: Host
`deskew_lost_u0`, comma realignments). The Device "before the runs" `pending_hp` counts of the t3/t4
reports are mostly the load order (the Device loaded while the Host still runs its previous
bitstream: ~1800, then ~360 during the Host load), not idle U0.

Scripted host fixed (both reproduced first):
- B: `USB3HostModel` counts the Device HPSTARTs from the U0 entry whatever the step (`OP_WAITHP`),
  `link_init` waits the Device LMPs on that count (`test_host_model.py`
  `test_link_init_device_lmp_early`: missed before, a `link_init` timeout).
- C: the idle run is kept through the Recoveries (LTSSM in Recovery.*; left on a Hot Reset or a
  training as before): Advertisement on each U0 re-entry (`TestPHYX2Core.
  test_core_x2_host_script_idle_recovery`: a Recovery while idle, 34 Device `pending_hp` requests
  until the next idle link initialization before, 0 now; `test_host_script.py`
  `test_idle_run_kept_through_recovery`: no new Hot Reset after a Recovery, a new one after a U0
  exit to another state). Hardware (t5 row): C confirmed (no Device Recovery storm, before the runs
  max 16), B fixed for the race but the looping loads (about 1 in 20) are another case: the Host
  receives nothing usable after the U0 entry (Host lane 0 comma realignments and `deskew_lost_u0`
  per run in the hundreds of thousands/hundreds), so the Device LMP is never acknowledged.

### Looping loads: Host Lane 1 loses 2 COM Symbols at the end of the TS2 burst (2026-11-14)

Host LiteScope capture (`--with-analyzer --analyzer-group realign`, built at `99ba623`, timing met:
design WNS +0.273ns, sys +0.333ns; Device t4), trigger `--state HotReset.Active:U0:Recovery.Active
--no-retrain` armed before `usb3_lanes.py script --runs 1` (files on the PC in
`build/hw_runs/crossed_t5/la/`): 2 captures on a normal load, 5 on a looping load (19/20, 1109
resets per 20 runs).

- On the looping load, in all 5 captures, the last TS2 of Host Lane 1 before the Logical Idle
  starts with 2 COM Symbols instead of 4 (`COM COM 01 38` at the deskew input: one 16-bit GTP
  word lost, the TS2 body intact); never on the normal load. No `rx_realign`/`rx_errors` on that
  word, not next to a SKP removal; the deskew sees one head mismatch, the single end of burst
  mismatch `LaneDeskew` tolerates: `aligned` stays 1, no Recovery.
- In U0, Lane 1 is then 2 Symbols off Lane 0 (every Device packet: Lane 0 `SLC SLC xx xx`, Lane 1
  `00 00 SLC EPF` then `yy yy 00 00`): every destriped word is garbage, the Device Advertisement and
  LMP are never decoded, the Device PENDING_HP_TIMER ends the U0 period (12.7-12.8us after the Host
  U0 entry in the two long captures); the Host lanes triggers fire only on the Device TS1.
- Not the deskew pairing (the COM words coincide during the burst), not a deskew loss, not after
  the deskew (the lane words are already 2 Symbols apart at its input). Open: where the 2 Symbols
  are lost (Host Lane 1 RX: GTP buffer/CDC/stride converter/word aligner, or the Device Lane 1
  transmitter at the TS2 -> Logical Idle switch); always on the last TS2 before the Logical Idle.

Reproduced in simulation (`sim.py --lanes 2 --lanes-core --host-script 900000 --lane-slip
900648,1`: 2 Symbols dropped by the Host Lane 1 receiver at the start of its last TS2 before the
run's U0; `--lane-rx-log` displays the lanes decoded words): the Host in U0 with Lane 1 2 Symbols
off, a Device `pending_hp` Recovery, the run restarted. Fixes (t6):
- Partial COM word (COM Symbols with other Symbols, not substituted decode errors) at the deskew
  input with the lanes deskewed: deskew cleared (Recovery in U0 once the search is armed),
  `com_slip`/`lane*_rx_com_partial` counters, control bit 5 (`usb3_lanes.py com-recovery-*`).
- In U0 with the deskew lost, a COM word at a lane head (the partner sending Training Sequences)
  is a Recovery at once (no gap to arm the search while the partner sends TS1).
- Found on the way, two Gen 1x2 issues behind Device `pending_hp` Recoveries after a Recovery or a
  Hot Reset: the TX words held out of U0 (packer held word, packets buffer) were sent at the next U0
  entry before the Link Layer Advertisement (an Advertisement LCSTART cut by a U0 exit sent with the
  next Advertisement: its LGOOD_n lost), now dropped out of U0 as the Gen 1x1 TX packets; the RX
  words received in HotReset.Exit/Polling.Idle (the partner in U0 first: its Advertisement) were
  dropped by the PHY, now kept for the Link Layer until U0 from the partner's first Logical Idle word
  (`rx_keep`, as Recovery.Idle). `TestPHYX2Core.test_core_x2_lane_slip` (no Device Link Layer
  Recovery request), `test_core_x2_skp_error_d2h` (no lost Advertisement).
- Not covered: 2 Symbols lost in a TS2 body (not the COM Symbols: `--lane-slip 900649,1`): the lane
  descrambler is then out of step (only COM resets it), the Host stays in HotReset.Exit until its
  timeout.
- Capture probes (t6, `realign` group): the physical lanes words before the word aligner (after the
  SKP removal/CDC), `rx_buferror`, the partial COM signals, to find where the 2 Symbols are lost.

t6 captures (2026-11-14, `30aab10`, Host `realign` group, Device `lanes` group; files on the PC in
`build/hw_runs/crossed_t6/la/`, 7 captures on a looping load):
- Host: 21 `com_slip` events, one signature. Before the word aligner (physical lanes words after
  the CDC, raw TS1 at COM offset 1: `4a COM COM COM | COM 00 00 4a`), the first 1-2 COM Symbols of
  an Ordered Set are K28.4 (substituted decode errors: ex `4a K28.4 K28.4 COM`), usually on both
  lanes in the same Ordered Set at the same Symbol positions, sometimes on one lane. After the
  aligner: `COM COM ff 17`, `COM COM COM xx`: `RXWordAligner` took the first intact COM as the start
  of a new marker run and moved 1-2 Symbols later (back on the next full COM run in a burst, never
  after the last TS2: the t5 looping loads). `rx_buferror` 0, `rx_realign` 0. All in TS bursts
  (Recovery.Active/Configuration/Idle, HotReset.Active).
- Device: every TS1/TS2 COM word sent is a full `COM COM COM COM` on both lanes, the last TS2 of
  the Hot Reset complete on both lanes, the TS2 -> Logical Idle switch on the same word: the COM
  errors happen after the Device lane words (Device SKP insertion/8b/10b/GTP TX, the channel, or
  the Host GTP/decode). A single decode error on the first COM gives 2 substitutions (the running
  disparity checker keeps its disparity on a decode error: the second COM is then a disparity
  error), a disparity error alone 1. Open.
- `com_slip` cleared the deskew on these (both lanes shifted the same way, still paired): a
  Recovery, a new TS burst, a new event: the t6 storm (A/B in the t6 row).

Fixes (t7):
- `RXWordAligner` (COM markers): substituted decode errors just before a COM run are part of the
  run (the alignment is kept on `K28.4 K28.4 COM COM`), also at the end of the previous word.
  `test_datapath.py` `test_rx_word_aligner_keeps_alignment_on_com_errors`.
- `com_slip` only when the deskewed lanes words disagree (COM/K28.4 Symbols positions): computed
  on the deskew outputs.
- Simulation: the `sim.py` SerDes model word aligner is always enabled, as on the hardware (it was
  gated by `rx_align`, off in HotReset.Active/Recovery.Idle: the t6 events could not happen there);
  `--lane-com-error CYCLE,LANE` (the first 2 COM Symbols of the next Host lane word with COM
  Symbols as K28.4): on the last TS2 of the run's Hot Reset (`900649,1`), `30aab10` shows the
  partial COM word and the Recoveries, now nothing (`TestPHYX2Core.test_core_x2_lane_com_error`).

t7 (2026-11-14, `ec85995`, row above): the storm is about 3 times smaller than t6 but still there
(screen load: 258 resets). Two findings:
- With `com-recovery-disable`, the Host counted 343000 `com_slip` in 20 runs: the TSEQ words (COM
  then 3 data Symbols, 65536 TSEQ per Polling.RxEQ) are partial COM words, counted with a deskew
  left aligned from before the Polling (about 5 RxEQ x 65536).
- The corrupted first COM Symbols are mostly not decoder `invalid` codes (25/38 events: `rx_errors`
  stays 0), so most likely running disparity errors: a single bit error on the first COM after the
  TS body (D10.2/D5.2, alternating bits, then the 5 identical bits of the comma) giving a valid code
  in the other running disparity column. Such an error can also give a valid data Symbol in the
  right column (no substitution at all): the K28.4 rule of `ec85995` does not cover it. Not
  proven (no separate decode/disparity probe); the rate is a receive quality figure (equalization,
  pre-emphasis) of these boards.

Fixes (t8):
- `RXWordAligner` (COM markers): a marker run of 2 or more starting later than the current
  alignment (or earlier, in the next word) only moves the alignment when it covers the Symbol where
  a 4 COM run on the current alignment ends; a run starting late and ending there is an Ordered Set
  whose first COM Symbols were received with errors, whatever they decode to (K28.4 or another
  Symbol). Single marker runs (TSEQ) move the alignment as before. A real shift (full 4 COM runs)
  always covers that Symbol (`test_rx_word_aligner_follows_shift`,
  `test_rx_word_aligner_keeps_alignment_on_com_errors` with K28.4 and data Symbols).
- `com_slip`/`rx_com_partial`: only words starting with 2-3 COM Symbols then other Symbols (a lane
  that lost Symbols; not the TSEQ, not a TS1/TS2 whose first COM Symbols were corrupted).
- `sim.py --lane-com-error CYCLE,LANE,data` (the COM Symbols received as D10.2):
  `TestPHYX2Core.test_core_x2_lane_com_error_data`.

t8 (2026-11-14, `2601dc1`, row above): the storm is gone (397/400, no looping load, `com_slip`
neutral in the A/B). The link is still noisier than t4/t5 on about half of the loads (resets,
Recoveries, `deskew_lost_u0`, Device `pending_hp`), with high comma realignments and decode error
cycles on those loads: the receive quality of the loads (the COM corruption is one of its effects),
or the t6 TX flush/RX keep changes (not separated: a t5 vs t8 A/B on the same loads would tell).
The t5 vs t8 A/B (row above, 20 rounds alternating the two builds) shows no difference: the noise
baseline is the loads (about half noisy, Host Lane 0 receive path fed by the Device SFP-1), not
the gateware changes since t5; t8 has no looping load and failed no run in it.

Receive errors by type (2026-11-14, for the next hardware run): per lane counters of the received
Symbols with a decode error (`lane*_rx_decode_errors`) or a running disparity error only
(`lane*_rx_disparity_errors`), and of the same errors on the Symbol just before a COM
(`lane*_rx_com_decode_errors`/`lane*_rx_com_disparity_errors`: the first COM of an Ordered Set
received with an error; with 2 corrupted COM Symbols, the second one is the Symbol counted), in
each SerDes RX clock domain (`RXErrorTypesCount`, `USB3LanesDebug`, `usb3_lanes.py status`,
`acorn_x2_loads.py --summary`). The t7 capture analysis suggested disparity errors (no decoder
`invalid` on 25/38 corrupted COM words): these counters measure it on every load. t9 (row above):
unusable, the RX clock domain counters were reset with each transceiver RX reset. Fixed: reset-less
8-bit Gray counters per Symbol in the RX clock domain, accumulated in sys (32-bit, kept through the
RX resets; `test_rx_error_types_count` resets the RX domain between the counts), and counted only
with the LTSSM in a state receiving symbols (Polling.RxEQ to U0, Recovery, Hot Reset) and the lane RX
not idle (not the LFPS: no symbols, decode errors by construction); no 32-bit adder left in the RX
clock domains (t9 Host Lane 0 RX WNS +0.095ns). t10 (row above): the counters hold; disparity errors per reset per lane
are the line quality figure (decode errors are mostly training/Recovery symbols, counted from
Polling.RxEQ); the weak receivers are the Device RX Lane 1 (most disparity errors) and the Host RX
Lane 0, on different loads: the TX post-cursor sweep should watch both. The Acorn Gen 1x2 builds now have the
GTP TX post-cursor pre-emphasis as a runtime register per SerDes (SerDes n on SFP-n, reset to the
`--tx-postcursor` value: `usb3_lanes_debug_lane{n}_tx_postcursor`, `usb3_lanes.py tx-postcursor
--value 6,10`), so a sweep needs one build per board. t11 (row above): no pre-emphasis value helps; the noise of a load is fixed at
the bitstream load and survives PHY retrains (t11, 14 per load), SerDes RX resets (t10) and TX
pre-emphasis changes: not the TX equalization nor the RX adaptation. Suspects set only at
configuration: the transceiver PLL lock (fabric reference clock on GTGREFCLK0), the TX phase
alignment/TX buffer, the Lane 1 TX on the Lane 0 TX clock (lanes in lockstep). Next: on a noisy
load, a full transceiver channel + PLL re-initialization at runtime (does the load turn clean?).
The Acorn Gen 1x2 builds now have it (`usb3_lanes_debug_xcvr_reinit`, `usb3_lanes.py xcvr-reinit`:
both SerDes held in reset 10us, the Lane 0 GTP resetting the shared Quad PLL; `sim.py --lanes-reinit`,
`test_core_x2_lanes_reinit`). t12 (row above): the re-init re-draws the noise without a bitstream
reload (the load explains none of the variance after re-inits vs 95% after retrains): it is drawn at
the transceivers start-up (PLL lock, TX initialization, clock phases), not by the FPGA configuration;
the Device RX SerDes 1 errors follow the Host SerDes 0 transmitter start-up. Next: compare a clean and
a noisy draw (PLL lock, TX buffer/phase status, user clock phases over DRP/status), and a gateware
mitigation (re-initialize until a short check burst is clean, keep the clean draw).
The Acorn Gen 1x2 builds now read the transceivers status (`usb3_lanes.py status` "xcvr", Quad PLL lock
lost/TX buffer error counters) and the GTP DRP (`usb3_lanes.py drp-dump`), and `acorn_x2_loads.py
--reinit-until-clean N` re-initializes both boards until a check burst is clean. t13 (row above): the
draws have two levels but nothing in the status or the DRP 0x000-0x0ff distinguishes them (whatever is
drawn is outside the readable configuration: TX buffer/clock phase, CDR/LPM state); a draw sets the rate
of short noise episodes rather than a steady state, so a 5-run check only catches the draws noisy all the
time: re-init until clean removes the reset-heavy draws (7/20 to 1/20 loads) but not the disparity
episodes, Host Recoveries or Device `pending_hp`. The check counts the scripted host resets
(`usb3_script_resets`, the port reset policy Warm Resets stay at ~0). Next: a monitor during operation
(re-init when the disparity rate stays high) and the TX buffer bypass/phase alignment, CDR/LPM state.
The Acorn Gen 1x2 builds now have that monitor (`LanesNoiseMonitor`, `usb3_lanes.py monitor`,
`acorn_x2_loads.py --monitor host|device|both [--monitor-ab]`): per window (1s by default) the RX
disparity errors of each lane and the Recovery entries, a re-initialization of the board's
transceivers after consecutive noisy windows (2), the next windows skipped (2), a budget per clear
(8), never in U3; disabled at reset (measuring only). t14 (row above): the monitor halves the noisy
bursts without failing runs, through the Host re-initializations only (a Device re-init re-draws
nothing that matters: the noise follows the Host SerDes 0 transmitter start-up, t12); the errors of a
run burst arrive within ~0.5s, so the windows are 2s (reset values now 2s, disparity 200 per lane, 30
Recovery entries; `acorn_x2_loads.py --monitor host`). The thresholds are absolute counts per window
(traffic dependent): a per Recovery entry normalization would make them independent of the traffic.
The monitor now has it (`ratio`: a window is noisy when its worst lane has more than
`disparity_per_training` disparity errors per training, trainings = Recovery entries + Hot Reset
entries (`with_hot_reset`, the Hot Reset entries per window read back), at least `min_trainings`;
disabled at reset; `usb3_lanes.py monitor --disparity-per-training N`, `acorn_x2_loads.py
--monitor-per-training N`).
t15 (row above): the ratio is traffic independent when the Hot Resets are counted, but on the Host it
is coarse (noisy ~2.2 vs clean 0.8 per training, integer threshold) and blind to the Device receive noise
(seen on the Host only as extra Recoveries); the Device ratio detects best but only a Host re-init cures
(t14): to use, a Device detection carried to the Host. Quiet bench: no A/B effect measurable.
Mixed pair (t16, planned): the Acorn Host SerDes 0 (SFP-0) to a Tang Mega 138K Pro Device (GTR12, Gen 1x1
Device Core, `--with-rx-errors`: the same RX error type counters, `usb3_rx_errors_*`) over one DAC cable,
Gen 1x1 (SuperSpeed fallback of the scripted host): does the Tang receiver see the draws of the Acorn
Host transmitter start-up (Host re-inits), and does the noise follow the Acorn draws or the Tang loads?
t16 (2026-11-15, blocked): the Tang never trains (Polling.LFPS: its LFPS bursts 3.9us every 39us, the Host
bursts seen as Ping). The user's dock MS5351 reference clocks were not programmed (25MHz crystal passed
through; set to 100/125MHz from the debugger console, not saved), and then the GTR12 TX fabric clock still
measures 32.0MHz instead of 125MHz (`--with-clk-meters`) on both lanes and with either reference clock,
QPLL1 locked, while 264 of the 268 `.csr` registers read back as configured (UPAR, the 4 others on unused
lanes): the fabric clock is not divided from the configured PLL path (GTR12_QUAD fabric clock parameters
in LiteICLink `gtr12_gw5.py` suspected). t16c: upstream master (8ece28c) fails the same way on this dock
(Tang LFPS 3.97us every 39.2us), and FABRIC_CLK_LIFE_DIV_I does not move the ~32MHz: not our code. The
builds target the engineering sample part (GW5AST-LV138FPG676AES, version B, the LiteX-Boards platform);
the user's dock (debugger serial 2025-03) likely carries the production version C: `--device C` to try.
t16d: `--device C` (GW5AST-LV138FPG676AC1/I0) the same (TX fabric clock 32.015MHz, CDR locked, no
Polling LFPS received); the revision cannot be read over JTAG (idcode 0x1081b for both). Left: the Gowin
IDE (V1.9.12.02 SP2 on the NUC) or this dock. t16e/f: not the TX idle UPAR writes, the GTR12 rate pins/clock tie-offs (identical to Sipeed's demos) or the
fabric clock root register; the clock follows the PLL: QPLL1 ~32MHz, the lane CPLL (our CPLL `.csr`)
~61MHz, both for 125MHz. Sipeed's 1.25G demo (CPLL) runs at its nominal TX clock on this dock and IDE
(LED2/3 ~2 toggles/s). t16g: dock MS5351 #0 100MHz, #1 125MHz (as Sipeed's SET_5351.md; the
switch-to-REFCLK pad mapping vs the schematic uncertain); the standalone `serdes_toml_to_csr_138k` of
this IDE fails on every TOML (Gowin's own examples too), `csr_task_gen` gives a 5G QPLL task differing from
the committed `.csr` in 8 TX (`cfg_txlane_clktree` 0x3310 vs 0x3350, MCU/start-up sequencing) and 4 RX
(CDR) registers: 0x3310 in our design changes nothing (TX 32.008MHz). Sipeed's 10.3125G QPLL demo
(unmodified design, rebuilt for the ES part without bitstream compression: the shipped bitstream does
not load, openFPGALoader "checksum data is truncated"): LED2/3 7 times on in 20s, a TX clock ~40-55MHz
instead of 128.9MHz: the QPLL path is slow with Sipeed's own design too, not our `.csr`/LiteICLink (the
dock/silicon revision or this IDE). t16h (`csr_task_gen` 5G tasks on q1.ln1 over the committed `.csr`,
`--pcs_tx_clk_src` 0 CPLL/1 QPLL0, 100 and 125MHz refmux0): neither the CPLL nor QPLL0 locks (only QPLL1),
all writes read back; the TX fabric clock stays 31.85-32.01MHz in every variant (QPLL1 locked or not
selected, either reference, lane clock tree 0x3550/0x3150/0x3310), the RX clock follows the reference
(48.9MHz at 100, 60.9MHz at 125): the TX fabric clock does not come from the selected PLL at all. Sipeed's
working 1.25G CPLL demo writes CPLL registers the task does not (0x90a20c 0x10280108, 0x90a220 0x14,
0x90a22c 0xB40DC, clock tree 0x7530). No lock/calibration register is named on the NUC (the names exist
only in the compiled Gowin SDK of `csr_task_gen`: `LCPLL.get_lock_status`, `Quad.check_all_pll_ok`,
`Quad.config_clk_mon`). Gowin V1.9.12.04 release notes: a new (encrypted) USB 3.2 PHY IP at 5/10/20Gbps,
USB3.1 PHY descrambling fix between two consecutive SKPs, new `csr_task_gen`/`serdes_toml_to_csr_138k`
binaries (not run). Likely cause (2026-11-15, found on the same dock by the litex_wr_nic bench session,
enjoy-digital/litex_wr_nic draft PR #109): Sipeed's debugger `pll` command programs the MS5351 PLL A but
routes MS0 (the SerDes reference) from the unprogrammed PLL B (CLK0 control register 16): the GW5 SerDes
ran at ~49MHz instead of 125MHz with PLL/CDR lock reported (our RX 48.9MHz at "100MHz"), fixed by programming
PLL B (`tools/tang_ms5351.py --restore --pll B` in litex_wr_nic: LiteEth 1000BASE-X link up, TX/RX ~125MHz).
The t16g register reading did not check the multisynth PLL source. Next on this dock: program the PLL B
routing, then t16 again (TX/RX clock meters first).
t16i (2026-11-15, reactive-turtle NUC session; Acorn Host 1-3 SFP-0 <-> Tang SFP0): confirmed. Before: MS5351 #0
outputs from PLL B (99.992MHz, left by the WR tuner), #1 outputs from an unprogrammed PLL B; after PLL A = PLL B
(#0 x36/9 = 100.000MHz, #1 x30/6 = 125.000MHz, not saved): Tang (`tang_device_t16b_sfp0_100M`, committed `.csr`,
QPLL1) TX fabric clock 125.0065MHz, RX 125.0151MHz. Host t15 build in Gen 1x1 (`x2-disable`): U0 on both sides,
20/20 scripted runs (0 errors/timeouts), Host Recoveries 1 -> 671, Tang RX errors decode +63674, disparity +924,
COM-preceding disparity +331; after the script a Recovery burst (Host 671 -> 5366, Tang 847 -> 6071 within ~1 min),
then quiet (0 Recoveries/errors over 10.7s). Open: that burst; then the nested Acorn Host re-inits x Tang reloads.
t16j (2026-11-15, nested, Gen 1x1, 10 Tang loads x 5 draws (load, then 4 acorn1 xcvr re-inits) x 10 runs):
426/500 runs (74 failed, no timeout, not following the draw noise); the line noise follows the Acorn
re-inits in both directions, not the Tang loads (Tang load share of log(1 + disparity errors per run):
Acorn TX -> Tang RX 23%, ANOVA p 0.24; Tang TX -> Acorn RX 20%, p 0.38; Acorn RX class kept across Tang
reloads 9/9 vs across Acorn re-inits 23/40, Fisher p 0.014), both directions noisy together (24/25 draws,
p 3e-6: the Acorn re-init restarts its TX, RX and Quad PLL together); Tang RX: clean draws (17-92 errors
per run) or whole numbers of ~153550-error episodes (fixed-length bursts); Acorn RX three groups (~1e2,
3e3-9e3, 3e4-1e5). After every Tang reload the Acorn Host stayed in U0 (no partner loss detected) and
the Tang went to Compliance: a Host link reset needed (draw 0 = load + Host reset). Post-script Recovery
bursts (3/50 draws, ~3s, ~400 Recovery cycles/s): reported as the Tang going WarmReset then Loopback,
but decoded with the U1/U2 LTSSM state table (the Tang Gen 1x1 PHY has no U1/U2 states: every state
from 7 up 2 lower): a normal Hot Reset, no WarmReset/Loopback (t16m correction). Reviewing it found
a real weakness, fixed anyway: the TS2 Link Functionality Symbol (Reset/Loopback bits) excluded from
the Ordered Set compare and reported from any single TS2 received without 8b/10b error (a bit error
there can decode as a valid Symbol); now reported when two consecutive TS2s carry it, a detection on
8 identical TS2s (7.5.4.9.2, `test_ts2_checker_link_config_corrupted`).
t16k (Gen 1x1 over the SFP-1 cable, `bench/acorn.py --sfp 1`, 5 Device loads x 20 runs): acorn1 Host <->
acorn2 Device 100/100, acorn2 Host <-> acorn1 Device 100/100, 2 Recoveries per run (the script's resets),
idle U0 silent; Acorn WNS +0.165/+0.118/+0.086ns. The Acorn Host does not leave U0 when the Device is
reloaded (the new Device then in Compliance, a Host link reset needed), as with the Tang. Three boards
wired, a Device can train with the other board on its other cage (two Devices): the unused board held in
reset. The 1.9.12.04 `serdes_toml_to_csr` rejects the 1.9.10 TOMLs (and Gowin's own examples): no generated
two lanes `.csr`; the lane 0/1 configurations merged instead (`gw5_csr_merge_lanes`).
t16l (Tang `--lanes 2 --role host --lanes-core --no-x2`, Gen 1x1 on SFP0, lane 0 `.csr`; acorn1 Device):
two build fixes (lane CPLL lock single driver, lane 1 TX clock alias not kept); sys timing fails (82.6MHz
for 125MHz, WNS -4.11ns) but 5/5 loads to U0 and 100/100 runs, idle U0 silent; one load noisy in the Tang
TX -> Acorn RX direction (~234k disparity errors, 20/20); after some loads 2-14s of training cycles before
U0.
t16m phase A (d800b7b): Acorn builds WNS +0.199..+0.313ns, Tang Gen 1x1 Device -0.045ns (one RX error
counter carry), Tang `--lanes 2` builds fail 125MHz (Device PRBS 71.6MHz/-5.96ns, Host 79.9MHz/-4.52ns,
Device Core 73.1MHz/-5.67ns: LanesNoiseMonitor 32-bit subtraction, Link RX aligner, CSR read mux; mostly
routing, the sys clock straight from the GTR12 TX clock ~3.3ns late with a 9493 fanout). A2 (acorn1 Host <->
Tang Gen 1x1 Device, 5 loads x 3 draws x 10 runs): 146/150, the 4 failures 2s timeouts on one very noisy
draw (~80 U0 exits per run, ~2e7 decode errors per run); the t16j failures all showed step 826 (the script
step counter is reset on an error: the failing step is lost); after the script a failed Recovery back to
Polling and U0 within ~100ms on 11/15 draws; noise unchanged by the TS2 fix (recurring ~247.9k disparity
error bursts at the Tang). A3: merged lanes configuration, Tang Host x2 build at Gen 1x1 <-> acorn1 Device
20/20, Lane 1 RX clock 124.64MHz (32.15MHz with the lane 0 `.csr`), Lane 1 PLL locked (no cable).
t16m phase B (Gen 1x2 Acorn <-> Tang, acorn1 SFP-0/SFP-1 <-> Tang SFP0/SFP1): B1 PRBS: U0 at Gen 1x2 at the
first try, the Acorn receives 37GB from the Tang with 0 errors, the Tang PRBS checker ~535M errors per 5s
(constant to 0.01%, per lane 8b/10b counters unchanged: after the decode, in the deskew/lanes merge/64-bit
words, the builds failing timing); Gen 1x1 0 errors both ways. B2 (acorn1 Host <-> Tang Device Core) and B3
(Tang Host <-> acorn1 Device): no lasting U0 (U0 at Gen 1x2 ~70 times in 15s, each lost through Recovery);
B4 Gen 1x1 cross-check 20/20. After B2 a deadlock: Tang in WarmReset, Acorn Host cycling Polling/WarmReset.
Gen 1x2 on the Tang needs the lanes PHY off the 125MHz sys (Gen 1x1 runs the PIPE at 125MHz and the rest at
62.5MHz).
t16n (86f960e, Tang `--lanes 2 --lean`): sys Fmax 83.4MHz (JTAGBone instead of UARTBone 94.8MHz, Gowin
place/route options +1.4MHz at most), the worst PHY-internal path (LTSSM state register -> next state, 12
levels) within 0.1ns of the worst; 85-90% of the ~14300 failing paths on the SoC side (LTSSM state history
built from registers, PRBS checker, counters, CSR bus); the sys clock already on the global network (3.3ns
insertion, 0.03ns skew). Lean build at Gen 1x2: Tang -> Acorn 0 errors, Acorn -> Tang the same ~535M errors
per 5s as the t16m build (different timing/placement: a logic fault). Gen 1x1 with the new debug features:
Tang states decoded with its own table, 120/120 runs. Candidate cause: the GTR12 RX words decoded every rx
cycle (RX_VLD_OUT ignored): a cycle without a word decodes a repeated word without 8b/10b error, a lane one
word off after the deskew; RX words now gated by RX_VLD_OUT on the Tang `--lanes 2` builds (18bf9b4, A/B
with `--no-rx-valid-gate`, `usb3_gtr12_lane{n}_rx_invalid` counters).
t16o (LiteScope on the Tang `--lanes 2 --lean` JTAGBone build, 128-deep analyzer: the default depth missed
timing at 50.5MHz): RX_VLD_OUT not the cause (rx_invalid +0 in U0 on both lanes, gated and ungated builds the
same 6.75G errors per 60s); every Tang lane counter 0 over 30s at Gen 1x2. Cause: `LaneDeskew` paired the lanes
one TS Ordered Set (4 words) apart: in U0 each destriped word joined Lane 0 word n with Lane 1 word n+4. In
the training, the Tang Lane 1 was not word aligned yet (garbage, no marker: counted as a gap) while Lane 0
already received TS Ordered Sets for 90+ words; the armed deskew held Lane 0's first marker, its FIFO filled
(words dropped), and Lane 1's first marker was paired with that stale one; markers every 4 words, so never
seen as a mismatch, and none in U0. Deterministic (12 retrains, same error rate). Fixed in `LaneDeskew`: a word
dropped on a full FIFO while armed or aligned clears the pairing and flushes the FIFOs, the search re-armed on
the next gap (the deskew-lost Recovery in U0 then pairs the lanes on its TS1); `test_deskew_late_lane_overflow`.
t16p (0ba2a12, Tang PRBS x2 <-> acorn1 PRBS Host): no stable U0 any more (~64 Host and ~32 Tang Recoveries per
second, deskew not aligned, no PRBS data), the ungated RX_VLD_OUT build the same; a 64-word deskew FIFO worse.
Capture: in Recovery the lanes now paired right on the TS1s (Lane 1 one word ahead), then Lane 1's deskew input
stalls for 20+ words while Lane 0 flows: Lane 0's FIFO overflows, the pairing cleared, no gap in the TS stream to
re-pair, U0 entered unpaired and left after 9 words (deskew lost). The Lane 1 stall also caused the t16o
mis-pairing. Suspect: the Lane 1 RX re-initialization on continuous decode errors (t16q).
t16q: not the RX re-initialization (all Recovery/re-init controls off: the same loop, ~63 Host and ~32 Tang
Recoveries/s). In the loop the Tang Lane 1 decodes errors on more than half of its cycles (~70M/s, 0.2 TS1/s)
while Lane 0 receives 1.47M TS1/s; Lane 1's datapath stops delivering words (no electrical idle). By Tang
build: d800b7b and 86f960e stable in U0 (with the t16o mis-pairing), 18bf9b4 (RX_VLD_OUT gate) loops (held U0
in t16o after ~1000 Recoveries), 0ba2a12 loops always; same GTR12 configuration in all. The RX_VLD_OUT gate is
off by default again (`--rx-valid-gate`); next: Lane 1 alone at Gen 1x1 (single lane and merged configurations).
t16r (00f218f): E1 Lane 1 path with its single lane configuration (Tang `--sfp 1` <-> acorn1 `--sfp 1`, Gen 1x1):
20/20 (the SFP-1 <-> SFP1 path noisy on 2 of 3 trainings); E2 Lane 1 alone with the merged configuration on the
two lanes build (Gen 1x1, Tang lane swap): clean (U0 in 0.09s, 0 PRBS errors both ways, 0 Recoveries); E3 both
lanes at Gen 1x2: 4/4 fail, the Tang Lane 1 CDR locked in 2 of 40 samples (~75M decode errors/s, no TS1),
Lane 0 clean. Lane 1 is silent until the Gen 1x2 negotiation and a GTR12 lane RX reset only resets its PCS: a
CDR that did not lock is never restarted (the RX re-initializations on continuous errors useless). Tang
`--lanes 2` builds now toggle the lane CDR signal detect through UPAR on each lane RX reset (`GW5CDRToggle`,
`usb3_gtr12_lane{n}_cdr_toggles`, `--no-cdr-toggle`). Side finding: a Tang Gen 1x1 Device on lane swap stays in
U0 when only the Host retrains (5/5).
Not reproduced in simulation (`sim.py --lanes 2 --lanes-crossed --dev-x2-disable --host-phy-reset 620000,12500
--host-port-reset --host-port-reset-timeout 6e-3`, `test_phy_x2_host_retrain_warm_reset`, slow): the Device stays
in U0 while the Host retrains (no Link Layer timeout with the PRBS stand-ins), then detects the Host port reset
Warm Reset on its swapped Lane 0 after ~25ms (tResetDelay) and both train again: on the Tang, the Warm Reset
LFPS detection on the GTR12 lane 1 in U0 is the suspect (to check with t16s).
t16s (387554e, split clocking: Tang lanes logic at 125MHz on the Lane 0 TX clock, LTSSM/SoC at 62.5MHz;
report `build/hw_runs/mixed_t16/t16s/report_t16s.md` on the NUC): sys 74.7MHz for 62.5MHz and RX clocks met, the
lanes clock 99.9MHz for 125MHz (-343ns TNS over 443 endpoints, was -2897ns over 2094: PRBS checker 64-bit compare,
deskew). Gen 1x2 PRBS Acorn Host <-> Tang Device with the CDR toggle: 9/9 fail (no U0, the Tang Lane 1 CDR never
locks, ~400 toggles/s: the toggle keeps it from locking); without it (`--no-cdr-toggle`), 11 trainings: U0 at Gen
1x2 every time, both lanes locked, deskew aligned, no Recovery; Tang -> Acorn clean 10/11, Acorn -> Tang clean 3/11
(the other 8 mis-paired, ~3.16G errors/30s, also once on the Acorn side), the clean ones 610MB/s each way with 0
errors. The mis-pairing forms without a FIFO overflow (0ba2a12 does not catch it). Warm Reset with lanes swapped:
the two lanes Tang build never detects the Acorn Host Warm Reset (its Lane 1 sees the bursts, stays in U0), the
single lane build on SFP1 does (+44). Fixes: the CDR toggle off by default (`--cdr-toggle`); `RXErrorMonitor` in a
reset-less RX clock domain (the lanes RX errors re-initializations of a lane receiving the Warm Reset LFPS in U0
cleared it every ~110us, never reaching tResetDelay); `LaneDeskew` `error_symbol`: a word with a decode error (K28.4)
breaks the gap and disarms the search (a not yet word aligned lane's garbage counted as a gap: its first COM paired
with a later TS of the other lane, the lanes an Ordered Set apart, `test_deskew_late_lane_errors_no_gap`).
t16t (ed8749f; report `build/hw_runs/mixed_t16/t16t/report_t16t.md` on the NUC): A, Gen 1x2 PRBS with the
new Acorn Host: 0/5, no U0 (the Acorn sees almost no TS1, decode errors on both lanes; the Tang Lane 1 never
locks); the t16s Tang build fails the same with it and locks again 20/20 with the t16s Acorn: the Acorn build.
The reset-less `RXErrorMonitor` is the suspect (the deskew only runs after the Gen 1x2 negotiation): through a
GTP RX reset (RX clock stopped) it kept its errors, the lanes RX errors re-initialization saw them after its
holdoff and re-initialized again, a loop. B, Warm Reset with the lanes swapped (new Tang, t16s Acorn): still
not detected (0/3). C: Tang lanes clock 95.4MHz (449 endpoints), sys 74.3MHz, RX met. Acorn -> Tang still
mis-paired with the t16s Acorn (its deskew fix only in the Tang build: the mis-pairing is the Tang's receive).
Fix: `RXErrorMonitor` back in the RX clock domain (reset with the RX), `rx_errors` held (`rx_errors_hold`)
during a lanes RX errors re-initialization and its holdoff instead.
t16u (66dce0f; report `build/hw_runs/mixed_t16/t16u/report_t16u.md` on the NUC): A 0/5 (new Acorn + new Tang: ~200
Recoveries/s per side, deskew never aligned); bisection: the new Acorn trains with the t16s Tang (7/8: the t16t
Acorn regression fixed), the failure follows the new Tang (same with the t16s Acorn). Cause: the deskew disarm on
an error word (ed8749f), the first COM Symbols of a TS after an idle period arriving as K28.4 (t6 captures): the
armed search dropped, never paired again. A2 (new Acorn + t16s Tang, 8 trainings): Acorn -> Tang clean 2/8, Tang
-> Acorn 6/8, a Recovery re-pairs (not permanent), a re-init cleared it 8/14. B: Warm Reset 0/8 (5 default, 3 with
the Tang RX re-init off: not the re-init). C: lanes clock 108.6MHz (180 failing endpoints). In simulation the two
lanes split Device detects the Host Warm Reset in U0 at Gen 1x2 with crossed lanes (`sim.py --lanes 2
--lanes-crossed --dev-pipe-cd --host-phy-reset 620000,12500 --host-port-reset --host-port-reset-timeout 6e-3`): the
hardware miss is the GTR12 receive (idle/decode errors during the LFPS): `warm` LiteScope group added. Fixes
(45d16b3): the deskew keeps an armed search on error words (gap only), marker flag stored in the deskew FIFOs, PRBS
checker compare pipelined (lanes clock).
t16v (65e470a; report `build/hw_runs/mixed_t16/t16v/report_t16v.md` on the NUC): B, `warm` captures (5, up to
268ms) on the two lanes Tang, lanes swapped: physical lane 1 `rx_idle` steady low for the 200ms Warm Reset LFPS but
`rx_errors` 0 throughout, no `rx_reset`, `lfps_rx_reset` never rises (the checker sees idle: `rx_idle | ~rx_errors`);
the single lane SFP1 Tang (`link` group) shows `rx_errors` steady high and detects it (+38, +39). Suspect: the GTR12
RX interface FIFO not delivering words (`RX_VLD_OUT` low) during the LFPS, the fabric decoding the last word again
without errors; fix: `RX_VLD_OUT` low for 64 consecutive rx cycles counted as RX errors (`rx_stall`), `rx_invalid`
and `rx_stall` added to the `warm` group. A: 65e470a Acorn 0/10 (Recovery loop), also 0/3 with the t16s Tang, the
66dce0f Acorn 3/3; 66dce0f Acorn + 65e470a Tang 4/10 stable U0, all 4 clean both ways at 610MB/s (no mis-pairing),
22-30s to U0. Cause of the 65e470a Acorn: without the disarm, a first marker word received with K28.4 Symbols on one
lane let the other lane's first marker pair with its next one, the lanes an Ordered Set apart. Fix: a marker word
with some Symbols as K28.4 (at least one COM) is a marker (`test_deskew_first_com_errors_one_lane`). C: Tang lanes
clock 109.3MHz (313 failing endpoints; worst: PRBS checker packet decode, deskew gap counter enable), 106.4MHz with
the analyzer, sys 69.4/72.2MHz; the single lane build meets all clocks.
t16w (f95b23c; report `build/hw_runs/mixed_t16/t16w/report_t16w.md` on the NUC): B, Warm Reset with the lanes
swapped on the two lanes Tang: detected 6/6 (Host-only retrains, both back in U0 within 0.64-0.73s); `rx_invalid`
(RX_VLD_OUT low) high on lane 1 for the whole capture (LFPS and the Host's Polling bursts; also on lane 0 without a far
end: no valid RX data), `rx_stall` then `rx_errors` steady high, `lfps_rx_reset` 25.0ms after `rx_idle` steady low. A:
66dce0f Acorn + f95b23c Tang 10/10 (U0 at Gen 1x2 in 0.08-2.1s, deskew aligned, 0 PRBS errors both ways at 610MB/s);
f95b23c Acorn + f95b23c Tang 0/10 (Recovery loop, as the 65e470a Acorn): the Acorn needs the disarm (a lane word
aligned after the arming), the Tang the corrupted marker words. Fix: error words that are not corrupted marker words
disarm again (both). C: Acorn Host WNS +0.071ns; Tang lanes clock 101.7MHz (worst: PRBS checker packet decode,
deskew gap counter ~-1.8ns), sys 75.7MHz; with the `warm` analyzer sys 60.5MHz (fails 62.5 by 2.45ns, captures fine).
t16x-t16z (6e30bcc, 2cae579, 1dbb0ef; reports `build/hw_runs/mixed_t16/t16{x,y,z}/report_t16*.md` on the NUC): the
Gen 1x2 Acorn Host <-> Tang Device result depends on the Acorn load (transceivers start-up draw): ~15% of the Acorn
loads good (t16x 2/17, C2 1/8; t16y 1/12 6e30bcc Tang, 2/12 2cae579 Tang, 0/4 1dbb0ef pair), whatever the Tang build or
reload (C1: 5 Tang reloads on a good Acorn load 5/5). The t16v/t16w "Acorn regression" verdicts rested on one Acorn load
each (confounded with the draw). Good loads: 17/20 trainings at x2 (1.8-30s to U0), every good load 0 PRBS errors both
ways at 610-613MB/s. Bad loads, at x2 only: both directions fail (Tang lane 1 CDR never locked, lane 0 locked about
half of the reads, Tang RX clocks 124.6-124.85MHz; Acorn 10-30M decode errors per 2s on both lanes) while the same load
trains at Gen 1x1 at once with 0 errors (4/4, t16x D 20/20, t16y 10/10, U0 in 0.07-0.09s). Not the Tang lanes RX errors
re-initializations (off: 0/2 recovered; 2cae579 A/B no difference). Runtime actions on bad loads (t16z): Acorn TX
post-cursor 0-14 0/20, Tang transceivers re-init 0/12, Acorn transceivers re-init (Quad PLL and both channels) + retrain
3/4 loads recovered after 1-3 re-inits, then clean. Fix: Host training watchdog (`LanesTrainingWatchdog`, 2s of
training without U0 -> transceivers re-init, `usb3_lanes.py watchdog`). Warm Reset at x2 not testable on the bad loads;
x2 off 5/5. Timing: Tang lanes clock 98.1MHz (6e30bcc), 97.2MHz (2cae579), 108.7MHz (1dbb0ef: PRBS checker/deskew input
stages; worst then deskew FIFO read -> pairing state and a lane TS1 checker -> idle handshake count, buffered/registered
in f9cdafa), sys met; Acorn WNS +0.248/+0.106ns.
t17 (0948c75/8173e58): the first watchdog never fired (the failing link passes through U0 ~65 times per
second: training time cleared), fixed (stable U0 = 100ms) and a Warm Reset 5ms after each re-init (8173e58): 7/20 Acorn
loads good within 60s (3 at once, 4 after 7-21 re-inits; 13 bad through 27 re-inits), every good load 612MB/s 0 errors
both ways. t18 (8173e58 Acorn, 6 bad loads x 15 tries): Tang PHY reset, Tang PHY reset held across an Acorn re-init,
Acorn re-init + Acorn retrain, Tang re-init + retrain, the t16z recipe: 0/90 recovered (Tang CDRs never both locked);
only an Acorn bitstream load changes a bad load, and the same load trains at Gen 1x1.
t19 (9700da1 Acorn, 8+3 bad and 2 good loads, watchdog off): the Acorn TX swing (`usb3_lanes.py tx-diffctrl`) at 15
trains every bad load at once (17/17 retrains: x2 U0 in 0.55-1.2s, both Tang CDRs locked, 0 Acorn errors, 30s PRBS 0
errors both ways), 14 3/3, 13 3/4, 12 (the former reset value) 0/22 (and back to 12 breaks a recovered link 6/6), 4/8/10
0/4; good loads clean at 12-15; order controlled on 3 fresh loads (15 first, 12/15 alternating). The 256 DRP registers of
both channels identical on good/bad loads, no status bit separating them. Acorn lane 1 TX forced idle: Tang lane 0
locks on a bad load. A bad load = too little Tang receiver margin at swing 12 with both Acorn lanes transmitting.
Fix: `--tx-diffctrl` (reset value of the runtime register), default 15 with `--lanes 2`; the watchdog kept as a fallback.
Acorn <-> Acorn Gen 1x2 not retested at 15 (bench wired Acorn/Tang).
t20 (0766db0 Acorn and Tang): Tang split PRBS build meets timing (lanes clock 125.35MHz, +0.023ns; sys 83.3MHz), Acorn
WNS +0.100ns, swing 15 read back on both lanes. Acorn loads: **20/20** good at x2 with the watchdog off (both Tang CDRs
locked at 124.996-124.997MHz, ~615MB/s each way, 0 watchdog re-inits), 10/10 with it on; Warm Reset at x2 (Host PHY held
in reset 1s: the port reset path): 15/15 back to x2 U0 in 1.14-1.18s; Gen 1x1 at swing 15: 2/2, 308MB/s. Open: in 7/47
PRBS measurements the Acorn checker (Tang -> Acorn) counts more errors than words (~1.16G errors for ~769M words in 10s,
also at Gen 1x1) with the link in U0 and no Recovery: the packet markers (K-codes, not scrambled) are received but every
data/idle word is wrong, i.e. the Acorn descrambler out of step with the Tang scrambler (likely one errored Symbol, e.g.
a SKP, advancing one LFSR); a Link Layer would see CRC errors and Recover. PRBS stand-ins now do the same: checker lost
(errors on most words of 1024 cycles) -> directed Recovery, `usb3_prbs_rx_resyncs`.
t21 (589865c, partial: the NUC went offline during the resync on/off A/B): Tang split build at the default placement
113MHz on the lanes clock (WNS -0.85ns, t20 met at 0766db0: margin placement dependent), `--place-option 1` 125.1MHz (used);
30 Acorn loads + Warm Resets + Tang retrains: 55/55 PRBS measurements clean, no garbage measurement (whether resyncs
occurred and the A/B not collected).
t21b (320eab6 bitstreams, 2 x 10 loads x 10 Host trainings (Warm Resets), resync off/on alternating, 10s PRBS each): the
Acorn checker loses step on ~18% of the trainings in both arms (line clean: no decode/disparity/COM/SKP errors, U0 x2
deskewed, normal packet rate: descrambler out of step); resync off 16/100 garbage measurements, on **0/100** (1-2 resyncs
during the training; re-enabled on the 16: cleared, 1 to 94 Recoveries). New: the Tang checker stops receiving (9 cases,
both arms, sticky on some loads, cleared by a later training): its RX words/packets/errors frozen, TX running, link in U0
x2 deskewed, CDRs locked, no Recovery, Acorn clean: start markers never seen whole, nothing counted, so not lost. Fix: a
window with no start marker while non-idle (or no) words were received is lost too (a partner sending Logical Idle only
is not). Tang place options (deterministic, lanes clock/sys): 0 118.5/62.8, 1 125.1/67.0, 2 113.0/67.1, 3 **126.1/74.4**,
4 112.0/69.5MHz: `--place-option` 0-4, default 3 for the `--lanes 2` PRBS split builds. `litex_mcp` read-only against
the Acorn SoC works (check, register reads/sequences); LiteX's `parse_build_reports` finds no Gowin timing (Gowin
1.9.12.02 SP2 writes `impl/pnr/project.tr.html`, not `project.tr`: upstream LiteX fix).
t22 (d512796, Tang place option 3 by default: lanes clock 125.2MHz, sys 65.4MHz, met; Acorn WNS +0.303ns): resync on
both boards, 10 loads x 10 Host Warm Resets: **0/110 garbage, 0/110 Tang stuck**, no resync or Recovery while measuring,
back to x2 U0 median 0.92s (max 1.96s); Tang resyncs in 80/100 trainings (102/109 while the Host PHY is held in reset: no
words received in U0, the new criterion), Acorn resyncs 54/100 trainings (up to 14, those trainings ~1.95s). Tang resync
off (2 x 5 loads x 10): no frozen case, but 5/110 measurements garbage for 10s with the Tang packets at ~9.7k/s instead of
4.67M/s (start markers almost never whole: a lane word misalignment on the Tang receiver with deskew reported aligned;
open, the split Tang build has no realign/SKP counters), cleared by re-enabling resync (4 and 11 Recoveries). 20 Acorn
loads (Tang loaded once): 20/20 x2 U0, first 10s clean (610MB/s each way, 0 errors, 0 resyncs).
t23 (Tang 28b0d99 `--with-lanes-counters` p3: lanes clock 125.49MHz, sys 65.1MHz; 5ae61a9 without the counter input
registers 85.9-106.5MHz on p0-p4; Acorn t22 bitstream): Tang resync off, 10 loads x 10 Warm Resets: 14/110 bad (G: ~12k
packets/1.25s instead of 5.8M, words erroneous; F: frozen; E: no words, errors on every cycle; P: in a packet on every
cycle, no packet), load 5 bad on 10/11 trainings then clean on the next Acorn load; **none of the 17 lanes counters moves
during a bad period** (deskew, com_slip, realign/skp odd in U0, per lane TS, COM partial, SKP odd, RX errors cycles):
invisible to the COM/SKP/deskew logic (no COM in U0); re-enabling resync cleared 14/14 (1-46 Recoveries); resync on 0/33.
Reading: the markers are not seen whole: the destriped 64-bit word put together wrong after the deskew (lanes paired one
lane word apart?). PRBS lane check added for the diagnosis builds (`--with-lanes-counters`: `usb3_prbs_rx_half_markers`,
`rx_lane1_late`, `rx_lane1_early`: a packet marker on a single lane, then on the other lane the next word).
Gowin 1.9.12.02 SP2 timing report: `impl/pnr/project.tr.html` is a frameset, the data is in `project_tr_content.html`
(HTML tables; the setup path list starts with sys -> JTAG TCK crossings of negative slack while the per clock TNS is 0).
t24 (28b0d99, all builds met: Tang Device split 125.34MHz / sys 71.4MHz, Tang Host split 125.14 / 70.6MHz, Acorn Host
WNS +0.269ns, Acorn Device +0.169ns): A. Acorn Host <-> Tang Device, 5 loads x 10 Warm Resets, resync on both: 0/55
garbage/stuck; first window ignored (db8a95e): Acorn resyncs 11/50 trainings, 21 in all (t22: 54/100, 218), back to x2 U0
median 0.93s, max 0.98s (t22 1.96s); Tang ~1 resync per training (Host PHY held in reset 1s: no words in U0, harmless).
**B. Tang Host <-> Acorn Device at Gen 1x2**: 10/10 Acorn loads (Tang loaded 3 times) x2 U0 in 8.0s, first 10s 610MB/s both
ways, 0 errors; Warm Reset from the Tang Host 15/15 (0.92s, 0 errors); x2 disabled at runtime 2/2 Gen 1x1 (~305MB/s, 0
errors), back to x2 2/2. The Tang watchdog fired once per Acorn load (Polling.LFPS while the Acorn reloads): the
watchdog no longer counts Polling.Entry/LFPS/LFPSPlus/ExitToRxDetect. `usb3_lanes.py prbs` MB/s per sample mode (x1).
t25 (Tang Device 0629fed `--with-lanes-counters` p3 125.02MHz; Tang Host 47514a9 125.07MHz): Tang resync off, 10 loads x
10 Warm Resets: 3/110 bad (G), PRBS lane check: clean 0 half markers; bad ~3.90 half markers, 0.008 lane1_late, 0
lane1_early per packet: matches (generator model) **Lane 1 paired 4 lane words (one TS Ordered Set) early**, not one word;
same offset in the 3 cases. Cause: Lane 1's first marker one TS later than Lane 0's (identical TS Ordered Sets: no mismatch
while they last), the single mismatch at the end of the TS stream tolerated. Fix: a marker against a plain data word (no K
Symbol: Logical Idle/TS body, not a corrupted marker) clears the pairing at once (`LaneDeskew`, re-armed on the gap: deskew
lost, Recovery; `test_deskew_os_apart_end_of_stream`). Tang Host watchdog at 47514a9: 0 on 3 Acorn reloads, x2 at 8.0s.
LiteX Gowin parser patch: clocks/Fmax/TNS/met identical to gowin_timing.py on 3 builds, WNS from the path list wrong (sys
-> JTAG TCK paths first): WNS now from the per clock Fmax.
t26 (deskew fix df60b2a/db5c7fa; Acorn Host WNS +0.281ns, Acorn Device +0.145ns; Tang Device 4bf5263 p3 125.06MHz, Tang
Host db5c7fa p3 125.22MHz; the `--with-lanes-counters` Tang Device builds miss 125MHz by up to 0.18ns on every placement
(routing 4-6ns of 8ns, paths spread): diagnosis builds only): Acorn Host <-> Tang Device, Tang PRBS resync off, 10 loads x 10
Warm Resets: **0/110 bad** (t25 3/110, t23 14/110), back to x2 U0 median 0.94s (4/100 at ~2.0s, as t25); resync on both
3 x 10: 0/33. Tang Host <-> Acorn Device (new deskew on the Acorn receive side): 5/5 loads x2, 0 errors; A/B old/new Acorn
Device deskew, 10 loads x 5 Warm Resets: x2 5/5 each, back in 0.94s each, 0 errors, Acorn resyncs in training 12 vs 28
(pairings cleared and re-paired: no measurable cost). LiteX parser patch `wns` = min(1/constraint - 1/Fmax): +0.021,
-2.001, -0.927ns on 3 builds, matching the worst lanes clock paths.
t27 (final Acorn Host <-> Tang Device PRBS regression; Tang Device 64b1d9b: p3 101.9MHz (lane 1 RX clock crossing/
descrambler -> PRBS checker, -1.8ns: placement, the same design met at p3 in t26), **p2 125.09MHz** used; Acorn Host
4bf5263): 20/20 Acorn loads at x2 in 8.0s, first 10s 610MB/s each way, 0 errors, 0 resyncs; 5 Warm Resets on 4 loads 20/20
back in 0.91-0.96s, 0 errors; 0/40 garbage/stuck. The Tang placement must be checked per build (p3 default, p2 fallback).
t28 (Tang Gen 1x2 Device Core split, 297761a): lanes clock 68.8MHz (p3) / 46.5MHz (p2) for 125MHz, all worst paths in
`LanesPacketAligner` (buffer level -> symbol destinations -> 32-symbol buffer write in one cycle, 9-11 levels, -6.5ns):
not run on hardware; the aligner needs a redesign for the GW5A. Acorn scripted host build met (+0.239ns). `--place-auto`
works (reports matched gowin_timing.py); it now stops when a clock is below 90% of its constraint.
`LanesPacketAligner` redesigned (per packet rotation, 32-bit slices of a two words window, 4 word FIFOs written in
rotation): no per symbol placement from a buffer level; aligner tests and the 31 Gen 1x2 simulations pass.
t29 (6140222): Tang Device Core lanes clock 68.8 -> 111.5MHz (p3; p4 113.8), worst groups ~-0.9ns (TX packets buffer
-> SerDes TX, idle handshake, deskew mismatch, aligner count): fixed in 985ed31; Acorn scripted host +0.068ns; PRBS
regression 3/3 clean. t30 (985ed31): Tang Device Core 114.4MHz (p4, sys 62.54MHz met), worst ~-0.74ns (lane RX words ->
Link RX buffer: descrambler output not registered; RX errors monitor hold -> errors; TS2 generator -> SerDes 1 TX; deskew
aligned): the first two fixed next; Acorn scripted host +0.184ns; PRBS regression (Tang p4 125.02MHz, Acorn +0.134ns): 5
loads x 3 Warm Resets, 0 errors, 610MB/s.
t31 (a842823): Tang Gen 1x2 Device Core met (p4: lanes 125.04MHz, sys 67.6MHz for 62.5MHz; p3 125.03MHz; worst lanes path
+0.002ns, aligner candidate -> word FIFO write); Acorn scripted host +0.333ns. **First Device Core runs on the Tang: Acorn
scripted host <-> Tang Device Core Gen 1x2 (SuperSpeedPlus) 97/100 runs on 10 loads (3 Tang loads), 0 timeouts, Gen 1x1
(x2 disabled on the host) 20/20**; run median 47.3ms (x2) / 76.5ms (x1); Tang `rx_overflow` 0, LBAD/retries 0. The 3
errors: step 510, `bulk_in_0` first DPP data word (after its SDP), in U0 at x2, on 3 loads (one each). Host Hot Resets per
load 12-277 (runs restarted after any U0 exit). PRBS regression (Tang p4, Acorn +0.154ns): 5 loads x 3 Warm Resets, 0
errors, 610MB/s, no resync. Next: the received word at the error (`usb3_script_error_data`/`error_prev`/`error_info`) and
the `script` LiteScope group (host aligner input/output, model words) on the Acorn host.
t32 (74b30d0, Tang t31 bitstream): 198/200 runs on 20 loads, then 2 of 3 first runs after ~20s in U0 failed. The
received words and the `script` captures of 4 errors: the Tang -> Acorn scrambled symbols (Logical Idle, DPH, DPP data)
are random on both lanes (zero symbols 0.3-0.5% per lane vs 99.2% in a good run), the framing K symbols intact and
placed as in a good run; one load stayed bad across 699 Hot Resets (U0 reached each time: the descramblers matched
during the Idle handshake). Cause: in the Tang split build (LTSSM in sys at 62.5MHz, lanes in the 125MHz lanes clock),
`tx_ready` and `idle_handshake` were resynchronized separately (untimed paths): at the Idle handshake -> U0 transition
the lanes clock could see both at 0 for a cycle, which resets the lanes TX scramblers (`~(tx_ready | idle_handshake)`)
to their start state in U0, both lanes at once (the same mechanism explains the Tang -> Acorn PRBS "descrambler out
of step" of t20/t21b). Fix: both resynchronized together, updated on two equal samples (`add_lanes_levels_stable`,
also the Gen 1x1 `pipe_cd` LTSSM CDC; `TestLanesLevelsStable`). The first version (d624cc8) delayed only these two
outputs, so the TS requests ended a cycle before the Idle handshake start (`test_phy_x2_dev_pipe_cd*` stuck in
Polling.Idle): all the LTSSM outputs are now resynchronized as one group (741c3b2).
t33 (741c3b2): PRBS with the resync off on both boards, 20 loads x 6 trainings (120 measurements each way): Tang -> Acorn
0 garbage, 0 stuck, 0 errors (t21b: 16/100 garbage): the "descrambler out of step" is gone; Acorn -> Tang 3 stuck
(the frozen Tang RX word misalignment type, cleared by the Tang resync); resync on 20/20 clean. Some Warm Reset returns
slower (13/100 over 1.5s, steps of ~1s, one 7.25s with resync on; t31 max 0.95s): to follow. Tang PRBS p3 met
(126.1MHz); the Tang Device Core missed on every placement (best p1 116.1MHz, p2 112.5MHz): the group compare drove the
update enable of all the resynchronized outputs, into the lanes TX words: compare registered (one more lanes cycle).
t34 (8430276): the group paths gone from the Tang Device Core worst list, best p2 120.1MHz (-0.328ns: Link RX AsyncFIFO
write Gray counter, a buffered FIFO memory read data -> read address; p4 88.4, p3 94.2, p1 113.2, p0 101.5MHz). Warm
Reset return A/B (6 alternating Tang loads x 8): a842823 0/24 over 1.5s (max 1.12s), 741c3b2 0/24 (max 1.13s): the t33
slow returns not reproduced. **t35 (8430276, Tang Device Core p2, -0.33ns, gate waived): Acorn scripted host <-> Tang
Device Core Gen 1x2 200/200 runs on 20 loads, 100/100 on 10 loads with the runs after 20s in U0 (t32: 2/3 failed),
Gen 1x1 20/20, 0 errors** (t31: 97/100): the scrambler fix confirmed on the Device Core. Route options 0/2 with p2/p1:
none met (p2: Gowin PR0004 error, no bitstream). One load took 16.5s to U0 (usual ~7.5s). Next: a met Device Core build
(9371917: registered Link RX FIFO input, the t34 worst path).
t36 (9371917): the t34 worst path gone but the Tang Device Core placement worse (best p2 101.1MHz, p4/p3/p1/p0 85-88MHz;
worst: deskew FIFO output -> `aligned` 11 levels, SerDes `rx_idle` -> `idle_count` clear 8.3ns of routing): the lanes
clock swings 85-125MHz from one small change to the next. Functionally, on the p2 build (-2.11ns): Gen 1x2 160/160 runs
(incl. 50 after 20s in U0), Gen 1x1 10/10, 0 errors, U0 in 7.51-7.54s on 16 loads; PRBS split p3 met, 5 loads x 3 Warm
Resets clean. Open: some loads of the fix builds with many host Hot Resets (`resets_csr` 733-4872, t35 up to 213051;
t31 max 277; every run passes): timing misses or behaviour, to separate on a met build.
t37 (3eabff2, 9 builds p0-p4 x route options): best p2 99.7MHz; the worst path cell by cell: deskew FIFO output data ->
COM masks of the deskewed words (`com_slip`) -> deskew clear -> `aligned` (10 levels, 68% routing): `com_slip` now
registered. 100/100 runs on the p2 build (-2.03ns); the Hot Reset bursts (3 loads, 9472-53976): runs restarted every
~30us for 0.2-0.8s, Tang Link Layer recovery causes 0, Acorn lanes counters ~100-200, ~1.5 Tang PHY Recoveries per Hot
Reset: the Tang PHY directs them (the deskew logic failing timing is the likely source).
**t38 (c260fd2): Tang Gen 1x2 Device Core met** (p2 route 1: lanes 125.09MHz, sys 63.55MHz; p2 route 0 125.05MHz; p3
119.7, p4 99.0, p1 92.7, p0 82.3MHz; worst lanes paths +0.006ns: Link TX buffer -> SerDes 1 TX, SerDes RX CDC outputs).
**Acorn scripted host <-> Tang Device Core: Gen 1x2 110/110 runs, Gen 1x1 10/10, 0 errors, host Hot Resets per load
10-43** (the t35-t37 bursts came with the timing misses); one run 181ms (eSS.Inactive, Polling retrains, completed).
PRBS split p3 met (125.16MHz): 5 loads x 3 Warm Resets clean.
**t39 soak (c260fd2, p2 route 1): 530/530 runs, 0 errors**: Gen 1x2 20 loads x 20 runs 400/400 (as the Acorn <->
Acorn reference), Gen 1x1 4 x 20 80/80, 60s in U0 before the runs 5 x 10 50/50 (failed 2 in 3 before the t32 fix);
U0 x2 in 7.51-7.57s on all loads, median run ~47ms, 19 runs over 100ms (LTSSM histories frozen). Host Hot Reset bursts
on 5/20 Gen 1x2 loads (4840-210376) on a met build: not timing. Two slow run kinds: (1) a Hot Reset loop (~10us per
loop): after `HotReset.Exit -> U0` both boards enter Recovery within ~1us, the Acorn returns to U0 once, the scripted
host takes it as a U0 exit and restarts the run with a new Hot Reset (2 Acorn Recoveries per Hot Reset); (2) a
Recovery timeout (12ms Acorn/6ms Tang) -> eSS.Inactive -> 1-3 Polling retrains. Tang Link Layer at Gen 1x2:
`pending_hp` only, 0-4 per load (26, 69, 552 on three loads). Gen 1x1 (open): Tang Link 3085-18379 `pending_hp`
and 53-122 `lcrd` Recoveries per load (Acorn <-> Acorn: ~20), runs still pass at normal times.
**t40 (63847af, U0 exit triggers on both boards; Tang p2 r1 met 125.01MHz): Gen 1x2 400/400, Gen 1x1 80/80, 0
errors.** Hot Reset loops on 6/20 loads (resets 174216-808302): **the Tang starts them with `lanes_deskew_lost`**
(saturated on every loop load, >= 1 per loop) right after `HotReset.Exit -> U0`; the Acorn exits are `ts1` (the Tang
Recovery) and `hot_reset_req` (scripted host run restart); Tang Link `directed` 0-1 on loop loads. Loops end only on a
retrain (Tang eSS.Inactive, Acorn WarmReset/Polling), 1.6-4.7s per looping run. Clean loads: occasional Tang deskew
lost or Link `pending_hp` Recoveries, single. Gen 1x1: ~1000-1750 Tang Link Layer Recoveries per run (`directed` =
`pending_hp` ~99% + `lcrd`), no lanes trigger, no loop: a Tang Device Core Link issue at Gen 1x1 (open). Next: the
deskew loss reason on the Tang (`deskew_loss`, t41).
**t41 (530ced3, both met): Gen 1x2 395/400** (5 timeouts at step 24 on loop loads: after a retrain the Acorn reaches
U0 from Polling.Idle while the Tang loops Polling.Idle -> Polling.ExitToRxDetect: no Idle Symbols seen by the Tang,
its deskewed lanes again), loops on 7/20 loads, all started by the Tang `lanes_deskew_lost`; the loop loads are the
noisy loads (Acorn comma realignments, `realign_u0`, `skp_odd_u0`, `lane_idle_u0` ~30x the clean loads; 8 clean loads
all 0). Tang controls on a looping load: realign/idle Recovery off no change, com Recovery off fewer loops (285 vs
1642-4718 resets / 20 runs), not stopped. `deskew_loss` read 0: CSR status assigned directly while a CSRStatus with
fields drives it from them (fixed: through the fields). Gen 1x1: Tang Link `pending_hp` ~1290 Recoveries per run again.
**t42 (3f453ee, both met): Gen 1x2 400/400, loops on 6/20 loads.** With `deskew_loss` working: each loop starts with
one Tang deskew clear in U0 (`clear,realign`: a lane comma realignment, 4 loops; `clear,com_slip`, 2 loops), then the
Tang deskew is **never re-acquired** through thousands of Recovery/Hot Reset Training Sequences (fast reads during the
loops: `aligned` 0 in 143/160, `deskew_loss` unchanged for seconds); every U0 entry then fires `lanes_deskew_lost`
until a retrain (Acorn Warm Reset after ~2.36s, or Tang eSS.Inactive). Simulation (`--lane-slip 902000,1`, Host lane
in U0 during the run): re-paired on the first Recovery, not reproduced. Next (t43): sticky deskew inputs flags
(`deskew_seen`: per lane marker/error/partial COM words, gap, armed, overflow, aligned) read during a loop.
**t43 (503596f; Tang p2 r1 hung in Gowin routing, p3 r1 met 125.04MHz): Gen 1x2 400/400**, loops on 13/20 loads (5
long, 2.4s). `deskew_seen` during the long loops (96 windows): markers, gaps and the search armed on both lanes, error
words on both lanes every window, **Tang lane 1 partial COM words in 84/96**, never aligned nor overflow; reference
runs: never armed nor partial. Cause (reproduced on `RXWordAligner` alone): after a lane shift of k Symbols (1-2), TS1s
with their first k COM Symbols received as K28.4 start their shortened COM run on the shifted alignment, which the
shortened-run rule (t8) keeps: lane 1 stays k Symbols off, its COM words partial, the deskew never pairs (errors
disarm, no whole marker on lane 1). Fix: the aligner output pattern (a word ending with k K28.4, then a word starting
with 4-k COM Symbols) moves the alignment back k Symbols (`test_rx_word_aligner_escapes_shift_kept_on_com_errors`).

**t44 (8ef1a79): no Tang Device Core build met timing** (p2 r1 98.9MHz, p3 r1 107.5MHz, p2 r0/p4 r1 worse; PRBS
split p3 113.8MHz): the worst paths end at the new aligner features (`trail_r`/`lead_r`, -0.8 to -2.1ns: alignment
selection -> output Symbol compares). The soak on the missed p3 r1 build shows long loops on loads 1, 3 and 4
(168k-252k resets): no verdict on the fix with a failing build. Change: the aligner output word registered before the
features, the correction two words later (still in the TS body). Next (t45): rebuild, soak.

**t45 (06f2d8f; Tang Device Core p2 r1 met 125.045MHz, aligner off the worst paths; p3 r1 120.4MHz; Acorn hosts
rebuilt, met): Gen 1x2 400/400, 0 errors; loads > 100 resets 2/20 (t43 13/20, t44 7/20), median resets per load 20
(one per run, the floor; t43 4835, t44 31.5), runs > 100ms 2 (t43 28, t44 34), no run between 100ms and 2.3s; the
t44 lane 0 partial COM words gone (timing miss). Two long loops left (loads 2, 18, ended by the Acorn Warm Reset): Tang
markers, error words on both lanes, gaps, armed, never aligned in 32/32 windows, lane 1 partial only in 20/32 (load 2:
12/16 windows without partial, `deskew_loss` plain): not the Symbol shift alone (open: error words disarming every
search, or lanes an Ordered Set apart); the Acorn stays paired, neither load Acorn-noisy. Gen 1x1 40/40 (resets 51/41,
no deskew lost, Tang Link `pending_hp` storm unchanged). PRBS (Tang p3 met 125.15MHz) resync on/off: 0 garbage/errors,
610MB/s, 3/18 Warm Reset returns 2.3s (load 2, not investigated).

**t46 (eef441f, `LaneDeskew` trailing error word before a marker word not disarming; Tang p2 r1 met 125.43MHz): Gen 1x2
400/400, loads > 100 resets 3/20 (t45 2/20), median 20, runs > 100ms 4, 2 long loops (loads 6, 16; load 17 ended alone
after ~0.5s): no change; partial COM words 0/38 loop windows; in the loops the search armed, error words on both
lanes, never paired. Gen 1x1 40/40, PRBS 18/18 Warm Resets 1.08-1.10s, 0 errors. Next (t47): `deskew` LiteScope group
(lanes clock domain) captured in a loop (`--trigger deskew_lost --no-retrain`).

**t47 (416214c): not run.** Every Tang Device Core build with the `deskew` LiteScope group missed timing by 3-5 ns
(90.9/81.4/77.7MHz): the LiteScope trigger (mask/value memory, compare, gray counter) at 125MHz with the 98-bit group.
Replaced by a purpose-built recorder (`--with-deskew-trace`, `LanesDeskewTrace`: block RAM ring buffer of deskew
events, frozen after deskew_lost). Next (t48): capture loops with it.

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
