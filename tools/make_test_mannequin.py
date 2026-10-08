import sys, trimesh, numpy as np
def cap(a,b,r):
    a,b=np.array(a,float),np.array(b,float); v=b-a; L=np.linalg.norm(v)
    m=trimesh.creation.capsule(height=L,radius=r,count=[24,24])
    T=trimesh.geometry.align_vectors([0,0,1],v/L); T[:3,3]=(a+b)/2; m.apply_transform(T); return m
parts=[cap((0,0,900),(0,0,1400),150),cap((0,0,1450),(0,0,1500),55),cap((0,0,1620),(0,0,1620.1),100),
 cap((-100,0,880),(-110,0,500),75),cap((-110,0,480),(-110,0,90),55),cap((100,0,880),(110,0,500),75),cap((110,0,480),(110,0,90),55),
 cap((-180,0,1380),(-330,0,1100),50),cap((180,0,1380),(330,0,1100),50)]
m=trimesh.boolean.union(parts,engine="manifold"); m.export(sys.argv[1]); print(m.extents, m.is_watertight)
