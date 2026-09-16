from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from .perception import LaneDetector, PIDController, TrafficDetector, YoloLaneDetector

LOG = logging.getLogger(__name__)


class Autopilot:
    """High-rate lane controller plus lower-rate traffic inference worker."""

    def __init__(self, config, motor, camera):
        self.config, self.motor, self.camera = config, motor, camera
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._enabled = False
        self._threads: list[threading.Thread] = []
        self._frame = None
        self._traffic = "NONE"
        self._traffic_confidence = 0.0
        self._traffic_updated = 0.0
        self._lane_error = 0.0
        self._lane_confidence = 0.0
        self._steering = 0.0
        self._fps = 0.0
        self._error: str | None = None

    @staticmethod
    def _resolve_model(path_value: str) -> Path:
        path = Path(path_value)
        return path if path.is_absolute() else Path(__file__).resolve().parent.parent / path

    def set_enabled(self, enabled: bool) -> dict:
        if enabled:
            self.start()
        else:
            self.stop()
        return self.status()

    def start(self) -> None:
        with self._lock:
            if self._enabled:
                return
            traffic_model = self._resolve_model(self.config.autonomous_model)
            lane_model = self._resolve_model(self.config.lane_model)
            if self.config.traffic_required and not traffic_model.exists():
                raise RuntimeError(f"required traffic model not found: {traffic_model}")
            if self.config.lane_required and self.config.lane_backend != "opencv" and not lane_model.exists():
                raise RuntimeError(f"required lane model not found: {lane_model}")
            self.motor.set_enabled(True, start_manual=False)
            self._stop.clear()
            self._enabled, self._error = True, None
            self._threads = [
                threading.Thread(target=self._control_loop, daemon=True, name="lane-control"),
                threading.Thread(target=self._traffic_loop, daemon=True, name="traffic-inference"),
            ]
            for thread in self._threads:
                thread.start()

    def stop(self) -> None:
        with self._lock:
            self._enabled = False
            self._stop.set()
            threads = list(self._threads)
        current = threading.current_thread()
        for thread in threads:
            if thread is not current and thread.is_alive():
                thread.join(timeout=0.5)
        try:
            self.motor.drive_tank(0, 0)
        except RuntimeError:
            pass

    def close(self) -> None:
        self.stop()
        for thread in self._threads:
            thread.join(timeout=1.0)

    def _control_loop(self) -> None:
        lane_model = self._resolve_model(self.config.lane_model)
        use_yolo_lane = self.config.lane_backend == "yolo" or (
            self.config.lane_backend == "auto" and lane_model.exists()
        )
        if self.config.lane_backend not in {"auto", "yolo", "opencv"}:
            raise ValueError("AUTOCAR_LANE_BACKEND must be auto, yolo, or opencv")
        if use_yolo_lane:
            detector = YoloLaneDetector(
                str(lane_model), self.config.inference_image_size,
                self.config.lane_min_confidence, self.config.lane_roi_start,
                self.config.lane_class_name,
            )
            LOG.info("YOLO lane segmentation enabled: %s", lane_model)
        elif self.config.lane_required:
            raise FileNotFoundError(f"required lane model not found: {lane_model}")
        else:
            detector = LaneDetector(roi_start=self.config.lane_roi_start)
            LOG.warning("Lane model unavailable; using OpenCV fallback")
        pid = PIDController(self.config.lane_kp, self.config.lane_ki, self.config.lane_kd)
        previous = time.monotonic()
        try:
            while not self._stop.is_set():
                frame = self.camera.capture_bgr()
                observation = detector.detect(frame)
                now = time.monotonic()
                with self._lock:
                    self._frame = frame
                    self._lane_error, self._lane_confidence = observation.error, observation.confidence
                    self._fps = 1.0 / max(now - previous, 1e-4)
                    traffic_fresh = now - self._traffic_updated <= self.config.traffic_stale_seconds
                    traffic = self._traffic if traffic_fresh else (
                        "STALE" if self.config.traffic_required else "NONE"
                    )
                previous = now
                if observation.confidence < self.config.lane_min_confidence or traffic in {"RED", "STOP_SIGN", "STALE"}:
                    pid.reset()
                    left = right = steering = 0.0
                else:
                    speed = self.config.autonomous_slow_speed if traffic == "YELLOW" else self.config.autonomous_base_speed
                    steering = pid.update(observation.error, now)
                    left, right = speed + steering, speed - steering
                self.motor.drive_tank(left, right)
                with self._lock:
                    self._steering = steering
        except Exception as exc:
            LOG.exception("Autopilot control loop stopped")
            with self._lock:
                self._error, self._enabled = str(exc), False
            try:
                self.motor.drive_tank(0, 0)
            except Exception:
                LOG.exception("Unable to stop after autopilot failure")
            self._stop.set()

    def _traffic_loop(self) -> None:
        model_path = self._resolve_model(self.config.autonomous_model)
        if not model_path.exists():
            message = f"traffic model not found: {model_path}"
            LOG.error(message)
            if self.config.traffic_required:
                with self._lock:
                    self._error, self._enabled = message, False
                self._stop.set()
                try:
                    self.motor.drive_tank(0, 0)
                except Exception:
                    LOG.exception("Unable to stop after missing traffic model")
            return
        try:
            detector = TrafficDetector(
                str(model_path), self.config.inference_image_size,
                self.config.traffic_confidence, self.config.traffic_history,
                self.config.traffic_votes,
            )
            while not self._stop.wait(0.01):
                with self._lock:
                    frame = None if self._frame is None else self._frame.copy()
                if frame is None:
                    continue
                state, confidence = detector.detect(frame)
                with self._lock:
                    self._traffic, self._traffic_confidence = state, confidence
                    self._traffic_updated = time.monotonic()
        except Exception as exc:
            LOG.exception("Traffic detector disabled")
            with self._lock:
                self._error = f"traffic detector: {exc}"

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self._enabled,
                "traffic": self._traffic,
                "traffic_confidence": round(self._traffic_confidence, 3),
                "lane_error": round(self._lane_error, 2),
                "lane_confidence": round(self._lane_confidence, 3),
                "steering": round(self._steering, 3),
                "fps": round(self._fps, 1),
                "error": self._error,
            }
