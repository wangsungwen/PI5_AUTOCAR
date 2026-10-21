"""Step check: is AirSim reachable, is the car there, does the camera work?

    python -m sim_airsim.check_airsim
Saves sim_runs/check_frame.png so you can confirm the camera angle.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim_airsim.adapters import AirSimCamera, AirSimLink  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ip", default="127.0.0.1")
    p.add_argument("--port", type=int, default=41451)
    p.add_argument("--vehicle", default="PhysXCar")
    p.add_argument("--camera", default="autocar_cam")
    args = p.parse_args()

    link = AirSimLink(args.ip, args.port, args.vehicle)
    link.call("confirmConnection")
    state = link.call("getCarState", args.vehicle)
    pos = state.kinematics_estimated.position
    print(f"[ok] car '{args.vehicle}' speed={state.speed:.2f} m/s pos=({pos.x_val:.1f}, {pos.y_val:.1f}, {pos.z_val:.1f})")
    frame = AirSimCamera(link, args.camera).capture_bgr()
    print(f"[ok] camera '{args.camera}' frame {frame.shape[1]}x{frame.shape[0]}")
    out = ROOT / "sim_runs" / "check_frame.png"
    out.parent.mkdir(exist_ok=True)
    try:
        import cv2
        cv2.imwrite(str(out), frame)
        print(f"[ok] saved {out}")
    except ImportError:
        print("[warn] OpenCV missing, frame not saved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
