"""Alignment-dowel placement and socket/peg boolean operations."""
from __future__ import annotations
import numpy as np
import trimesh
from shapely.geometry import Point
from trimesh.transformations import inverse_matrix


def section_polygons(mesh, axis, pos):
    """Cross-section of `mesh` at world plane axis=pos -> (polygons, to_3D matrix)."""
    n = np.zeros(3); n[axis] = 1
    o = np.zeros(3); o[axis] = pos
    sec = mesh.section(plane_origin=o, plane_normal=n)
    if sec is None:
        return [], None
    to_2d = trimesh.geometry.plane_transform(o, n)
    planar, to_3d = sec.to_2D(to_2D=to_2d)
    return list(planar.polygons_full), to_3d


def place_dowels(mesh, polys, to_3d, axis, pos, d, depth, wall, max_per_region=6):
    """Pick dowel centres (world coords) on a cut. Returns (centres, warnings)."""
    r = d / 2
    centres, warns = [], []
    n = np.zeros(3); n[axis] = 1
    for poly in polys:
        if poly.area < 40:  # sliver
            continue
        inner = poly.buffer(-(r + wall))
        if inner.is_empty:
            warns.append(f"section of {poly.area:.0f} mm² too thin for a {d:g} mm dowel (wall {wall:g} mm) — glue-only seam")
            continue
        parts = list(inner.geoms) if hasattr(inner, "geoms") else [inner]
        pts = []
        for g in parts:
            minx, miny, maxx, maxy = g.bounds
            step = max(r, 2.0)
            for x in np.arange(minx, maxx + 1e-6, step):
                for y in np.arange(miny, maxy + 1e-6, step):
                    if g.contains(Point(x, y)):
                        pts.append((x, y))
        if not pts:
            c = inner.representative_point(); pts = [(c.x, c.y)]
        pts = np.array(pts)
        want = int(np.clip(2 + poly.area // 1500, 2, max_per_region))
        # farthest-point sampling starting from the most interior point
        dist_edge = np.array([poly.exterior.distance(Point(p)) for p in pts])
        chosen = [int(np.argmax(dist_edge))]
        while len(chosen) < min(want, len(pts)):
            dd = np.min(np.linalg.norm(pts[:, None] - pts[chosen][None], axis=2), axis=1)
            if dd.max() < 2.5 * d:
                break
            chosen.append(int(np.argmax(dd)))
        for i in chosen:
            c3 = (to_3d @ np.array([pts[i][0], pts[i][1], 0, 1]))[:3]
            # verify material exists on both sides of the cut (hollow shells fail here)
            probes = []
            for s in (-1, 1):
                for ang in (None, 0, 90, 180, 270):
                    q = c3.copy(); q[axis] += s * depth * 0.9
                    if ang is not None:
                        a = np.radians(ang); o = [i2 for i2 in range(3) if i2 != axis]
                        q[o[0]] += r * np.cos(a); q[o[1]] += r * np.sin(a)
                    probes.append(q)
            if mesh.contains(np.array(probes)).all():
                centres.append(c3)
            else:
                warns.append("dowel position rejected: not enough solid material behind the cut (thin shell?)")
    return centres, warns


def _cyl(c, axis, radius, length):
    cyl = trimesh.creation.cylinder(radius=radius, height=length, sections=48)
    # cylinder is along Z; rotate to axis
    if axis == 0:
        cyl.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    elif axis == 1:
        cyl.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    cyl.apply_translation(c)
    return cyl


def socket_tools(centres, axis, d, depth, clearance):
    return [_cyl(c, axis, d / 2 + clearance, 2 * (depth + clearance)) for c in centres]


def dowel_mesh(d, depth):
    """One loose dowel, printed lying down; chamfered ends help insertion."""
    return trimesh.creation.cylinder(radius=d / 2, height=2 * depth, sections=48)
