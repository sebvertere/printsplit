# -*- coding: utf-8 -*-
"""Import a PrintSplit result into Rhino, one layer per printer.

Run in Rhino:  Tools > Script Editor (or the RunPythonScript command), open this file, Run.
Pick the plan.json from PrintSplit's output folder when asked.

Creates
  PrintSplit::<printer>            the parts in assembled position (real CAD coordinates)
  PrintSplit::Volumes::<printer>   wireframe box of that printer's build volume around each part
  PrintSplit::PrintReady::<printer>  (optional) flat, bed-oriented copies laid out beside the model
Each part carries user text: printer, print_up (suggested up direction), hint, height_mm.
Works in Rhino 7 (IronPython) and Rhino 8 (Python 3).
"""
import os
import glob
import json
import struct

import Rhino
import scriptcontext as sc
import System.Drawing as SD

PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#b07aa1", "#edc948", "#76b7b2", "#9c755f"]


def hex_color(h):
    h = h.lstrip("#")
    return SD.Color.FromArgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def read_stl(path):
    """Binary or ASCII STL -> Rhino.Geometry.Mesh (welded)."""
    with open(path, "rb") as f:
        data = f.read()
    mesh = Rhino.Geometry.Mesh()
    n = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else 0
    if len(data) == 84 + 50 * n:
        for k in range(n):
            rec = struct.unpack_from("<12fH", data, 84 + 50 * k)
            i = mesh.Vertices.Count
            mesh.Vertices.Add(rec[3], rec[4], rec[5])
            mesh.Vertices.Add(rec[6], rec[7], rec[8])
            mesh.Vertices.Add(rec[9], rec[10], rec[11])
            mesh.Faces.AddFace(i, i + 1, i + 2)
    else:  # ASCII
        pts = []
        for line in data.decode("utf-8", "ignore").splitlines():
            t = line.split()
            if len(t) == 4 and t[0] == "vertex":
                pts.append((float(t[1]), float(t[2]), float(t[3])))
        for k in range(0, len(pts) - 2, 3):
            i = mesh.Vertices.Count
            for p in pts[k:k + 3]:
                mesh.Vertices.Add(*p)
            mesh.Faces.AddFace(i, i + 1, i + 2)
    mesh.Vertices.CombineIdentical(True, True)
    mesh.Normals.ComputeNormals()
    mesh.Compact()
    return mesh


def get_layer(doc, path, color=None):
    """Create (if needed) a layer by 'A::B::C' path; return its index."""
    parent_id = System_Guid_Empty()
    idx = -1
    full = []
    for name in path.split("::"):
        full.append(name)
        idx = doc.Layers.FindByFullPath("::".join(full), -1)
        if idx < 0:
            layer = Rhino.DocObjects.Layer()
            layer.Name = name
            layer.ParentLayerId = parent_id
            if color is not None and len(full) == len(path.split("::")):
                layer.Color = color
            idx = doc.Layers.Add(layer)
        parent_id = doc.Layers[idx].Id
    return idx


def System_Guid_Empty():
    import System
    return System.Guid.Empty


def box_edges(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    c = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    e = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
    return [Rhino.Geometry.Line(Rhino.Geometry.Point3d(*c[a]), Rhino.Geometry.Point3d(*c[b])) for a, b in e]


def find_stl(folder, part_id):
    hits = glob.glob(os.path.join(folder, part_id + "_*.stl"))
    return hits[0] if hits else None


def run(doc, plan_path, with_print_ready=False, with_volumes=True):
    plan = json.load(open(plan_path))
    root = os.path.dirname(plan_path)
    colors, added = {}, 0
    bb = Rhino.Geometry.BoundingBox.Empty
    for r in plan["parts"]:
        printer = r["printer"]
        base = printer.split(" #")[0]
        colors.setdefault(base, PALETTE[len(colors) % len(PALETTE)])
        col = hex_color(colors[base])
        stl = find_stl(os.path.join(root, "assembled"), r["id"])
        if not stl:
            continue
        mesh = read_stl(stl)
        bb.Union(mesh.GetBoundingBox(True))
        attr = Rhino.DocObjects.ObjectAttributes()
        attr.LayerIndex = get_layer(doc, "PrintSplit::" + printer, col)
        attr.Name = r["id"]
        attr.SetUserString("printer", printer)
        attr.SetUserString("print_up", ("+" if r.get("print_up_sign", 1) > 0 else "-") + r.get("print_up_axis", "Z"))
        attr.SetUserString("hint", r.get("orientation_hint", ""))
        attr.SetUserString("height_mm", str(r.get("print_height_mm", "")))
        doc.Objects.AddMesh(mesh, attr)
        added += 1
        if with_volumes and r.get("printer_volume_box"):
            va = Rhino.DocObjects.ObjectAttributes()
            va.LayerIndex = get_layer(doc, "PrintSplit::Volumes::" + printer, col)
            va.Name = r["id"] + "_volume"
            for ln in box_edges(*r["printer_volume_box"]):
                doc.Objects.AddLine(ln, va)
    pr_count = 0
    if with_print_ready and bb.IsValid:
        x = bb.Max.X + 200.0
        rows = {}
        for r in plan["parts"]:
            stl = find_stl(os.path.join(root, "print_ready"), r["id"])
            if not stl:
                continue
            base = r["printer"].split(" #")[0]
            mesh = read_stl(stl)
            row = rows.setdefault(r["printer"], [0.0, len(rows) * 600.0])
            mesh.Translate(x + row[0], bb.Min.Y + row[1], 0.0)
            bx = mesh.GetBoundingBox(True)
            row[0] += (bx.Max.X - bx.Min.X) + 20.0
            attr = Rhino.DocObjects.ObjectAttributes()
            attr.LayerIndex = get_layer(doc, "PrintSplit::PrintReady::" + r["printer"], hex_color(colors[base]))
            attr.Name = r["id"] + "_flat"
            doc.Objects.AddMesh(mesh, attr)
            pr_count += 1
    doc.Views.Redraw()
    return added, pr_count


def main():
    fd = Rhino.UI.OpenFileDialog()
    fd.Title = "Choose PrintSplit plan.json"
    fd.Filter = "PrintSplit plan (plan.json)|plan.json|JSON (*.json)|*.json"
    if not fd.ShowOpenDialog():
        return
    flat = Rhino.Input.RhinoGet.GetBool("Also import flat print-ready copies?", False, "No", "Yes", False)
    flat = flat[1] if flat[0] == Rhino.Commands.Result.Success else False
    n, m = run(sc.doc, fd.FileName, with_print_ready=flat)
    Rhino.RhinoApp.WriteLine("PrintSplit: imported {} parts{}".format(n, " + {} flat copies".format(m) if m else ""))


if __name__ == "__main__":
    main()
