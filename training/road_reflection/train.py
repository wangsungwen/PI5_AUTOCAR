"""Train a road segmentation baseline or reflection experiment."""
import argparse
from pathlib import Path


PROFILES = {
    "baseline": dict(hsv_h=0.0, hsv_s=0.3, hsv_v=0.2, scale=0.2,
                     perspective=0.0, mosaic=0.0),
    "reflection": dict(hsv_h=0.0, hsv_s=0.5, hsv_v=0.3, scale=0.3,
                       perspective=0.0002, mosaic=0.2),
    # Use after Roboflow/offline photometric augmentation to reduce stacking.
    "stacked": dict(hsv_h=0.0, hsv_s=0.3, hsv_v=0.15, scale=0.2,
                    perspective=0.0002, mosaic=0.0),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--profile", choices=PROFILES, default="baseline")
    parser.add_argument("--name", required=True)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="0")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not args.data.is_file():
        raise FileNotFoundError(args.data)
    if Path("runs/road", args.name).exists():
        raise FileExistsError("Choose a new run name to avoid ambiguous result paths.")
    from ultralytics import YOLO

    model = YOLO("yolo26n-seg.pt")
    model.train(
        data=str(args.data.resolve()), epochs=args.epochs, imgsz=args.imgsz,
        batch=args.batch, device=args.device, workers=0, seed=args.seed,
        deterministic=True, project="runs/road", name=args.name, exist_ok=False,
        optimizer="AdamW", lr0=0.001, patience=0,
        degrees=0.0, translate=0.05, shear=0.0, flipud=0.0, fliplr=0.0,
        mixup=0.0, copy_paste=0.0, close_mosaic=10,
        **PROFILES[args.profile],
    )
    print(f"Best checkpoint: {model.trainer.best}")


if __name__ == "__main__":
    main()
