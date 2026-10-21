"""AirSim stand-ins for autocar.camera.CameraRecorder and autocar.motor.MotorController.

Only the methods used by autocar.autopilot.Autopilot are implemented:
  AirSimCamera.capture_bgr()
  AirSimMotor.set_enabled(enabled, start_manual=...)
  AirSimMotor.drive_tank(left, right)
  AirSimMotor.status()

Mapping from the tank (differential) command to an Ackermann car:
  forward = (left + right) / 2      -> target speed = forward * max_speed_mps
  turn    = (left - right) / 2      -> steering     = turn / steering_full_scale
Autopilot's PID output is clamped to +-0.35 (PIDController.max_output), so the
default steering_full_scale=0.35 maps the PID's full range to full steering lock.
Positive turn (left wheel faster) turns right, matching AirSim's positive steering.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

LOG = logging.getLogger(__name__)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class AirSimLink:
    """One shared msgpack-rpc connection guarded by a lock.

    The AirSim Python client is not thread-safe; Autopilot calls the camera and
    motor from its control thread while the runner polls telemetry from the main
    thread, so every RPC goes through ``call``.
    """

    def __init__(self, ip: str = "127.0.0.1", port: int = 41451, vehicle: str = "PhysXCar",
                 timeout: float = 10.0, client=None):
        if client is None:
            import airsim  # imported lazily so unit tests can inject a fake client

            client = airsim.CarClient(ip=ip, port=port, timeout_value=timeout)
        self.client = client
        self.vehicle = vehicle
        self.lock = threading.RLock()

    def call(self, method: str, *args, **kwargs):
        with self.lock:
            return getattr(self.client, method)(*args, **kwargs)

    def connect(self, api_control: bool = True) -> None:
        self.call("confirmConnection")
        self.call("enableApiControl", api_control, self.vehicle)

    def release(self) -> None:
        try:
            self.stop_car()
            self.call("enableApiControl", False, self.vehicle)
        except Exception:  # simulator may already be closed
            LOG.debug("release failed", exc_info=True)

    def stop_car(self) -> None:
        import airsim

        self.call("setCarControls", airsim.CarControls(throttle=0, steering=0, brake=1), self.vehicle)


class AirSimCamera:
    """Replaces CameraRecorder.capture_bgr() with an AirSim Scene image."""

    def __init__(self, link: AirSimLink, camera_name: str = "autocar_cam",
                 swap_rb: bool = False, retries: int = 20, max_fps: float = 15.0):
        self.link, self.camera_name = link, camera_name
        self.swap_rb, self.retries = swap_rb, retries
        # Cap the frame rate to roughly what the Pi 5 achieves, so PID gains
        # (especially Kd, which depends on dt) behave like on the real car.
        self.min_interval = 1.0 / max_fps if max_fps > 0 else 0.0
        self._last_capture = 0.0
        self.frames = 0

    def capture_bgr(self):
        import airsim
        import numpy as np

        wait = self.min_interval - (time.monotonic() - self._last_capture)
        if wait > 0:
            time.sleep(wait)
        self._last_capture = time.monotonic()
        request = [airsim.ImageRequest(self.camera_name, airsim.ImageType.Scene, False, False)]
        for _ in range(self.retries):
            response = self.link.call("simGetImages", request, self.link.vehicle)[0]
            if response.width and response.height:
                buffer = np.frombuffer(response.image_data_uint8, dtype=np.uint8)
                frame = buffer.reshape(response.height, response.width, -1)[:, :, :3]
                if self.swap_rb:
                    frame = frame[:, :, ::-1]
                self.frames += 1
                return np.ascontiguousarray(frame)
            time.sleep(0.05)  # AirSim returns an empty image during the first frames
        raise RuntimeError(
            f"AirSim camera '{self.camera_name}' returned no image; check Cameras in settings.json"
        )

    # CameraRecorder-compatible no-ops so other autocar modules do not break.
    def status(self) -> dict:
        return {"backend": "airsim", "camera": self.camera_name, "frames": self.frames}

    def close(self) -> None:
        pass


@dataclass
class DriveTuning:
    max_speed_mps: float = 6.0       # forward=1.0 maps to this speed in the sim
    steering_full_scale: float = 0.35  # |turn| that produces full steering lock
    speed_kp: float = 0.35           # throttle per m/s of speed error
    throttle_limit: float = 0.8
    brake_gain: float = 0.25


class AirSimMotor:
    """Replaces MotorController for Autopilot (drive_tank + enable/disable)."""

    def __init__(self, link: AirSimLink, tuning: DriveTuning | None = None):
        self.link = link
        self.tuning = tuning or DriveTuning()
        self._lock = threading.RLock()
        self._enabled = False
        self._left = self._right = 0.0
        self._last = {"throttle": 0.0, "steering": 0.0, "brake": 1.0, "speed": 0.0, "target": 0.0}

    def set_enabled(self, enabled: bool, *, start_manual: bool = True) -> dict:
        with self._lock:
            self._enabled = bool(enabled)
            if not enabled:
                self.drive_tank(0, 0)
            return self.status()

    def tank_to_controls(self, left: float, right: float, speed: float):
        """Pure function (no RPC) so it can be unit-tested."""
        t = self.tuning
        left, right = _clamp(float(left), -1, 1), _clamp(float(right), -1, 1)
        forward = (left + right) / 2
        turn = (left - right) / 2
        steering = _clamp(turn / max(t.steering_full_scale, 1e-6), -1, 1)
        target = forward * t.max_speed_mps
        if abs(target) < 1e-6:
            return {"throttle": 0.0, "steering": steering, "brake": 1.0, "target": 0.0, "reverse": False}
        reverse = target < 0
        error = abs(target) - abs(speed)
        throttle = _clamp(t.speed_kp * error + 0.15, 0.0, t.throttle_limit)
        brake = _clamp(-error * t.brake_gain, 0.0, 1.0) if error < -0.5 else 0.0
        if brake:
            throttle = 0.0
        return {"throttle": throttle, "steering": steering, "brake": brake,
                "target": target, "reverse": reverse}

    def drive_tank(self, left: float, right: float) -> dict:
        import airsim

        with self._lock:
            if (left or right) and not self._enabled:
                raise RuntimeError("vehicle is disabled")
            state = self.link.call("getCarState", self.link.vehicle)
            command = self.tank_to_controls(left, right, state.speed)
            controls = airsim.CarControls(steering=command["steering"], brake=command["brake"])
            controls.set_throttle(command["throttle"], not command["reverse"])
            self.link.call("setCarControls", controls, self.link.vehicle)
            self._left, self._right = float(left), float(right)
            self._last = {**command, "speed": float(state.speed)}
            return self.status()

    def status(self) -> dict:
        with self._lock:
            return {
                "backend": "airsim",
                "enabled": self._enabled,
                "left": round(self._left, 3),
                "right": round(self._right, 3),
                **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in self._last.items()},
            }

    def close(self) -> None:
        self.set_enabled(False)
