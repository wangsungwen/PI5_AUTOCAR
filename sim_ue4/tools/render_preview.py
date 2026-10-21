"""Software geometry previews, NOT UE4 renders. Requires numpy and Pillow.

Uses exactly the meshes read by the UE4 runtime; no simulated UE material/reflection.
"""
import json
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"preview"
W,H = 960,540


def font(size):
    for path in ("C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path,size)
    return ImageFont.load_default()


def clip_near(vertices, near=1.0):
    result = []
    previous = vertices[-1]
    for current in vertices:
        a,b = previous[2]>=near, current[2]>=near
        if a != b:
            t = (near-previous[2])/(current[2]-previous[2])
            result.append(previous+t*(current-previous))
        if b:
            result.append(current)
        previous = current
    return result


def render(scene):
    yaw,pitch = math.radians(scene["start_yaw"]),math.radians(scene["camera"]["pitch_deg"])
    forward = np.array([math.cos(pitch)*math.cos(yaw),math.cos(pitch)*math.sin(yaw),math.sin(pitch)])
    right = np.array([-math.sin(yaw),math.cos(yaw),0])
    up = np.cross(forward,right)
    camera = np.array(scene["start"],dtype=float)+[0,0,scene["camera"]["height_cm"]]
    focal = W/2/math.tan(math.radians(scene["camera"]["fov_deg"])/2)
    rgb = np.full((H,W,3),[174,180,171],dtype=np.uint8)
    depth = np.full((H,W),np.inf)

    def triangle(v,color):
        p = np.array([[W/2+focal*a[0]/a[2],H/2-focal*a[1]/a[2]] for a in v])
        lo = np.maximum(np.floor(p.min(axis=0)).astype(int),[0,0])
        hi = np.minimum(np.ceil(p.max(axis=0)).astype(int),[W-1,H-1])
        if np.any(hi<lo): return
        xs,ys = np.meshgrid(np.arange(lo[0],hi[0]+1)+.5,np.arange(lo[1],hi[1]+1)+.5)
        (x0,y0),(x1,y1),(x2,y2) = p
        denom = (y1-y2)*(x0-x2)+(x2-x1)*(y0-y2)
        if abs(denom)<1e-8: return
        a = ((y1-y2)*(xs-x2)+(x2-x1)*(ys-y2))/denom
        b = ((y2-y0)*(xs-x2)+(x0-x2)*(ys-y2))/denom
        c = 1-a-b
        inside = (a>=-1e-7)&(b>=-1e-7)&(c>=-1e-7)
        iz = a/v[0][2]+b/v[1][2]+c/v[2][2]
        z = np.divide(1,iz,out=np.full_like(iz,np.inf),where=iz>0)
        region = depth[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
        mask = inside & (z<region)
        region[mask] = z[mask]
        rgb[lo[1]:hi[1]+1,lo[0]:hi[0]+1][mask] = color

    for mesh in scene["meshes"]:
        vertices = np.array(mesh["vertices"])
        rel = vertices-camera
        view = np.stack([rel@right,rel@up,rel@forward],axis=1)
        for i in range(0,len(mesh["triangles"]),3):
            ids = mesh["triangles"][i:i+3]
            polygon = clip_near(view[ids])
            if len(polygon)<3: continue
            normal = np.array(mesh["normals"][ids[0]])
            light = .72+.28*max(0,np.dot(normal,np.array([-.3,-.2,.93])))
            color = np.array(mesh["colors"][ids[0]])*light
            color = (np.clip(color,0,1)**(1/2.2)*255).astype(np.uint8)
            for j in range(1,len(polygon)-1):
                triangle([polygon[0],polygon[j],polygon[j+1]],color)
    # Same lamp positions as the UE runtime; display initial RED state.
    if scene["has_signal"]:
        base = np.array(scene["signal_position"],dtype=float)
        for i,col in enumerate(("#ff3528","#513a15","#173b25")):
            point = base+[-6.5,0,32-i*11]-camera
            z = point@forward
            if z>1:
                x,y = W/2+focal*(point@right)/z,H/2-focal*(point@up)/z
                r = focal*4.25/z
                im = Image.fromarray(rgb)
                ImageDraw.Draw(im).ellipse((x-r,y-r,x+r,y+r),fill=col)
                rgb = np.asarray(im).copy()
    im = Image.fromarray(rgb)
    draw = ImageDraw.Draw(im)
    draw.rectangle((0,0,W,66),fill="#142329")
    draw.text((24,10),scene["title"],font=font(23),fill="white")
    draw.text((24,39),"GEOMETRY PREVIEW / NOT UE4 RENDER / dimensions provisional",font=font(14),fill="#e6c888")
    return im


def topview(scene):
    image = Image.new("RGB",(W,H),"#142329")
    d = ImageDraw.Draw(image)
    scale=.68
    ox,oy=195,70
    x0,y0,x1,y1=scene["bounds"]
    d.rectangle((ox,oy,ox+x1*scale,oy+y1*scale),fill="#80775a",outline="#e1d7bf",width=2)
    path=scene["centerline"]
    from generate_scenes import boundaries
    for side in (-1,1):
        pts=boundaries(path,side*scene["lane_width_cm"]/2)
        d.line([(ox+x*scale,oy+y*scale) for x,y in pts],fill="#f5f7f0",width=3)
    sx,sy,_=scene["start"]
    d.ellipse((ox+sx*scale-5,oy+sy*scale-5,ox+sx*scale+5,oy+sy*scale+5),fill="#58e0bc")
    if scene["has_signal"]:
        x,y,_=scene["signal_position"]
        d.ellipse((ox+x*scale-6,oy+y*scale-6,ox+x*scale+6,oy+y*scale+6),fill="#ff6656")
    d.text((24,12),scene["title"]+" / layout",font=font(23),fill="white")
    d.text((24,500),"Estimated room: 8 x 6 m | lane: 58 cm | tape: 2.5 cm | not surveyed",font=font(17),fill="#e6c888")
    return image


def main():
    OUT.mkdir(exist_ok=True)
    contact = Image.new("RGB",(W,3*(H+50)),"#0c171d")
    for i in (1,2,3):
        scene=json.loads((ROOT/"Content"/"Data"/f"scene_{i}.json").read_text())
        im=render(scene)
        im.save(OUT/f"scene_{i}.png")
        topview(scene).save(OUT/f"layout_{i}.png")
        contact.paste(im,(0,(i-1)*(H+50)))
        print("Rendered software preview:",scene["title"])
    contact.save(OUT/"scenes_contact.png")


if __name__ == "__main__":
    main()
