#!/usr/bin/env python3

#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""USB3 Gen 1x2 link test client (bench/acorn.py --lanes 2: USB3PHYDebug, USB3LanesDebug and
PRBSLinkTester CSRs, through litex_server), one board per litex_server.

Two Acorn Baseboard Minis, SFP-0 <-> SFP-0 and SFP-1 <-> SFP-1 (SFP DAC cables), one board in each
role:
  ./bench/acorn.py --lanes 2 --role host   --with-jtagbone --output-dir build/acorn_x2_host   --build --load
  ./bench/acorn.py --lanes 2 --role device --with-jtagbone --output-dir build/acorn_x2_device --build --load

Examples (litex_server --jtag on ports 1234/1235, one per board):
  ./bench/usb3_lanes.py --port 1234 --csr-csv build/acorn_x2_host/csr.csv status
  ./bench/usb3_lanes.py --port 1235 --csr-csv build/acorn_x2_device/csr.csv retrain --wait 2
  ./bench/usb3_lanes.py --port 1235 --csr-csv build/acorn_x2_device/csr.csv prbs --duration 60
  ./bench/usb3_lanes.py --port 1235 --csr-csv build/acorn_x2_device/csr.csv watch

Gen 1x2 Device Core between the two boards (Host: scripted USB host, Device: loopback example):
  ./bench/acorn.py --lanes 2 --role host   --lanes-core --with-jtagbone --output-dir build/acorn_x2_host_script --build --load
  ./bench/acorn.py --lanes 2 --role device --lanes-core --example loopback --with-jtagbone --output-dir build/acorn_x2_device_core --build --load
  ./bench/usb3_lanes.py --port 1234 --csr-csv build/acorn_x2_host_script/csr.csv script --runs 100
"""

import json
import time
import argparse

from common import add_remote_args, open_remote # First: repository root on the path.

from usb3_debug import USB3DebugClient

LANES_COUNTERS = ["deskew"] + [f"lane{lane}_{name}" for lane in range(2)
    for name in ["ts1", "ts1_inv", "ts2", "rx_errors_cycles"]]

PRBS_COUNTERS = ["tx_words", "rx_words", "rx_packets", "rx_errors"]

PRBS_WORD_BYTES = {1: 8, 0: 4} # 64-bit link words (x2), 32-bit (Gen 1x1 negotiated, Lane 0).

# USB3 Lanes Client --------------------------------------------------------------------------------

class USB3LanesClient:
    def __init__(self, bus):
        self.bus = bus
        self.dbg = USB3DebugClient(bus)

    def reg(self, name):
        return getattr(self.bus.regs, name)

    def has_prbs(self):
        # PRBS Link-Layer stand-ins (not in the --lanes-core builds: USB3 Device Core instead).
        return hasattr(self.bus.regs, "usb3_prbs_control")

    def prbs(self):
        return {name: self.reg(f"usb3_prbs_{name}").read() for name in PRBS_COUNTERS}

    def status(self):
        dbg    = self.dbg.status()
        status = self.reg("usb3_lanes_debug_status").read()
        r = {
            "time_us"        : dbg["time_us"],
            "ltssm_state"    : dbg["ltssm_state"],
            "x2"             : (status >> 0) & 0x1,
            "gen2"           : (status >> 1) & 0x1,
            "deskew_aligned" : (status >> 2) & 0x1,
            "lane_swap"      : (status >> 3) & 0x1,
            "ready"          : [(status >> (4 + lane)) & 0x1 for lane in range(2)],
            "rx_idle"        : [(status >> (6 + lane)) & 0x1 for lane in range(2)],
            "rx_polarity"    : [(status >> (8 + lane)) & 0x1 for lane in range(2)],
            "rx_overflow"    : (status >> 10) & 0x1, # Link RX buffer (USB3PHYX2Link builds).
            "u0_count"       : dbg["u0"],
            "recovery_count" : dbg["recovery"],
        }
        r.update({name: self.reg(f"usb3_lanes_debug_{name}_count").read() for name in LANES_COUNTERS})
        # U0 exits requested by the lanes (Recovery causes) and lanes RX idle cycles in U0.
        for name in ["deskew_lost_u0", "lane_idle_u0", "realign_u0", "skp_odd_u0", "lane0_rx_idle_u0_cycles", "lane1_rx_idle_u0_cycles"] + [
            f"lane{lane}_{name}" for lane in range(2) for name in ["rx_buferror", "rx_realign", "rx_skp_odd", "rx_errors_reinit",
            "rx_idle_raw_u0_cycles"]]:
            if hasattr(self.bus.regs, f"usb3_lanes_debug_{name}_count"):
                r[name] = self.reg(f"usb3_lanes_debug_{name}_count").read()
        if hasattr(self.bus.regs, "usb3_lanes_debug_control"):
            control = self.reg("usb3_lanes_debug_control").read()
            r["idle_recovery"]    = (control >> 0) & 0x1
            r["rx_errors_reinit"] = (control >> 1) & 0x1
            r["realign_recovery"] = (control >> 2) & 0x1
            r["x2_enable"]        = (control >> 3) & 0x1
            r["skp_recovery"]     = (control >> 4) & 0x1
        if hasattr(self.bus.regs, "usb3_lanes_debug_rx_drop_count"):
            r["rx_drop"] = self.reg("usb3_lanes_debug_rx_drop_count").read()
        if self.has_prbs():
            r.update({f"prbs_{k}": v for k, v in self.prbs().items()})
        return r

    def clear(self):
        # PHY/lanes counters (the PRBS counters are free running, see PRBSLinkTester).
        self.dbg.clear()
        self.reg("usb3_lanes_debug_clear").write(1)

    def idle_recovery(self, enable=True):
        # Recovery on a lane in electrical idle in U0 at Gen 1x2 (debug: 0 disables).
        control = self.reg("usb3_lanes_debug_control").read()
        self.reg("usb3_lanes_debug_control").write((control & ~0x1) | int(enable))

    def rx_errors_reinit(self, enable=True):
        # RX re-initialization of a lane with continuous decode errors (debug: 0 disables).
        control = self.reg("usb3_lanes_debug_control").read()
        self.reg("usb3_lanes_debug_control").write((control & ~0x2) | (int(enable) << 1))

    def skp_recovery(self, enable=True):
        # Recovery on a lane SKP run of odd length in U0 at Gen 1x2 (debug: 0 disables, still counted).
        control = self.reg("usb3_lanes_debug_control").read()
        self.reg("usb3_lanes_debug_control").write((control & ~0x10) | (int(enable) << 4))

    def x2_enable(self, enable=True):
        # Gen 1x2 advertised in the SuperSpeedPlus Polling (0: Gen 1x1 only), from the next training.
        control = self.reg("usb3_lanes_debug_control").read()
        self.reg("usb3_lanes_debug_control").write((control & ~0x8) | (int(enable) << 3))

    def prbs_enable(self, enable=True):
        self.reg("usb3_prbs_control").write(int(enable))

def counters_delta(new, old):
    """32-bit wrapping counters differences."""
    return {k: (new[k] - old[k]) % 2**32 for k in new}

# Main ---------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="USB3 Gen 1x2 link test client.")
    add_remote_args(parser)
    parser.add_argument("--wait",     default=1.0,  type=float, help="Wait time (s) after retrain.")
    parser.add_argument("--period",   default=1.0,  type=float, help="watch/prbs polling period (s).")
    parser.add_argument("--duration", default=10.0, type=float, help="prbs: test duration (s).")
    parser.add_argument("--runs",     default=1,    type=int,   help="script: runs of the scripted host.")
    parser.add_argument("--timeout",  default=2.0,  type=float, help="script: run timeout (s).")
    parser.add_argument("command",    choices=["status", "clear", "retrain", "watch", "prbs",
        "prbs-enable", "prbs-disable", "script",
        "idle-recovery-enable", "idle-recovery-disable", "rx-reinit-enable", "rx-reinit-disable",
        "x2-enable", "x2-disable", "skp-recovery-enable", "skp-recovery-disable"])
    args = parser.parse_args()

    bus   = open_remote(args)
    lanes = USB3LanesClient(bus)

    if args.command == "status":
        print(json.dumps(lanes.status()))
    elif args.command == "clear":
        lanes.clear()
    elif args.command in ["idle-recovery-enable", "idle-recovery-disable"]:
        lanes.idle_recovery(args.command == "idle-recovery-enable")
    elif args.command in ["rx-reinit-enable", "rx-reinit-disable"]:
        lanes.rx_errors_reinit(args.command == "rx-reinit-enable")
    elif args.command in ["skp-recovery-enable", "skp-recovery-disable"]:
        lanes.skp_recovery(args.command == "skp-recovery-enable")
    elif args.command in ["x2-enable", "x2-disable"]:
        # Gen 1x2 capability advertised (x2-disable: Gen 1x1 negotiated), then retrain.
        lanes.x2_enable(args.command == "x2-enable")
        lanes.dbg.retrain()
        lanes.reg("usb3_lanes_debug_clear").write(1)
        time.sleep(args.wait)
        print(json.dumps(lanes.status()))
    elif args.command == "retrain":
        lanes.dbg.retrain()
        lanes.reg("usb3_lanes_debug_clear").write(1)
        time.sleep(args.wait)
        print(json.dumps(lanes.status()))
        count, entries = lanes.dbg.history()
        print(json.dumps({"transitions": count, "history": entries}))
    elif args.command == "watch":
        last = None
        try:
            while True:
                s   = lanes.status()
                key = {k: v for k, v in s.items() if (k != "time_us") and not k.startswith("prbs_")}
                if key != last:
                    print(json.dumps(s), flush=True)
                    last = key
                time.sleep(args.period)
        except KeyboardInterrupt:
            pass
    elif args.command.startswith("prbs") and not lanes.has_prbs():
        raise SystemExit("No PRBS Link-Layer stand-ins in this build (--lanes-core: USB3 Device Core).")
    elif args.command == "prbs":
        # PRBS packets rate/errors from the counters differences (polled faster than the 32-bit
        # counters wrap: ~34s for the words at 125M words/s).
        assert args.period <= 10.0
        start    = time.time()
        last     = lanes.prbs()
        total    = {k: 0 for k in last}
        recovery = lanes.dbg.status()["recovery"]
        x2       = lanes.status()["x2"]
        word_bytes = PRBS_WORD_BYTES[x2] # Counters of the negotiated mode.
        while time.time() - start < args.duration:
            time.sleep(args.period)
            t     = time.time()
            prbs  = lanes.prbs()
            delta = counters_delta(prbs, last)
            total = {k: total[k] + delta[k] for k in total}
            last  = prbs
            print(json.dumps({
                "time_s"       : round(t - start, 1),
                "tx_MBps"      : round(delta["tx_words"]*word_bytes/args.period/1e6, 1),
                "rx_MBps"      : round(delta["rx_words"]*word_bytes/args.period/1e6, 1),
                "rx_errors"    : delta["rx_errors"],
                "ltssm_state"  : lanes.dbg.status()["ltssm_state"],
            }), flush=True)
        elapsed = time.time() - start
        status  = lanes.status()
        print(json.dumps({
            "duration_s"   : round(elapsed, 1),
            "tx_bytes"     : total["tx_words"]*word_bytes,
            "rx_bytes"     : total["rx_words"]*word_bytes,
            "rx_packets"   : total["rx_packets"],
            "rx_errors"    : total["rx_errors"],
            "rx_MBps"      : round(total["rx_words"]*word_bytes/elapsed/1e6, 1),
            "recoveries"   : status["recovery_count"] - recovery,
            "x2"           : status["x2"],
        }))
    elif args.command == "script":
        # Scripted USB host (bench/acorn.py --lanes 2 --role host --lanes-core): runs of the
        # enumeration + Bulk loopback script (Bulk IN data checked), failing step and script section.
        from usb3_soc import usb3_host_script
        from usb3_core.host_model import OP_MARK
        assert hasattr(bus.regs, "usb3_script_control"), "No scripted host in this build (--role host --lanes-core)."
        # Both scripts in the scripted host ROM (SuperSpeedPlus, then SuperSpeed from ss_start), or a
        # single one in older builds (usb3_script_ssp: its kind).
        if hasattr(bus.regs, "usb3_script_ss_start"):
            ss_start = lanes.reg("usb3_script_ss_start").read()
        else:
            ss = hasattr(bus.regs, "usb3_script_ssp") and not lanes.reg("usb3_script_ssp").read()
            ss_start = 0 if ss else 2**32
        scripts = {True: usb3_host_script(ssp=True), False: usb3_host_script(ssp=False)}
        def section(step):
            ssp    = step < ss_start
            script = scripts[ssp]
            name   = "start"
            for i, s in enumerate(script.steps[:(step if ssp else step - ss_start) + 1]):
                if s[0] == OP_MARK:
                    name = script.marks[s[1]]
            return name if ssp else f"ss:{name}"
        results = {"done": 0, "error": 0, "timeout": 0}
        for run in range(args.runs):
            # Run restart (enable 0 -> 1), the other control bits kept (idle_init).
            control = lanes.reg("usb3_script_control").read()
            lanes.reg("usb3_script_control").write(control & ~1)
            lanes.reg("usb3_script_control").write(control | 1)
            start = time.time()
            last  = 0 # Last step seen (the step is reset with the model when the link leaves U0).
            while True:
                step   = lanes.reg("usb3_script_step").read()
                status = lanes.reg("usb3_script_status").read()
                last   = step if step else last
                if status & 0b011:
                    result = "done" if (status & 0b001) else "error"
                    step   = lanes.reg("usb3_script_step").read() or last
                    break
                if time.time() - start > args.timeout:
                    result = "timeout" # Script not done (ex: link not in U0).
                    break
            results[result] += 1
            print(json.dumps({"run": run, "result": result, "step": step, "section": section(step),
                "time_ms": round(1e3*(time.time() - start), 1)}), flush=True)
        lanes.reg("usb3_script_control").write(lanes.reg("usb3_script_control").read() & ~1)
        status = lanes.status()
        resets = {"resets_csr": lanes.reg("usb3_script_resets").read()} if hasattr(bus.regs, "usb3_script_resets") else {}
        if hasattr(bus.regs, "usb3_script_ss_start"):
            resets["ssp"] = lanes.reg("usb3_script_ssp").read() # Script of the last run.
        print(json.dumps({**results, "passes_csr": lanes.reg("usb3_script_passes").read(),
            "fails_csr": lanes.reg("usb3_script_fails").read(), **resets, "x2": status["x2"],
            "lane_swap": status["lane_swap"], "recovery_count": status["recovery_count"],
            "rx_overflow": status["rx_overflow"]}))
    elif args.command == "prbs-enable":
        lanes.prbs_enable(True)
    elif args.command == "prbs-disable":
        lanes.prbs_enable(False)

    bus.close()

if __name__ == "__main__":
    main()
