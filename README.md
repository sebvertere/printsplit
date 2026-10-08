# PrintSplit

Open-source tool that splits a big model (armor, costume pieces, props) into parts that fit the printers you actually own — one printer or a mixed fleet — with dowel sockets on every seam, a 3D preview showing each printer's build volume around its part, and a Rhino importer.

**Try it:** [live demo viewer](https://sebvertere.github.io/printsplit/demo/) · [Open in GitHub Codespaces](https://codespaces.new/sebvertere/printsplit) (runs in your browser, no install)

## Install
    pip install git+https://github.com/sebvertere/printsplit      # or: pipx install git+https://github.com/sebvertere/printsplit
    printsplit                                               # opens the web app on http://localhost:8765


Split a body-sized mesh (armor, props) into pieces that fit *your* printers, with alignment-dowel sockets on every seam.

## Setup
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

## Web app (easiest)
    .venv/bin/python -m printsplit          # opens http://localhost:8765

1. Drop in your STL/OBJ/3MF/GLB (set real height in mm or scale, and the up axis).
2. Type to search printers ("pru" → Prusa…), click to add, +/− for how many of each.
   Tick **I only have one printer** to plan for one machine printed part-by-part over days.
3. **Plan the split** → 3D view shows every part with its printer's build volume drawn as a box
   around it. Explode slider, click a part to isolate, download everything as a zip.

**Advanced settings** (collapsed): real height / scale / up axis, dowel size, bed margin, seam preference,
print-orientation hints, and **manual cut planes** (axis + position, shown live in 3D, applied before the auto-cuts).
Click a part (in the list or the 3D view) to isolate it; click it again or click anywhere else to see everything.

## Rhino
`rhino/import_printsplit.py` → open in Rhino's Script Editor, run, pick the output's `plan.json`.
Parts land on `PrintSplit::<printer>` layers (with user text: printer, suggested print-up, hint), printer volume
boxes on `PrintSplit::Volumes::…`, and optionally flat print-ready copies on `PrintSplit::PrintReady::…`.
Tested in Rhino 8.

`examples/WomanBody13.obj` — CC0 female figure by Daniel Quevedo ([OpenGameArt](https://opengameart.org/content/female-body)); Y-up, set height ≈ 1650.

## Command line
    # browse the bundled DB (385 printers, from OrcaSlicer's open profiles)
    .venv/bin/python -m printsplit list "bambu"  --by-volume

    # explicit fleet (Name*N = N identical machines; custom:XxYxZ for anything else)
    .venv/bin/python -m printsplit plan chestplate.stl --scale 1000 \
        -p "Bambu Lab H2D" -p "Prusa MK4S*2" -p custom:300x300x400

    # one printer, many days
    .venv/bin/python -m printsplit plan armor.stl -p "Bambu Lab A1"

    # no -p => it asks how many printers you have and which
    .venv/bin/python -m printsplit plan armor.stl

Output folder: `plan.html` (3D preview, exploded, coloured per printer), `plan.json`,
`assembled/` (CAD coordinates, for re-checking fit), `print_ready/` (rotated flat on the bed),
`dowel_x1.stl` (print as many as `plan.json` says).

Export from Blender as STL/OBJ/3MF. `--scale 1000` if Blender units were metres; `--height 1800` to force a Z height in mm.

## How it decides
Cuts are axis-aligned planes. For each oversized piece it scores candidate planes by
(estimated pieces left, using the best printer) + seam-weight × cross-section area, so seams
land at necks, waists, ankles. Parts go largest-first to the printer slot with the least load.
Tweak `--seam-weight` (higher = smaller seams, more parts), `--margin`, `--balance`.

## Limits (v0.1)
- Mesh must be watertight (Blender 3D-Print Toolbox → Make Manifold).
- Thin shells (< dowel + 2×wall) get glue-only seams; hollow your armor with ≥ 4 mm walls and
  dowels still need solid material — consider `--dowel-d 5 --dowel-length 14`.
- Cuts are along world axes; no curved/zig-zag seams.

## License & credits
Code: MIT. Printer volumes were extracted from [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer)'s machine profiles (AGPL-3.0 project; only public machine specs are used, rebuild any time with `tools/build_printer_db.py`). Example model: CC0, Daniel Quevedo / OpenGameArt. Geometry by [trimesh](https://trimsh.org) and [manifold3d](https://github.com/elalish/manifold).

Printer data: [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer) `resources/profiles`; rebuild with `tools/build_printer_db.py`.
