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
        self._frame_sequence = 0
        self._frame_time = 0.0
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
            if any(thread.is_alive() for thread in self._threads):
                raise RuntimeError("Previous inference is still stopping; retry after it finishes")
            if self.config.lane_backend not in {"auto", "yolo", "opencv"}:
                raise ValueError("AUTOCAR_LANE_BACKEND must be auto, yolo, or opencv")
            if not 0 <= self.config.lane_roi_start < 1:
                raise ValueError("Lane ROI must be in [0, 1)")
            if self.config.traffic_stale_seconds <= 0 or self.config.watchdog_seconds <= 0:
                raise ValueError("Freshness and watchdog timeouts must be positive")
            traffic_model = self._resolve_model(self.config.autonomous_model)
            lane_model = self._resolve_model(self.config.lane_model)
            if self.config.traffic_required and not traffic_model.exists():
                raise RuntimeError(f"required traffic model not found: {traffic_model}")
            if self.config.lane_required and self.config.lane_backend != "opencv" and not lane_model.exists():
                raise RuntimeError(f"required lane model not found: {lane_model}")
            self.motor.set_enabled(True, start_manual=False)
            self.motor.drive_tank(0, 0)
            self._frame = None
            self._frame_sequence = 0
            self._traffic, self._traffic_confidence, self._traffic_updated = "NONE", 0.0, 0.0
            self._lane_error = self._lane_confidence = self._steering = self._fps = 0.0
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
            # Serialize the final zero command with all autonomous motor writes.
            try:
                self.motor.drive_tank(0, 0)
            except RuntimeError:
                pass
        current = threading.current_thread()
        for thread in threads:
            if thread is not current and thread.is_alive():
                thread.join(timeout=0.5)

    def close(self) -> None:
        self.stop()
        for thread in self._threads:
            thread.join(timeout=1.0)

    def _control_loop(self) -> None:
        try:
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
            while not self._stop.is_set():
                frame = self.camera.capture_bgr()
                captured = time.monotonic()
                with self._lock:
                    if self._stop.is_set():
                        break
                    self._frame, self._frame_time = frame, captured
                    self._frame_sequence += 1
                observation = detector.detect(frame)
                now = time.monotonic()
                with self._lock:
                    self._lane_error, self._lane_confidence = observation.error, observation.confidence
                    self._fps = 1.0 / max(now - previous, 1e-4)
                    traffic_fresh = now - self._traffic_updated <= self.config.traffic_stale_seconds
                    traffic = self._traffic if traffic_fresh else (
                        "STALE" if self.config.traffic_required else "NONE"
                    )
                previous = now
                if now - captured > self.config.watchdog_seconds or observation.confidence < self.config.lane_min_confidence or traffic in {"RED", "STOP_SIGN", "STALE"}:
                    pid.reset()
                    left = right = steering = 0.0
                else:
                    speed = self.config.autonomous_slow_speed if traffic == "YELLOW" else self.config.autonomous_base_speed
                    steering = pid.update(observation.error, now)
                    steering = max(-speed, min(speed, steering))
                    left, right = speed + steering, speed - steering
                with self._lock:
                    if self._stop.is_set() or not self._enabled:
                        break
                    # Traffic can change while lane steering is being computed.
                    age = time.monotonic() - self._traffic_updated
                    if (self._traffic in {"RED", "STOP_SIGN"} and age <= self.config.traffic_stale_seconds
                            or self.config.traffic_required and age > self.config.traffic_stale_seconds):
                        left = right = steering = 0.0
                        pid.reset()
                    self.motor.drive_tank(left, right)
                    self._steering = steering
        except Exception as exc:
            LOG.exception("Autopilot control loop stopped")
            self._fail(str(exc))

    def _fail(self, message: str) -> None:
        with self._lock:
            self._error = message
            if self._enabled:
                self._enabled = False
                self._stop.set()
                try:
                    self.motor.drive_tank(0, 0)
                except Exception:
                    LOG.exception("Unable to stop after autopilot failure")

    def _traffic_loop(self) -> None:
        model_path = self._resolve_model(self.config.autonomous_model)
        if not model_path.exists():
            message = f"traffic model not found: {model_path}"
            LOG.error(message)
            if self.config.traffic_required:
                self._fail(message)
            return
        try:
            detector = TrafficDetector(
                str(model_path), self.config.inference_image_size,
                self.config.traffic_confidence, self.config.traffic_history,
                self.config.traffic_votes,
            )
            sequence = -1
            while not self._stop.wait(0.01):
                with self._lock:
                    if self._frame is None or self._frame_sequence == sequence:
                        continue
                    sequence = self._frame_sequence
                    frame, captured = self._frame, self._frame_time
                if frame is None:
                    continue
                state, confidence = detector.detect(frame)
                with self._lock:
                    if self._stop.is_set():
                        break
                    self._traffic, self._traffic_confidence = state, confidence
                    self._traffic_updated = captured
        except Exception as exc:
            LOG.exception("Traffic detector disabled")
            if self.config.traffic_required:
                self._fail(f"traffic detector: {exc}")
            else:
                with self._lock:
                    self._error = f"traffic detector: {exc}"
                    self._traffic_updated = 0.0

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
