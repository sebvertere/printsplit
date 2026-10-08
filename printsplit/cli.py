"""printsplit CLI:  list | plan"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
from .printers import load_db, search, parse_spec, Printer
from . import planner as PL
from .output import write_all


def cmd_list(a):
    db = load_db()
    hits = search(a.query, db) if a.query else db
    for p in sorted(hits, key=lambda p: -p["x"] * p["y"] * p["z"]) if a.by_volume else hits:
        print(f"{p['vendor']:<14} {p['model']:<34} {p['x']:>6.0f} x {p['y']:>5.0f} x {p['z']:>5.0f} mm{'  (round bed)' if p.get('shape')=='circle' else ''}")
    print(f"\n{len(hits)} printers")


def ask_fleet():
    print("\nHow many DIFFERENT printers do you have access to? (1 = just one machine)")
    n = int(input("> ").strip() or 1)
    fleet = []
    for i in range(n):
        while True:
            q = input(f"Printer {i+1} — model name (e.g. 'Bambu Lab A1', 'Prusa XL') or custom 300x300x400: ").strip()
            try:
                p = parse_spec(q); break
            except ValueError as e:
                print("  ", e)
        if n == 1:
            print("One printer type. Is that ONE machine used over several days, or several identical machines?")
        qty = input(f"  How many {p.name} machines can print at the same time? [1] ").strip()
        p.qty = int(qty or 1)
        fleet.append(p)
    return fleet


def cmd_plan(a):
    fleet = [parse_spec(s) for s in a.printer] if a.printer else ask_fleet()
    mesh = PL.load_mesh(a.model, a.scale, a.height, a.up)
    for n in PL.repair(mesh):
        print("!", n)
    print(f"\nModel: {a.model}  size {mesh.extents.round(0)} mm")
    print("Fleet: " + ", ".join(f"{p.name} {p.x:g}x{p.y:g}x{p.z:g} ×{p.qty}" for p in fleet))
    P = PL.Params(margin=a.margin, dowel_d=a.dowel_d, dowel_depth=a.dowel_length / 2, clearance=a.clearance,
                  connectors=not a.no_connectors, balance=a.balance, seam_weight=a.seam_weight, max_parts=a.max_parts)
    parts, cuts, nd = PL.plan(mesh, fleet, P)
    out = Path(a.out or (Path(a.model).stem + "_split"))
    write_all(out, parts, fleet, cuts, nd, P, Path(a.model).name)
    print(f"\n{len(parts)} parts, {len(cuts)} cuts, {nd} dowels needed (print {nd} of dowel_x1.stl)")
    per = {}
    for p in parts:
        per.setdefault(p.printer, []).append(p)
    for k, v in per.items():
        print(f"  {k}: " + ", ".join(f"{p.id} ({abs(p.mesh.volume)/1000:.0f} cm³)" for p in v))
    print(f"\nOpen {out/'plan.html'} to preview. STLs: {out}/assembled (CAD coords) and {out}/print_ready (oriented).")


def cmd_serve(a):
    from .server import serve
    serve(a.port, open_browser=not a.no_browser, host=a.host)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="printsplit")
    sub = ap.add_subparsers(dest="cmd")
    sv = sub.add_parser("serve", help="launch the web app (default)"); sv.add_argument("--port", type=int, default=8765); sv.add_argument("--no-browser", action="store_true"); sv.add_argument("--host", default="127.0.0.1"); sv.set_defaults(f=cmd_serve)
    l = sub.add_parser("list", help="search the printer database"); l.add_argument("query", nargs="?", default="")
    l.add_argument("--by-volume", action="store_true"); l.set_defaults(f=cmd_list)
    p = sub.add_parser("plan", help="split a mesh for your printers")
    p.add_argument("model"); p.add_argument("-p", "--printer", action="append",
                   help="name from DB, 'Name*3' for 3 machines, or custom:300x300x400. Omit to be prompted.")
    p.add_argument("-o", "--out"); p.add_argument("--scale", type=float, default=1.0, help="mesh units -> mm (Blender m export: 1000)")
    p.add_argument("--up", choices=["z", "y", "-y"], default="z", help="model up axis (OBJ/glTF exports are usually y)")
    p.add_argument("--height", type=float, help="scale model so its Z height is this many mm")
    p.add_argument("--margin", type=float, default=3.0, help="unused border per bed side, mm")
    p.add_argument("--dowel-d", type=float, default=8.0); p.add_argument("--dowel-length", type=float, default=20.0)
    p.add_argument("--clearance", type=float, default=0.25); p.add_argument("--no-connectors", action="store_true")
    p.add_argument("--balance", action="store_true", help="split further so all printers get work")
    p.add_argument("--seam-weight", type=float, default=1.5, help="higher = favour tiny seams over fewer parts")
    p.add_argument("--max-parts", type=int, default=200); p.set_defaults(f=cmd_plan)
    a = ap.parse_args(argv)
    if not getattr(a, "f", None):
        a = ap.parse_args(["serve"])
    a.f(a)


if __name__ == "__main__":
    main()
