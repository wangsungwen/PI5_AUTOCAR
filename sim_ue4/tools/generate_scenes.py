"""Generate shared scene geometry in cm. No third-party dependencies.

The room, paths and object positions are estimates, not surveyed reconstruction.
Outputs are consumed directly by UE4 and the software preview renderer.
"""
import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Mesh:
    def __init__(self, material):
        self.data = dict(material=material, vertices=[], normals=[], colors=[], triangles=[])

    def quad(self, points, color):
        a, b, c = points[:3]
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        n = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        length = math.sqrt(sum(x*x for x in n))
        if length < 1e-8:
            raise ValueError("Degenerate quad")
        n = [x / length for x in n]
        offset = len(self.data["vertices"])
        self.data["vertices"].extend([[round(v, 5) for v in p] for p in points])
        self.data["normals"].extend([n] * 4)
        self.data["colors"].extend([color] * 4)
        self.data["triangles"].extend([offset, offset+1, offset+2, offset, offset+2, offset+3])

    def rect(self, x, y, w, h, z, color):
        self.quad([(x,y,z),(x+w,y,z),(x+w,y+h,z),(x,y+h,z)], color)

    def box(self, x, y, z, w, d, h, color):
        # Outward normal on each face.
        self.rect(x, y, w, d, z+h, color)
        self.quad([(x,y,z),(x,y+d,z),(x+w,y+d,z),(x+w,y,z)], color)
        self.quad([(x,y,z),(x+w,y,z),(x+w,y,z+h),(x,y,z+h)], color)
        self.quad([(x+w,y+d,z),(x,y+d,z),(x,y+d,z+h),(x+w,y+d,z+h)], color)
        self.quad([(x,y+d,z),(x,y,z),(x,y,z+h),(x,y+d,z+h)], color)
        self.quad([(x+w,y,z),(x+w,y+d,z),(x+w,y+d,z+h),(x+w,y,z+h)], color)


def path_points(control, samples=24):
    """Catmull-Rom interpolation with linear extrapolation at endpoints."""
    first = [2*control[0][i]-control[1][i] for i in (0, 1)]
    last = [2*control[-1][i]-control[-2][i] for i in (0, 1)]
    extended = [first] + control + [last]
    result = []
    for k in range(1, len(extended)-2):
        p0,p1,p2,p3 = extended[k-1:k+3]
        for j in range(samples):
            t = j/samples
            result.append([
                .5*(2*p1[i]+(-p0[i]+p2[i])*t+
                    (2*p0[i]-5*p1[i]+4*p2[i]-p3[i])*t*t+
                    (-p0[i]+3*p1[i]-3*p2[i]+p3[i])*t*t*t)
                for i in (0, 1)
            ])
    result.append(control[-1])
    return result


def boundaries(path, offset):
    points = []
    for i,p in enumerate(path):
        prev, nxt = path[max(i-1,0)], path[min(i+1,len(path)-1)]
        dx,dy = nxt[0]-prev[0], nxt[1]-prev[1]
        length = math.hypot(dx,dy)
        points.append([p[0]-dy/length*offset, p[1]+dx/length*offset])
    return points


def make_scene(cfg, spec):
    rng = random.Random(1900 + spec["id"])
    length, width = cfg["room"]["length_cm"], cfg["room"]["width_cm"]
    floor = Mesh("M_Gloss" if spec["floor"] == "gloss" else "M_Floor")
    tape, props, emitter = Mesh("M_Tape"), Mesh("M_Props"), Mesh("M_Emitter")
    floor.rect(0, 0, length, width, -0.1, [.17,.16,.12])
    wood = spec["floor"] == "wood"
    tile_x, tile_y = (120, 18) if wood else (60, 60)
    base = [.40,.32,.20] if wood else ([.39,.40,.29] if spec["floor"] == "gloss" else [.53,.49,.37])
    for row, y in enumerate(range(0, width, tile_y)):
        shift = tile_x//2 if row%2 and wood else 0
        for x0 in range(-shift, length, tile_x):
            x, right = max(0,x0), min(length,x0+tile_x)
            variation = rng.uniform(.91,1.09)
            color = [min(1,c*variation) for c in base]
            floor.rect(x+.12, y+.12, right-x-.24, min(tile_y,width-y)-.24, 0, color)
            if wood:
                for _ in range(12):
                    gx = rng.uniform(x+.3, right-.3)
                    gy = rng.uniform(y+.4, y+tile_y-.4)
                    gl = min(rng.uniform(8,60),right-gx-.15)
                    floor.rect(gx,gy,gl,.035,.012,[c*.84 for c in color])
    path = path_points(spec["control_points"])
    half, line_half = cfg["lane_width_cm"]/2, cfg["tape_width_cm"]/2
    for side in (-1, 1):
        inner = boundaries(path, side*half-line_half)
        outer = boundaries(path, side*half+line_half)
        for i in range(len(path)-1):
            tape.quad([[*inner[i],.08],[*inner[i+1],.08],
                       [*outer[i+1],.08],[*outer[i],.08]], [.88,.91,.89])
    h = cfg["room"]["wall_height_cm"]
    props.box(-5,-5,0,length+10,5,h,[.64,.63,.54])
    props.box(-5,width,0,length+10,5,h,[.64,.63,.54])
    props.box(length,0,0,5,width,h,[.64,.63,.54])
    props.box(-5,0,0,5,width,h,[.64,.63,.54])
    props.box(length-4,0,0,4,width,9,[.14,.15,.14])
    props.box(0,width-4,0,length,4,9,[.14,.15,.14])
    # Simplified background landmarks, placed outside the road corridor.
    for cy in (35, 430):
        props.box(length-70,cy,0,60,120,85,[.46,.45,.35])
        props.box(length-71,cy+3,6,1,55,73,[.54,.53,.43])
        props.box(length-71,cy+62,6,1,55,73,[.54,.53,.43])
    props.box(580,40,0,55,45,45,[.43,.31,.16])
    props.box(645,55,0,38,35,38,[.55,.43,.25])
    for x in (180,400,620):
        emitter.box(x-45, 150, h-3, 90, 14, 2, [.9,.96,1])
        emitter.box(x-45, 440, h-3, 90, 14, 2, [.9,.96,1])
    if spec["has_signal"]:
        x,y,z = spec["signal_position"]
        props.box(x-6,y-8,z+3,12,16,38,[.018,.022,.02])
        props.box(x-10,y-11,z,20,22,3,[.025,.028,.025])
        tape.rect(spec["stop_x_cm"],path[0][1]-half,4,2*half,.09,[.88,.91,.89])
    start = path[8]
    yaw = math.degrees(math.atan2(path[9][1]-start[1],path[9][0]-start[0]))
    return {
        "schema_version": 1, "units": "cm", "id": spec["id"],
        "calibration_status": cfg["calibration_status"], "title": spec["title"],
        "reference": spec["reference"], "camera": cfg["camera"],
        "start": [*start,0], "start_yaw": yaw,
        "speed_cm_s": cfg["speed_cm_s"], "turn_deg_s": cfg["turn_deg_s"],
        "bounds": [0,0,length,width], "lane_width_cm": cfg["lane_width_cm"],
        "tape_width_cm": cfg["tape_width_cm"], "centerline": path,
        "has_signal": spec["has_signal"], "signal_position": spec.get("signal_position", [0,0,0]),
        "lights": [[180,180,h-20],[400,320,h-20],[620,440,h-20]],
        "light_intensity": spec["light_intensity"],
        "meshes": [m.data for m in (floor,tape,props,emitter)]
    }


def main():
    cfg = json.loads((ROOT/"scene_config.json").read_text(encoding="utf-8"))
    out = ROOT/"Content"/"Data"
    out.mkdir(parents=True,exist_ok=True)
    for spec in cfg["scenes"]:
        scene = make_scene(cfg,spec)
        target = out/f"scene_{spec['id']}.json"
        target.write_text(json.dumps(scene,separators=(",",":")),encoding="utf-8")
        print(f"{target.name}: {sum(len(m['triangles'])//3 for m in scene['meshes'])} triangles")


if __name__ == "__main__":
    main()
