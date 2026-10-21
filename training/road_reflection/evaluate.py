"""Evaluate the union of road instances, grouped by a user-reviewed scene CSV."""
import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np
import yaml

from augment import read_image
from prepare import EXTENSIONS, polygons


def scores(tp, fp, fn, tn):
    def ratio(a, b):
        return a / b if b else None
    return dict(road_iou=ratio(tp, tp + fp + fn),
                road_recall=ratio(tp, tp + fn),
                background_fpr=ratio(fp, fp + tn))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--scenes", type=Path, required=True)
    parser.add_argument("--split", choices=("valid", "test"), default="valid")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    cfg = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    root = Path(cfg["path"])
    if not root.is_absolute():
        raise ValueError("Run prepare.py first to create an absolute dataset path.")
    images = sorted(p for p in (root / args.split / "images").iterdir()
                    if p.suffix.lower() in EXTENSIONS)
    if not images:
        raise ValueError("Empty evaluation split")
    with args.scenes.open(encoding="utf-8-sig", newline="") as stream:
        entries = list(csv.DictReader(stream))
    scene_map = {}
    for row in entries:
        if row["file"] in scene_map or not row["scene"].strip() or row["scene"] == "overall":
            raise ValueError("Duplicate filename, empty scene or reserved scene name: overall")
        scene_map[row["file"]] = row["scene"]
    if set(scene_map) != {p.name for p in images}:
        raise ValueError("Scene CSV must contain exactly one row per evaluation image.")
    from ultralytics import YOLO
    model = YOLO(args.model, task="segment")
    if model.names != {0: "road"}:
        raise ValueError(f"Expected model class 0 = road, got {model.names}")
    totals, records = {}, []
    for path in images:
        image = read_image(path)
        h, w = image.shape[:2]
        gt = np.zeros((h, w), np.uint8)
        for coords in polygons(root / args.split / "labels" / f"{path.stem}.txt"):
            points = np.array(coords).reshape(-1, 2) * [w, h]
            points = np.clip(points, [0, 0], [w - 1, h - 1]).astype(np.int32)
            cv2.fillPoly(gt, [points], 1)
        result = model.predict(image, imgsz=args.imgsz, conf=args.conf, device=args.device,
                               retina_masks=True, verbose=False)[0]
        pred = np.zeros((h, w), dtype=bool)
        if result.masks is not None:
            for mask, cls in zip(result.masks.data, result.boxes.cls):
                if int(cls.item()) == 0:
                    mask = mask.cpu().numpy()
                    if mask.shape != (h, w):
                        raise ValueError("Expected original-size retina masks")
                    pred |= mask >= 0.5
        truth = gt.astype(bool)
        values = [int(np.count_nonzero(x)) for x in
                  (pred & truth, pred & ~truth, ~pred & truth, ~pred & ~truth)]
        scene = scene_map[path.name]
        for group in ("overall", scene):
            total = totals.setdefault(group, dict(images=0, pixels=[0, 0, 0, 0]))
            total["images"] += 1
            total["pixels"] = [a + b for a, b in zip(total["pixels"], values)]
        records.append(dict(file=path.name, scene=scene, **scores(*values)))
    summary = {name: dict(images=v["images"], **scores(*v["pixels"]))
               for name, v in totals.items()}
    report = dict(model=args.model, split=args.split, conf=args.conf, imgsz=args.imgsz,
                  summary=summary, images=records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
