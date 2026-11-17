#!/usr/bin/env python3

#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2019-2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""USB3-PIPE on the SQRL Acorn CLE-215+ (Artix7 GTP) in a LiteX Acorn Baseboard.

Baseboard Mini by default (--variant standard), SFP2USB adapter in the SFP cage: Gen 1x1 (5Gbps),
main validation target (doc/manual/09_boards.md).

Clocking: GTP reference clock from the 200MHz oscillator (GTGREFCLK0, no PCIe host clock:
doc/manual/06_transceivers.md), sys at 125MHz.

Bridge: UARTBone by default, JTAGBone with --with-jtagbone (baseboard FT4232H). Optional DDR3
(--with-dram, msc_dram example) with a VexRiscv CPU.

Build and load (JTAG, volatile): ./bench/acorn.py --build --load [--example <name>]. Shared
options: bench/usb3_soc.py.
"""

import argparse

import common # Repository root on the path.

from migen import *

from litex.gen import *

from litex_boards.platforms import sqrl_acorn

from litex.build.generic_platform import *

from litex.soc.cores.clock import *
from litex.soc.cores.xadc  import S7SystemMonitor

from litedram.modules import MT41K512M16
from litedram.phy     import s7ddrphy
from litedram.gen     import LiteDRAMCoreControl

from usb3_pipe import A7USB3SerDes

from usb3_soc import USB3BaseSoC, add_usb3_device, add_usb3_lanes_link, usb3_analyzer
from usb3_soc import usb3_soc_args, usb3_soc_argdict, usb3_soc_build

# USB3 IOs -----------------------------------------------------------------------------------------

_usb3_io_standard = [
    # SFP.
    ("sfp_tx", 0,
        Subsignal("p", Pins("D7")),
        Subsignal("n", Pins("C7")),
    ),

    ("sfp_rx", 0,
        Subsignal("p", Pins("D9")),
        Subsignal("n", Pins("C9")),
    ),
]

_usb3_io_mini = [
    # SFP.
    ("sfp_tx", 0,
        Subsignal("p", Pins("D5")),
        Subsignal("n", Pins("C5")),
    ),

    ("sfp_rx", 0,
        Subsignal("p", Pins("D11")),
        Subsignal("n", Pins("C11")),
    ),

    # SFP-1 (Gen 1x2: Lane 1).
    ("sfp_tx", 1,
        Subsignal("p", Pins("B4")),
        Subsignal("n", Pins("A4")),
    ),

    ("sfp_rx", 1,
        Subsignal("p", Pins("B8")),
        Subsignal("n", Pins("A8")),
    ),
]

# CRG ----------------------------------------------------------------------------------------------

class _CRG(LiteXModule):
    def __init__(self, platform, sys_clk_freq, with_dram=False):
        self.cd_sys    = ClockDomain()
        self.cd_oob    = ClockDomain()
        self.cd_clk200 = ClockDomain()
        if with_dram:
            self.cd_sys4x     = ClockDomain()
            self.cd_sys4x_dqs = ClockDomain()
            self.cd_idelay    = ClockDomain()

        # # #

        # Clk200.
        clk200_pads = platform.request("clk200")
        clk200      = Signal()
        self.specials += [
            Instance("IBUFDS", i_I=clk200_pads.p, i_IB=clk200_pads.n, o_O=clk200),
            Instance("BUFG",   i_I=clk200, o_O=self.cd_clk200.clk),
        ]

        # PLL.
        self.pll = pll = S7PLL(speedgrade=-2)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq,   margin=0)
        pll.create_clkout(self.cd_oob, sys_clk_freq/8, margin=0)

        # DRAM clocks (A7DDRPHY: sys4x/sys4x_dqs, IDELAYCTRL reference).
        if with_dram:
            pll.create_clkout(self.cd_sys4x,     4*sys_clk_freq, margin=0)
            pll.create_clkout(self.cd_sys4x_dqs, 4*sys_clk_freq, margin=0, phase=90)
            pll.create_clkout(self.cd_idelay,    200e6,          margin=0)
            self.idelayctrl = S7IDELAYCTRL(self.cd_idelay)

# USB3SoC ------------------------------------------------------------------------------------------

class USB3SoC(USB3BaseSoC):
    def __init__(self, platform, cpu_type=None, with_dram=False,
        gtp_params={}, rxcdr_cfg=None, lpm_hold="none", tx_postcursor=None, tx_diffctrl=None, lanes=1, role="device", x2_capable=True,
        lanes_core=False, sfp=0,
        with_analyzer=False, analyzer_group="link", analyzer_csv="analyzer.csv",
        usb3_kwargs={}, **kwargs):
        sys_clk_freq = int(125e6)

        # CRG --------------------------------------------------------------------------------------
        self.crg = _CRG(platform, sys_clk_freq, with_dram=with_dram)

        # USB3BaseSoC ------------------------------------------------------------------------------
        # DRAM: CPU required (BIOS DRAM initialization/calibration). The BIOS console goes to a stub
        # UART: a crossover UART would block the BIOS (and the DRAM initialization) until a host
        # reads it. Initialization status: ddrctrl_init_done/init_error CSRs.
        assert not (with_dram and cpu_type is None), "DRAM requires a CPU (BIOS initialization)."
        with_stub_uart = with_dram and usb3_kwargs.get("example") not in ["console", "composite"]
        USB3BaseSoC.__init__(self, platform, sys_clk_freq,
            cpu_type  = cpu_type,
            with_uart = with_stub_uart,
            **kwargs)

        # DDR3 SDRAM -------------------------------------------------------------------------------
        if with_dram:
            self.ddrphy = s7ddrphy.A7DDRPHY(platform.request("ddram"),
                memtype          = "DDR3",
                nphases          = 4,
                sys_clk_freq     = sys_clk_freq,
                iodelay_clk_freq = 200e6)
            self.add_sdram("sdram",
                phy           = self.ddrphy,
                module        = MT41K512M16(sys_clk_freq, "1:4"),
                l2_cache_size = 8192)
            # DRAM initialization status (written by the BIOS).
            self.ddrctrl = LiteDRAMCoreControl()

        # USB3 SerDes ------------------------------------------------------------------------------
        # Gen 1x2 (lanes=2): Lane 0 on SFP-0, Lane 1 on SFP-1 (same GTP quad), Lane 1 on the Lane 0
        # Quad PLL and TX clock (lanes TX in lockstep). sfp: SFP cage of Lane 0 (Gen 1x1: the cage;
        # Gen 1x2: sfp=1 swaps the cages, Lane 0/Configuration Lane on SFP-1: single lane fallback
        # and Gen 1x1 links over SFP-1, ex: one cable per board pair with three boards).
        assert sfp in [0, 1]
        usb3_serdes = []
        for lane in range(lanes):
            cage = lane ^ sfp
            serdes = A7USB3SerDes(platform,
                sys_clk      = self.crg.cd_sys.clk,
                sys_clk_freq = sys_clk_freq,
                refclk_pads  = ClockSignal("clk200"), # Directly from the oscillator (no PLL jitter).
                refclk_freq  = 200e6,
                tx_pads      = platform.request("sfp_tx", cage),
                rx_pads      = platform.request("sfp_rx", cage),
                rxcdr_cfg    = rxcdr_cfg,
                pll          = None if lane == 0 else usb3_serdes[0].pll,
                tx_clk       = None if lane == 0 else usb3_serdes[0].gtp.cd_tx.clk,
                # Gen 1x2 (two Acorn Minis): RX electrical idle detection spikes after the partner
                # Polling LFPS bursts on some bitstream loads, rejected below the shortest LFPS burst.
                rx_idle_min_burst = 40e-9 if lanes == 2 else None)
            # TX post-cursor pre-emphasis (--tx-postcursor, UG482 TXPOSTCURSOR), per SFP cage. Gen 1x2:
            # a runtime control (tx_postcursor, reset to the --tx-postcursor value: USB3LanesDebug
            # lane{n}_tx_postcursor CSR, usb3_lanes.py tx-postcursor) for pre-emphasis sweeps.
            if lanes == 2:
                serdes.tx_postcursor = Signal(5, reset=tx_postcursor[cage] if tx_postcursor else 0)
                serdes.gtp.gtp_params.update(i_TXPOSTCURSOR=serdes.tx_postcursor)
                # Runtime TX differential swing (TXDIFFCTRL, reset: --tx-diffctrl) and forced TX
                # electrical idle (debug, Gen 1x2 Acorn <-> Tang: a lane transmitter disturbing the
                # others, t18): USB3LanesDebug lane{n}_tx_diffctrl/lane{n}_tx_idle_force CSRs.
                serdes.tx_diffctrl   = Signal(4, reset=tx_diffctrl[cage] if tx_diffctrl else 0b1100)
                serdes.tx_idle_force = Signal()
                serdes.gtp.gtp_params.update(
                    i_TXDIFFCTRL = serdes.tx_diffctrl,
                    i_TXELECIDLE = serdes.tx_idle | serdes.tx_idle_force)
            elif tx_postcursor is not None and tx_postcursor[0]:
                serdes.gtp.gtp_params.update(i_TXPOSTCURSOR=tx_postcursor[0])
            serdes.gtp.gtp_params.update(gtp_params) # Debug overrides (--gtp-param).
            usb3_serdes.append(serdes)
        # Fabric reference clock on GTGREFCLK0 (doc/manual: Transceivers): allowed as a warning.
        platform.add_platform_command("set_property SEVERITY {{Warning}} [get_drc_checks REQP-49]")

        # USB3 (PHY, Debug, Core, Leds) ------------------------------------------------------------
        leds = [platform.request("user_led", i) for i in range(3)]
        if lanes == 1:
            add_usb3_device(self, usb3_serdes[0],
                leds          = leds,
                leds_inverted = True,
                **usb3_kwargs)
        else:
            add_usb3_lanes_link(self, usb3_serdes,
                role          = role,
                x2_capable    = x2_capable,
                leds          = leds,
                leds_inverted = True,
                with_core     = lanes_core,
                example       = usb3_kwargs.get("example", "loopback"),
                with_lpm      = usb3_kwargs.get("with_lpm", False),
                max_burst     = usb3_kwargs.get("max_burst", 8))
        self.comb += platform.request("user_led", 3).eq(1) # Not Used.

        # FPGA temperature/voltages (RX quality vs temperature, bench/usb3_soak.py) ----------------
        if usb3_kwargs.get("with_serdes_debug", False):
            self.xadc = S7SystemMonitor()

        # GTP LPM adaptation hold (debug, --lpm-hold): adapt only in Polling.RxEQ, or never.
        if lpm_hold != "none":
            ltssm_state     = self.usb3_phy.ltssm_state
            ltssm_states    = self.usb3_phy.ltssm_states
            lpm_hold_signal = Signal()
            if lpm_hold == "rxeq":
                self.comb += lpm_hold_signal.eq(ltssm_state != ltssm_states["Polling.RxEQ"])
            else:
                self.comb += lpm_hold_signal.eq(1)
            for serdes in usb3_serdes:
                serdes.gtp.gtp_params.update(
                    i_RXLPMHFHOLD = lpm_hold_signal,
                    i_RXLPMLFHOLD = lpm_hold_signal,
                    i_RXOSHOLD    = lpm_hold_signal,
                )

        # Analyzer ---------------------------------------------------------------------------------
        if with_analyzer:
            self.analyzer = usb3_analyzer(self, analyzer_group, analyzer_csv)

# Build --------------------------------------------------------------------------------------------

def parse_tx_postcursor(value, lanes):
    """--tx-postcursor: one value for all the SFP cages or one per cage (SFP-0 first), default 6
    with --lanes 2, else 0. Returns one value per lane (SFP cage)."""
    if value is None:
        return [6 if lanes == 2 else 0]*lanes
    values = [int(v, 0) for v in str(value).split(",")]
    if len(values) == 1:
        values = values*lanes
    assert len(values) == lanes, f"--tx-postcursor: one value or {lanes} values ({value})."
    assert all(0 <= v < 32 for v in values), f"--tx-postcursor: 0 to 31 ({value})."
    return values

def parse_tx_diffctrl(value, lanes):
    """--tx-diffctrl (--lanes 2): one value for all the SFP cages or one per cage (SFP-0 first),
    default 15. Returns one value per lane (SFP cage)."""
    values = [15] if value is None else [int(v, 0) for v in str(value).split(",")]
    if len(values) == 1:
        values = values*lanes
    assert len(values) == lanes, f"--tx-diffctrl: one value or {lanes} values ({value})."
    assert all(0 <= v < 16 for v in values), f"--tx-diffctrl: 0 to 15 ({value})."
    return values

def main():
    parser = argparse.ArgumentParser(
        description="USB3-PIPE on the SQRL Acorn CLE-215+ (Artix7 GTP), LiteX Acorn Baseboard (Mini).")
    parser.add_argument("--variant",   default="mini",      help="LiteX Acorn Baseboard variant.", choices=["mini", "standard"])
    parser.add_argument("--with-dram", action="store_true", help="Enable the DDR3 SDRAM (requires a CPU, default with the msc_dram example).")
    usb3_soc_args(parser, output_dir="build/sqrl_acorn")
    gtp_group = parser.add_argument_group(title="GTP bring-up/debug overrides")
    gtp_group.add_argument("--rxcdr-cfg", default=None,   help="GTP RXCDR_CFG override (hex).")
    gtp_group.add_argument("--gtp-param", default=[],     help="GTP parameter override NAME=VALUE (ex: p_RXCDR_HOLD_DURING_EIDLE=1).", action="append")
    gtp_group.add_argument("--tx-postcursor", default=None, help="GTP TX post-cursor pre-emphasis (TXPOSTCURSOR 0-31), one value or one per SFP cage (ex: 6,10 for SFP-0/SFP-1; default: 6 with --lanes 2, else 0).")
    gtp_group.add_argument("--tx-diffctrl", default=None, help="--lanes 2: GTP TX differential swing (TXDIFFCTRL 0-15, runtime register reset value), one value or one per SFP cage (default: 15).")
    gtp_group.add_argument("--lpm-hold",  default=None,   help="GTP LPM adaptation hold (rxeq: adapt only in Polling.RxEQ; default: rxeq with --lanes 2, else none).", choices=["none", "rxeq", "always"])
    x2_group = parser.add_argument_group(title="Gen 1x2 (two lanes, SFP-0/SFP-1: two boards link tests with PRBS Link-Layer stand-ins, or dual SFP to USB-C breakout)")
    x2_group.add_argument("--lanes",      default=1, type=int, help="Lanes: 1 (Gen 1x1, SFP-0) or 2 (Gen 1x2, SFP-0/SFP-1, Mini only).", choices=[1, 2])
    x2_group.add_argument("--sfp",        default=0, type=int, help="SFP cage of Lane 0 (Mini): Gen 1x1 cage, or --lanes 2 with 1: Lane 0 (Configuration Lane, Gen 1x1 fallback) on SFP-1, Lane 1 on SFP-0.", choices=[0, 1])
    x2_group.add_argument("--role",       default="device",    help="USB3PHY role with --lanes 2 (one board in each role).", choices=["device", "host"])
    x2_group.add_argument("--no-x2",      action="store_true", help="--lanes 2: not Gen 1x2 capable (Gen 1x1 negotiated: single lane fallback on SFP-0).")
    x2_group.add_argument("--lanes-core", action="store_true", help="--lanes 2 instead of the PRBS stand-ins: Device: USB3 Device Core (--example; Gen 1x2 (SuperSpeedPlus) with loopback/wishbone/bench, Gen 1x1 otherwise); Host: scripted USB host (enumeration + Bulk loopback with data checks, for a Device running --example loopback).")
    args = parser.parse_args()

    # Gen 1x2: two SFPs (Mini), PRBS Link-Layer stand-ins, or the Device Core (--lanes-core).
    if args.lanes == 2:
        assert args.variant == "mini", "--lanes 2 requires the Mini (SFP-0/SFP-1)."
        assert not args.with_serdes_debug, "--lanes 2: --with-serdes-debug not supported."
        assert args.cpu_type is None and not args.with_dram, "--lanes 2: no CPU/DRAM."
        assert not (args.lanes_core and args.no_core), "--lanes-core: USB3 Device Core required."
    else:
        assert args.variant == "mini" or args.sfp == 0, "--sfp 1 requires the Mini."
        assert args.role == "device", "--role host requires --lanes 2."
        assert not args.no_x2, "--no-x2 requires --lanes 2."
        assert not args.lanes_core, "--lanes-core requires --lanes 2."
        assert args.tx_diffctrl is None, "--tx-diffctrl requires --lanes 2."

    # DRAM disk: DDR3 SDRAM, initialized by the BIOS (VexRiscv CPU by default, console on a stub
    # UART).
    with_dram = args.with_dram or (args.example == "msc_dram")
    if with_dram and args.cpu_type is None:
        args.cpu_type = "vexriscv"

    platform = sqrl_acorn.Platform(with_multiboot=False)
    if args.variant == "standard":
        platform.add_extension(_usb3_io_standard)
    if args.variant == "mini":
        platform.add_extension(_usb3_io_mini)
        platform.add_extension(sqrl_acorn._litex_acorn_baseboard_mini_io, prepend=True)
    soc = USB3SoC(platform,
        with_dram   = with_dram,
        rxcdr_cfg   = None if args.rxcdr_cfg is None else int(args.rxcdr_cfg, 0),
        gtp_params  = {k: int(v, 0) for k, v in (p.split("=") for p in args.gtp_param)},
        # Gen 1x2 (two Acorn Minis, SFP DAC cables): with the GTP LPM adapting continuously, the
        # receive quality of a lane changed from one bitstream load to the next (LFPS idle detection
        # spikes, millions of comma realignments, links never trained on some loads): adaptation
        # only on the partner's TSEQ (Polling.RxEQ), 400/400 runs on 20 loads at Gen 1x2 and 1x1.
        lpm_hold    = args.lpm_hold or ("rxeq" if args.lanes == 2 else "none"),
        # Gen 1x2 (two Acorn Minis, SFP DAC cables): the receivers fed by an SFP-1 transmitter were
        # the weak ones on both boards (millions of comma realignments on some loads, 759/1000
        # scripted runs on one cabling): TX post-cursor pre-emphasis 6 (~1.7dB), 998/1000.
        tx_postcursor = parse_tx_postcursor(args.tx_postcursor, args.lanes),
        # Gen 1x2 Acorn Host <-> Tang Mega 138K Pro (t19): with the swing at 12, ~85-90% of the Acorn
        # bitstream loads left the Tang receivers unlocked at x2 (both directions failing, no runtime
        # re-init recovering them); swing 15 trained every such load at once (17/17, 0 PRBS errors).
        tx_diffctrl   = parse_tx_diffctrl(args.tx_diffctrl, args.lanes) if args.lanes == 2 else None,
        lanes       = args.lanes,
        role        = args.role,
        x2_capable  = not args.no_x2,
        lanes_core  = args.lanes_core,
        sfp         = args.sfp,
        **usb3_soc_argdict(args))
    usb3_soc_build(parser, args, soc)

if __name__ == "__main__":
    main()
