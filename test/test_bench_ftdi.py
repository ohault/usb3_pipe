#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteX Acorn Baseboard FTDI selection (bench/common.py): FT2232H or FT4232H baseboards, several
boards selected by USB location (fake USB sysfs)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench"))
import common

class TestAcornFTDI(unittest.TestCase):
    def setUp(self):
        self.sysfs = tempfile.mkdtemp()
        for location, product, busnum, devnum in [("1-2", "Dual RS232-HS", 1, 5),
            ("1-4", "Quad RS232-HS", 1, 7), ("1-5", "USB Keyboard", 1, 9)]:
            d = os.path.join(self.sysfs, location)
            os.makedirs(d)
            for name, value in [("product", product), ("busnum", busnum), ("devnum", devnum),
                ("serial", f"S{devnum}")]:
                with open(os.path.join(d, name), "w") as f:
                    f.write(f"{value}\n")
        self.sysfs_orig, common.USB_SYSFS = common.USB_SYSFS, self.sysfs
        os.environ.pop("USB3_PIPE_FTDI", None)

    def tearDown(self):
        common.USB_SYSFS = self.sysfs_orig

    def test_list_find_openocd(self):
        devs = common.acorn_ftdi_list()
        self.assertEqual([(d["location"], d["chip"], d["cable"]) for d in devs],
            [("1-2", "FT2232H", "ft2232"), ("1-4", "FT4232H", "ft4232")])
        # Two boards: never guessed.
        with self.assertRaises(RuntimeError):
            common.acorn_ftdi_find()
        dev = common.acorn_ftdi_find("1-2")
        self.assertEqual((dev["busnum"], dev["devnum"], dev["ocd_location"]), (1, 5, "1:2"))
        cfg = os.path.join(self.sysfs, "openocd.cfg")
        common.acorn_openocd_config(dev, cfg)
        text = open(cfg).read()
        self.assertIn("ftdi_vid_pid 0x0403 0x6010", text)
        self.assertIn("ftdi_location 1:2", text)
        self.assertIn("ftdi_channel 0", text)
        common.acorn_openocd_config(common.acorn_ftdi_find("1-4"), cfg)
        self.assertIn("ftdi_vid_pid 0x0403 0x6011", open(cfg).read())
        # $USB3_PIPE_FTDI selection.
        os.environ["USB3_PIPE_FTDI"] = "1-4"
        self.assertEqual(common.acorn_ftdi_find()["chip"], "FT4232H")
        os.environ.pop("USB3_PIPE_FTDI")

if __name__ == "__main__":
    unittest.main()
