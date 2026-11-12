#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Targets (bench/) elaborations (no bitstream build): each target with each USB3 Device Core
example it supports, and debug/analyzer configurations.

The software (BIOS) is not compiled (CPU examples: no RISC-V toolchain needed): the targets are run
with LiteX's Builder compile_software defaulting to False.
"""

import re
import sys
import subprocess

from pathlib import Path

import pytest

from usb3_core.examples import USB3_EXAMPLES

ROOT = Path(__file__).resolve().parents[1]

# Helpers ------------------------------------------------------------------------------------------

RUN_TARGET = """
import os, sys, runpy
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[1]))) # As when run directly (bench/).
import litex.soc.integration.builder as builder
class Builder(builder.Builder):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("compile_software", False)
        super().__init__(*args, **kwargs)
builder.Builder = Builder
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""

def elaborate(target, output_dir, args=[]):
    """Elaborate target (gateware/software generation, no build) into output_dir, return csr.csv."""
    cmd = [sys.executable, "-c", RUN_TARGET, f"bench/{target}.py",
        "--output-dir", str(output_dir)] + args
    p = subprocess.run(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True)
    assert p.returncode == 0, p.stdout[-4000:]
    assert list((output_dir / "gateware").glob("*.v")), p.stdout[-4000:]
    return (output_dir / "csr.csv").read_text()

# Targets x Examples -------------------------------------------------------------------------------

TARGETS = ["acorn", "kc705", "alibaba_xcku3p"]

CPU_EXAMPLES  = ["console", "composite"] # Require a CPU.
DRAM_EXAMPLES = ["msc_dram"]             # Require a DRAM controller (Acorn only).

def target_examples():
    for target in TARGETS:
        for example in USB3_EXAMPLES:
            if example in DRAM_EXAMPLES and target != "acorn":
                continue
            yield target, example

@pytest.mark.parametrize("target, example", list(target_examples()))
def test_target_example(target, example, tmp_path):
    args = ["--example", example]
    if example in CPU_EXAMPLES:
        args += ["--cpu-type", "vexriscv"]
    csr = elaborate(target, tmp_path, args)
    assert "usb3" in csr

# Debug/Analyzer -----------------------------------------------------------------------------------

DEBUG_ARGS = {
    "acorn_jtagbone_serdes_debug" : ("acorn", ["--no-core", "--with-jtagbone", "--with-serdes-debug"]),
    "acorn_analyzer_lfps"         : ("acorn", ["--no-core", "--with-analyzer", "--analyzer-group", "lfps"]),
    "acorn_analyzer_datapath"     : ("acorn", ["--no-core", "--with-analyzer", "--analyzer-group", "datapath"]),
    "acorn_analyzer_phase"        : ("acorn", ["--no-core", "--with-serdes-debug", "--with-analyzer",
        "--analyzer-group", "phase", "--lpm-hold", "rxeq", "--gtp-param", "p_RXCDR_HOLD_DURING_EIDLE=1"]),
    "kc705_analyzer_ts"           : ("kc705", ["--with-analyzer", "--analyzer-group", "ts", "--with-lpm"]),
    "alibaba_xcku3p_analyzer_phase" : ("alibaba_xcku3p", ["--no-core", "--with-serdes-debug",
        "--with-analyzer", "--analyzer-group", "phase"]),
}

@pytest.mark.parametrize("name", list(DEBUG_ARGS))
def test_target_debug(name, tmp_path):
    # Targets elaborate with the USB3PHY + debug + analyzer groups (no Vivado).
    target, args = DEBUG_ARGS[name]
    csr = elaborate(target, tmp_path, args)
    assert "usb3_debug_history_count" in csr
    assert "usb3_debug_serdes_rx_reset" in csr
    if "--with-serdes-debug" in args:
        for name in ["usb3_serdes_debug_drp_sel", "usb3_serdes_debug_drp_addr",
                     "usb3_serdes_debug_tx_inhibit_state"]:
            assert name in csr
    if "--with-analyzer" in args:
        assert "analyzer_trigger_enable" in csr
        assert (tmp_path / "analyzer.csv").exists()

# Gen 1x2 Link Tests (two boards) ------------------------------------------------------------------

LANES_ARGS = {
    "acorn_x2_device"          : ["--lanes", "2", "--role", "device"],
    "acorn_x2_host"            : ["--lanes", "2", "--role", "host", "--with-jtagbone"],
    "acorn_x2_analyzer_link"   : ["--lanes", "2", "--with-analyzer", "--analyzer-group", "link",
        "--lpm-hold", "rxeq"],
    "acorn_x2_no_x2"           : ["--lanes", "2", "--no-x2"],
}

@pytest.mark.parametrize("name", list(LANES_ARGS))
def test_target_lanes(name, tmp_path):
    # Acorn Mini Gen 1x2 (SFP-0/SFP-1): USB3PHY(lanes=2) + debug + PRBS Link-Layer stand-ins, one
    # Quad PLL and the Lane 0 TX clock shared by both lanes.
    csr = elaborate("acorn", tmp_path, LANES_ARGS[name])
    for csr_name in ["usb3_debug_history_count", "usb3_lanes_debug_status",
        "usb3_lanes_debug_deskew_count", "usb3_lanes_debug_lane1_ts1_count", "usb3_prbs_control",
        "usb3_prbs_rx_errors"]:
        assert csr_name in csr
    verilog = next((tmp_path / "gateware").glob("*.v")).read_text()
    assert verilog.count("\nGTPE2_COMMON ") == 1
    assert verilog.count("\nGTPE2_CHANNEL ") == 2
    tx_clks = set(re.findall(r"\.TXUSRCLK\s*\((\w+)\)", verilog))
    assert len(tx_clks) == 1

LANES_CORE_EXAMPLES = [e for e in USB3_EXAMPLES if e not in CPU_EXAMPLES + DRAM_EXAMPLES]

@pytest.mark.parametrize("example", LANES_CORE_EXAMPLES)
def test_target_lanes_core(example, tmp_path):
    # Acorn Mini, Gen 1x2 PHY with the USB3 Device Core (USB3PHYX2Link: Gen 1x2 with the 64-bit
    # endpoints examples, USB3PHYX1Link: Gen 1x1 otherwise): the core CSRs, no PRBS stand-ins, both
    # lanes.
    csr = elaborate("acorn", tmp_path, ["--lanes", "2", "--lanes-core", "--example", example])
    assert "usb3_lanes_debug_status" in csr
    assert "usb3_prbs" not in csr
    if example in ["loopback", "bench"]:
        for csr_name in ["usb3_core_status", "usb3_core_link_state"]:
            assert csr_name in csr
    # USB3PHYX2Link (64-bit endpoints examples): RX buffer drops counter.
    assert ("usb3_lanes_debug_rx_drop_count" in csr) == (example in ["loopback", "wishbone", "bench"])
    verilog = next((tmp_path / "gateware").glob("*.v")).read_text()
    assert verilog.count("\nGTPE2_CHANNEL ") == 2

def test_target_lanes_host_script(tmp_path):
    # Acorn Mini, Gen 1x2 PHY in the Host role with the scripted USB host (USB3HostScript on a
    # USB3PHYX2Link): the script CSRs, no PRBS stand-ins, both lanes.
    csr = elaborate("acorn", tmp_path, ["--lanes", "2", "--role", "host", "--lanes-core"])
    for csr_name in ["usb3_script_control", "usb3_script_status", "usb3_script_step",
        "usb3_script_passes", "usb3_script_fails", "usb3_lanes_debug_rx_drop_count",
        "usb3_script_ss_start", "usb3_script_ssp", "usb3_port_reset_count",
        "usb3_lanes_debug_control"]:
        assert csr_name in csr
    assert "usb3_prbs" not in csr
    verilog = next((tmp_path / "gateware").glob("*.v")).read_text()
    assert verilog.count("\nGTPE2_CHANNEL ") == 2

def test_target_lanes_host_script_ss(tmp_path):
    # Scripted host not x2 capable: SuperSpeed script (Gen 1x1 negotiated with the Device).
    csr = elaborate("acorn", tmp_path, ["--lanes", "2", "--role", "host", "--lanes-core", "--no-x2"])
    assert "usb3_script_ssp" in csr

def test_target_lanes_host_script_analyzer(tmp_path):
    # Scripted host with the realign LiteScope group: lanes Recovery triggers and both lanes SerDes RX
    # status probes (usb3_analyzer.py --trigger lanes_realign).
    elaborate("acorn", tmp_path, ["--lanes", "2", "--role", "host", "--lanes-core", "--with-jtagbone",
        "--with-analyzer", "--analyzer-group", "realign"])
    probes = [l.split(",")[2] for l in (tmp_path / "analyzer.csv").read_text().splitlines()
        if l.startswith("signal,")]
    for name in ["lanes_realign", "lanes_deskew_lost", "lanes_idle"]:
        assert any(re.search(rf"_{name}\d*$", p) for p in probes), name
    for name in ["rx_realign", "rx_errors", "rx_idle"]:
        assert sum(bool(re.search(rf"_{name}\d*$", p)) for p in probes) >= 2, name

@pytest.mark.parametrize("args, postcursor", [
    ([],                                    0),  # Gen 1x1: no pre-emphasis (unchanged).
    (["--lanes", "2"],                      6),  # Gen 1x2 default.
    (["--lanes", "2", "--tx-postcursor", "0"], 0),
    (["--tx-postcursor", "10"],             10),
])
def test_target_tx_postcursor(args, postcursor, tmp_path):
    # GTP TX post-cursor pre-emphasis (--tx-postcursor, default 6 with --lanes 2) on every GTP.
    elaborate("acorn", tmp_path, args)
    verilog = next((tmp_path / "gateware").glob("*.v")).read_text()
    values  = re.findall(r"\.TXPOSTCURSOR\s*\(([^)]*)\)", verilog)
    assert values, "TXPOSTCURSOR not found"
    for v in values:
        assert int(v.split("'d")[-1] if "'d" in v else v.split("'b")[-1], 10 if "'d" in v else 2) == postcursor, v

def test_target_lanes_args(tmp_path):
    # --role host/--no-x2/--lanes-core require --lanes 2, --lanes 2 requires the Mini, --lanes-core
    # requires the core.
    for args in [["--role", "host"], ["--no-x2"], ["--lanes-core"], ["--lanes", "2", "--variant", "standard"],
        ["--lanes", "2", "--lanes-core", "--no-core"]]:
        cmd = [sys.executable, "-c", RUN_TARGET, "bench/acorn.py", "--output-dir", str(tmp_path)] + args
        p = subprocess.run(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert p.returncode != 0
