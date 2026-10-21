"""Make a separate train-only photometric augmentation dataset; preserve polygons."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import albumentations as A
import cv2
import numpy as np
import yaml

from prepare import EXTENSIONS, polygons


def read_image(path):
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Unreadable image: {path}")
    return image


def write_image(path, image):
    ok, encoded = cv2.imencode(path.suffix, image)
    if not ok:
        raise ValueError(f"Cannot encode {path}")
    encoded.tofile(path)


def pipeline(height, width, seed):
    # All are ImageOnlyTransform: no crop, flip, warp or coordinate movement.
    return A.Compose([
        A.RandomBrightnessContrast(brightness_limit=0.15, contrast_limit=0.15, p=0.5),
        A.RandomGamma(gamma_limit=(90, 110), p=0.2),
        A.ToGray(p=0.12),
        A.RandomSunFlare(flare_roi=(0.1, 0.0, 0.9, 0.45),
                         src_radius=max(2, int(min(height, width) * 0.12)),
                         num_flare_circles_range=(1, 3), p=0.15),
        A.AdvancedBlur(blur_limit=(3, 5), p=0.1),
    ], seed=seed, strict=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fraction", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not 0 <= args.fraction <= 1:
        raise ValueError("fraction must be between 0 and 1")
    source, output = args.source.resolve(), args.output.resolve()
    if output.exists() or output.is_relative_to(source):
        raise ValueError("Output must be new and outside the source folder.")
    cfg = yaml.safe_load((source / "data.yaml").read_text(encoding="utf-8"))
    if cfg.get("names") != {0: "road"} or cfg.get("train") != "train/images":
        raise ValueError("Run prepare.py first; this script requires the course layout.")
    images = sorted(p for p in (source / "train/images").iterdir()
                    if p.suffix.lower() in EXTENSIONS)
    if not images:
        raise ValueError("No training images")
    if any(p.stem.startswith("aug_") for p in images):
        raise ValueError("Use original prepared data, not an augmented dataset.")
    for image in images:
        polygons(source / "train/labels" / f"{image.stem}.txt")
    # Only copy the three splits, not caches or previous QC output.
    for split in ("train", "valid", "test"):
        for folder in ("images", "labels"):
            shutil.copytree(source / split / folder, output / split / folder)
    (output / "qc").mkdir()
    rng = np.random.default_rng(args.seed)
    count = round(len(images) * args.fraction)
    indices = sorted(rng.choice(len(images), size=count, replace=False).tolist())
    records = []
    for number, index in enumerate(indices):
        path = images[index]
        label = source / "train/labels" / f"{path.stem}.txt"
        bgr = read_image(path)
        height, width = bgr.shape[:2]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        result = pipeline(height, width, args.seed + index)(image=rgb)["image"]
        aug = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)
        name = f"aug_{path.stem}"
        write_image(output / "train/images" / f"{name}.png", aug)
        shutil.copy2(label, output / "train/labels" / f"{name}.txt")
        if number < 30:
            left, right = bgr.copy(), aug.copy()
            for coords in polygons(label):
                points = np.array(coords).reshape(-1, 2) * [width, height]
                points = np.clip(points, [0, 0], [width - 1, height - 1]).astype(np.int32)
                for canvas in (left, right):
                    cv2.polylines(canvas, [points], True, (0, 255, 0), 2)
            write_image(output / "qc" / f"{name}.jpg", np.hstack([left, right]))
        records.append(dict(source=path.name, output=f"{name}.png", seed=args.seed + index))
    cfg["path"] = output.as_posix()
    (output / "data.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    manifest = dict(albumentations=A.__version__, seed=args.seed,
                    fraction=args.fraction, records=records)
    (output / "augmentation.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Original train: {len(images)}; added: {count}; inspect {output / 'qc'}")


if __name__ == "__main__":
    main()
