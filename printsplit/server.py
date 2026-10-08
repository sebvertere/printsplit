"""Tiny local web server (stdlib only) for the printsplit UI."""
from __future__ import annotations
import base64, io, json, shutil, tempfile, threading, uuid, webbrowser, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np
from . import planner as PL
from .output import write_all, PALETTE
from .printers import Printer, load_db

WEB = Path(__file__).with_name("web") / "index.html"
SESS = {}   # id -> {"path": Path, "name": str, "dir": Path, "zip": bytes}
LOCK = threading.Lock()


def b64tris(mesh):
    return base64.b64encode(mesh.triangles.astype("<f4").reshape(-1).tobytes()).decode()


def load_for(sid, o):
    s = SESS[sid]
    return PL.load_mesh(s["path"], float(o.get("scale") or 1), float(o["height"]) if o.get("height") else None, o.get("up") or "z")


def api_upload(name, body):
    sid = uuid.uuid4().hex[:10]
    d = Path(tempfile.mkdtemp(prefix="printsplit_"))
    safe = "".join(c for c in Path(name).name if c.isalnum() or c in "._- ") or "model.stl"
    path = d / safe
    path.write_bytes(body)
    SESS[sid] = {"path": path, "name": safe, "dir": d}
    m = PL.load_mesh(path)
    ext = [float(v) for v in m.extents]
    guess_up = "y" if safe.lower().endswith((".obj", ".glb", ".gltf", ".fbx")) and ext[1] > ext[2] * 1.2 else "z"
    return {"id": sid, "name": safe, "extents": ext, "faces": int(len(m.faces)), "watertight": bool(m.is_watertight),
            "bodies": len(m.split(only_watertight=False)), "guess_up": guess_up}


def api_preview(o):
    m = load_for(o["id"], o)
    return {"extents": [float(v) for v in m.extents], "pos": b64tris(m)}


def api_plan(o):
    sid = o["id"]; s = SESS[sid]
    m = load_for(sid, o)
    notes = PL.repair(m)
    fleet = [Printer(p["name"], float(p["x"]), float(p["y"]), float(p["z"]), p.get("shape", "rect"), int(p.get("qty", 1))) for p in o["fleet"]]
    if o.get("single"):
        fleet = fleet[:1]; fleet[0].qty = 1
    q = o.get("params", {})
    P = PL.Params(margin=float(q.get("margin", 3)), dowel_d=float(q.get("dowel_d", 8)), dowel_depth=float(q.get("dowel_length", 20)) / 2,
                  connectors=bool(q.get("connectors", True)), balance=bool(q.get("balance", False)) and not o.get("single"),
                  seam_weight=float(q.get("seam_weight", 1.5)), smart_orient=bool(q.get("smart_orient", True)),
                  manual_cuts=[("xyz".index(c["axis"].lower()), float(c["pos"])) for c in q.get("manual_cuts", [])])
    log = list(notes)
    parts, cuts, nd = PL.plan(m, fleet, P, log=log.append)
    out = s["dir"] / "out"
    shutil.rmtree(out, ignore_errors=True)
    write_all(out, parts, fleet, cuts, nd, P, s["name"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in out.rglob("*"):
            if f.is_file() and f.name != "plan.html":
                z.write(f, f.relative_to(out))
    s["zip"] = buf.getvalue()
    colors = {}
    res = []
    for pt in parts:
        base = pt.printer.split(" #")[0]
        colors.setdefault(base, PALETTE[len(colors) % len(PALETTE)])
        res.append({"id": pt.id, "printer": pt.printer, "color": colors[base], "pos": b64tris(pt.mesh), "box": pt.box,
                    "extents": [round(float(v), 1) for v in pt.mesh.extents], "cm3": round(abs(pt.mesh.volume) / 1000, 1),
                    "up": ("+" if pt.up_sign > 0 else "-") + "XYZ"[pt.up_axis], "hint": pt.hint, "height": round(pt.height, 1)})
    return {"parts": res, "cuts": cuts, "dowels": int(nd), "legend": colors, "log": log,
            "oversize": [r["id"] for r in res if "NONE" in r["printer"]]}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", extra=None):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            self._send(200, WEB.read_bytes(), "text/html; charset=utf-8")
        elif u.path == "/api/printers":
            self._send(200, load_db())
        elif u.path == "/api/download":
            s = SESS.get(parse_qs(u.query).get("id", [""])[0])
            if not s or "zip" not in s:
                return self._send(404, {"error": "no plan yet"})
            self._send(200, s["zip"], "application/zip", {"Content-Disposition": f'attachment; filename="{Path(s["name"]).stem}_split.zip"'})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            with LOCK:
                if u.path == "/api/upload":
                    r = api_upload(parse_qs(u.query).get("name", ["model.stl"])[0], body)
                elif u.path == "/api/preview":
                    r = api_preview(json.loads(body))
                elif u.path == "/api/plan":
                    r = api_plan(json.loads(body))
                else:
                    return self._send(404, {"error": "not found"})
            self._send(200, r)
        except Exception as e:  # surface to UI
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, *a):
        pass


def serve(port=8765, open_browser=True, host="127.0.0.1"):
    srv = ThreadingHTTPServer((host, port), H)
    url = f"http://localhost:{port}"
    print(f"printsplit running at {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
