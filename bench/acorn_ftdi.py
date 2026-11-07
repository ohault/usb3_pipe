#!/usr/bin/env python3

#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteX Acorn Baseboard JTAG (baseboard FTDI: FT2232H or FT4232H depending on the revision, channel A)
with several boards connected: each board selected by the USB location of its FTDI.

  ./bench/acorn_ftdi.py list                                             # FTDIs: location, chip.
  ./bench/acorn_ftdi.py --location 1-2 load build/acorn_x2_host/gateware/sqrl_acorn.bit
  ./bench/acorn_ftdi.py --location 1-2 server --port 1240                # litex_server (JTAGBone).
  ./bench/acorn_ftdi.py --location 1-2 openocd-cfg host.cfg              # OpenOCD config only.

To know which board is which: unplug the J7 USB-C cable of one board, run list again.
"""

import os
import sys
import json
import argparse
import subprocess
import tempfile

from common import acorn_ftdi_list, acorn_ftdi_find, acorn_openocd_config # First: repository root on the path.

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--location", default=None, help="FTDI USB sysfs location (ex: 1-2, see list; default: $USB3_PIPE_FTDI, or the only one).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List the FT2232H/FT4232H devices.")
    p = sub.add_parser("load", help="Load a bitstream (SRAM) with openFPGALoader.")
    p.add_argument("bitstream")
    p = sub.add_parser("server", help="Start litex_server (JTAGBone) on this board.")
    p.add_argument("--port", default=1240, type=int, help="litex_server port (one per board, ex: 1240/1241).")
    p = sub.add_parser("openocd-cfg", help="Write the OpenOCD config of this board.")
    p.add_argument("filename")
    args = parser.parse_args()

    if args.command == "list":
        for d in acorn_ftdi_list():
            print(json.dumps({k: d[k] for k in ["location", "chip", "busnum", "devnum", "serial"]}))
        return

    dev = acorn_ftdi_find(args.location)
    if args.command == "load":
        cmd = ["openFPGALoader", "-c", dev["cable"], "--busdev-num", f"{dev['busnum']}:{dev['devnum']}",
            "--write-sram", args.bitstream]
        print(" ".join(cmd), flush=True)
        sys.exit(subprocess.run(cmd).returncode)
    elif args.command == "openocd-cfg":
        acorn_openocd_config(dev, args.filename)
    elif args.command == "server":
        # OpenOCD config in a temporary directory (litex_server runs OpenOCD in its working directory).
        tmp = tempfile.mkdtemp(prefix=f"acorn_{dev['location']}_")
        acorn_openocd_config(dev, os.path.join(tmp, "openocd.cfg"))
        cmd = ["litex_server", "--jtag", "--jtag-config", "openocd.cfg",
            "--jtag-port", str(args.port + 18800), "--bind-port", str(args.port)]
        print(f"{dev['chip']} {dev['location']}: " + " ".join(cmd), flush=True)
        os.chdir(tmp)
        os.execvp(cmd[0], cmd)

if __name__ == "__main__":
    main()
