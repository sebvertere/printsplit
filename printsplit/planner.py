"""Recursive cut planner: split a mesh until every piece fits some printer."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
import numpy as np
import trimesh

from .printers import Printer
from . import connectors as C


@dataclass
class Params:
    margin: float = 3.0          # unusable border per bed side (brim / skirt), mm
    dowel_d: float = 8.0
    dowel_depth: float = 10.0    # per side
    clearance: float = 0.25      # socket radial clearance
    wall: float = 3.0            # min material around a dowel
    min_piece: float = 20.0      # don't cut closer than this to an end
    seam_weight: float = 1.5     # higher => prefer small cross-sections over fewer parts
    connectors: bool = True
    balance: bool = False
    smart_orient: bool = True    # suggest print orientation by overhang / flat-contact
    manual_cuts: list = field(default_factory=list)   # [(axis_index, pos_mm)] applied before auto-cuts
    max_parts: int = 200


@dataclass
class Part:
    mesh: trimesh.Trimesh
    id: str = ""
    box: list = field(default_factory=list)   # [min, max] of the printer volume around the part
    printer: str = ""
    up_axis: int = 2
    height: float = 0.0
    up_sign: int = 1
    hint: str = ""
    overhang_pct: float = 0.0
    flat_cm2: float = 0.0


def load_mesh(path, scale=1.0, height=None, up="z"):
    scene = trimesh.load(path, force="mesh") if not str(path).lower().endswith((".3mf", ".glb", ".gltf", ".obj")) else trimesh.load(path, force="mesh")
    m = scene if isinstance(scene, trimesh.Trimesh) else trimesh.util.concatenate(scene.dump())
    m.merge_vertices()
    if up == "y":      # Y-up exports (OBJ/glTF/FBX defaults) -> Z-up
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    elif up == "-y":
        m.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    if height:
        scale = height / m.extents[2]
    if scale != 1.0:
        m.apply_scale(scale)
    m.apply_translation(-m.bounds[0])
    return m


def close_boundary_loops(mesh):
    """Cap every open boundary loop with a centroid fan. Returns number of loops closed."""
    import networkx as nx
    u, c = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    bd = u[c == 1]
    if not len(bd):
        return 0
    g = nx.Graph(); g.add_edges_from(bd.tolist())
    verts, faces, n = mesh.vertices.tolist(), mesh.faces.tolist(), 0
    for comp in nx.connected_components(g):
        sub = g.subgraph(comp)
        if any(d != 2 for _, d in sub.degree()):
            continue                      # branching boundary: non-manifold, leave alone
        loop = [next(iter(comp))]
        prev = None
        while True:
            nxt = [v for v in sub.neighbors(loop[-1]) if v != prev and v not in loop[1:]]
            if not nxt:
                break
            prev = loop[-1]; loop.append(nxt[0])
            if nxt[0] == loop[0]:
                loop.pop(); break
        if len(loop) < 3:
            continue
        verts.append(np.mean([verts[i] for i in loop], axis=0).tolist())
        ci = len(verts) - 1
        faces += [[loop[i], loop[(i + 1) % len(loop)], ci] for i in range(len(loop))]
        n += 1
    mesh.vertices, mesh.faces = np.array(verts), np.array(faces)
    return n


def repair(mesh):
    notes = []
    if mesh.is_volume:
        return notes
    mesh.merge_vertices(merge_tex=True, merge_norm=True)
    mesh.update_faces(mesh.nondegenerate_faces()); mesh.update_faces(mesh.unique_faces())
    trimesh.repair.fill_holes(mesh)
    if not mesh.is_watertight:
        k = close_boundary_loops(mesh)
        if k:
            notes.append(f"repaired: capped {k} open hole(s)")
    trimesh.repair.fix_normals(mesh)
    if not mesh.is_volume:
        notes.append("mesh is still not a clean solid (self-intersections / non-manifold edges); cuts may fail — "
                     "in Blender: Mesh ▸ Clean Up ▸ Make Manifold (3D-Print Toolbox), or Remesh / Voxel Remesh, then re-export")
    return notes


def split_bodies(mesh):
    bodies = mesh.split(only_watertight=False)
    return [b for b in bodies if abs(b.volume) > 1.0 or len(b.faces) > 50] or [mesh]


def fits_any(extents, fleet, margin):
    return any(p.fit(extents, margin) for p in fleet)


def est_pieces(extents, fleet, margin):
    """Lower-bound-ish piece count from bbox alone using the best printer."""
    best = math.inf
    for p in fleet:
        c = p.usable(margin)
        caps = (c[0], c[1], c[2]) if p.shape == "rect" else (c[0] * 0.7, c[0] * 0.7, c[2])
        for perm in {(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)}:
            n = 1
            for e, cap in zip(extents, [caps[i] for i in perm]):
                n *= max(1, math.ceil(e / cap - 1e-9))
            best = min(best, n)
    return best


def choose_cut(mesh, fleet, P: Params, log):
    lo, hi = mesh.bounds
    ext = hi - lo
    caps = sorted({round(v, 1) for p in fleet for v in p.usable(P.margin)})
    cands = []
    for axis in range(3):
        L = ext[axis]
        if L < 2 * P.min_piece:
            continue
        pos = set(lo[axis] + L * np.linspace(0.1, 0.9, 17))
        for c in caps:
            pos.add(lo[axis] + c); pos.add(hi[axis] - c)
        for x in pos:
            if lo[axis] + P.min_piece <= x <= hi[axis] - P.min_piece:
                cands.append((axis, float(x)))
    scored = []
    for axis, x in cands:
        polys, _ = C.section_polygons(mesh, axis, x)
        if not polys:
            continue
        area = sum(p.area for p in polys)
        e1, e2 = ext.copy(), ext.copy()
        e1[axis] = x - lo[axis]; e2[axis] = hi[axis] - x
        n = est_pieces(e1, fleet, P.margin) + est_pieces(e2, fleet, P.margin)
        scored.append((axis, x, area, n))
    if not scored:
        return None
    ref = np.median([s[2] for s in scored]) or 1.0
    best = min(scored, key=lambda s: s[3] + P.seam_weight * s[2] / ref)
    return best[0], best[1], best[2]


def box_for(mesh, axis, pos, side):
    lo, hi = mesh.bounds
    pad = (hi - lo) * 0.5 + 10
    a, b = lo - pad, hi + pad
    if side < 0:
        b[axis] = pos
    else:
        a[axis] = pos
    return trimesh.creation.box(bounds=[a, b])


def apply_cut(mesh, axis, pos, P: Params, dowels_out, log):
    polys, to_3d = C.section_polygons(mesh, axis, pos)
    work = mesh
    n_d = 0
    if P.connectors and polys:
        centres, warns = C.place_dowels(mesh, polys, to_3d, axis, pos, P.dowel_d, P.dowel_depth, P.wall)
        for w, k in sorted({w: warns.count(w) for w in warns}.items()):
            log(f"    ! {k}× {w}")
        if centres:
            tools = C.socket_tools(centres, axis, P.dowel_d, P.dowel_depth, P.clearance)
            work = trimesh.boolean.difference([mesh] + tools, engine="manifold")
            n_d = len(centres)
            dowels_out.append(n_d)
    halves = []
    for side in (-1, 1):
        h = trimesh.boolean.intersection([work, box_for(mesh, axis, pos, side)], engine="manifold")
        halves.extend(split_bodies(h) if len(h.faces) else [])
    return halves, n_d


def plan(mesh, fleet, P: Params, log=print):
    for p in fleet:
        p.qty = max(1, p.qty)
    queue = split_bodies(mesh)
    done, dowel_counts, cuts = [], [], []
    for axis, pos in P.manual_cuts:
        nxt = []
        for m in queue:
            lo, hi = m.bounds
            if lo[axis] + 1.0 < pos < hi[axis] - 1.0:
                halves, nd = apply_cut(m, axis, pos, P, dowel_counts, log)
                area = sum(q.area for q in C.section_polygons(m, axis, pos)[0])
                cuts.append({"axis": "XYZ"[axis], "pos": pos, "seam_mm2": area, "dowels": nd, "manual": True})
                log(f"  manual cut {'XYZ'[axis]} = {pos:.1f} mm")
                nxt.extend(halves)
            else:
                nxt.append(m)
        queue = nxt
    guard = 0
    while queue:
        m = queue.pop(0)
        if fits_any(m.extents, fleet, P.margin):
            done.append(m); continue
        guard += 1
        if guard > P.max_parts or len(done) + len(queue) > P.max_parts:
            raise RuntimeError("exceeded max parts — the model is huge for this fleet; add printers or raise --max-parts")
        cut = choose_cut(m, fleet, P, log)
        if cut is None:
            log("  ! no viable cut for a piece; leaving oversize"); done.append(m); continue
        axis, pos, area = cut
        log(f"  cut {'XYZ'[axis]} = {pos:7.1f} mm  (seam {area:7.0f} mm²) on piece {m.extents.round(0)}")
        halves, nd = apply_cut(m, axis, pos, P, dowel_counts, log)
        cuts.append({"axis": "XYZ"[axis], "pos": pos, "seam_mm2": area, "dowels": nd})
        queue = halves + queue
    parts = assign(done, fleet, P)
    if P.balance:
        parts = rebalance(parts, fleet, P, log, dowel_counts, cuts)
    return parts, cuts, sum(dowel_counts)


def orient_options(mesh, printer, P):
    """Score each feasible (up axis, sign): fewer overhangs and more flat bed contact is better."""
    opts = printer.fit_all(mesh.extents, P.margin)
    if not opts:
        return []
    area_f, nrm = mesh.area_faces, mesh.face_normals
    total = area_f.sum() or 1.0
    res = []
    for up, h in opts:
        for sign in (1, -1):
            d = np.zeros(3); d[up] = sign
            dots = nrm @ d
            z = mesh.triangles_center[:, up] * sign
            on_bed = z <= z.min() + 0.6
            flat = area_f[(dots < -0.97) & on_bed].sum()
            over = area_f[(dots < -0.707) & ~on_bed].sum()
            score = over / total - min(flat / total, 0.3) + 0.02 * h / printer.usable(P.margin)[2]
            res.append((score, up, sign, h, 100 * over / total, flat / 100.0))
    res.sort()
    return res


def make_hint(axis, sign, over_pct, flat_cm2):
    s = f"{'+' if sign > 0 else '−'}{'XYZ'[axis]} up · {over_pct:.0f}% overhang · {flat_cm2:.0f} cm² flat on bed"
    if over_pct > 25:
        s += " · likely needs supports"
    elif flat_cm2 < 5:
        s += " · small bed contact, consider a brim"
    return s


def assign(meshes, fleet, P):
    """Largest parts first; each goes to the printer slot with least load among those it fits."""
    slots = [(p, i, 0.0) for p in fleet for i in range(p.qty)]
    load = {(p.name, i): 0.0 for p, i, _ in slots}
    parts = []
    for m in sorted(meshes, key=lambda m: -abs(m.volume)):
        opts = []
        for p, i, _ in slots:
            f = p.fit(m.extents, P.margin)
            if f:
                opts.append((load[(p.name, i)] + abs(m.volume) / 1000.0, p.volume, p, i, f))
        if not opts:
            parts.append(Part(m, printer="NONE (oversize)")); continue
        opts.sort(key=lambda o: (o[0], o[1]))
        _, _, p, i, f = opts[0]
        load[(p.name, i)] += abs(m.volume) / 1000.0
        label = p.name + (f" #{i + 1}" if p.qty > 1 else "")
        pt = Part(m, printer=label, up_axis=f[0], height=f[1], box=volume_box(p, m, f[0]))
        if P.smart_orient:
            o = orient_options(m, p, P)
            if o:
                _, up, sign, h, over, flat = o[0]
                pt.up_axis, pt.up_sign, pt.height, pt.overhang_pct, pt.flat_cm2 = up, sign, h, over, flat
                pt.box = volume_box(p, m, up)
                pt.hint = make_hint(up, sign, over, flat)
        parts.append(pt)
    for n, pt in enumerate(parts, 1):
        pt.id = f"part_{n:02d}"
    return parts


def volume_box(p, mesh, up):
    """The printer's full build volume, oriented for this part and sitting on the part's lowest point."""
    a, b = [i for i in range(3) if i != up]
    ext, (lo, hi) = mesh.extents, mesh.bounds
    cx, cy = p.x, (p.x if p.shape == "circle" else p.y)
    dims = [0.0] * 3
    dims[up] = p.z
    ucx, ucy, _ = p.usable(0)
    dims[a], dims[b] = (cx, cy) if (ext[a] <= cx and ext[b] <= cy) else (cy, cx)
    bmin, bmax = [0.0] * 3, [0.0] * 3
    for i in (a, b):
        c = (lo[i] + hi[i]) / 2
        bmin[i], bmax[i] = c - dims[i] / 2, c + dims[i] / 2
    bmin[up], bmax[up] = lo[up], lo[up] + dims[up]
    return [bmin, bmax]


def rebalance(parts, fleet, P, log, dowel_counts, cuts):
    def makespan(ps):
        d = {}
        for p in ps:
            d[p.printer] = d.get(p.printer, 0) + abs(p.mesh.volume)
        return max(d.values())
    for _ in range(12):
        base = makespan(parts)
        heavy = max(parts, key=lambda p: abs(p.mesh.volume))
        cut = choose_cut(heavy.mesh, fleet, P, log)
        if not cut:
            break
        halves, _ = apply_cut(heavy.mesh, cut[0], cut[1], P, dowel_counts, log)
        trial = assign([p.mesh for p in parts if p is not heavy] + halves, fleet, P)
        if makespan(trial) < base * 0.9 and all("NONE" not in t.printer for t in trial):
            log(f"  balance: split {heavy.id} -> makespan {base/1e3:.0f}k -> {makespan(trial)/1e3:.0f}k mm³")
            cuts.append({"axis": "XYZ"[cut[0]], "pos": cut[1], "seam_mm2": cut[2], "dowels": 0, "balance": True})
            parts = trial
        else:
            break
    return parts
