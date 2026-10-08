"""Printer fleet model + lookup in the bundled OrcaSlicer-derived database."""
from __future__ import annotations
import itertools, json, math, re
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).with_name("printers.json")


@dataclass
class Printer:
    name: str
    x: float
    y: float
    z: float
    shape: str = "rect"   # "circle" => x is the diameter
    qty: int = 1

    def usable(self, margin: float):
        return (max(self.x - 2 * margin, 1), max(self.y - 2 * margin, 1), self.z)

    @property
    def volume(self):
        return self.x * self.y * self.z

    def fit_all(self, extents, margin: float):
        """Every up-axis this part could be printed along: [(axis, height)]."""
        cx, cy, cz = self.usable(margin)
        out = []
        for up in range(3):
            a, b = [extents[i] for i in range(3) if i != up]
            if extents[up] > cz:
                continue
            ok = math.hypot(a, b) <= cx if self.shape == "circle" else ((a <= cx and b <= cy) or (b <= cx and a <= cy))
            if ok:
                out.append((up, extents[up]))
        return out

    def fit(self, extents, margin: float):
        """Best printing orientation for a part with bbox `extents` (world x,y,z).

        Returns (up_axis, height) or None. Any axis may be pointed up; the other two
        must fit the bed (either way round, or inside the circle for delta beds).
        Prefers the lowest print height (more stable).
        """
        cx, cy, cz = self.usable(margin)
        best = None
        for up in range(3):
            a, b = [extents[i] for i in range(3) if i != up]
            h = extents[up]
            if h > cz:
                continue
            if self.shape == "circle":
                ok = math.hypot(a, b) <= cx
            else:
                ok = (a <= cx and b <= cy) or (b <= cx and a <= cy)
            if ok and (best is None or h < best[1]):
                best = (up, h)
        return best


def load_db():
    return json.loads(DB_PATH.read_text())["printers"]


def search(query: str, db=None):
    db = db or load_db()
    q = query.lower().strip()
    exact = [p for p in db if p["model"].lower() == q]
    if exact:
        return exact
    toks = q.split()
    return [p for p in db if all(t in (p["vendor"] + " " + p["model"]).lower() for t in toks)]


def parse_spec(spec: str, db=None) -> Printer:
    """'Bambu Lab A1', 'Prusa XL*2', 'custom:300x300x400', 'Big Boy=500x500x600'."""
    qty = 1
    m = re.match(r"^(.*?)\s*[*x]\s*(\d+)$", spec) if "*" in spec else None
    if m:
        spec, qty = m.group(1), int(m.group(2))
    m = re.match(r"^(?:custom:)?([^=:]*?)[=:]?\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)$", spec, re.I)
    if m:
        name = m.group(1).strip() or "Custom"
        return Printer(name, float(m.group(2)), float(m.group(3)), float(m.group(4)), qty=qty)
    hits = search(spec, db)
    if not hits:
        raise ValueError(f"No printer matches '{spec}'. Try `printsplit list {spec.split()[0]}`.")
    if len(hits) > 1:
        names = ", ".join(h["model"] for h in hits[:12])
        raise ValueError(f"'{spec}' is ambiguous ({len(hits)} matches): {names}")
    h = hits[0]
    return Printer(h["model"], h["x"], h["y"], h["z"], h.get("shape", "rect"), qty)
