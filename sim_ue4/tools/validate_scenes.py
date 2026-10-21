"""Validate geometry, camera, lane bounds and scene separation before UE import."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate(scene):
    assert scene["schema_version"] == 1 and scene["units"] == "cm"
    assert scene["calibration_status"] == "provisional_not_measured"
    camera = scene["camera"]
    assert 1 < camera["height_cm"] < 200
    assert -80 < camera["pitch_deg"] < 20
    assert 10 < camera["fov_deg"] < 150
    assert 0 < scene["tape_width_cm"] < scene["lane_width_cm"]
    assert 0 < scene["speed_cm_s"] < 1000
    assert 0 < scene["turn_deg_s"] < 360
    x0,y0,x1,y1 = scene["bounds"]
    margin = (scene["lane_width_cm"] + scene["tape_width_cm"])/2
    for x,y in scene["centerline"]:
        assert x0+margin < x < x1-margin and y0+margin < y < y1-margin
    for mesh in scene["meshes"]:
        vertices, triangles = mesh["vertices"], mesh["triangles"]
        assert len(vertices) == len(mesh["normals"]) == len(mesh["colors"])
        assert len(triangles)%3 == 0
        assert all(len(v) == 3 and all(math.isfinite(c) for c in v) for v in vertices)
        assert all(0 <= v <= 1 for color in mesh["colors"] for v in color)
        for i in range(0,len(triangles),3):
            inds = triangles[i:i+3]
            assert all(isinstance(j,int) and 0 <= j < len(vertices) for j in inds)
            a,b,c = [vertices[j] for j in inds]
            u,v = [b[k]-a[k] for k in range(3)], [c[k]-a[k] for k in range(3)]
            cross = [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
            assert sum(t*t for t in cross) > 1e-12, "Degenerate triangle"
            normal = mesh["normals"][inds[0]]
            assert abs(sum(n*n for n in normal)-1) < 1e-5
            assert sum(cross[k]*normal[k] for k in range(3)) > 0
    assert all(len(p) == 3 for p in scene["lights"])
    if scene["has_signal"]:
        sx,sy,sz = scene["signal_position"]
        assert x0 < sx < x1 and y0 < sy < y1 and sz >= 0


def main():
    scenes = [json.loads((ROOT/"Content"/"Data"/f"scene_{i}.json").read_text()) for i in (1,2,3)]
    assert [s["id"] for s in scenes] == [1,2,3]
    assert len({s["title"] for s in scenes}) == 3
    assert [s["has_signal"] for s in scenes] == [False,False,True]
    assert len({json.dumps(s["centerline"]) for s in scenes}) == 3
    for scene in scenes:
        validate(scene)
        print(f"PASS scene {scene['id']}: camera, lane bounds, triangles, normals, material colors")
    report = {
        "geometry_validation": "passed",
        "scenes": 3,
        "ue4_compilation": "not_run_editor_and_cpp_toolchain_not_found",
        "ue4_runtime_switching": "not_run",
        "airsim_integration": "not_implemented",
        "calibration": "provisional_not_measured",
        "preview": "software_geometry_preview_not_ue4_render"
    }
    (ROOT/"validation.json").write_text(json.dumps(report,indent=2)+"\n")


if __name__ == "__main__":
    main()
