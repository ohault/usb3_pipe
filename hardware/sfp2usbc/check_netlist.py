#!/usr/bin/env python3

#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Check a KiCad netlist export of the breakout schematic against the intended netlist (netlist.py).

Connectivity is compared, not net names: each intended net must be exactly one KiCad net (same
pins, no extra pins except test points/mounting holes), no connect pins must be unconnected. The
components with symbolic pins in netlist.py (ESD arrays, cages) are checked by net membership.

Usage:
  kicad-cli sch export netlist --format kicadsexpr -o sfp2usbc.net sfp2usbc.kicad_sch
  ./check_netlist.py sfp2usbc.net
"""

import os
import re
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from netlist import COMPONENTS, NETS, NO_CONNECT, SYMBOLIC_PIN_REFS

# Refs allowed on nets without being in the intended netlist (test points, mounting holes, logos).
EXTRA_REF_PREFIXES = ("TP", "H", "MH", "FID", "LOGO", "G")

# KiCad netlist (s-expression) parser -------------------------------------------------------------

def parse_sexpr(text):
    """Parse an s-expression into nested lists of strings."""
    tokens = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)
    stack = [[]]
    for token in tokens:
        if token == "(":
            stack.append([])
        elif token == ")":
            node = stack.pop()
            stack[-1].append(node)
        elif token.startswith('"'):
            stack[-1].append(token[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
        else:
            stack[-1].append(token)
    assert len(stack) == 1, "Unbalanced s-expression."
    return stack[0][0]

def children(node, name):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == name]

def field(node, name):
    found = children(node, name)
    return found[0][1] if found else None

def read_kicad_netlist(text):
    """Return ({ref: value}, {net name: set of (ref, pin)}) from a KiCad netlist export."""
    root = parse_sexpr(text)
    assert root[0] == "export", "Not a KiCad netlist (kicadsexpr) export."
    components = {}
    for comps in children(root, "components"):
        for comp in children(comps, "comp"):
            components[field(comp, "ref")] = field(comp, "value")
    nets = {}
    for nets_node in children(root, "nets"):
        for net in children(nets_node, "net"):
            nodes = {(field(n, "ref"), field(n, "pin")) for n in children(net, "node")}
            nets[field(net, "name")] = nodes
    return components, nets

# Check --------------------------------------------------------------------------------------------

def is_extra(ref):
    return ref.startswith(EXTRA_REF_PREFIXES) and ref not in COMPONENTS

def check(components, nets):
    """Return (errors, warnings) of the KiCad netlist vs the intended netlist."""
    errors, warnings = [], []

    # Components.
    for ref, (description, value) in COMPONENTS.items():
        if ref not in components:
            errors.append(f"Missing component {ref} ({description}).")
        elif value.split()[0].lower() not in (components[ref] or "").lower():
            warnings.append(f"{ref}: value '{components[ref]}', expected '{value}'.")
    for ref in components:
        if ref not in COMPONENTS and not is_extra(ref):
            errors.append(f"Unexpected component {ref} ({components[ref]}).")

    # Pin -> KiCad net.
    pin_net = {}
    for name, nodes in nets.items():
        for node in nodes:
            pin_net[node] = name

    def concrete(nodes):
        return {(ref, pin) for ref, pin in nodes if ref not in SYMBOLIC_PIN_REFS}

    # Intended nets.
    used = set()
    for name, nodes in NETS.items():
        pins = concrete(nodes)
        found = {pin_net.get(pin) for pin in pins}
        if None in found:
            missing = sorted(pin for pin in pins if pin not in pin_net)
            errors.append(f"{name}: pins not connected: {missing}.")
            found.discard(None)
        if len(found) > 1:
            errors.append(f"{name}: split over KiCad nets {sorted(found)}.")
            continue
        if not found:
            continue
        kicad_name = found.pop()
        used.add(kicad_name)
        kicad_pins = nets[kicad_name]
        extra = sorted(p for p in concrete(kicad_pins) - pins if not is_extra(p[0]))
        if extra:
            errors.append(f"{name}: extra pins {extra} (KiCad net '{kicad_name}').")
        # Symbolic pins: one pin of the component per intended node on this net.
        for ref in SYMBOLIC_PIN_REFS:
            expected = sum(1 for r, _ in nodes if r == ref)
            actual   = sum(1 for r, _ in kicad_pins if r == ref)
            if (name != "GND") and (expected != actual):
                errors.append(f"{name}: {actual} pin(s) of {ref}, expected {expected}.")
            if (name == "GND") and expected and not actual:
                errors.append(f"GND: no pin of {ref}.")
        if kicad_name.lstrip("/") != name and not kicad_name.startswith("Net-("):
            warnings.append(f"{name}: KiCad net named '{kicad_name}'.")

    # Symbolic components: no pin on a net outside the intended ones (except no connects).
    for name, nodes in nets.items():
        if name in used or len(nodes) <= 1:
            continue
        refs = sorted({ref for ref, _ in nodes if ref in SYMBOLIC_PIN_REFS})
        if refs:
            errors.append(f"KiCad net '{name}': unexpected connection of {refs}: {sorted(nodes)}.")

    # No connect pins.
    for pin in NO_CONNECT:
        name = pin_net.get(pin)
        if name is not None and len(nets[name] - {pin}) > 0:
            others = sorted(p for p in nets[name] - {pin} if not is_extra(p[0]))
            if others:
                errors.append(f"{pin[0]}.{pin[1]} should be unconnected, on '{name}' with {others}.")

    return errors, warnings

def main():
    parser = argparse.ArgumentParser(description="Check the breakout KiCad netlist export against netlist.py.")
    parser.add_argument("netlist", help="KiCad netlist export (kicad-cli sch export netlist --format kicadsexpr).")
    args = parser.parse_args()

    components, nets = read_kicad_netlist(open(args.netlist).read())
    errors, warnings = check(components, nets)
    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"{len(errors)} error(s), {len(warnings)} warning(s).")
    sys.exit(1 if errors else 0)

if __name__ == "__main__":
    main()
