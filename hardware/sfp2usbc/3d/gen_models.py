#!/usr/bin/env python3

#
# This file is part of USB3-PIPE project.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""3D models (VRML, KiCad conventions) of the breakout parts missing from the KiCad 3D library:

- SFP_Cage_TE_2227302.wrl            : SFP 1x1 cage + 20-pin connector (Connector:Connector_SFP_and_Cage),
                                        outline from the footprint fab layer (cage 48.7 x 14.5mm).
- USB_C_Receptacle_Amphenol_12401610E4-2A.wrl : USB-C receptacle (KiCad 7 library: no model; KiCad 8+
                                        libraries have the manufacturer STEP).

Approximate shapes for the board 3D views (not mechanical models: use the manufacturer STEP files for
enclosure work). KiCad VRML conventions: 1 unit = 0.1 inch, x right, y up (KiCad -y), z up from the
board top, origin at the footprint origin.
"""

import os
import math

UNIT = 2.54 # mm per VRML unit.

# Materials (KiCad 3D models style): (diffuse, specular, shininess).
MATERIALS = {
    "metal"   : ((0.78, 0.79, 0.81), (0.90, 0.90, 0.92), 0.60),
    "metal_dk": ((0.58, 0.59, 0.61), (0.80, 0.80, 0.82), 0.50),
    "plastic" : ((0.10, 0.10, 0.11), (0.25, 0.25, 0.25), 0.15),
    "gold"    : ((0.86, 0.68, 0.30), (0.95, 0.85, 0.55), 0.55),
    "tin"     : ((0.82, 0.83, 0.85), (0.90, 0.90, 0.92), 0.55),
}

class Mesh:
    """Triangle/quad faces in mm (KiCad footprint coordinates: x right, y down, z up)."""
    def __init__(self):
        self.verts = []
        self.faces = []

    def v(self, x, y, z):
        self.verts.append((x/UNIT, -y/UNIT, z/UNIT))
        return len(self.verts) - 1

    def face(self, *idx):
        self.faces.append(idx)

    def box(self, x0, x1, y0, y1, z0, z1):
        p = [self.v(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
        # p: 0 (x0,y0,z0) 1 (x1,y0,z0) 2 (x0,y1,z0) 3 (x1,y1,z0) 4-7 same at z1.
        for f in [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]:
            self.face(*[p[i] for i in f])

    def tube(self, outer, inner, y0, y1, back_closed=True):
        """Hollow prism along y (front at y1 open, back at y0 closed): outer/inner cross-sections
        [(x, z)] with the same point count (counter-clockwise seen from the front)."""
        n = len(outer)
        o0 = [self.v(x, y0, z) for x, z in outer]
        o1 = [self.v(x, y1, z) for x, z in outer]
        i0 = [self.v(x, y0, z) for x, z in inner]
        i1 = [self.v(x, y1, z) for x, z in inner]
        for k in range(n):
            j = (k + 1) % n
            self.face(o0[k], o0[j], o1[j], o1[k])   # Outer surface.
            self.face(i0[k], i1[k], i1[j], i0[j])   # Inner surface.
            self.face(o1[k], o1[j], i1[j], i1[k])   # Front rim.
        if back_closed:
            c = self.v(sum(x for x, _ in outer)/n, y0, sum(z for _, z in outer)/n)
            for k in range(n):
                self.face(c, o0[(k + 1) % n], o0[k])

def stadium(w, h, zc, n=10):
    """Rounded rectangle cross-section (x, z) of width w, height h (radius h/2), centered on z=zc."""
    r = h/2
    pts = []
    for side, a0 in [(1, -math.pi/2), (-1, math.pi/2)]:
        cx = side*(w/2 - r)
        for i in range(n + 1):
            a = a0 + i/n*math.pi
            pts.append((cx + r*math.cos(a), zc + r*math.sin(a)))
    return pts

def write_vrml(path, shapes):
    """shapes: [(material, Mesh)]."""
    with open(path, "w") as f:
        f.write("#VRML V2.0 utf8\n")
        for name, mesh in shapes:
            diffuse, specular, shininess = MATERIALS[name]
            coords = ",\n".join(f"{x:.5f} {y:.5f} {z:.5f}" for x, y, z in mesh.verts)
            index  = ",\n".join(",".join(str(i) for i in face) + ",-1" for face in mesh.faces)
            f.write(f"""Shape {{
  appearance Appearance {{
    material Material {{
      diffuseColor {diffuse[0]} {diffuse[1]} {diffuse[2]}
      emissiveColor 0 0 0
      specularColor {specular[0]} {specular[1]} {specular[2]}
      ambientIntensity 0.3
      transparency 0
      shininess {shininess}
    }}
  }}
  geometry IndexedFaceSet {{
    creaseAngle 0.5
    coord Coordinate {{ point [
{coords}
    ] }}
    coordIndex [
{index}
    ]
  }}
}}
""")

# SFP cage + connector (TE 2227302) ----------------------------------------------------------------

def sfp_cage():
    cage, dark, plastic, gold = Mesh(), Mesh(), Mesh(), Mesh()
    x0, x1 = -48.7, 0.0      # Fab outline (front at x0, overhangs the PCB edge at x=-43).
    hw, h, t = 7.25, 9.3, 0.25
    cage.box(x0, x1, -hw, hw, h - t, h)              # Top.
    cage.box(x0, x1, -hw, -hw + t, 0, h)             # Sides.
    cage.box(x0, x1, hw - t, hw, 0, h)
    cage.box(x1 - t, x1, -hw, hw, 0, h)              # Back.
    cage.box(x0, -12.0, -hw, hw, 0, t)               # Bottom plate (front part, over the board edge).
    # Front EMI collar (bezel side of the PCB edge) with spring fingers.
    xc, fo, ct = -44.4, 0.9, 0.3
    dark.box(xc - ct, xc, -hw - fo, hw + fo, h, h + fo)
    dark.box(xc - ct, xc, -hw - fo, hw + fo, -fo, 0)
    dark.box(xc - ct, xc, -hw - fo, -hw, -fo, h + fo)
    dark.box(xc - ct, xc, hw, hw + fo, -fo, h + fo)
    for k in range(9):
        y = -hw + 0.9 + k*(2*hw - 1.8)/8
        dark.box(xc, xc + 2.2, y - 0.35, y + 0.35, h, h + 0.35)
    # Top: latch window and embossed ribs.
    dark.box(-46.5, -44.9, -2.0, 2.0, h, h + 0.05)
    for y in (-4.2, 4.2):
        cage.box(-38.0, -14.0, y - 0.6, y + 0.6, h, h + 0.15)
    # Press-fit pins (through the board).
    for x, y in [(-37.1, 1.45), (0.0, 0.0), (-37.1, -7.12), (-14.3, -7.12), (-32.1, 7.12), (-22.1, 7.12),
                 (-4.6, -7.12), (0.0, -4.8), (-17.1, -1.45), (-7.1, -7.12), (-17.1, 3.95), (-2.1, 7.12),
                 (-9.6, 7.12), (0.0, 4.8), (-12.1, 7.12), (-14.3, 7.12), (-17.1, -7.12), (-4.6, 7.12),
                 (-27.1, -7.12), (-9.6, -7.12)]:
        cage.box(x - 0.3, x + 0.3, y - 0.15, y + 0.15, -1.9, 0.1)
    # 20-pin connector (fab outline), card slot, contacts tails.
    plastic.box(-9.9, -2.5, -5.6, 5.6, 0.0, 3.3)
    dark.box(-10.0, -9.9, -4.6, 4.6, 1.2, 2.1)
    for x in (-10.3, -2.1):
        for k in range(10):
            y = -3.8 + k*0.8
            gold.box(x - 0.6, x + 0.6, y - 0.15, y + 0.15, 0.0, 0.12)
    return [("metal", cage), ("metal_dk", dark), ("plastic", plastic), ("gold", gold)]

# USB-C receptacle (Amphenol 12401610E4#2A) --------------------------------------------------------

def usb_c():
    shell, plastic, gold, tin = Mesh(), Mesh(), Mesh(), Mesh()
    w, h, t = 8.94, 3.26, 0.25
    zc = h/2
    y_back, y_front = -2.4, 5.23 # Fab outline front at y=5.23 (mating face).
    shell.tube(stadium(w, h, zc), stadium(w - 2*t, h - 2*t, zc), y_back, y_front)
    # Tongue with contacts (top/bottom, 12 each).
    plastic.box(-3.35, 3.35, 0.0, 4.6, zc - 0.35, zc + 0.35)
    for k in range(12):
        x = -2.75 + k*0.5
        gold.box(x - 0.12, x + 0.12, 1.6, 4.4, zc + 0.35, zc + 0.37)
        gold.box(x - 0.12, x + 0.12, 1.6, 4.4, zc - 0.37, zc - 0.35)
    # Rear housing, SMT terminals (A row y=-5.02, B row y=-3.32), shell legs (S1).
    plastic.box(-4.4, 4.4, -4.7, y_back, 0.0, 2.9)
    for k in range(12):
        x = -2.75 + k*0.5
        tin.box(x - 0.13, x + 0.13, -5.3, -4.7, 0.0, 0.12)
        tin.box(x - 0.13 + 0.25, x + 0.13 + 0.25, -3.6, -3.0, 0.0, 0.12)
    for x, y in [(4.49, 2.84), (-4.49, 2.84), (-4.13, -3.11), (4.13, -3.11)]:
        shell.box(x - 0.25, x + 0.25, y - 0.5, y + 0.5, -1.9, 0.2)
    return [("metal", shell), ("plastic", plastic), ("gold", gold), ("tin", tin)]

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    write_vrml(os.path.join(here, "SFP_Cage_TE_2227302.wrl"), sfp_cage())
    write_vrml(os.path.join(here, "USB_C_Receptacle_Amphenol_12401610E4-2A.wrl"), usb_c())
    print("Wrote the models.")

if __name__ == "__main__":
    main()
