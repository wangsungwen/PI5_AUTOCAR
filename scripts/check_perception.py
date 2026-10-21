"""Offline road/traffic smoke test. Never initializes camera, GPIO or motors."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autocar.perception import TrafficDetector, YoloLaneDetector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lane-model', required=True, type=Path)
    parser.add_argument('--traffic-model', required=True, type=Path)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--lane-class', default='road')
    parser.add_argument('--imgsz', type=int, default=416)
    parser.add_argument('--output', type=Path, default=ROOT / 'runs/perception-smoke.json')
    args = parser.parse_args()
    for path in (args.lane_model, args.traffic_model, args.image):
        if not path.exists():
            parser.error(f'Missing input: {path}')
    import cv2
    import numpy as np
    frame = cv2.imdecode(np.fromfile(args.image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        parser.error('Cannot decode image')
    lane = YoloLaneDetector(str(args.lane_model), args.imgsz, class_name=args.lane_class)
    traffic = TrafficDetector(str(args.traffic_model), args.imgsz)
    start = time.perf_counter()
    observation = lane.detect(frame)
    state, confidence = traffic.detect(frame)
    report = {'mode': 'offline; no motor commands', 'image': str(args.image.resolve()),
              'lane_model': str(args.lane_model.resolve()),
              'traffic_model': str(args.traffic_model.resolve()),
              'imgsz': args.imgsz, 'lane': vars(observation),
              'traffic': state, 'traffic_confidence': confidence,
              'lane_classes': lane.model.names, 'traffic_classes': traffic.model.names,
              'cold_inference_seconds': time.perf_counter() - start,
              'limitation': 'One-image smoke test; not accuracy or Pi latency validation.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
