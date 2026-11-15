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

With --reinit-until-clean N, each load first checks its transceivers start-up draw (the line noise
of a Gen 1x2 load is drawn at the transceivers start-up, doc/gen1x2-hardware-validation.md t12): a
check burst of --check-runs scripted host runs, clean when the scripted host resets and the RX disparity
errors per reset of every lane are under --clean-resets/--clean-disparity; else both boards
transceivers re-initialized (`usb3_lanes.py xcvr-reinit`, Device then Host) and checked again, up to
N times (the first clean draw kept, or the last one). The draws (check results, transceivers status,
optional DRP dumps: --drp-addrs) are in the load results (`draws`).

A load is bad when no run was done (link down) or on an error (ex: a board reconfigured from its
flash during the runs): reported apart from the runs done on the good loads.
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
CORE_CAUSES   = ["hp_seq", "lgood", "lcrd", "pending_hp", "credit_hp"] # usb3_core_recovery_cause counts 1-5.

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

def ident(port, csr_csv):
    """SoC identifier (bitstream build date): a board reconfigured from its flash (power glitch)
    answers with another design (CSR reads then meaningless)."""
    code, out = run(["litex_cli", "--port", str(port), "--csr-csv", csr_csv, "--ident"], timeout=10)
    return out.strip().splitlines()[-1].strip() if (code == 0 and out.strip()) else None

def port_resets(port, csr_csv):
    """Host port reset policy Warm Resets count (bench/usb3_soc.py USB3HostPortReset), None without."""
    from litex import RemoteClient
    try:
        bus = RemoteClient(port=port, csr_csv=csr_csv)
        bus.open()
    except Exception:
        return None
    count = bus.regs.usb3_port_reset_count.read() if hasattr(bus.regs, "usb3_port_reset_count") else None
    bus.close()
    return count

def script_resets(port, csr_csv):
    """Scripted host resets count (usb3_script_resets: one Hot Reset per run on a clean link, more on
    a noisy one), None without."""
    from litex import RemoteClient
    try:
        bus = RemoteClient(port=port, csr_csv=csr_csv)
        bus.open()
    except Exception:
        return None
    count = bus.regs.usb3_script_resets.read() if hasattr(bus.regs, "usb3_script_resets") else None
    bus.close()
    return count

def x1_retrain(boards):
    """Gen 1x2 not advertised on both boards (usb3_lanes_debug_control x2_enable = 0), both PHYs
    retrained together: Gen 1x1 negotiated, with the same bitstreams."""
    from litex import RemoteClient
    buses = [RemoteClient(port=port, csr_csv=csr_csv) for port, csr_csv in boards]
    for bus in buses:
        bus.open()
        control = bus.regs.usb3_lanes_debug_control.read()
        bus.regs.usb3_lanes_debug_control.write(control & ~0x8)
    for bus in buses: bus.regs.usb3_debug_phy_reset.write(1)
    for bus in buses: bus.regs.usb3_debug_clear.write(1)
    for bus in buses[::-1]: bus.regs.usb3_debug_phy_reset.write(0)
    for bus in buses: bus.close()

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
        reg   = bus.regs.usb3_core_recovery_cause
        cause = reg.read()
        # 16-bit counts (3 CSR words), 8-bit counts on older bitstreams (2 CSR words).
        w = 16 if getattr(reg, "length", 3) >= 3 else 8
        r.update({c: (cause >> (w*(i + 1))) & (2**w - 1) for i, c in enumerate(CORE_CAUSES)})
    bus.close()
    return r

def lanes_status(lanes, args):
    return last_json(run(lanes + args + ["status"], timeout=30)[1]) or {}

def wait_u0_x2(lanes, host_args, dev_args, timeout=3.0):
    """Both boards in U0 at Gen 1x2 within timeout (s), else both retrained once; True when in U0 x2."""
    def ok():
        h, d = lanes_status(lanes, host_args), lanes_status(lanes, dev_args)
        return all(x.get("ltssm_state") == "U0" and x.get("x2") == 1 for x in [h, d])
    start = time.time()
    while time.time() - start < timeout:
        if ok():
            return True
        time.sleep(0.2)
    run(lanes + dev_args  + ["retrain"], timeout=30)
    run(lanes + host_args + ["retrain"], timeout=30)
    time.sleep(1.0)
    return ok()

def check_draw(lanes, host_args, dev_args, host_port, host_csr, check_runs, drp_addrs=None):
    """Transceivers start-up draw check: check_runs scripted host runs, Host port resets and RX
    disparity errors per reset per lane (both boards), transceivers status (and DRP dumps)."""
    run(lanes + host_args + ["clear"])
    run(lanes + dev_args  + ["clear"])
    before = script_resets(host_port, host_csr) or 0
    code, output = run(lanes + host_args + ["script", "--runs", str(check_runs)])
    lines  = [json.loads(l) for l in output.splitlines() if l.startswith("{")]
    resets = (script_resets(host_port, host_csr) or 0) - before
    status = {"host": lanes_status(lanes, host_args), "device": lanes_status(lanes, dev_args)}
    r = {"done": lines[-1].get("done", 0) if lines else 0, "resets": resets, "disparity_per_reset": {},
        "xcvr": {side: status[side].get("xcvr") for side in status}}
    for side in status:
        for lane in range(2):
            r["disparity_per_reset"][f"{side}{lane}"] = (
                status[side].get(f"lane{lane}_rx_disparity_errors", 0)/max(resets, 1))
        r[f"{side}_recovery_count"] = status[side].get("recovery_count")
    if drp_addrs:
        for side, args in [("host", host_args), ("device", dev_args)]:
            r.setdefault("drp", {})[side] = last_json(run(lanes + args + ["drp-dump", "--addrs", drp_addrs],
                timeout=300)[1])
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

def summary(loads):
    def median(values):
        return statistics.median(values) if values else None
    def is_bad(d):
        # Load without any run done (link down: PHY level) or with an error (ex: a board
        # reconfigured during the runs).
        return ("error" in d) or (d.get("script", {}).get("done", 0) == 0)
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
        for k in ["recovery_count", "deskew_lost_u0", "realign_u0", "skp_odd_u0", "com_slip", "lane0_rx_realign",
            "lane1_rx_realign", "lane0_rx_skp_odd", "lane1_rx_skp_odd", "lane0_rx_com_partial", "lane1_rx_com_partial"] + [
            f"lane{lane}_{name}" for lane in range(2) for name in ["rx_decode_errors", "rx_disparity_errors",
            "rx_com_decode_errors", "rx_com_disparity_errors"]]:
            r[f"{side}_{k}_median"] = median([d[side][k] for d in good if k in d[side]])
    draws = [d for d in good if "draws" in d]
    if draws:
        r["draws_loads_clean"]   = f"{sum(d['draws'][-1]['clean'] for d in draws)}/{len(draws)}"
        r["draws_first_clean"]   = f"{sum(d['draws'][0]['clean'] for d in draws)}/{len(draws)}"
        r["draws_reinits_median"] = median([len(d["draws"]) - 1 for d in draws])
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
    parser.add_argument("--x1",              action="store_true", help="Gen 1x1: Gen 1x2 not advertised on both boards after each load (runtime control), both retrained.")
    parser.add_argument("--reinit-until-clean", default=0,   type=int, help="Transceivers start-up draws: up to N re-initializations of both boards per load until a clean check (0: disabled).")
    parser.add_argument("--check-runs",      default=5,      type=int, help="--reinit-until-clean: scripted host runs per check.")
    parser.add_argument("--clean-resets",    default=1.5,    type=float, help="--reinit-until-clean: max scripted host resets (usb3_script_resets) per check run of a clean draw.")
    parser.add_argument("--clean-disparity", default=25,     type=float, help="--reinit-until-clean: max RX disparity errors per reset on every lane of a clean draw (t13: clean draws <= 12, noisy >= 34).")
    parser.add_argument("--drp-addrs",       default=None,   help="--reinit-until-clean: transceivers DRP addresses dumped per draw (usb3_lanes.py drp-dump --addrs).")
    parser.add_argument("--settle",          default=2.0,    type=float, help="Time (s) after the servers start.")
    parser.add_argument("--out",             default=None,   help="Results (JSON lines, appended; default: build/hw_runs/<time>/loads.jsonl).")
    parser.add_argument("--summary",         default=None,   help="Only print the summary of a results file.")
    args = parser.parse_args()

    if args.summary:
        print(json.dumps(summary([json.loads(l) for l in open(args.summary)]), indent=2))
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
                if args.x1:
                    x1_retrain([(args.host_port, host_csr), (args.device_port, device_csr)])
                    time.sleep(args.settle)
                idents = [ident(args.host_port, host_csr), ident(args.device_port, device_csr)]
                if args.reinit_until_clean:
                    r["draws"] = []
                    for draw in range(args.reinit_until_clean + 1):
                        if draw:
                            run(lanes + dev_args  + ["xcvr-reinit", "--wait", "0"])
                            run(lanes + host_args + ["xcvr-reinit", "--wait", "0"])
                        d = {"draw": draw, "u0_x2": wait_u0_x2(lanes, host_args, dev_args)}
                        d.update(check_draw(lanes, host_args, dev_args, args.host_port, host_csr,
                            args.check_runs, args.drp_addrs))
                        d["clean"] = (d["u0_x2"] and d["done"] == args.check_runs and
                            d["resets"] <= args.clean_resets*args.check_runs and
                            max(d["disparity_per_reset"].values()) <= args.clean_disparity)
                        r["draws"].append(d)
                        print(f"load {load} draw {draw}: clean {int(d['clean'])} resets {d['resets']} "
                            f"disparity/reset {json.dumps({k: round(v, 1) for k, v in d['disparity_per_reset'].items()})}",
                            flush=True)
                        if d["clean"]:
                            break
                run(lanes + host_args + ["clear"])
                run(lanes + dev_args  + ["clear"])
                before = core_counters(args.device_port, device_csr)
                r["script_resets_before"] = script_resets(args.host_port, host_csr)
                code, output = run(lanes + host_args + ["script", "--runs", str(args.runs)])
                after  = core_counters(args.device_port, device_csr)
                lines  = [json.loads(l) for l in output.splitlines() if l.startswith("{")]
                r["script"] = lines[-1] if lines else {"done": 0, "output": output[-500:]}
                r["fail_sections"] = {}
                r["fails"] = [] # (run, result, step, section) of the failed runs.
                for l in lines[:-1]:
                    if l.get("result") in ["error", "timeout"]:
                        r["fail_sections"][l["section"]] = r["fail_sections"].get(l["section"], 0) + 1
                        r["fails"].append((l["run"], l["result"], l["step"], l["section"]))
                r["ident"] = {"host": idents[0], "device": idents[1]}
                r["port_resets"] = port_resets(args.host_port, host_csr)
                if [ident(args.host_port, host_csr), ident(args.device_port, device_csr)] != idents:
                    # A board no longer runs the loaded bitstream (reconfigured from its flash):
                    # its counters/runs results are not valid.
                    r["error"] = "board reconfigured during the runs"
                r["host"]   = last_json(run(lanes + host_args + ["status"])[1]) or {}
                r["device"] = last_json(run(lanes + dev_args  + ["status"])[1]) or {}
                r["core"]   = {"before": before, "after": after,
                    "runs": {k: (after[k] - before[k]) for k in after} if (before and after) else None}
            results.append(r)
            with open(out, "a") as f:
                f.write(json.dumps(r) + "\n")
            print(f"load {load}: " + (f"ERROR {r['error']}: " if "error" in r else "") +
                json.dumps(r.get("script", r.get("error"))) +
                (f" port resets: {r['port_resets']}" if r.get("port_resets") is not None else "") +
                (f" core runs: {json.dumps(r['core']['runs'])}" if r.get("core", {}).get("runs") else ""), flush=True)
    finally:
        servers.stop()
        print(f"results: {out} (litex_servers stopped)", flush=True)
    print(json.dumps(summary(results), indent=2))

if __name__ == "__main__":
    main()
