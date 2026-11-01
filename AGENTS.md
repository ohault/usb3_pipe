# USB3-PIPE for AI Agents

Guidance for a software agent working *in* USB3-PIPE (fix, extend, review the PHY or the Device Core)
or *with* it (integrate it in a LiteX SoC, bring up a board, drive a board from the host). It follows
LiteX's [LiteX for AI Agents](https://github.com/enjoy-digital/litex/blob/master/doc/wiki/LiteX-for-AI-Agents.md)
and only adds what is specific to this repository; read that page first for LiteX itself. When this
page and the code disagree, the code is right and this page needs a fix.

## USB3-PIPE in ten lines

1. USB 3.2 SuperSpeed (Gen 1x1, 5Gbps) and SuperSpeedPlus (Gen 2x1, 10Gbps) on FPGA transceivers,
   without an external USB chip, in Migen/LiteX ([README](README.md)).
2. `usb3_pipe/`: the PHY: SerDes wrappers (Artix7 GTP, Kintex7 GTX, UltraScale+ GTY, through
   LiteICLink), LFPS, Training Sequences, 8b/10b and 128b/132b datapaths, scrambling, SKP, framing,
   LTSSM, multi-lane (Gen 1x2) and debug ([doc/usb3-pipe.md](doc/usb3-pipe.md)).
3. `usb3_core/`: the USB3 Device Core: Link/Protocol layers, Control endpoint, Bulk/Isochronous
   endpoints, descriptors, device classes (CDC-ACM, UVC, MSC), the shared example designs
   (`usb3_core/examples.py`) and a Python host model ([doc/usb3-core.md](doc/usb3-core.md)).
4. `bench/`: the board targets (`acorn.py`, `kc705.py`, `alibaba_xcku3p.py`, shared SoC in
   `usb3_soc.py`) and the host tools (`usb3_bulk.py`, `usb3_bench.py`, `usb3_debug.py`,
   `usb3_lanes.py`...), shared host helpers in `bench/common.py` ([doc/examples.md](doc/examples.md)).
5. `sim.py`: Verilator system simulation, Host model <-> PHYs <-> Device Core (Gen 1 and Gen 2).
6. `test/`: ~390 pytest tests (Migen simulations with Python host/GT/LTSSM models in `test/model/`,
   target elaborations in `test_targets.py`); markers `slow` and `sim` in `pytest.ini`.
7. `usb3_pipe_gen` (`usb3_pipe/gen.py`, `examples/*.yml`): the PHY (or PHY + Device Core) as a
   standalone Verilog core ([doc/standalone-core.md](doc/standalone-core.md)).
8. Hardware debugging (CSRs, traces, LiteScope, soak): [doc/debugging-guide.md](doc/debugging-guide.md).
9. Roadmap and status of Gen 2x1/Gen 1x2/Gen 2x2: [doc/gen2-x2-roadmap.md](doc/gen2-x2-roadmap.md),
   Gen 1x2 hardware procedure: [doc/gen1x2-hardware-validation.md](doc/gen1x2-hardware-validation.md).
10. BSD-2-Clause, Python 3.9 in CI, LiteX `master` (installed by `litex_setup.py --config=standard`).

## Where the key things are

| You need | Look at |
| --- | --- |
| The PHY top-level and its options (lanes, Gen 2, link width) | `usb3_pipe/phy.py` (`USB3PHY`), `usb3_pipe/core.py` (`USB3PIPE`) |
| A transceiver wrapper | `usb3_pipe/serdes.py` (vendor primitives stay there) |
| The LTSSM states and timeouts | `usb3_pipe/ltssm.py`, `test/test_ltssm*.py`, `test/model/ltssm.py` |
| Multi-lane (Gen 1x2) striping/deskew | `usb3_pipe/lanes.py`, `test/test_lanes.py` |
| The Device Core assembly | `usb3_core/device.py` (`USB3DeviceCore`), `usb3_core/link.py`, `usb3_core/protocol.py` |
| An example design and its board options | `usb3_core/examples.py` (`USB3_EXAMPLES`), `bench/usb3_soc.py` |
| The options of a target | `./bench/<target>.py --help` |
| The PHY/Link debug CSRs | `usb3_pipe/debug.py`, `bench/usb3_debug.py` |
| What CI runs | `.github/workflows/ci.yml` |

## Commands that answer questions fast

```sh
python3 -m pytest test/test_lanes.py                         # one test file (Migen simulation, no toolchain)
python3 -m pytest -n auto -m "not slow and not sim"          # what CI runs first (pytest-xdist)
python3 -m pytest -n 2 -m "not slow and sim"                 # the Verilator simulations of CI
python3 -m pytest -m slow                                    # long simulations (nightly in CI)
python3 -m pytest test/test_targets.py -k acorn              # elaborate the Acorn targets (no Vivado)
./sim.py                                                     # Host model <-> PHYs <-> Device Core in Verilator
./bench/acorn.py --build --no-compile --output-dir=/tmp/x    # the map, CSRs and Verilog in seconds, no Vivado
usb3_pipe_gen examples/a7_device.yml --output-dir build/usb3_pipe_core  # the standalone Verilog core
```

Reading the `csr.csv` and the generated Verilog of an elaboration (as `test/test_targets.py` does) is
the fastest way to check what a target or an option really produces.

## Conventions

- **Style**: LiteX's [coding_style.md](https://github.com/enjoy-digital/litex/blob/master/doc/coding_style.md):
  the file header with the SPDX line, section banners `# Name ----...` (100 columns), the `# # #`
  separator between a module's interface and its implementation, aligned argument blocks; look at the
  neighboring files first and keep edits scoped.
- **Architecture**: LiteX's [architectural_style.md](https://github.com/enjoy-digital/litex/blob/master/doc/architectural_style.md):
  the USB3 protocol logic is vendor independent (`usb3_pipe/` above the SerDes, `usb3_core/`); the
  vendor primitives are in `usb3_pipe/serdes.py`; pins, clocks and SFP/connector choices are in the
  `bench/` targets. Keep public class names, constructor arguments, CSR names, clock domain names and
  command-line options (the host tools and `test_targets.py` rely on them), or provide a compatibility path.
- **Spec references**: the docstrings cite the USB 3.2 specification sections (`7.5.4.10.2`...); keep
  citing them for new protocol behavior.
- **Commits**: `module: Description of the change.` (`phy/ltssm: Gen 1x2 single lane fallback.`), one
  change per commit; say what was tested and on which hardware.
- **Tests**: a test in `test/` for new logic; mark long ones `slow` and Verilator ones `sim`
  (`pytestmark = pytest.mark.sim` at the module level, as in `test/test_phy.py`); a new target option gets an elaboration case in `test/test_targets.py`.
- **Docs**: update the matching `doc/*.md` and the README status tables when a feature or a result changes.
- **Generated files are never edited** (`build/`, `csr.csv`, `*.init`, the Verilog): change the Python.
- **Do not bump dependencies, rename options or reformat unrelated code** in a fix.

## How to verify a change

1. Simulate: the relevant `test/` files, then the CI selections above; `./sim.py` for anything that
   touches link training, enumeration or the datapath end to end.
2. Elaborate: `test/test_targets.py` (or a `--build --no-compile` of a target) for anything that
   touches a target, a SerDes wrapper or an example; a Python import alone proves nothing.
3. Build: a real `--build` with Vivado when it is available; look at the timing report (the GTP/GTX/GTY
   clock domains are tight at 5/10Gbps).
4. Hardware: say what ran on a board (which board, which host controller, which cable/adapter) and
   what did not. Simulation and elaboration cannot establish signal integrity, CDR lock, equalization
   or interoperability with a real xHCI host.

## Pitfalls

- LiteX, Migen and LiteICLink come from `litex_setup.py` (LiteX `master`), not from PyPI; a system
  Python refuses `pip` installs (PEP 668): use a venv.
- The `sim` tests and `./sim.py` need Verilator (CI pins the same version as LiteX CI) and
  `libevent-dev libjson-c-dev`.
- `bench/*.py` are run as scripts (they import `usb3_soc`/`common` from `bench/`, not as a package);
  `build/` is written in the current directory, run them from the repository root.
- CPU examples (`console`, `composite`) need `--cpu-type vexriscv`, and the RISC-V gcc for a full
  build; `msc_dram` is Acorn only; `--link-words 2` applies to `loopback`/`bench`.
- Gen 2 (10Gbps) needs UltraScale+ GTY; `--lanes 2` is Acorn Mini only and has no Device Core yet
  (PRBS Link-Layer stand-ins).

## Contribute back

As LiteX asks: when the work here needed a fix or an addition in LiteX, LiteICLink or LiteX-Boards
(a transceiver parameter, a stream/CDC fix, a board pin), send it upstream to the repository it
belongs to rather than working around it here, one topic per pull request, with how it was verified.
Say that an agent wrote it and who supervised; the direction stays with the maintainers.
