"""Drive the AirSim car by keyboard and save camera frames for labelling.

    python -m sim_airsim.manual_collect --every 0.5
Keys (focus the OpenCV window):
    W / S  : faster / slower (S below 0 = reverse)     A / D : steer left / right
    SPACE  : stop (brake)       C : centre steering
    R      : start / pause saving frames              Q / ESC : quit
Frames go to datasets/sim_frames/<session>/frame_000001.jpg, ready for the
same Roboflow -> YOLO26 workflow used for the real-car videos.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim_airsim.adapters import AirSimCamera, AirSimLink, AirSimMotor, DriveTuning  # noqa: E402


def main() -> int:
    import cv2

    p = argparse.ArgumentParser()
    p.add_argument("--ip", default="127.0.0.1")
    p.add_argument("--vehicle", default="PhysXCar")
    p.add_argument("--camera", default="autocar_cam")
    p.add_argument("--every", type=float, default=0.5, help="seconds between saved frames")
    p.add_argument("--max-speed", type=float, default=6.0)
    p.add_argument("--out", default="datasets/sim_frames")
    args = p.parse_args()

    link = AirSimLink(args.ip, vehicle=args.vehicle)
    link.connect(api_control=True)
    camera = AirSimCamera(link, args.camera, max_fps=20)
    motor = AirSimMotor(link, DriveTuning(max_speed_mps=args.max_speed, steering_full_scale=1.0))
    motor.set_enabled(True)

    session = ROOT / args.out / time.strftime("%Y%m%d-%H%M%S")
    speed, steer, saving, saved, last_save = 0.0, 0.0, False, 0, 0.0
    print(__doc__)
    try:
        while True:
            frame = camera.capture_bgr()
            now = time.monotonic()
            if saving and now - last_save >= args.every:
                session.mkdir(parents=True, exist_ok=True)
                saved += 1
                cv2.imwrite(str(session / f"frame_{saved:06d}.jpg"), frame)
                last_save = now
            view = frame.copy()
            text = f"speed {speed:+.2f} steer {steer:+.2f} {'REC' if saving else 'pause'} saved {saved}"
            cv2.putText(view, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255) if saving else (255, 255, 255), 2)
            cv2.imshow("AirSim manual collect", view)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("w"):
                speed = min(1.0, speed + 0.05)
            elif key == ord("s"):
                speed = max(-0.5, speed - 0.05)
            elif key == ord("a"):
                steer = max(-1.0, steer - 0.1)
            elif key == ord("d"):
                steer = min(1.0, steer + 0.1)
            elif key == ord("c"):
                steer = 0.0
            elif key == ord(" "):
                speed = 0.0
            elif key == ord("r"):
                saving = not saving
            # tank form so the same mapping as the autopilot is exercised
            motor.drive_tank(speed + steer, speed - steer) if speed else motor.drive_tank(0, 0)
    except KeyboardInterrupt:
        pass
    finally:
        motor.close()
        link.release()
        cv2.destroyAllWindows()
    print(f"saved {saved} frames -> {session}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
