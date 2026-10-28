#!/usr/bin/env python3

#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Generate the breakout KiCad 7 schematic (sfp2usbc.kicad_sch) from the intended netlist
(netlist.py): KiCad library symbols (embedded), footprints, net labels on each pin (no wires between
symbols), no connect flags, test points, power flag and mounting holes.

The schematic is a generated, readable view of netlist.py: edit netlist.py and regenerate, then
check with KiCad (ERC, netlist export + check_netlist.py):
  ./gen_schematic.py
  kicad-cli sch erc --exit-code-violations sfp2usbc.kicad_sch
  kicad-cli sch export netlist --format kicadsexpr -o sfp2usbc.net sfp2usbc.kicad_sch
  ./check_netlist.py sfp2usbc.net
"""

import os
import sys
import math
import uuid
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from netlist import COMPONENTS, NETS, NO_CONNECT

KICAD_SYMBOLS = "/usr/share/kicad/symbols"

# Symbols / Footprints / Placement -----------------------------------------------------------------

# ref: (lib_id, footprint, x, y) (mm, A3 sheet, symbols not rotated).
PARTS = {
    "J1" : ("Interface_Optical:SFP+",                "Connector:Connector_SFP_and_Cage",                        63.5,  76.2),
    "J2" : ("Interface_Optical:SFP+",                "Connector:Connector_SFP_and_Cage",                        63.5, 190.5),
    "C1" : ("Device:C",                              "Capacitor_SMD:C_0402_1005Metric",                         127.0,  63.5),
    "C2" : ("Device:C",                              "Capacitor_SMD:C_0402_1005Metric",                         152.4,  63.5),
    "C3" : ("Device:C",                              "Capacitor_SMD:C_0402_1005Metric",                         127.0, 177.8),
    "C4" : ("Device:C",                              "Capacitor_SMD:C_0402_1005Metric",                         152.4, 177.8),
    "U1" : ("Power_Protection:TPD4E05U06DQA",        "Package_SON:USON-10_2.5x1.0mm_P0.5mm",                    203.2,  76.2),
    "U2" : ("Power_Protection:TPD4E05U06DQA",        "Package_SON:USON-10_2.5x1.0mm_P0.5mm",                    203.2, 190.5),
    "J3" : ("Connector:USB_C_Receptacle",            "Connector_USB:USB_C_Receptacle_Amphenol_12401610E4-2A",   292.1, 127.0),
    "R1" : ("Device:R",                              "Resistor_SMD:R_0402_1005Metric",                          355.6,  88.9),
    "R2" : ("Device:R",                              "Resistor_SMD:R_0402_1005Metric",                          381.0,  88.9),
    "R3" : ("Device:R",                              "Resistor_SMD:R_0402_1005Metric",                          355.6, 177.8),
    "C5" : ("Device:C",                              "Capacitor_SMD:C_0402_1005Metric",                         381.0, 177.8),
}

# Extra parts (not in netlist.py): ref: (lib_id, footprint, value, x, y, net of pin 1 or None).
EXTRA_PARTS = {
    "TP1"    : ("Connector:TestPoint",       "TestPoint:TestPoint_Pad_D1.0mm",       "VBUS",    355.6, 127.0, "VBUS"),
    "#FLG01" : ("power:PWR_FLAG",            "",                                     "PWR_FLAG", 266.7, 228.6, "GND"),
    "H1"     : ("Mechanical:MountingHole",   "MountingHole:MountingHole_3.2mm_M3",   "M3",       38.1, 254.0, None),
    "H2"     : ("Mechanical:MountingHole",   "MountingHole:MountingHole_3.2mm_M3",   "M3",       50.8, 254.0, None),
    "H3"     : ("Mechanical:MountingHole",   "MountingHole:MountingHole_3.2mm_M3",   "M3",       63.5, 254.0, None),
    "H4"     : ("Mechanical:MountingHole",   "MountingHole:MountingHole_3.2mm_M3",   "M3",       76.2, 254.0, None),
}

STUB = 2.54 # Wire stub between a pin and its net label (mm).

# KiCad library symbols ----------------------------------------------------------------------------

def sexpr_blocks(text, start, depth_name):
    """Yield (name, start, end) of the "(<depth_name> "name" ..." blocks directly under the block at
    start (raw text, quotes aware)."""
    i, depth, in_str = start, 0, False
    block_start = None
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
            if depth == 2:
                block_start = i
        elif c == ")":
            if depth == 2 and block_start is not None:
                head = text[block_start + 1:block_start + 1 + len(depth_name) + 2]
                if head == f'{depth_name} "':
                    name = text[block_start + len(depth_name) + 3:text.index('"', block_start + len(depth_name) + 3)]
                    yield name, block_start, i + 1
            depth -= 1
            if depth == 0:
                return
        i += 1

def library_symbol(lib_id):
    """Raw KiCad symbol definition for lib_id, renamed "lib:name" for the schematic lib_symbols, with
    a derived symbol (extends) flattened on its parent."""
    lib, name = lib_id.split(":")
    text    = open(os.path.join(KICAD_SYMBOLS, f"{lib}.kicad_sym")).read()
    symbols = {n: text[s:e] for n, s, e in sexpr_blocks(text, text.index("("), "symbol")}
    raw = symbols[name]
    if "(extends " in raw.split("(property", 1)[0]:
        parent_name = raw.split('(extends "', 1)[1].split('"', 1)[0]
        parent      = symbols[parent_name]
        props = [raw[s:e] for _, s, e in sexpr_blocks(raw, 0, "property")]
        # Parent without its properties, derived properties instead, units renamed.
        body = parent
        for _, s, e in reversed(list(sexpr_blocks(parent, 0, "property"))):
            body = body[:s] + body[e:]
        head, rest = body.split("\n", 1)
        body = head + "\n" + "\n".join("    " + p for p in props) + "\n" + rest
        body = body.replace(f'(symbol "{parent_name}_', f'(symbol "{name}_')
        raw  = body.replace(f'(symbol "{parent_name}"', f'(symbol "{name}"', 1)
    return raw.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)

def symbol_property_at(raw, name):
    """Position of a property in a raw symbol definition: (x, y, angle) (symbol coordinates, y up)."""
    at = raw.split(f'(property "{name}"', 1)[1].split("(at ", 1)[1].split(")", 1)[0].split()
    return float(at[0]), float(at[1]), int(float(at[2]))

def symbol_pins(raw):
    """Pins of a raw symbol definition: [(number, x, y, angle)] (symbol coordinates, y up)."""
    pins = []
    for part in raw.split("(pin ")[1:]:
        at     = part.split("(at ", 1)[1].split(")", 1)[0].split()
        number = part.split('(number "', 1)[1].split('"', 1)[0]
        pins.append((number, float(at[0]), float(at[1]), int(float(at[2]))))
    return pins

# Schematic ----------------------------------------------------------------------------------------

# Deterministic UUIDs (stable files/diffs, symbols linked to the board footprints by their UUID).
UUID_NAMESPACE = uuid.UUID("5f3c1c2e-8a4b-4c6e-9d1a-2b7e0c5a9f10")
_uid_count     = [0]

def uid(name=None):
    if name is None:
        _uid_count[0] += 1
        name = f"item{_uid_count[0]}"
    return str(uuid.uuid5(UUID_NAMESPACE, name))

def symbol_uuid(ref):
    """UUID of the schematic symbol of ref (the board footprint path is /<symbol uuid>)."""
    return uid(f"symbol:{ref}")

ROOT_UUID = uid("root")

def fmt(v):
    return f"{round(v, 4):g}"

class Schematic:
    def __init__(self, project):
        self.project  = project
        self.root     = ROOT_UUID
        self.libs     = {}
        self.items    = []

    def add_symbol(self, ref, lib_id, value, footprint, x, y, pin_nets, datasheet="~"):
        """Symbol instance at (x, y) with a net label (or a no connect flag: net None) on each pin
        group (stacked pins: same position)."""
        if lib_id not in self.libs:
            self.libs[lib_id] = library_symbol(lib_id)
        raw    = self.libs[lib_id]
        pins   = symbol_pins(raw)
        power  = ref.startswith("#")
        hide   = " hide" if power else ""
        # Reference/Value at their library positions.
        rx, ry, ra = symbol_property_at(raw, "Reference")
        vx, vy, va = symbol_property_at(raw, "Value")
        pins_txt = "".join(f'\n    (pin "{n}" (uuid {uid(f"pin:{ref}:{n}")}))' for n in sorted({p[0] for p in pins}))
        self.items.append(f'''  (symbol (lib_id "{lib_id}") (at {fmt(x)} {fmt(y)} 0) (unit 1)
    (in_bom {"no" if power else "yes"}) (on_board yes) (dnp no)
    (uuid {symbol_uuid(ref)})
    (property "Reference" "{ref}" (at {fmt(x + rx)} {fmt(y - ry)} {ra})
      (effects (font (size 1.27 1.27)){hide})
    )
    (property "Value" "{value}" (at {fmt(x + vx)} {fmt(y - vy)} {va})
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "{footprint}" (at {fmt(x)} {fmt(y)} 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "{datasheet}" (at {fmt(x)} {fmt(y)} 0)
      (effects (font (size 1.27 1.27)) hide)
    ){pins_txt}
    (instances
      (project "{self.project}"
        (path "/{self.root}" (reference "{ref}") (unit 1))
      )
    )
  )''')
        # Pin groups (stacked pins share their position: one label).
        groups = {}
        for number, px, py, angle in pins:
            groups.setdefault((px, py, angle), []).append(number)
        for (px, py, angle), numbers in groups.items():
            nets = {pin_nets.get(n, "?") for n in numbers}
            assert len(nets) == 1, f"{ref}: stacked pins {numbers} on different nets {nets}."
            net = nets.pop()
            assert net != "?", f"{ref}: pins {numbers} not in netlist.py (net or no connect)."
            # Pin end (schematic coordinates, y down) and outward direction (opposite to the body).
            ex, ey = x + px, y - py
            dx = -round(math.cos(math.radians(angle)))
            dy =  round(math.sin(math.radians(angle)))
            if net is None:
                self.items.append(f"  (no_connect (at {fmt(ex)} {fmt(ey)}) (uuid {uid()}))")
                continue
            lx, ly = ex + STUB*dx, ey + STUB*dy
            self.items.append(f"  (wire (pts (xy {fmt(ex)} {fmt(ey)}) (xy {fmt(lx)} {fmt(ly)}))\n"
                f"    (stroke (width 0) (type default)) (uuid {uid()}))")
            label_angle, justify = {(1, 0): (0, "left"), (-1, 0): (180, "right"),
                                    (0, -1): (90, "left"), (0, 1): (270, "right")}[(dx, dy)]
            self.items.append(f'  (label "{net}" (at {fmt(lx)} {fmt(ly)} {label_angle})\n'
                f"    (effects (font (size 1.27 1.27)) (justify {justify} bottom)) (uuid {uid()}))")

    def text(self, txt, x, y, size=2.0):
        self.items.append(f'  (text "{txt}" (at {fmt(x)} {fmt(y)} 0)\n'
            f"    (effects (font (size {size} {size})) (justify left bottom)) (uuid {uid()}))")

    def render(self, title):
        libs = "\n".join("    " + raw.replace("\n", "\n  ") for raw in self.libs.values())
        return f'''(kicad_sch (version 20230121) (generator eeschema)

  (uuid {self.root})

  (paper "A3")

  (title_block
    (title "{title}")
    (company "USB3-PIPE")
    (comment 1 "Generated by gen_schematic.py from netlist.py: do not edit, regenerate.")
  )

  (lib_symbols
{libs}
  )

{chr(10).join(self.items)}

  (sheet_instances
    (path "/" (page "1"))
  )
)
'''

def build():
    pin_nets = {}
    for name, nodes in NETS.items():
        for node in nodes:
            pin_nets[node] = name
    for node in NO_CONNECT:
        pin_nets[node] = None

    sch = Schematic("sfp2usbc")
    for ref, (lib_id, footprint, x, y) in PARTS.items():
        description, value = COMPONENTS[ref]
        nets = {pin: net for (r, pin), net in pin_nets.items() if r == ref}
        sch.add_symbol(ref, lib_id, value, footprint, x, y, nets)
    assert set(PARTS) == set(COMPONENTS), "netlist.py components without placement."
    for ref, (lib_id, footprint, value, x, y, net) in EXTRA_PARTS.items():
        sch.add_symbol(ref, lib_id, value, footprint, x, y, {"1": net} if net else {})

    sch.text("SFP-A (to Acorn SFP-0, Lane 0)",  38.1,  45.72)
    sch.text("SFP-B (to Acorn SFP-1, Lane 1)",  38.1, 160.02)
    sch.text("TX AC coupling",                 119.38, 45.72)
    sch.text("ESD (close to J3)",              190.5,  45.72)
    sch.text("USB-C (CC1: TX1/RX1 = Lane 0)",  269.24, 71.12)
    sch.text("Rd (UFP), VBUS test pad, shield", 345.44, 71.12)
    sch.text("Power flag",                     261.62, 215.9)
    sch.text("Mounting holes (M3)",             33.02, 241.3)
    return sch.render("Dual SFP to USB-C breakout (USB 3.2 Gen 1x2)")

def main():
    parser = argparse.ArgumentParser(description="Generate the breakout KiCad schematic from netlist.py.")
    parser.add_argument("--output", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "sfp2usbc.kicad_sch"))
    args = parser.parse_args()
    open(args.output, "w").write(build())
    print(f"Wrote {args.output}.")

if __name__ == "__main__":
    main()
