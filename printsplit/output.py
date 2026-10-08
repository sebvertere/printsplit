"""Write STLs, plan.json and a self-contained 3D preview (plan.html)."""
from __future__ import annotations
import base64, json
from pathlib import Path
import numpy as np
import trimesh
from . import connectors as C

PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#b07aa1", "#edc948", "#76b7b2", "#9c755f"]


def print_ready(part, margin_x=None):
    """Rotate so the chosen up direction is +Z, drop onto the bed at the origin."""
    m = part.mesh.copy()
    up = np.zeros(3); up[part.up_axis] = part.up_sign
    m.apply_transform(trimesh.geometry.align_vectors(up, [0, 0, 1]))
    m.apply_translation(-m.bounds[0])
    return m


def write_all(out, parts, fleet, cuts, n_dowels, P, model_name):
    out = Path(out); (out / "assembled").mkdir(parents=True, exist_ok=True); (out / "print_ready").mkdir(exist_ok=True)
    colors = {}
    rows = []
    for pt in parts:
        base = pt.printer.split(" #")[0]
        colors.setdefault(base, PALETTE[len(colors) % len(PALETTE)])
        slug = "".join(c if c.isalnum() else "_" for c in pt.printer).strip("_")
        pt.mesh.export(out / "assembled" / f"{pt.id}_{slug}.stl")
        print_ready(pt).export(out / "print_ready" / f"{pt.id}_{slug}.stl")
        rows.append({"id": pt.id, "printer": pt.printer, "extents_mm": [round(float(v), 1) for v in pt.mesh.extents],
                     "volume_cm3": round(abs(pt.mesh.volume) / 1000, 1), "print_up_axis": "XYZ"[pt.up_axis],
                     "print_height_mm": round(pt.height, 1),
                     "print_up_sign": pt.up_sign, "orientation_hint": pt.hint, "printer_volume_box": pt.box})
    if n_dowels:
        d = C.dowel_mesh(P.dowel_d, P.dowel_depth); d.export(out / "dowel_x1.stl")
    plan = {"model": model_name, "parts": rows, "cuts": cuts, "dowels_needed": int(n_dowels),
            "dowel": {"diameter": P.dowel_d, "length": 2 * P.dowel_depth, "socket_clearance": P.clearance},
            "fleet": [{"name": p.name, "volume": [p.x, p.y, p.z], "qty": p.qty} for p in fleet]}
    (out / "plan.json").write_text(json.dumps(plan, indent=1))
    blobs = []
    for pt, r in zip(parts, rows):
        tri = pt.mesh.triangles.astype("<f4").reshape(-1)
        base = pt.printer.split(" #")[0]
        blobs.append({"id": pt.id, "printer": pt.printer, "color": colors.get(base, "#888"),
                      "pos": base64.b64encode(tri.tobytes()).decode(), "info": r})
    centre = parts[0].mesh.bounds if parts else np.zeros((2, 3))
    allb = np.array([p.mesh.bounds for p in parts]); lo, hi = allb[:, 0].min(0), allb[:, 1].max(0)
    html = HTML.replace("__DATA__", json.dumps({"parts": blobs, "lo": lo.tolist(), "hi": hi.tolist(),
                        "legend": colors, "cuts": len(cuts), "dowels": int(n_dowels), "name": model_name,
                        "dowel": plan["dowel"]}))
    (out / "plan.html").write_text(html)
    return plan


HTML = r"""<!doctype html><meta charset=utf-8><title>PrintSplit plan</title>
<style>body{margin:0;font:14px system-ui;background:#16181d;color:#eee;display:flex;height:100vh}
#v{flex:1}#s{width:340px;padding:14px;overflow:auto;background:#1f222a}h2{margin:.2em 0}
.row{padding:6px 8px;border-radius:6px;cursor:pointer;margin:2px 0;font-size:12px}.row:hover{background:#2c313c}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}input{width:100%}small{color:#9aa}</style>
<div id=v></div><div id=s><h2 id=t></h2><small id=sum></small><p>Explode<input id=ex type=range min=0 max=1 step=.01 value=.25></p>
<div id=leg></div><hr style="border-color:#333"><div id=rows></div></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const D=__DATA__;const el=document.getElementById('v');const W=()=>Math.max(innerWidth-340,200);
const R=new THREE.WebGLRenderer({antialias:true});R.setSize(W(),innerHeight);el.appendChild(R.domElement);
const S=new THREE.Scene();S.background=new THREE.Color(0x16181d);
const C=new THREE.PerspectiveCamera(40,W()/innerHeight,1,1e5);
addEventListener('resize',()=>{R.setSize(W(),innerHeight);C.aspect=W()/innerHeight;C.updateProjectionMatrix()});
S.add(new THREE.HemisphereLight(0xffffff,0x444455,.9));const dl=new THREE.DirectionalLight(0xffffff,.8);dl.position.set(1,2,3);S.add(dl);
const ctr=new THREE.Vector3((D.lo[0]+D.hi[0])/2,(D.lo[1]+D.hi[1])/2,(D.lo[2]+D.hi[2])/2);
const size=Math.max(D.hi[0]-D.lo[0],D.hi[1]-D.lo[1],D.hi[2]-D.lo[2]);
C.up.set(0,0,1);C.position.set(ctr.x+size*1.3,ctr.y-size*1.6,ctr.z+size*.6);
const O=new THREE.OrbitControls(C,R.domElement);O.target.copy(ctr);O.update();
const meshes=[];
D.parts.forEach(p=>{const b=atob(p.pos),u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);
const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(new Float32Array(u.buffer),3));g.computeVertexNormals();g.computeBoundingBox();
const m=new THREE.Mesh(g,new THREE.MeshStandardMaterial({color:p.color,roughness:.6,metalness:.1}));
const c=new THREE.Vector3();g.boundingBox.getCenter(c);m.userData={c,p};S.add(m);meshes.push(m)});
function explode(k){meshes.forEach(m=>{const d=m.userData.c.clone().sub(ctr).multiplyScalar(k);m.position.copy(d)})}
ex.oninput=()=>explode(+ex.value);explode(.25);
t.textContent=D.name;sum.textContent=`${D.parts.length} parts · ${D.cuts} cuts · ${D.dowels} dowels (Ø${D.dowel.diameter}×${D.dowel.length} mm)`;
leg.innerHTML=Object.entries(D.legend).map(([n,c])=>`<div><span class=sw style="background:${c}"></span>${n}</div>`).join('');
rows.innerHTML=D.parts.map((p,i)=>`<div class=row data-i=${i}><span class=sw style="background:${p.color}"></span><b>${p.id}</b> → ${p.printer}<br><small>${p.info.extents_mm.join(' × ')} mm · ${p.info.volume_cm3} cm³ · print ${p.info.print_up_axis}-up (${p.info.print_height_mm} mm tall)</small></div>`).join('');
document.querySelectorAll('.row').forEach(r=>r.onclick=()=>{const i=+r.dataset.i;meshes.forEach((m,j)=>m.material.opacity=(i==j)?1:.15,meshes.forEach(m=>m.material.transparent=true))});
(function a(){requestAnimationFrame(a);R.render(S,C)})();
</script>"""
