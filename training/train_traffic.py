"""Validate traffic-light data, train YOLO26, evaluate and export best weights."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASSES = ['red_light', 'yellow_light', 'green_light']


def check_dataset(path):
    import yaml
    from PIL import Image
    path = Path(path).resolve()
    config = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
    if not isinstance(config, dict):
        raise ValueError('Dataset YAML must be a mapping')
    names = config.get('names')
    if isinstance(names, dict):
        if set(names) != set(range(len(names))):
            raise ValueError('Class IDs must start at zero and be consecutive')
        names = [names[i] for i in range(len(names))]
    if names not in (CLASSES, CLASSES + ['stop_sign']):
        raise ValueError(f'Expected {CLASSES}, optionally followed by stop_sign')
    root = (path.parent / config.get('path', '.')).resolve()
    resolved = {'path': str(root), 'names': names}
    summary, seen = {}, {}
    for split in ('train', 'val', 'test'):
        if split == 'test' and not config.get(split):
            continue
        entry = config.get(split)
        if not isinstance(entry, str):
            raise ValueError(f'{split}: supply an images directory')
        folder = (root / entry).resolve()
        if folder.parent.name != 'images':
            raise ValueError(f'{split}: expected images/{split} and labels/{split}')
        images = sorted(p for p in folder.rglob('*') if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.bmp', '.webp'})
        if not images:
            raise ValueError(f'No images in {folder}; collect and label data first')
        counts, negatives, labels = [0] * len(names), 0, set()
        label_root = folder.parent.parent / 'labels' / folder.name
        for image in images:
            with Image.open(image) as im:
                im.verify()
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            if digest in seen:
                raise ValueError(f'Duplicate image: {image} and {seen[digest]}')
            seen[digest] = image
            label = label_root / image.relative_to(folder).with_suffix('.txt')
            if label in labels:
                raise ValueError(f'Two images share label {label}')
            labels.add(label)
            if not label.is_file():
                raise ValueError(f'Missing label: {label}; background needs an empty file')
            lines = [s for s in label.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
            negatives += not lines
            for number, line in enumerate(lines, 1):
                try:
                    cls, x, y, w, h = map(float, line.split())
                    valid = (all(math.isfinite(v) for v in (cls, x, y, w, h))
                             and cls.is_integer() and 0 <= cls < len(names)
                             and 0 < w <= 1 and 0 < h <= 1
                             and 0 <= x <= 1 and 0 <= y <= 1
                             and x-w/2 >= -1e-6 and x+w/2 <= 1+1e-6
                             and y-h/2 >= -1e-6 and y+h/2 <= 1+1e-6)
                    if not valid:
                        raise ValueError()
                except ValueError:
                    raise ValueError(f'Invalid YOLO box at {label}:{number}: {line}') from None
                counts[int(cls)] += 1
        orphans = set(label_root.rglob('*.txt')) - labels
        if orphans:
            raise ValueError(f'Label has no image: {sorted(orphans)[0]}')
        if any(n == 0 for n in counts):
            raise ValueError(f'{split}: every declared class needs examples; counts={counts}')
        resolved[split] = str(folder)
        summary[split] = {'images': len(images), 'backgrounds': negatives, 'boxes': dict(zip(names, counts))}
    return resolved, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'training/traffic_lights_only.yaml')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--model', default='yolo26n.pt')
    parser.add_argument('--epochs', type=int, default=60)
    parser.add_argument('--imgsz', type=int, default=416)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--device', default='cpu', help='cpu or CUDA index, e.g. 0')
    parser.add_argument('--project', type=Path, default=ROOT / 'runs/traffic')
    parser.add_argument('--name', default='lights')
    parser.add_argument('--export', choices=('ncnn', 'none'), default='ncnn')
    args = parser.parse_args()
    if min(args.epochs, args.imgsz, args.batch) <= 0 or args.imgsz % 32:
        parser.error('epochs/batch must be positive; imgsz must be a positive multiple of 32')
    if not args.name or args.name in {'.', '..'} or any(c in args.name for c in '/\\:'):
        parser.error('name must be a single directory name')
    try:
        resolved, summary = check_dataset(args.data)
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Dataset check failed: {exc}\n')
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.check_only:
        return
    import yaml
    from ultralytics import YOLO
    run = args.project.resolve() / args.name
    run.mkdir(parents=True, exist_ok=False)
    data = run / 'dataset.resolved.yaml'
    data.write_text(yaml.safe_dump(resolved, allow_unicode=True), encoding='utf-8')
    (run / 'dataset_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    model = YOLO(args.model, task='detect')
    model.train(data=str(data), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                device=args.device, workers=0, project=str(run.parent), name=run.name,
                exist_ok=True, seed=42, deterministic=True,
                hsv_h=0.0, hsv_s=0.25, hsv_v=0.25, bgr=0.0,
                degrees=0.0, flipud=0.0, fliplr=0.0, mosaic=0.2,
                mixup=0.0, close_mosaic=10)
    best = Path(model.trainer.best)
    if not best.is_file():
        raise FileNotFoundError(f'No best checkpoint: {best}')
    trained = YOLO(str(best), task='detect')
    split = 'test' if 'test' in resolved else 'val'
    metrics = trained.val(data=str(data), split=split, imgsz=args.imgsz,
                          device=args.device, project=str(run), name='evaluation')
    report = {'checkpoint': str(best), 'evaluation_split': split,
              'metrics': {k: float(v) for k, v in metrics.results_dict.items()}}
    (run / 'evaluation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Best checkpoint: {best}')
    if args.export == 'ncnn':
        exported = trained.export(format='ncnn', imgsz=args.imgsz, batch=1, device='cpu')
        print(f'NCNN model directory: {exported}')


if __name__ == '__main__':
    main()
