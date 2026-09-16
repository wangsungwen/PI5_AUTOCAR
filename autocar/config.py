from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _integer(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _number(name: str, default: str) -> int:
    return int(os.getenv(name, default), 0)


def _boolean(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    host: str = os.getenv("AUTOCAR_HOST", "0.0.0.0")
    port: int = _integer("AUTOCAR_PORT", 8000)
    gpio_backend: str = os.getenv("AUTOCAR_GPIO", "mock")
    left_forward: int = _integer("AUTOCAR_LEFT_FORWARD", 17)
    left_backward: int = _integer("AUTOCAR_LEFT_BACKWARD", 18)
    right_forward: int = _integer("AUTOCAR_RIGHT_FORWARD", 22)
    right_backward: int = _integer("AUTOCAR_RIGHT_BACKWARD", 23)
    watchdog_seconds: float = float(os.getenv("AUTOCAR_WATCHDOG_SECONDS", "0.8"))
    manual_speed: int = _integer("AUTOCAR_MANUAL_SPEED", 50)
    manual_speed_step: int = _integer("AUTOCAR_MANUAL_SPEED_STEP", 5)
    manual_steering_step: int = _integer("AUTOCAR_MANUAL_STEERING_STEP", 5)
    manual_steering_max: int = _integer("AUTOCAR_MANUAL_STEERING_MAX", 45)
    direction_change_delay: float = float(os.getenv("AUTOCAR_DIRECTION_CHANGE_DELAY", "0.15"))
    recordings_dir: Path = Path(os.getenv("AUTOCAR_RECORDINGS", str(Path.home() / "Videos" / "autocar")))
    camera_index: int = _integer("AUTOCAR_CAMERA_INDEX", 0)
    camera_rotate_180: bool = os.getenv("AUTOCAR_CAMERA_ROTATE_180", "1") == "1"
    gimbal_backend: str = os.getenv("AUTOCAR_GIMBAL", "mock")
    pan_pin: int = _integer("AUTOCAR_PAN_PIN", 12)
    tilt_pin: int = _integer("AUTOCAR_TILT_PIN", 13)
    gimbal_step: int = _integer("AUTOCAR_GIMBAL_STEP", 10)
    pan_min: int = _integer("AUTOCAR_PAN_MIN", -80)
    pan_max: int = _integer("AUTOCAR_PAN_MAX", 80)
    tilt_min: int = _integer("AUTOCAR_TILT_MIN", -80)
    tilt_max: int = _integer("AUTOCAR_TILT_MAX", 80)
    pan_center: int = _integer("AUTOCAR_PAN_CENTER", 0)
    tilt_center: int = _integer("AUTOCAR_TILT_CENTER", -80)
    pan_invert: bool = os.getenv("AUTOCAR_PAN_INVERT", "0") == "1"
    tilt_invert: bool = os.getenv("AUTOCAR_TILT_INVERT", "1") == "1"
    tilt_logical_min: int = _integer("AUTOCAR_TILT_LOGICAL_MIN", -40)
    tilt_logical_max: int = _integer("AUTOCAR_TILT_LOGICAL_MAX", 10)
    i2c_bus: int = _integer("AUTOCAR_I2C_BUS", 1)
    pca9685_address: int = _number("AUTOCAR_PCA9685_ADDRESS", "0x40")
    pan_channel: int = _integer("AUTOCAR_PAN_CHANNEL", 12)
    tilt_channel: int = _integer("AUTOCAR_TILT_CHANNEL", 13)
    preview_model: str = os.getenv("AUTOCAR_PREVIEW_MODEL", "models/yolo26n_ncnn_model")
    preview_image_size: int = _integer("AUTOCAR_PREVIEW_IMGSZ", 640)
    preview_confidence: float = float(os.getenv("AUTOCAR_PREVIEW_CONFIDENCE", "0.40"))
    preview_max_detections: int = _integer("AUTOCAR_PREVIEW_MAX_DET", 20)
    preview_jpeg_quality: int = _integer("AUTOCAR_PREVIEW_JPEG_QUALITY", 65)
    autonomous_model: str = os.getenv("AUTOCAR_MODEL", "models/traffic_best.onnx")
    lane_model: str = os.getenv("AUTOCAR_LANE_MODEL", "models/lane_best_ncnn_model")
    lane_backend: str = os.getenv("AUTOCAR_LANE_BACKEND", "auto").strip().lower()
    inference_image_size: int = _integer("AUTOCAR_INFERENCE_IMGSZ", 416)
    traffic_confidence: float = float(os.getenv("AUTOCAR_TRAFFIC_CONFIDENCE", "0.45"))
    traffic_history: int = _integer("AUTOCAR_TRAFFIC_HISTORY", 5)
    traffic_votes: int = _integer("AUTOCAR_TRAFFIC_VOTES", 3)
    traffic_required: bool = _boolean("AUTOCAR_TRAFFIC_REQUIRED", True)
    lane_required: bool = _boolean("AUTOCAR_LANE_REQUIRED", True)
    lane_roi_start: float = float(os.getenv("AUTOCAR_LANE_ROI_START", "0.55"))
    lane_class_name: str = os.getenv("AUTOCAR_LANE_CLASS", "lane")
    autonomous_base_speed: float = float(os.getenv("AUTOCAR_AUTO_SPEED", "0.42"))
    autonomous_slow_speed: float = float(os.getenv("AUTOCAR_AUTO_SLOW_SPEED", "0.22"))
    lane_kp: float = float(os.getenv("AUTOCAR_LANE_KP", "0.0030"))
    lane_ki: float = float(os.getenv("AUTOCAR_LANE_KI", "0.00002"))
    lane_kd: float = float(os.getenv("AUTOCAR_LANE_KD", "0.0010"))
    lane_min_confidence: float = float(os.getenv("AUTOCAR_LANE_MIN_CONFIDENCE", "0.3"))
    traffic_stale_seconds: float = float(os.getenv("AUTOCAR_TRAFFIC_STALE_SECONDS", "1.0"))


CONFIG = Config()
