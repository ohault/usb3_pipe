# Gen 1x2 Hardware Validation: LiteX Acorn Baseboard Mini (Two Boards, SFP2USB, Gen 1x2 Host)

Hardware validation of the USB 3.2 Gen 1x2 PHY (`USB3PHY(lanes=2)`) between two boards, one in the
Host role and one in the Device role, without a Gen 1x2 USB host or a USB Type-C breakout
([Gen 1x2 hardware milestones](gen2-x2-roadmap.md#gen-1x2-hardware-milestones), M0,
[issue #140](https://github.com/enjoy-digital/usb3_pipe/issues/140)). The same tests run in
simulation with `sim.py --lanes 2` (`test/test_phy.py` `TestPHYX2`).

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
it needs the breakout (`dual-sfp2usbc-breakout` branch, `hardware/sfp2usbc/`) and such a host.

| Part | Boards | Link partner | Link Layer | Simulation |
|------|--------|--------------|------------|------------|
| Two boards (tests 1-6) | 2 | Acorn Mini, Host role, 2 DAC cables | PRBS stand-ins | `sim.py --lanes 2` (`TestPHYX2`) |
| Two boards, core (tests 7-10) | 2 | Acorn Mini, scripted USB host, 2 DAC cables | Device Core, SuperSpeedPlus at Gen 1x2 | `sim.py --lanes 2 --lanes-core` (`TestPHYX2Core`) |
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

For the single lane fallback test (step 5), a Device without the x2 capability:

```sh
./bench/acorn.py --lanes 2 --role device --no-x2 --with-jtagbone --output-dir build/acorn_x1_device --build
```

Optional: `--lpm-hold rxeq` (GTP LPM adaptation only in Polling.RxEQ), `--with-analyzer
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
litex_cli --port 1240 --ident # USB3SoC ...
litex_cli --port 1241 --ident # USB3SoC ...
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
`retrain` (link retraining, status and LTSSM state history), `watch` (status on changes), `prbs`
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

```sh
for i in $(seq 10); do ./bench/usb3_lanes.py $D retrain --wait 2; done
./bench/usb3_lanes.py $D prbs --duration 30
```

Pass: U0 with `x2: 1` and `deskew_aligned: 1` after each retrain, PRBS still without errors. Also
from the Host (`$H retrain`).

### 4. Lanes swap (crossed cables)

Cross the DAC cables: Host SFP-0 <-> Device SFP-1 and Host SFP-1 <-> Device SFP-0 (as a flipped USB
Type-C plug on the dual SFP to USB-C breakout), then:

```sh
./bench/usb3_lanes.py $D retrain --wait 2
./bench/usb3_lanes.py $D status
./bench/usb3_lanes.py $D prbs --duration 60
```

Pass: Device `lane_swap: 1` (Configuration Lane detected on SFP-1 from the Host Polling.LFPS), Host
`lane_swap: 0` (the Host keeps its lanes), `x2: 1`, deskewed, PRBS without errors. Put the cables
back straight after this test.

### 5. Single lane fallback (Gen 1x1 negotiated)

Load `build/acorn_x1_device` (built with `--no-x2`) on the Device board, use its CSRs:

```sh
./bench/acorn_ftdi.py --location <dev_location>  load build/acorn_x1_device/gateware/sqrl_acorn.bit
D1="--port 1241 --csr-csv build/acorn_x1_device/csr.csv"
./bench/usb3_lanes.py $D1 status
./bench/usb3_lanes.py $D1 prbs --duration 60
./bench/usb3_lanes.py $H status
```

Pass: `x2: 0` on both boards (Gen 1x1 negotiated in the LBPM PHY Capability exchange), U0 on SFP-0
only, SFP-1 in electrical idle (`rx_idle: [0, 1]`), PRBS without errors (32-bit link words: about
half the Gen 1x2 rate). With crossed cables (step 4), the same on the Device SFP-1.

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

Pass: as test 1 (U0, `x2: 1`, `deskew_aligned: 1`) on both boards, `rx_overflow: 0`. The link
stays in U0 between the script runs (the scripted host sends a LUP keep-alive every 10us, as a
host: no Device Recovery for a lack of link activity), `recovery_count` stable over a minute.

### 8. Scripted host runs

```sh
./bench/usb3_lanes.py $H2 script --runs 100
./bench/usb3_lanes.py $D2 status
litex_cli --port 1241 --regs | grep usb3_core     # Device Link Layer counters (LBAD, retries, Recovery).
```

Pass: `done` for each run (one JSON line per run with its duration), final line with `done: 100`,
`error: 0`, `timeout: 0`, `x2: 1`, `rx_overflow: 0` on both boards, `recovery_count` stable, no
LBAD/retries in the Device Link Layer counters (`usb3_core_rx_lbad`, `usb3_core_tx_retry`,
`usb3_core_recovery_req`). An `error` gives the failing step and script section (`link_init`,
`get_device_descriptor`... `bulk_in_1`): report them; a `timeout` is a link not in U0.

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

## Single Board With a USB 3 Host (SFP2USB Adapter)

One Acorn Mini built with `--lanes 2 --lanes-core`: `USB3PHY(lanes=2)` on SFP-0/SFP-1 and the USB3
Device Core example design (`bench`: `USB3PHYX2Link`, Gen 1x2 capable; a Gen 1x1 host through the
single lane adapter negotiates Gen 1x1 on the Configuration Lane, SuperSpeed operation). The SFP2USB adapter carries a single lane: in SFP-0,
the host Configuration Lane is on SFP-0 (`lane_swap: 0`); in SFP-1, the Device detects it from the
host Polling.LFPS and swaps its lanes (`lane_swap: 1`), as for a flipped plug on the dual SFP to
USB-C breakout. Simulation: `sim.py --lanes 2 --lanes-core` (`test/test_phy.py` `TestPHYX2Core`).

Hardware: one Acorn Mini (power, J7 to the PC, J10 Pico-EZmate as above), the SFP2USB adapter and a
USB 3 cable to the host (xHCI, Linux: `bench/99-usb3-pipe.rules` for user access to the vendor
class examples). The device is `1d50:605a`.

### Build and load

```sh
./bench/acorn.py --lanes 2 --lanes-core --example bench --with-jtagbone --output-dir build/acorn_x1_bench --build --load
litex_server --jtag --jtag-config openocd.cfg --jtag-port 20040 --bind-port 1240 # OpenOCD config: see above.
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
Acorn build ([examples.md](examples.md): ~450MB/s IN/OUT).

### 12. SFP2USB in SFP-1 (lanes swap)

Unplug the USB cable, move the SFP2USB adapter to SFP-1, plug the USB cable (the PHY retrains:
Polling from Rx.Detect, or `./bench/usb3_lanes.py $B retrain --wait 2`), then the same commands as
step 7.

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
  Lane 1 on SFP-1, Rd on CC1/CC2 (Device), no USB 2.0 ([breakout README](https://github.com/ohault/usb3_pipe/tree/dual-sfp2usbc-breakout/hardware/sfp2usbc)).
- A USB 3.2 x2 capable host (ex: ASMedia ASM3242 based Gen 2x2 PCIe card; Gen 1x2 support to check
  in its specification), a USB-C to USB-C cable rated for USB 3.2 x2 (both SuperSpeed pairs wired,
  ex: USB 3.2 Gen 2x2/20Gbps or USB4 cable), Linux (the negotiated lanes are in the sysfs).
- Optional: a Gen 1x1/Gen 2x1 host with a USB-C port (fallback test).

Build and load as in the single board part (the same bitstream: `build/acorn_x1_bench`, `$B`).

### 14. Enumeration at Gen 1x2

```sh
lsusb -t                                                          # Device under the x2 host port.
D=$(grep -l 605a /sys/bus/usb/devices/*/idProduct | xargs -n1 dirname | head -1)
cat $D/speed $D/rx_lanes $D/tx_lanes                              # Negotiated speed/lanes.
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
`rx_drop: 0` in `usb3_lanes.py $B status` (no RX words dropped by the Gen 1x2 RX buffer). Rates: above the
Gen 1x1 build (~450MB/s), up to ~1GB/s for 64-bit link words at 125MHz (the Gen 1x2 throughput has
not been characterized yet: report the rates, they are a result).

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

Results to report (in [issue #140](https://github.com/enjoy-digital/usb3_pipe/issues/140) or with the
branch), per test and per board:
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

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `litex_cli --ident` fails or returns another design | `--location` of the board (`acorn_ftdi.py list`), J10 Pico-EZmate cable, `--bind-port`/`--port`, `litex_server` restarted after the load. |
| No U0, `rx_idle: [1, x]` | No signal on Lane 0: SFP-0 cable seated, the partner bitstream loaded. |
| Stuck in Polling, `rx_errors_cycles` increasing | Receiver equalization through the DAC cable: try `--lpm-hold rxeq`, a shorter cable. |
| U0 with `x2: 0` and straight cables (x2 bitstreams) | Lane 1: `lane1_ts1` stays at 0 or `rx_idle[1]` stays at 1 (SFP-1 cable), `--no-x2` bitstream loaded by mistake. |
| U0 but `deskew_aligned: 0`, or PRBS errors in one direction only | `retrain` output of both boards (history), `deskew` counter. |
| PRBS errors increasing slowly | `rx_errors_cycles` per lane (link quality), `recovery_count`, cable length. |
| `lane_swap: 1` with straight cables | Cables swapped (SFP-0/SFP-1 cages). |
| Two boards, core: script `timeout` | Link not in U0 (`status` of both boards, test 1 with the PRBS bitstreams), Host board `--lanes-core` bitstream loaded. |
| Two boards, core: script `error` at `link_init` | Advertisements/LMPs not exchanged: Device board bitstream (`--lanes-core --example loopback`), `x2: 1` on both (SuperSpeedPlus script: a Gen 1x1 link is SuperSpeed), Device `usb3_core` state. |
| Two boards, core: script `error` at `bulk_in_*` | Data check failed: step offset in the section (DPH words, SDP, data word, CRC-32, END), `rx_overflow`, Device LBAD/retries; the same with `--runs` repeated (systematic or random). |
| Single board: not enumerated, U0 not reached | `status`/`retrain` history, the same SFP2USB/host/cable with the Gen 1x1 build (`bench/acorn.py` without `--lanes`) for a reference. |
| Single board: enumerated in one cage only | `lane_swap` and `rx_idle` per cage, `retrain` history in the failing cage. |
| Gen 1x2 core: `x2: 0` with a x2 host | Host x2 support (port, `rx_lanes`), cable with both SuperSpeed pairs, Lane 1 signal (`rx_idle[1]`, `lane1_ts1`), the two boards part (tests 1-4) for the lanes themselves. |
| Gen 1x2 core: U0 at x2 but not enumerated/transfer errors | `usb3_debug.py` Link Layer counters (LBAD/retries, recovery causes), `retrain` history; RX buffer overflow (`rx_overflow`/`rx_drop` in `usb3_lanes.py status`: dropped RX words, the Link Layer too slow); framing re-alignment (host packets right after a DPP of a length not a multiple of 4: not supported yet, [gen2-x2-roadmap.md](gen2-x2-roadmap.md)). |
| Gen 1x2 core: works in one plug orientation only | `lane_swap` per orientation, CC/lane routing of the breakout (TX1/RX1 on SFP-0). |

## References

- [gen2-x2-roadmap.md](gen2-x2-roadmap.md): Gen 1x2 PHY (`USB3PHY(lanes=2)`), simulation coverage,
  hardware milestones.
- [debugging-guide.md](debugging-guide.md): JTAG/`litex_server` setup, CSRs, LiteScope.
- `usb3_pipe/phy.py` (`USB3PHYX2Link`), `usb3_pipe/lanes.py` (`LanesTXPacker`, `LanesFramingAligner`,
  `LanesIdleFilter`): the Gen 1x2 Link interface.
- `bench/acorn.py` (`--lanes 2`, `--role`, `--no-x2`, `--lanes-core`), `bench/usb3_soc.py` (`add_usb3_lanes_link`),
  `bench/usb3_lanes.py` (client), `bench/acorn_ftdi.py` (FT2232H/FT4232H boards selection: list, load,
  litex_server).
