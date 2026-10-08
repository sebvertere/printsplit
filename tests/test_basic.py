import trimesh
from printsplit import planner as PL
from printsplit.printers import parse_spec

def test_box_splits_and_fits():
    m = trimesh.creation.box(extents=[600, 100, 100]); m.apply_translation(-m.bounds[0])
    fleet = [parse_spec("custom:256x256x256")]
    parts, cuts, nd = PL.plan(m, fleet, PL.Params(), log=lambda *_: None)
    assert len(parts) >= 3
    assert all(p.printer and "NONE" not in p.printer for p in parts)

def test_db_lookup():
    p = parse_spec("Bambu Lab A1*2")
    assert (p.x, p.qty) == (256.0, 2)
