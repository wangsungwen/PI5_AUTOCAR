"""Tiny AirSim-compatible RPC server for checking the bridge without Unreal.

It speaks the same msgpack-rpc API (port 41451) for the calls this package uses
and renders a synthetic straight road with two white lane lines from a simple
bicycle model. Use it in class on PCs without a GPU, or in CI:

    python -m sim_airsim.fake_airsim_server --offset -1.0
    python -m sim_airsim.run_autopilot --lane-backend opencv --duration 20

If the car starts 1 m left of centre and the summary shows it drifting back to
the centre, the camera -> perception -> PID -> drive_tank -> AirSim loop works.
This is a plumbing test, not a physics or image-realism test.
"""
from __future__ import annotations

import argparse
import math
import threading
import time

import msgpack
import msgpackrpc
import numpy as np

W, H = 640, 480
FOCAL = 330.0        # px, roughly a 88 deg horizontal FOV
HORIZON = 200        # px row of the horizon
CAM_HEIGHT = 1.4     # m
LANE_HALF = 1.75     # m (3.5 m lane)
WHEELBASE = 2.7      # m
MAX_STEER = math.radians(30)


def vec(x=0.0, y=0.0, z=0.0):
    return {"x_val": float(x), "y_val": float(y), "z_val": float(z)}


def quat(yaw=0.0):
    return {"w_val": math.cos(yaw / 2), "x_val": 0.0, "y_val": 0.0, "z_val": math.sin(yaw / 2)}


class FakeCar:
    def __init__(self, offset: float):
        self.lock = threading.Lock()
        self.start_offset = offset
        self.reset()

    def reset(self):
        with self.lock:
            self.x, self.y, self.yaw, self.speed = 0.0, self.start_offset, 0.0, 0.0
            self.throttle = self.steering = 0.0
            self.brake, self.reverse = 1.0, False
            self.t = time.monotonic()

    def step(self):
        now = time.monotonic()
        dt = min(now - self.t, 0.2)
        self.t = now
        accel = 4.0 * self.throttle - 8.0 * self.brake - 0.3 * self.speed
        self.speed = max(0.0, self.speed + accel * dt)
        delta = self.steering * MAX_STEER
        sign = -1.0 if self.reverse else 1.0
        self.yaw += sign * self.speed / WHEELBASE * math.tan(delta) * dt
        self.x += sign * self.speed * math.cos(self.yaw) * dt
        self.y += sign * self.speed * math.sin(self.yaw) * dt

    def render(self) -> bytes:
        image = np.zeros((H, W, 3), dtype=np.uint8)
        image[:HORIZON] = (200, 160, 120)          # sky (BGR)
        image[HORIZON:] = (70, 90, 60)             # grass
        cx = W / 2
        for v in range(HORIZON + 2, H):
            d = CAM_HEIGHT * FOCAL / (v - HORIZON)  # ground distance for this row
            def u(lateral):
                rel = lateral - self.y - d * math.tan(self.yaw)
                return int(cx + FOCAL * rel / d)
            left_edge, right_edge = u(-LANE_HALF - 0.6), u(LANE_HALF + 0.6)
            image[v, max(0, left_edge):max(0, min(W, right_edge))] = (90, 90, 90)  # asphalt
            half = max(1, int(FOCAL * 0.15 / d))
            for lateral in (-LANE_HALF, LANE_HALF):
                c = u(lateral)
                lo, hi = max(0, c - half), min(W, c + half)
                if lo < hi:
                    image[v, lo:hi] = (255, 255, 255)
        return image.tobytes()


class Handler:
    def __init__(self, car: FakeCar):
        self.car = car
        self.collided = False

    # --- connection -----------------------------------------------------
    def ping(self): return True
    def getServerVersion(self): return 1
    def getMinRequiredClientVersion(self): return 1
    def enableApiControl(self, enabled, vehicle_name=""): return None
    def isApiControlEnabled(self, vehicle_name=""): return True
    def reset(self):
        self.car.reset()
        return None

    # --- car ------------------------------------------------------------
    def setCarControls(self, controls, vehicle_name=""):
        with self.car.lock:
            self.car.step()
            self.car.throttle = abs(float(controls.get("throttle", 0)))
            self.car.reverse = float(controls.get("throttle", 0)) < 0 or controls.get("manual_gear") == -1
            self.car.steering = max(-1.0, min(1.0, float(controls.get("steering", 0))))
            self.car.brake = float(controls.get("brake", 0))
        return None

    def getCarState(self, vehicle_name=""):
        with self.car.lock:
            self.car.step()
            return {
                "speed": self.car.speed, "gear": 1, "rpm": 0.0, "maxrpm": 7000.0,
                "handbrake": False, "timestamp": int(time.time() * 1e9),
                "collision": self._collision(),
                "kinematics_estimated": {
                    "position": vec(self.car.x, self.car.y), "orientation": quat(self.car.yaw),
                    "linear_velocity": vec(self.car.speed), "angular_velocity": vec(),
                    "linear_acceleration": vec(), "angular_acceleration": vec(),
                },
            }

    def simGetCollisionInfo(self, vehicle_name=""):
        return self._collision()

    def _collision(self):
        off_road = abs(self.car.y) > LANE_HALF + 0.6
        return {"has_collided": off_road, "normal": vec(), "impact_point": vec(), "position": vec(),
                "penetration_depth": 0.0, "time_stamp": 0, "object_name": "offroad" if off_road else "",
                "object_id": -1}

    def simGetImages(self, requests, vehicle_name="", external=False):
        with self.car.lock:
            self.car.step()
            data = self.car.render()
        return [{
            "image_data_uint8": data, "image_data_float": [], "camera_position": vec(0.6, 0, -CAM_HEIGHT),
            "camera_orientation": quat(), "time_stamp": int(time.time() * 1e9), "message": "",
            "pixels_as_float": False, "compress": False, "width": W, "height": H, "image_type": 0,
        } for _ in requests]


def _use_bin_type():
    """Send bytes as msgpack 'bin' like the real AirSim server does."""
    original = msgpack.Packer.__init__

    def patched(self, *args, **kwargs):
        kwargs["use_bin_type"] = True
        original(self, *args, **kwargs)

    msgpack.Packer.__init__ = patched


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=41451)
    p.add_argument("--offset", type=float, default=-1.0, help="start lateral offset in metres (+ = right)")
    args = p.parse_args()
    _use_bin_type()
    server = msgpackrpc.Server(Handler(FakeCar(args.offset)), pack_encoding="utf-8", unpack_encoding="utf-8")
    server.listen(msgpackrpc.Address("127.0.0.1", args.port))
    print(f"fake AirSim listening on 127.0.0.1:{args.port} (Ctrl+C to stop)")
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
