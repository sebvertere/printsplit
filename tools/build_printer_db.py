#!/usr/bin/env python3
"""Build printsplit/printers.json from OrcaSlicer's open machine profiles.

Usage:
  git clone --depth 1 --filter=blob:none --sparse https://github.com/SoftFever/OrcaSlicer.git
  (cd OrcaSlicer && git sparse-checkout set resources/profiles)
  python tools/build_printer_db.py OrcaSlicer/resources/profiles printsplit/printers.json

Resolves each profile's `inherits` chain, reads printable_area / printable_height,
and keeps one entry per printer model (nozzle variants share a bed).
"""
import json, re, sys
from pathlib import Path


def load_vendor(vdir: Path):
    profs = {}
    for f in (vdir / "machine").glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if d.get("name"):
            profs[d["name"]] = d
    return profs


def resolve(name, profs, seen=None):
    seen = seen or set()
    if name in seen or name not in profs:
        return {}
    seen.add(name)
    d = profs[name]
    base = resolve(d["inherits"], profs, seen) if d.get("inherits") else {}
    return {**base, **d}


def parse_area(area):
    pts = [tuple(float(v) for v in p.split("x")) for p in area]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return max(xs) - min(xs), max(ys) - min(ys), len(pts)


def main(src, out):
    src = Path(src)
    db = {}
    for vdir in sorted(p for p in src.iterdir() if p.is_dir() and (p / "machine").is_dir()):
        profs = load_vendor(vdir)
        for name, d in profs.items():
            if d.get("instantiation") != "true":
                continue
            r = resolve(name, profs)
            model = r.get("printer_model")
            if not model or "printable_area" not in r or "printable_height" not in r:
                continue
            try:
                x, y, npts = parse_area(r["printable_area"])
                z = float(r["printable_height"])
            except Exception:
                continue
            if x <= 0 or y <= 0 or z <= 0:
                continue
            key = (vdir.name, model)
            # prefer the plain 0.4 variant when several exist
            score = 1 if r.get("printer_variant") == "0.4" else 0
            if key in db and db[key][0] >= score:
                continue
            # delta / round beds have many polygon points
            shape = "circle" if npts > 8 else "rect"
            db[key] = (score, {
                "vendor": vdir.name, "model": model,
                "x": round(x, 1), "y": round(y, 1), "z": round(z, 1),
                "shape": shape,
            })
    printers = sorted((v[1] for v in db.values()), key=lambda p: (p["vendor"], p["model"]))
    Path(out).write_text(json.dumps({
        "source": "OrcaSlicer resources/profiles (AGPL-3.0 project; values are public machine specs)",
        "units": "mm",
        "printers": printers,
    }, indent=1))
    print(f"{len(printers)} printers from {len({p['vendor'] for p in printers})} vendors -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
