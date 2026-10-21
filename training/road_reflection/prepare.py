"""Validate a one-class Roboflow polygon export and create a clean course dataset."""
from __future__ import annotations

import argparse
import hashlib
import math
import shutil
from pathlib import Path

import yaml

EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}


def polygons(path: Path) -> list[list[float]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        values = [float(x) for x in line.split()]
        if (len(values) < 7 or len(values) % 2 != 1 or values[0] != 0
                or not all(math.isfinite(v) and 0 <= v <= 1 for v in values[1:])):
            raise ValueError(f"Invalid class-0 polygon: {path}:{number}")
        points = list(zip(values[1::2], values[2::2]))
        area = abs(sum(x * v - u * y for (x, y), (u, v)
                       in zip(points, points[1:] + points[:1]))) / 2
        if len(set(points)) < 3 or area < 1e-9:
            raise ValueError(f"Degenerate polygon: {path}:{number}")
        rows.append(values[1:])
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output.exists() or output.is_relative_to(source):
        raise ValueError("Output must be new and outside the source folder.")
    cfg = yaml.safe_load((source / "data.yaml").read_text(encoding="utf-8-sig"))
    names = cfg.get("names")
    values = list(names.values()) if isinstance(names, dict) else names
    if values not in (["road"], ["Road-Area"], ["road-area"]):
        raise ValueError("This course expects exactly one class: 0 = road.")
    inventory, seen = {}, {}
    for split in ("train", "valid", "test"):
        images = sorted(p for p in (source / split / "images").glob("*")
                        if p.suffix.lower() in EXTENSIONS)
        if not images:
            raise ValueError(f"No images in {source / split / 'images'}")
        stems = set()
        for image in images:
            stem = image.stem.casefold()
            if stem in stems:
                raise ValueError(f"Duplicate image stem in {split}: {image}")
            stems.add(stem)
            label = source / split / "labels" / f"{image.stem}.txt"
            if not label.is_file():
                raise ValueError(f"Missing label (use empty txt for reviewed negatives): {label}")
            polygons(label)
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            if digest in seen and seen[digest] != split:
                raise ValueError(f"Identical image in {seen[digest]} and {split}: {image}")
            seen[digest] = split
        inventory[split] = images
    for split, images in inventory.items():
        for sub in ("images", "labels"):
            (output / split / sub).mkdir(parents=True, exist_ok=True)
        for image in images:
            shutil.copy2(image, output / split / "images" / image.name)
            label = source / split / "labels" / f"{image.stem}.txt"
            shutil.copy2(label, output / split / "labels" / label.name)
    config = dict(path=output.as_posix(), train="train/images", val="valid/images",
                  test="test/images", names={0: "road"})
    (output / "data.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print({split: len(images) for split, images in inventory.items()})
    print(output / "data.yaml")


if __name__ == "__main__":
    main()
