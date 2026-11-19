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
    tx_clks = set(verilog_net(verilog, n) for n in re.findall(r"\.TXUSRCLK\s*\((\w+)\)", verilog))
    assert len(tx_clks) == 1

def verilog_net(verilog, name):
    """Net driving name through `assign name = other;` aliases."""
    while True:
        m = re.search(rf"\nassign {name} = (\w+);", verilog)
        if m is None:
            return name
        name = m.group(1)

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
    for csr_name in ["usb3_script_control", "usb3_script_status", "usb3_script_step", "usb3_script_error_step",
        "usb3_script_passes", "usb3_script_fails", "usb3_lanes_debug_rx_drop_count",
        "usb3_script_ss_start", "usb3_script_ssp", "usb3_port_reset_count",
        "usb3_lanes_debug_control", "usb3_lanes_debug_lane0_rx_disparity_errors_count",
        "usb3_lanes_debug_lane1_rx_com_disparity_errors_count", "usb3_lanes_debug_xcvr_reinit",
        "usb3_lanes_debug_lane1_xcvr_status", "usb3_lanes_debug_lane0_drp_do",
        "usb3_lanes_debug_lane0_qpll_lock_lost_count", "usb3_lanes_debug_lane1_tx_buferror_count",
        "usb3_lanes_debug_monitor_control", "usb3_lanes_debug_monitor_thresholds", "usb3_lanes_debug_monitor_window",
        "usb3_lanes_debug_monitor_window_status", "usb3_lanes_debug_monitor_reinits_count",
        "usb3_lanes_debug_monitor_ratio", "usb3_lanes_debug_monitor_window_hot_resets",
        "usb3_lanes_debug_watchdog_timeout", "usb3_lanes_debug_watchdog_count",
        "usb3_lanes_debug_lane1_tx_diffctrl", "usb3_lanes_debug_lane1_tx_idle_force"]:
        assert csr_name in csr
    assert "usb3_prbs" not in csr
    verilog = next((tmp_path / "gateware").glob("*.v")).read_text()
    assert verilog.count("\nGTPE2_CHANNEL ") == 2

def test_target_lanes_training_watchdog(tmp_path):
    # Gen 1x2 training watchdog (transceivers re-initialization after training without U0): 2000ms
    # reset value in the Host role, disabled (0) in the Device role (Tang Device split build too).
    for target, args, reset in [
        ("acorn", ["--lanes", "2", "--role", "host"],   2000),
        ("acorn", ["--lanes", "2", "--role", "device"], 0),
        ("sipeed_tang_mega_138k_pro", ["--lanes", "2"], 0)]:
        out = tmp_path / f"{target}_{reset}_{args[-1]}"
        elaborate(target, out, args)
        verilog = next((out / "gateware").glob("*.v")).read_text()
        assert "usb3_lanes_debug_watchdog_timeout" in (out / "csr.csv").read_text()
        assert re.search(r"reg\s+\[15:0\]\s+\S*timeout_storage\s*=\s*16'd" + str(reset) + ";",
            verilog), (target, args)

def test_target_lanes_tx_diffctrl(tmp_path):
    # Acorn Gen 1x2 TX differential swing: runtime register reset to 15 by default (t19), per cage
    # with --tx-diffctrl.
    for args, values in [([], [15, 15]), (["--tx-diffctrl", "12,14"], [12, 14])]:
        out = tmp_path / ("_".join(args) or "default")
        elaborate("acorn", out, ["--lanes", "2", "--role", "host"] + args)
        verilog = next((out / "gateware").glob("*.v")).read_text()
        for lane, value in enumerate(values):
            # TXDIFFCTRL port <- tx_diffctrl<lane> <- CSR storage (generated names).
            storage = re.search(r"assign\s+tx_diffctrl" + str(lane) + r"\s*=\s*(\S+);", verilog).group(1)
            assert re.search(r"reg\s+\[3:0\]\s+" + storage + r"\s*=\s*4'd" + str(value) + ";", verilog), \
                (args, lane, value)

def test_target_lanes_split_counters(tmp_path):
    # Tang Mega 138K Pro Gen 1x2 split build (lanes logic in pipe_cd): the lanes event counters
    # counted in pipe_cd with --with-lanes-counters (lane word misalignment diagnosis, t22), not with --lean.
    csr = elaborate("sipeed_tang_mega_138k_pro", tmp_path / "default", ["--lanes", "2"])
    assert "usb3_lanes_debug_deskew_count" not in csr # Opt-in (lanes clock timing, t23).
    csr = elaborate("sipeed_tang_mega_138k_pro", tmp_path / "counters", ["--lanes", "2", "--with-lanes-counters"])
    for name in ["deskew", "realign_u0", "skp_odd_u0", "com_slip", "lane0_rx_skp_odd", "lane1_rx_com_partial",
        "lane1_rx_errors_cycles", "lane0_ts2"]:
        assert f"usb3_lanes_debug_{name}_count" in csr, name
    for name in ["rx_half_markers", "rx_lane1_late", "rx_lane1_early"]: # PRBS lane check.
        assert f"usb3_prbs_{name}" in csr, name
    csr = elaborate("sipeed_tang_mega_138k_pro", tmp_path / "lean", ["--lanes", "2", "--lean", "--with-lanes-counters"])
    assert "usb3_lanes_debug_deskew_count" not in csr

def test_target_tang_lanes_core_split(tmp_path):
    # Tang Mega 138K Pro Gen 1x2 Device Core: split clocking (Link Layer/Core in sys at 62.5MHz, the
    # USB3PHYX2Link lanes side at 125MHz); the scripted host (Host role) split as well (was a single
    # 125MHz domain: 81-89MHz on hardware builds, t50).
    csr = elaborate("sipeed_tang_mega_138k_pro", tmp_path / "device", ["--lanes", "2", "--lanes-core"])
    assert re.search(r"constant,config_clock_frequency,62500000,", csr)
    csr = elaborate("sipeed_tang_mega_138k_pro", tmp_path / "host", ["--lanes", "2", "--lanes-core",
        "--role", "host"])
    assert re.search(r"constant,config_clock_frequency,62500000,", csr)
    assert "usb3_script_ssp" in csr

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
    assert gtp_tx_postcursors(tmp_path) == [postcursor]*(2 if "--lanes" in args else 1)

def gtp_tx_postcursors(output_dir):
    """TXPOSTCURSOR of the GTPE2_CHANNEL instances of an elaborated target (Verilog order): a
    constant, or the reset value of the register driving it (Gen 1x2 runtime control)."""
    verilog = next((output_dir / "gateware").glob("*.v")).read_text()
    values  = re.findall(r"\.TXPOSTCURSOR\s*\(([^)]*)\)", verilog)
    assert values, "TXPOSTCURSOR not found"
    def resolve(v):
        if re.fullmatch(r"\w+", v) and not v[0].isdigit():
            net = verilog_net(verilog, v)
            v   = re.search(rf"\nreg\s+(?:\[[^]]*\]\s*)?{net} = ([^;]+);", verilog).group(1)
        return int(v.split("'d")[-1]) if "'d" in v else int(v.split("'b")[-1], 2)
    return [resolve(v.strip()) for v in values]

def test_target_tx_postcursor_per_sfp(tmp_path):
    # One value per SFP cage (SFP-0/SFP-1): both values on the two GTPs.
    elaborate("acorn", tmp_path, ["--lanes", "2", "--tx-postcursor", "6,10"])
    assert sorted(gtp_tx_postcursors(tmp_path)) == [6, 10]

def sfp_pins(output_dir):
    """SFP TX P pins of the elaborated target, in the GTP instances (lanes) order."""
    verilog = next((output_dir / "gateware").glob("*.v")).read_text()
    xdc     = next((output_dir / "gateware").glob("*.xdc")).read_text()
    pins    = []
    for port in re.findall(r"\.GTPTXP\s*\(\s*(\w+)\s*\)", verilog):
        pins.append(re.search(rf"LOC (\w+) \[get_ports {{{port}}}\]", xdc).group(1))
    return pins

def test_target_sfp_select(tmp_path):
    # --sfp 1: Gen 1x1 on SFP-1; Gen 1x2 Lane 0 (Configuration Lane) on SFP-1, Lane 1 on SFP-0, the
    # per cage TX post-cursor following the cages.
    elaborate("acorn", tmp_path / "x1", ["--sfp", "1"])
    assert sfp_pins(tmp_path / "x1") == ["B4"]
    elaborate("acorn", tmp_path / "x2", ["--lanes", "2", "--sfp", "1", "--tx-postcursor", "6,10"])
    assert sfp_pins(tmp_path / "x2") == ["B4", "D5"]
    assert gtp_tx_postcursors(tmp_path / "x2") == [10, 6]

def test_target_lanes_args(tmp_path):
    # --role host/--no-x2/--lanes-core require --lanes 2, --lanes 2 requires the Mini, --lanes-core
    # requires the core.
    for args in [["--role", "host"], ["--no-x2"], ["--lanes-core"], ["--lanes", "2", "--variant", "standard"],
        ["--lanes", "2", "--lanes-core", "--no-core"], ["--sfp", "1", "--variant", "standard"]]:
        cmd = [sys.executable, "-c", RUN_TARGET, "bench/acorn.py", "--output-dir", str(tmp_path)] + args
        p = subprocess.run(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert p.returncode != 0

def test_target_tang_rx_errors_count(tmp_path):
    # Tang Mega 138K Pro Device (mixed Acorn Host/Tang Device line noise tests): RX 8b/10b errors by
    # type counters (USB3RXErrorTypesDebug, SerDes logic on the GTR12 TX clock: counts synchronized).
    csr = elaborate("sipeed_tang_mega_138k_pro", tmp_path, ["--example", "loopback", "--with-rx-errors",
        "--with-clk-meters"])
    for name in ["rx_decode_errors", "rx_disparity_errors", "rx_com_decode_errors", "rx_com_disparity_errors"]:
        assert f"usb3_rx_errors_{name}_count" in csr
    assert "usb3_rx_errors_clear" in csr
    assert "usb3_tx_freq_value" in csr and "usb3_rx_freq_value" in csr

def test_target_tang_x2_warm_analyzer(tmp_path):
    # Tang Gen 1x2 split PRBS Device with the warm LiteScope group (Warm Reset detection per lane).
    csr = elaborate("sipeed_tang_mega_138k_pro", tmp_path, ["--lanes", "2", "--with-analyzer",
        "--analyzer-group", "warm"])
    assert "analyzer_" in csr

def test_target_tang_x2(tmp_path):
    # Tang Mega 138K Pro Gen 1x2 (SFP0/SFP1, Q1 lanes 0/1): one GTR12 quad instance/UPAR/register
    # configuration for both lanes, Lane 1 TX on the Lane 0 TX clock (sys), Host (scripted host)
    # and Device (PRBS stand-ins) roles, the merged lanes 0/1 register configuration.
    for role, args in [("device", []), ("host", ["--lanes-core"])]:
        out = tmp_path / role
        csr = elaborate("sipeed_tang_mega_138k_pro", out, ["--lanes", "2", "--role", role,
            "--with-clk-meters"] + args)
        assert "usb3_lanes_debug_xcvr_reinit" in csr and "usb3_rx1_freq_value" in csr
        assert "usb3_gtr12_lane1_rx_invalid" in csr
        assert "usb3_gtr12_lane1_cdr_toggles" not in csr # --cdr-toggle only.
        assert ("usb3_script" in csr) == (role == "host")
        verilog = next((out / "gateware").glob("*.v")).read_text()
        assert len(re.findall(r"\nGTR12_QUAD #\(", verilog)) == 1
        assert len(re.findall(r"\nGTR12_UPAR GTR12_UPAR\(", verilog)) == 1
        tx_clk = re.search(r"\.LANE0_PCS_TX_O_FABRIC_CLK\s*\((\w+)\)", verilog).group(1)
        for lane in [0, 1]:
            assert re.search(rf"\.LANE{lane}_FABRIC_TX_CLK\s*\({tx_clk}\)", verilog)
        assert "LANE1_PCS_TX_O_FABRIC_CLK" not in verilog
        tcl = (out / "gateware" / "run.tcl").read_text()
        assert tcl.count("set_csr ") == 1
        assert "0x900b91,0x0000F300" in tcl


def test_target_tang_x2_lean(tmp_path):
    # Tang Gen 1x2 --lean: USB3LanesDebug status/control/re-initialization only (timings).
    csr = elaborate("sipeed_tang_mega_138k_pro", tmp_path, ["--lanes", "2", "--lean"])
    assert "usb3_lanes_debug_status" in csr and "usb3_lanes_debug_xcvr_reinit" in csr
    assert "usb3_lanes_debug_lane0_ts1_count" not in csr
    assert "usb3_lanes_debug_monitor" not in csr
    assert "usb3_prbs_rx_errors" in csr

def test_target_ltssm_states_constants(tmp_path):
    # LTSSM states encoding of the build in csr.csv (Tang Gen 1x1: no U1/U2 states, the states after
    # U0 shifted), decoded by the debug client (t16j: HotReset.Active read as Loopback with the
    # default encoding).
    csr = elaborate("sipeed_tang_mega_138k_pro", tmp_path, ["--example", "loopback"])
    constants = {}
    for line in csr.splitlines():
        row = line.split(",")
        if row[0] == "constant" and row[1].startswith("usb3_ltssm_"):
            constants[row[1]] = int(row[2])
    assert "usb3_ltssm_u1" not in constants
    sys.path.insert(0, str(ROOT / "bench"))
    from types import SimpleNamespace
    from usb3_debug import USB3DebugClient
    client = USB3DebugClient(SimpleNamespace(constants=SimpleNamespace(d=constants)))
    assert client.state_name(constants["usb3_ltssm_hotreset_active"]) == "HotReset.Active"
    assert client.state_name(constants["usb3_ltssm_u0"]) == "U0"

def test_target_tang_device_c(tmp_path):
    # Tang Mega 138K Pro production part (--device C): Gowin device set for version C.
    elaborate("sipeed_tang_mega_138k_pro", tmp_path, ["--example", "loopback", "--device", "C"])
    tcl = (tmp_path / "gateware" / "run.tcl").read_text()
    assert "set_device -name GW5AST-138C GW5AST-LV138FPG676AC1/I0" in tcl
