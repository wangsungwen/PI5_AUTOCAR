"""Run the unchanged RPI5_AutoCAR Autopilot inside AirSim.

Usage (from the project root, with AirSim already running):
    python -m sim_airsim.run_autopilot --show
    python -m sim_airsim.run_autopilot --lane-backend opencv --duration 60
    python -m sim_airsim.run_autopilot --traffic-required --record sim_runs/run1.mp4

Outputs go to sim_runs/<timestamp>/ : telemetry.csv, summary.json, optional video.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import logging
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autocar.autopilot import Autopilot  # noqa: E402  (the real car code)
from autocar.config import CONFIG  # noqa: E402

from sim_airsim.adapters import AirSimCamera, AirSimLink, AirSimMotor, DriveTuning  # noqa: E402

DEFAULT_LANE = "runs/segment/runs/road/baseline_v1-2/weights/best.pt"
DEFAULT_TRAFFIC = "runs/detect/kingfisher-raccoon-2/traffic-light/train/weights/best.pt"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="RPI5_AutoCAR autopilot in AirSim")
    p.add_argument("--ip", default="127.0.0.1")
    p.add_argument("--port", type=int, default=41451)
    p.add_argument("--vehicle", default="PhysXCar")
    p.add_argument("--camera", default="autocar_cam")
    p.add_argument("--swap-rb", action="store_true", help="use if colours look blue/red swapped")
    p.add_argument("--lane-model", default=DEFAULT_LANE)
    p.add_argument("--lane-class", default="road", help="class name in the seg model (road / lane)")
    p.add_argument("--lane-backend", choices=["auto", "yolo", "opencv"], default="auto")
    p.add_argument("--roi-start", type=float, default=CONFIG.lane_roi_start)
    p.add_argument("--traffic-model", default=DEFAULT_TRAFFIC)
    p.add_argument("--no-traffic", action="store_true",
                   help="lane following only; do not load the traffic-light model")
    p.add_argument("--traffic-required", action="store_true",
                   help="stop when traffic model is missing/stale (real-car behaviour)")
    p.add_argument("--imgsz", type=int, default=CONFIG.inference_image_size)
    p.add_argument("--speed", type=float, default=CONFIG.autonomous_base_speed)
    p.add_argument("--max-speed", type=float, default=6.0, help="m/s that speed=1.0 maps to")
    p.add_argument("--kp", type=float, default=CONFIG.lane_kp)
    p.add_argument("--ki", type=float, default=CONFIG.lane_ki)
    p.add_argument("--kd", type=float, default=CONFIG.lane_kd)
    p.add_argument("--fps", type=float, default=15.0,
                   help="cap the control loop near the Pi 5 frame rate (0 = no cap)")
    p.add_argument("--duration", type=float, default=0, help="seconds, 0 = until Ctrl+C / q")
    p.add_argument("--stop-on-collision", action="store_true")
    p.add_argument("--reset", action="store_true", help="reset the car to its start pose first")
    p.add_argument("--show", action="store_true", help="OpenCV preview window with overlay")
    p.add_argument("--record", default="", help="save overlay video (mp4)")
    p.add_argument("--out", default="sim_runs")
    return p.parse_args(argv)


def _abs(path: str) -> str:
    candidate = Path(path)
    return str(candidate if candidate.is_absolute() else ROOT / candidate)


def build_config(args):
    return dataclasses.replace(
        CONFIG,
        lane_model=_abs(args.lane_model),
        lane_backend=args.lane_backend,
        lane_class_name=args.lane_class,
        lane_roi_start=args.roi_start,
        lane_required=args.lane_backend == "yolo",
        autonomous_model=_abs(args.traffic_model) if not args.no_traffic else str(ROOT / "__no_traffic_model__"),
        traffic_required=args.traffic_required,
        inference_image_size=args.imgsz,
        autonomous_base_speed=args.speed,
        lane_kp=args.kp, lane_ki=args.ki, lane_kd=args.kd,
    )


def draw_overlay(frame, status, motor, car):
    import cv2

    view = frame.copy()
    h, w = view.shape[:2]
    roi_y = int(h * status["_roi"])
    cv2.line(view, (0, roi_y), (w, roi_y), (255, 200, 0), 1)
    cv2.line(view, (w // 2, roi_y), (w // 2, h), (200, 200, 200), 1)
    lane_x = int(w // 2 + status["lane_error"])
    cv2.line(view, (lane_x, roi_y), (lane_x, h), (0, 255, 0), 2)
    lines = [
        f"traffic {status['traffic']} ({status['traffic_confidence']:.2f})",
        f"lane err {status['lane_error']:+.1f}px conf {status['lane_confidence']:.2f}",
        f"steer {motor['steering']:+.2f} thr {motor['throttle']:.2f} brk {motor['brake']:.2f}",
        f"speed {car['speed']:.2f} m/s  fps {status['fps']:.1f}",
    ]
    if car["collided"]:
        lines.append("COLLISION")
    for i, text in enumerate(lines):
        cv2.putText(view, text, (8, 20 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
        cv2.putText(view, text, (8, 20 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return view


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = build_config(args)

    link = AirSimLink(args.ip, args.port, args.vehicle)
    link.connect(api_control=True)
    if args.reset:
        link.call("reset")
        link.connect(api_control=True)  # reset drops API control
        time.sleep(1.0)
    camera = AirSimCamera(link, args.camera, swap_rb=args.swap_rb, max_fps=args.fps)
    motor = AirSimMotor(link, DriveTuning(max_speed_mps=args.max_speed))
    autopilot = Autopilot(config, motor, camera)

    run_dir = ROOT / args.out / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    telemetry_file = open(run_dir / "telemetry.csv", "w", newline="", encoding="utf-8")
    writer = csv.writer(telemetry_file)
    writer.writerow(["t", "x", "y", "speed", "target", "throttle", "steering", "brake",
                     "lane_error", "lane_confidence", "traffic", "fps", "collided"])

    video = None
    collisions, distance, last_xy = 0, 0.0, None
    abs_errors, confident = [], 0
    samples = 0
    start = time.monotonic()
    stop_reason = "user"
    last_warning = None
    print(f"[sim] lane={config.lane_model} backend={config.lane_backend} class={config.lane_class_name}")
    print(f"[sim] traffic={config.autonomous_model} required={config.traffic_required}")
    print(f"[sim] output -> {run_dir}")
    try:
        autopilot.start()
        while True:
            time.sleep(0.1)
            status = autopilot.status()
            state = link.call("getCarState", link.vehicle)
            collision = link.call("simGetCollisionInfo", link.vehicle)
            pos = state.kinematics_estimated.position
            xy = (pos.x_val, pos.y_val)
            if last_xy is not None:
                distance += math.dist(xy, last_xy)
            last_xy = xy
            collided = bool(collision.has_collided)
            if collided:
                collisions += 1
            m = motor.status()
            t = time.monotonic() - start
            writer.writerow([f"{t:.2f}", f"{xy[0]:.2f}", f"{xy[1]:.2f}", f"{state.speed:.2f}",
                             m.get("target", 0), m.get("throttle", 0), m.get("steering", 0),
                             m.get("brake", 0), status["lane_error"], status["lane_confidence"],
                             status["traffic"], status["fps"], int(collided)])
            samples += 1
            abs_errors.append(abs(status["lane_error"]))
            confident += status["lane_confidence"] >= config.lane_min_confidence

            if args.show or args.record:
                frame = autopilot._frame  # latest frame used by the controller
                if frame is not None:
                    import cv2

                    view = draw_overlay(frame, {**status, "_roi": config.lane_roi_start}, m,
                                        {"speed": state.speed, "collided": collided})
                    if args.record:
                        if video is None:
                            Path(args.record).parent.mkdir(parents=True, exist_ok=True)
                            video = cv2.VideoWriter(args.record, cv2.VideoWriter_fourcc(*"mp4v"),
                                                    10, (view.shape[1], view.shape[0]))
                        video.write(view)
                    if args.show:
                        cv2.imshow("RPI5_AutoCAR @ AirSim", view)
                        if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                            break

            if status["error"] and not status["enabled"]:
                stop_reason = f"autopilot error: {status['error']}"
                print("[sim]", stop_reason)
                break
            if status["error"] and status["error"] != last_warning:
                # e.g. traffic detector failed: Autopilot keeps steering, so do we
                last_warning = status["error"]
                print("[sim] warning (autopilot keeps running):", last_warning)
            if args.stop_on_collision and collided:
                stop_reason = "collision"
                print("[sim] collision -> stop")
                break
            if args.duration and t >= args.duration:
                stop_reason = "duration"
                break
    except KeyboardInterrupt:
        pass
    finally:
        autopilot.close()
        link.release()
        telemetry_file.close()
        if video is not None:
            video.release()
        if args.show:
            try:
                import cv2
                cv2.destroyAllWindows()
            except Exception:
                pass

    summary = {
        "duration_s": round(time.monotonic() - start, 1),
        "distance_m": round(distance, 1),
        "samples": samples,
        "mean_abs_lane_error_px": round(sum(abs_errors) / len(abs_errors), 1) if abs_errors else None,
        "lane_confident_ratio": round(confident / samples, 3) if samples else None,
        "collision_samples": collisions,
        "stop_reason": stop_reason,
        "config": {
            "lane_model": config.lane_model, "lane_backend": config.lane_backend,
            "lane_class": config.lane_class_name, "traffic_model": config.autonomous_model,
            "speed": config.autonomous_base_speed, "max_speed_mps": args.max_speed,
            "kp": config.lane_kp, "ki": config.lane_ki, "kd": config.lane_kd,
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
