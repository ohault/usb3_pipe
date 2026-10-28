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
    "metal"   : ((0.70, 0.71, 0.73), (0.80, 0.80, 0.82), 0.50),
    "metal_dk": ((0.58, 0.59, 0.61), (0.80, 0.80, 0.82), 0.50),
    "cage"    : ((0.66, 0.64, 0.60), (0.45, 0.44, 0.42), 0.35), # Tin plated steel (SFP cage).
    "cage_dk" : ((0.46, 0.45, 0.43), (0.40, 0.40, 0.38), 0.30),
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

    def face(self, *idx, out):
        """Face oriented to its outward direction out (mm coordinates, y down): counter-clockwise
        seen from outside in the VRML coordinates (the y mirror reverses the winding)."""
        a, b, c = (self.verts[i] for i in idx[:3])
        u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        w = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        n = (u[1]*w[2] - u[2]*w[1], u[2]*w[0] - u[0]*w[2], u[0]*w[1] - u[1]*w[0])
        if n[0]*out[0] - n[1]*out[1] + n[2]*out[2] < 0:
            idx = idx[::-1]
        self.faces.append(idx)

    def box(self, x0, x1, y0, y1, z0, z1):
        p = [self.v(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
        # p: 0 (x0,y0,z0) 1 (x1,y0,z0) 2 (x0,y1,z0) 3 (x1,y1,z0) 4-7 same at z1.
        for f, out in [((0, 2, 3, 1), (0, 0, -1)), ((4, 5, 7, 6), (0, 0, 1)), ((0, 1, 5, 4), (0, -1, 0)),
                       ((2, 6, 7, 3), (0, 1, 0)), ((0, 4, 6, 2), (-1, 0, 0)), ((1, 3, 7, 5), (1, 0, 0))]:
            self.face(*[p[i] for i in f], out=out)

    def plate_with_holes(self, x0, x1, y0, y1, z0, z1, cols, rows, pitch, r, n=24):
        """Plate [x0, x1] x [y0, y1] x [z0, z1] with round holes (radius r) on a grid of square tiles
        (pitch) centered on (cols x rows) centers; the rest of the plate as boxes."""
        tx0, tx1 = min(cols) - pitch/2, max(cols) + pitch/2
        ty0, ty1 = min(rows) - pitch/2, max(rows) + pitch/2
        # Plate around the tiles grid.
        for bx0, bx1, by0, by1 in [(x0, tx0, y0, y1), (tx1, x1, y0, y1), (tx0, tx1, y0, ty0), (tx0, tx1, ty1, y1)]:
            if bx1 > bx0 and by1 > by0:
                self.box(bx0, bx1, by0, by1, z0, z1)
        for cx in cols:
            for cy in rows:
                h = pitch/2
                ring_top, ring_bot, sq_top, sq_bot = [], [], [], []
                for k in range(n):
                    a = 2*math.pi*k/n
                    ca, sa = math.cos(a), math.sin(a)
                    m = h/max(abs(ca), abs(sa))
                    for z, ring, sq in [(z1, ring_top, sq_top), (z0, ring_bot, sq_bot)]:
                        ring.append(self.v(cx + r*ca, cy + r*sa, z))
                        sq.append(self.v(cx + m*ca, cy + m*sa, z))
                for k in range(n):
                    j = (k + 1) % n
                    a = 2*math.pi*(k + 0.5)/n
                    self.face(ring_top[k], sq_top[k], sq_top[j], ring_top[j], out=(0, 0, 1))
                    self.face(ring_bot[k], ring_bot[j], sq_bot[j], sq_bot[k], out=(0, 0, -1))
                    self.face(ring_top[k], ring_top[j], ring_bot[j], ring_bot[k],
                        out=(-math.cos(a), -math.sin(a), 0))

    def tube(self, outer, inner, y0, y1, back_closed=True):
        """Hollow prism along y (front at y1 open, back at y0 closed): outer/inner cross-sections
        [(x, z)] with the same point count (counter-clockwise seen from the front)."""
        n = len(outer)
        xc, zc = sum(x for x, _ in outer)/n, sum(z for _, z in outer)/n
        o0 = [self.v(x, y0, z) for x, z in outer]
        o1 = [self.v(x, y1, z) for x, z in outer]
        i0 = [self.v(x, y0, z) for x, z in inner]
        i1 = [self.v(x, y1, z) for x, z in inner]
        for k in range(n):
            j = (k + 1) % n
            mx = (outer[k][0] + outer[j][0])/2 - xc
            mz = (outer[k][1] + outer[j][1])/2 - zc
            self.face(o0[k], o0[j], o1[j], o1[k], out=(mx, 0, mz))    # Outer surface.
            self.face(i0[k], i1[k], i1[j], i0[j], out=(-mx, 0, -mz))  # Inner surface.
            self.face(o1[k], o1[j], i1[j], i1[k], out=(0, 1, 0))      # Front rim.
        if back_closed:
            c = self.v(xc, y0, zc)
            for k in range(n):
                self.face(c, o0[(k + 1) % n], o0[k], out=(0, -1, 0))

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
    cage, dark, plastic, gold, black = Mesh(), Mesh(), Mesh(), Mesh(), Mesh()
    x0, x1 = -48.7, 0.0      # Fab outline (front at x0, overhangs the PCB edge at x=-43).
    hw, h, t = 7.25, 9.3, 0.25
    # Top: vent holes (3 rows x 6 columns) over the connector/module area.
    pitch = 3.6
    cols  = [-31.0 + k*pitch for k in range(6)]
    rows  = [-pitch, 0.0, pitch]
    cage.plate_with_holes(x0, x1, -hw, hw, h - t, h, cols, rows, pitch, 1.05)
    # Sides (with a rectangular window near the front), back.
    for y0, y1 in [(-hw, -hw + t), (hw - t, hw)]:
        cage.box(x0, -40.0, y0, y1, 0, h)
        cage.box(-37.0, x1, y0, y1, 0, h)
        cage.box(-40.0, -37.0, y0, y1, 0, 2.0)
        cage.box(-40.0, -37.0, y0, y1, 6.5, h)
    cage.box(x1 - t, x1, -hw, hw, 0, h)
    cage.box(x0, -12.0, -hw, hw, 0, t)               # Bottom plate (front part, over the board edge).
    # Front EMI collar (bezel side of the PCB edge) with spring fingers.
    xc, fo, ct = -44.4, 0.9, 0.3
    dark.box(xc - ct, xc, -hw - fo, hw + fo, h, h + fo)
    dark.box(xc - ct, xc, -hw - fo, hw + fo, -fo, 0)
    dark.box(xc - ct, xc, -hw - fo, -hw, -fo, h + fo)
    dark.box(xc - ct, xc, hw, hw + fo, -fo, h + fo)
    for k in range(9):
        y = -hw + 0.9 + k*(2*hw - 1.8)/8
        dark.box(xc, xc + 2.4, y - 0.35, y + 0.35, h, h + 0.3)
    for y in (-hw - 0.3, hw):
        for k in range(3):
            z = 1.5 + k*2.8
            dark.box(xc, xc + 2.4, y, y + 0.3, z - 0.4, z + 0.4)
    # Front: latch window, module guides (front opening edge folded in).
    black.box(-47.6, -45.6, -1.6, 1.6, h - t - 0.02, h + 0.02)
    dark.box(x0, x0 + 0.6, -hw, hw, h - 0.8, h - t)
    # Press-fit pins (through the board).
    for x, y in [(-37.1, 1.45), (0.0, 0.0), (-37.1, -7.12), (-14.3, -7.12), (-32.1, 7.12), (-22.1, 7.12),
                 (-4.6, -7.12), (0.0, -4.8), (-17.1, -1.45), (-7.1, -7.12), (-17.1, 3.95), (-2.1, 7.12),
                 (-9.6, 7.12), (0.0, 4.8), (-12.1, 7.12), (-14.3, 7.12), (-17.1, -7.12), (-4.6, 7.12),
                 (-27.1, -7.12), (-9.6, -7.12)]:
        cage.box(x - 0.3, x + 0.3, y - 0.15, y + 0.15, -1.9, 0.1)
    # 20-pin connector (fab outline), card slot, contacts tails.
    plastic.box(-9.9, -2.5, -5.6, 5.6, 0.0, 3.3)
    black.box(-10.0, -9.9, -4.6, 4.6, 1.2, 2.1)
    for x in (-10.3, -2.1):
        for k in range(10):
            y = -3.8 + k*0.8
            gold.box(x - 0.6, x + 0.6, y - 0.15, y + 0.15, 0.0, 0.12)
    return [("cage", cage), ("cage_dk", dark), ("plastic", plastic), ("gold", gold), ("plastic", black)]

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
