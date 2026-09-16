from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass


@dataclass
class LaneObservation:
    error: float
    confidence: float
    lane_center: int
    frame_center: int


class PIDController:
    """PID with derivative timing and integral anti-windup."""

    def __init__(self, kp=0.003, ki=0.00002, kd=0.001, max_output=0.35, windup=80.0):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.max_output, self.windup = max_output, windup
        self.integral = 0.0
        self.previous_error = 0.0
        self.previous_time = time.monotonic()

    def reset(self) -> None:
        self.integral = self.previous_error = 0.0
        self.previous_time = time.monotonic()

    def update(self, error: float, now: float | None = None) -> float:
        current = time.monotonic() if now is None else now
        dt = max(current - self.previous_time, 1e-4)
        self.integral = max(-self.windup, min(self.windup, self.integral + error * dt))
        derivative = (error - self.previous_error) / dt
        output = self.kp * error + self.ki * self.integral + self.kd * derivative
        self.previous_error, self.previous_time = error, current
        return max(-self.max_output, min(self.max_output, output))


class LaneDetector:
    def __init__(self, roi_start=0.60, threshold=165, lane_half_width=140, min_peak=800):
        self.roi_start = roi_start
        self.threshold = threshold
        self.lane_half_width = lane_half_width
        self.min_peak = min_peak

    def detect(self, frame) -> LaneObservation:
        import numpy as np

        height, width = frame.shape[:2]
        roi = frame[int(height * self.roi_start):, :]
        try:
            import cv2
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            _, binary = cv2.threshold(blurred, self.threshold, 255, cv2.THRESH_BINARY)
        except ImportError:
            # BGR luminance + threshold fallback for minimal Pi installations.
            gray = roi[..., 0] * 0.114 + roi[..., 1] * 0.587 + roi[..., 2] * 0.299
            binary = np.where(gray >= self.threshold, 255, 0).astype(np.uint8)
        histogram = np.sum(binary[len(binary) // 2:, :], axis=0)
        midpoint = width // 2
        left = int(np.argmax(histogram[:midpoint]))
        right = int(np.argmax(histogram[midpoint:]) + midpoint)
        left_strength, right_strength = float(histogram[left]), float(histogram[right])
        has_left, has_right = left_strength > self.min_peak, right_strength > self.min_peak
        if has_left and has_right:
            center, confidence = (left + right) // 2, 1.0
        elif has_left:
            center, confidence = left + self.lane_half_width, 0.55
        elif has_right:
            center, confidence = right - self.lane_half_width, 0.55
        else:
            center, confidence = midpoint, 0.0
        return LaneObservation(float(center - midpoint), confidence, center, midpoint)


class YoloLaneDetector:
    """Lane centre estimator backed by a YOLO26 segmentation export."""

    def __init__(self, model_path: str, image_size=416, confidence=0.30,
                 roi_start=0.55, class_name="lane"):
        from ultralytics import YOLO

        self.model = YOLO(model_path, task="segment")
        self.image_size = image_size
        self.confidence = confidence
        self.roi_start = roi_start
        self.class_name = class_name.lower()

    def detect(self, frame) -> LaneObservation:
        import cv2
        import numpy as np

        height, width = frame.shape[:2]
        frame_center = width // 2
        result = self.model.predict(
            frame, imgsz=self.image_size, conf=self.confidence, device="cpu", verbose=False
        )[0]
        if result.masks is None or result.boxes is None:
            return LaneObservation(0.0, 0.0, frame_center, frame_center)

        combined = np.zeros((height, width), dtype=np.uint8)
        confidences: list[float] = []
        for box, raw_mask in zip(result.boxes, result.masks.data):
            class_id = int(box.cls[0])
            if str(self.model.names[class_id]).lower() != self.class_name:
                continue
            mask = raw_mask.detach().cpu().numpy()
            mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
            combined |= (mask >= 0.5).astype(np.uint8)
            confidences.append(float(box.conf[0]))

        roi_y = max(0, min(height - 1, int(height * self.roi_start)))
        roi_mask = combined[roi_y:, :]
        moments = cv2.moments(roi_mask)
        if not confidences or moments["m00"] <= 0:
            return LaneObservation(0.0, 0.0, frame_center, frame_center)
        lane_center = int(moments["m10"] / moments["m00"])
        coverage = float(np.count_nonzero(roi_mask)) / max(1, roi_mask.size)
        confidence = min(1.0, max(confidences) * min(1.0, coverage / 0.02))
        return LaneObservation(float(lane_center - frame_center), confidence, lane_center, frame_center)


class TrafficStateFilter:
    """Require repeated observations while allowing safety-critical states immediately."""

    def __init__(self, history_size=5, votes_required=3):
        self.history = deque(maxlen=max(1, history_size))
        self.votes_required = max(1, min(votes_required, self.history.maxlen))
        self.stable_state = "NONE"

    def update(self, state: str) -> str:
        self.history.append(state)
        # A single red/stop observation must stop the car; release still needs votes.
        if state in {"RED", "STOP_SIGN"}:
            self.stable_state = state
            return self.stable_state
        winner, votes = Counter(self.history).most_common(1)[0]
        if votes >= self.votes_required:
            self.stable_state = winner
        return self.stable_state


class TrafficDetector:
    """Lazy Ultralytics wrapper; importing the base project stays dependency-free."""

    PRIORITY = {"NONE": 0, "GREEN": 1, "YELLOW": 2, "RED": 3, "STOP_SIGN": 4}

    def __init__(self, model_path: str, image_size=416, confidence=0.45,
                 history_size=5, votes_required=3):
        from ultralytics import YOLO

        self.model = YOLO(model_path, task="detect")
        self.image_size, self.confidence = image_size, confidence
        self.filter = TrafficStateFilter(history_size, votes_required)

    def detect(self, frame) -> tuple[str, float]:
        state, best_confidence = "NONE", 0.0
        results = self.model.predict(frame, imgsz=self.image_size, conf=self.confidence, verbose=False)
        aliases = {
            "red_light": "RED", "yellow_light": "YELLOW", "green_light": "GREEN",
            "stop_sign": "STOP_SIGN", "stop": "STOP_SIGN",
        }
        for result in results:
            for box in result.boxes:
                label = aliases.get(str(self.model.names[int(box.cls[0])]).lower())
                confidence = float(box.conf[0])
                if label and (self.PRIORITY[label], confidence) > (self.PRIORITY[state], best_confidence):
                    state, best_confidence = label, confidence
        return self.filter.update(state), best_confidence
