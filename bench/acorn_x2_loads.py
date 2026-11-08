#!/usr/bin/env python3

#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Gen 1x2 Device Core pair on two Acorn Minis: bitstream loads x scripted host runs, per load
results (JSON lines) and a summary. The behavior of a Gen 1x2 build depends on the bitstream load
(and on the build: compare two builds of the same source before crediting a change): ~20 loads
per build.

On each load: both boards loaded (Device first), litex_servers (re)started, PHY/lanes counters
cleared, Device Core counters read before and after the runs (deltas: Recoveries during the runs),
`usb3_lanes.py script --runs N` on the Host, PHY/lanes status of both boards.

  ./bench/acorn_x2_loads.py --host-build build/acorn_x2_host_script --device-build build/acorn_x2_device_core \\
      --loads 20 --runs 20 --out build/hw_runs/my_change/loads.jsonl
  ./bench/acorn_x2_loads.py --summary build/hw_runs/my_change/loads.jsonl

A load is bad when the Host lanes flap (recovery_count > --bad-recoveries): PHY level, reported
apart from the runs done on the good loads.
"""

import os
import sys
import json
import time
import argparse
import statistics
import subprocess

from common import ROOT # First: repository root on the path.

BENCH = os.path.join(ROOT, "bench")

CORE_COUNTERS = ["recovery_req", "rx_lbad", "tx_retry", "rx_errors"]
CORE_CAUSES   = ["hp_seq", "lgood", "lcrd", "pending_hp", "credit_hp"] # usb3_core_recovery_cause bytes 1-5.

# Helpers ------------------------------------------------------------------------------------------

def run(cmd, timeout=None):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    return r.returncode, r.stdout

def last_json(out):
    for line in reversed(out.strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            pass
    return None

def core_counters(port, csr_csv):
    """Device Core counters (8-bit saturating Recovery causes decoded), None if not reachable."""
    from litex import RemoteClient
    try:
        bus = RemoteClient(port=port, csr_csv=csr_csv)
        bus.open()
    except Exception:
        return None
    r = {}
    for name in CORE_COUNTERS:
        if hasattr(bus.regs, f"usb3_core_{name}"):
            r[name] = getattr(bus.regs, f"usb3_core_{name}").read()
    if hasattr(bus.regs, "usb3_core_recovery_cause"):
        cause = bus.regs.usb3_core_recovery_cause.read()
        r.update({c: (cause >> (8*(i + 1))) & 0xff for i, c in enumerate(CORE_CAUSES)})
    bus.close()
    return r

class Servers:
    """litex_servers of the two boards (bench/acorn_ftdi.py server)."""
    def __init__(self, boards, log):
        self.boards = boards # [(location, port, csr_csv)].
        self.log    = log
        self.procs  = []

    def stop(self):
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        self.procs = []
        # Servers started outside this script on the same ports (and their OpenOCDs).
        for location, port, csr_csv in self.boards:
            subprocess.run(["pkill", "-f", f"litex_server.*--bind-port {port}"])
            subprocess.run(["pkill", "-f", f"jtagstream_serve.*{port + 18800}"])
        time.sleep(1)

    def start(self, timeout=30):
        for location, port, csr_csv in self.boards:
            self.procs.append(subprocess.Popen([sys.executable, os.path.join(BENCH, "acorn_ftdi.py"),
                "--location", location, "server", "--port", str(port)],
                stdout=self.log, stderr=subprocess.STDOUT))
        start = time.time()
        while time.time() - start < timeout:
            if all(run(["litex_cli", "--port", str(port), "--csr-csv", csr_csv, "--ident"], timeout=10)[0] == 0
                for location, port, csr_csv in self.boards):
                return True
            time.sleep(1)
        return False

# Summary ------------------------------------------------------------------------------------------

def summary(loads, bad_recoveries=500):
    def median(values):
        return statistics.median(values) if values else None
    def is_bad(d):
        return ("error" in d) or (d["host"].get("recovery_count", 0) > bad_recoveries)
    good = [d for d in loads if not is_bad(d)]
    bad  = [d["load"] for d in loads if is_bad(d)]
    runs = sum(d["runs"] for d in loads if "runs" in d)
    sections = {}
    for d in loads:
        for k, v in d.get("fail_sections", {}).items():
            sections[k] = sections.get(k, 0) + v
    r = {
        "loads"                 : len(loads),
        "bad_loads"             : bad,
        "runs_done"             : f"{sum(d['script']['done'] for d in loads if 'script' in d)}/{runs}",
        "runs_done_good_loads"  : f"{sum(d['script']['done'] for d in good)}/{sum(d['runs'] for d in good)}",
        "fail_sections"         : sections,
    }
    for side in ["host", "device"]:
        for k in ["recovery_count", "deskew_lost_u0", "realign_u0", "lane0_rx_realign", "lane1_rx_realign"]:
            r[f"{side}_{k}_median"] = median([d[side][k] for d in good if k in d[side]])
    for k in CORE_COUNTERS + CORE_CAUSES:
        for when in ["before", "runs"]:
            values = [d["core"][when][k] for d in good if d.get("core", {}).get(when) and k in d["core"][when]]
            r[f"core_{k}_{when}_median"] = median(values)
    return r

# Main ---------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host-build",      default="build/acorn_x2_host_script", help="Host (scripted host) build directory.")
    parser.add_argument("--device-build",    default="build/acorn_x2_device_core", help="Device (Device Core) build directory.")
    parser.add_argument("--host-location",   default="1-3",  help="Host board FTDI location (acorn_ftdi.py list).")
    parser.add_argument("--device-location", default="1-5",  help="Device board FTDI location.")
    parser.add_argument("--host-port",       default=1240,   type=int, help="Host litex_server port.")
    parser.add_argument("--device-port",     default=1241,   type=int, help="Device litex_server port.")
    parser.add_argument("--loads",           default=20,     type=int, help="Bitstream loads.")
    parser.add_argument("--runs",            default=20,     type=int, help="Scripted host runs per load.")
    parser.add_argument("--settle",          default=2.0,    type=float, help="Time (s) after the servers start.")
    parser.add_argument("--bad-recoveries",  default=500,    type=int, help="Host recovery_count of a bad load (summary).")
    parser.add_argument("--out",             default=None,   help="Results (JSON lines, appended; default: build/hw_runs/<time>/loads.jsonl).")
    parser.add_argument("--summary",         default=None,   help="Only print the summary of a results file.")
    args = parser.parse_args()

    if args.summary:
        print(json.dumps(summary([json.loads(l) for l in open(args.summary)], args.bad_recoveries), indent=2))
        return

    out = args.out or os.path.join("build", "hw_runs", time.strftime("%Y%m%d-%H%M%S"), "loads.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    log = open(os.path.join(os.path.dirname(out), "servers.log"), "a")
    host_csr   = os.path.join(args.host_build,   "csr.csv")
    device_csr = os.path.join(args.device_build, "csr.csv")
    lanes      = [sys.executable, os.path.join(BENCH, "usb3_lanes.py")]
    host_args  = ["--port", str(args.host_port),   "--csr-csv", host_csr]
    dev_args   = ["--port", str(args.device_port), "--csr-csv", device_csr]
    servers = Servers([(args.host_location, args.host_port, host_csr),
        (args.device_location, args.device_port, device_csr)], log)

    results = []
    try:
        for load in range(1, args.loads + 1):
            r = {"load": load, "runs": args.runs}
            servers.stop()
            for name, location, build in [("device", args.device_location, args.device_build),
                                          ("host",   args.host_location,   args.host_build)]:
                code, output = run([sys.executable, os.path.join(BENCH, "acorn_ftdi.py"), "--location", location,
                    "load", os.path.join(build, "gateware", "sqrl_acorn.bit")])
                log.write(output)
                if code:
                    r["error"] = f"{name} load"
                    break
            if "error" not in r and not servers.start():
                r["error"] = "servers"
            if "error" not in r:
                time.sleep(args.settle)
                run(lanes + host_args + ["clear"])
                run(lanes + dev_args  + ["clear"])
                before = core_counters(args.device_port, device_csr)
                code, output = run(lanes + host_args + ["script", "--runs", str(args.runs)])
                after  = core_counters(args.device_port, device_csr)
                lines  = [json.loads(l) for l in output.splitlines() if l.startswith("{")]
                r["script"] = lines[-1] if lines else {"done": 0, "output": output[-500:]}
                r["fail_sections"] = {}
                for l in lines[:-1]:
                    if l.get("result") in ["error", "timeout"]:
                        r["fail_sections"][l["section"]] = r["fail_sections"].get(l["section"], 0) + 1
                r["host"]   = last_json(run(lanes + host_args + ["status"])[1]) or {}
                r["device"] = last_json(run(lanes + dev_args  + ["status"])[1]) or {}
                r["core"]   = {"before": before, "after": after,
                    "runs": {k: (after[k] - before[k]) for k in after} if (before and after) else None}
            results.append(r)
            with open(out, "a") as f:
                f.write(json.dumps(r) + "\n")
            print(f"load {load}: " + json.dumps(r.get("script", r.get("error"))) +
                (f" core runs: {json.dumps(r['core']['runs'])}" if r.get("core", {}).get("runs") else ""), flush=True)
    finally:
        servers.stop()
        print(f"results: {out} (litex_servers stopped)", flush=True)
    print(json.dumps(summary(results, args.bad_recoveries), indent=2))

if __name__ == "__main__":
    main()
