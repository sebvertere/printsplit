# Contributing

PrintSplit is a small, hackable tool — improvements of any size are welcome.

    git clone https://github.com/sebvertere/printsplit && cd printsplit
    python -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest

## Map of the code
| File | Job |
|---|---|
| `printsplit/printers.py` | Printer model, search, "does this part fit, and which way up?" |
| `printsplit/planner.py` | Mesh repair, cut selection, part→printer assignment, orientation hints |
| `printsplit/connectors.py` | Dowel placement + socket booleans |
| `printsplit/output.py` | STL / plan.json / standalone viewer export |
| `printsplit/server.py`, `web/index.html` | Local web app (stdlib server + three.js) |
| `rhino/import_printsplit.py` | Rhino importer |
| `tools/build_printer_db.py` | Rebuilds `printers.json` from OrcaSlicer profiles |

## Ideas that would help most
- **Fully in-browser version** (no install): port the planner to JS with `manifold-3d` (WASM) + three.js, or run it on Pyodide.
- Non-axis-aligned / curved / zig-zag seams, and dragging cut planes directly in 3D.
- Better seam scoring (hide seams along natural edges, avoid faces/detail).
- Hollowing / shell-aware connectors (pegs for thin armor, magnets, snap-fits).
- Bed packing (several parts per plate) and print-time estimates.
- Blender add-on and Fusion / Grasshopper front-ends.
- Refreshing printer data; adding resin printers.
