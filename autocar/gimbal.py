from __future__ import annotations

import logging
import threading

from .config import Config
from .pca9685 import get_pca9685

LOG = logging.getLogger(__name__)


class GimbalController:
    def __init__(self, config: Config):
        self._config = config
        self._lock = threading.Lock()
        self._pan = 0
        self._tilt = 0
        self._pan_servo = self._tilt_servo = None
        self._pca = None
        if config.gimbal_backend == "pca9685":
            self._pca = get_pca9685(config)
            self._apply()
            LOG.info("PCA9685 gimbal enabled on channels %d/%d", config.pan_channel, config.tilt_channel)
        elif config.gimbal_backend == "gpiozero":
            from gpiozero import AngularServo

            self._pan_servo = AngularServo(config.pan_pin, min_angle=config.pan_min,
                max_angle=config.pan_max, min_pulse_width=0.0005, max_pulse_width=0.0025)
            self._tilt_servo = AngularServo(config.tilt_pin, min_angle=config.tilt_min,
                max_angle=config.tilt_max, min_pulse_width=0.0005, max_pulse_width=0.0025)
            self._apply()
            LOG.info("Legacy GPIO gimbal enabled on BCM %d/%d", config.pan_pin, config.tilt_pin)
        else:
            LOG.warning("Gimbal is running in mock mode")

    def move(self, axis: str, delta: int) -> dict:
        if axis not in {"pan", "tilt"}:
            raise ValueError("unsupported gimbal axis")
        delta = max(-self._config.gimbal_step, min(self._config.gimbal_step, int(delta)))
        with self._lock:
            if axis == "pan":
                if self._config.pan_invert:
                    low = self._config.pan_center - self._config.pan_max
                    high = self._config.pan_center - self._config.pan_min
                else:
                    low = self._config.pan_min - self._config.pan_center
                    high = self._config.pan_max - self._config.pan_center
                self._pan = max(low, min(high, self._pan + delta))
            else:
                low = self._config.tilt_logical_min
                high = self._config.tilt_logical_max
                self._tilt = max(low, min(high, self._tilt + delta))
            self._apply()
            return self.status()

    def center(self) -> dict:
        with self._lock:
            self._pan = self._tilt = 0
            self._apply()
            return self.status()

    def _apply(self) -> None:
        physical_pan = self._config.pan_center + (-self._pan if self._config.pan_invert else self._pan)
        physical_tilt = self._config.tilt_center + (-self._tilt if self._config.tilt_invert else self._tilt)
        if self._pca is not None:
            self._pca.set_servo_angle(self._config.pan_channel, physical_pan,
                self._config.pan_min, self._config.pan_max)
            self._pca.set_servo_angle(self._config.tilt_channel, physical_tilt,
                self._config.tilt_min, self._config.tilt_max)
        if self._pan_servo is not None:
            self._pan_servo.angle = physical_pan
        if self._tilt_servo is not None:
            self._tilt_servo.angle = physical_tilt

    def status(self) -> dict:
        return {
            "pan": self._pan, "tilt": self._tilt,
            "physical_pan": self._config.pan_center + (-self._pan if self._config.pan_invert else self._pan),
            "physical_tilt": self._config.tilt_center + (-self._tilt if self._config.tilt_invert else self._tilt),
            "pan_invert": self._config.pan_invert,
            "tilt_invert": self._config.tilt_invert,
            "tilt_min": self._config.tilt_logical_min,
            "tilt_max": self._config.tilt_logical_max,
            "backend": self._config.gimbal_backend,
            "pan_channel": self._config.pan_channel if self._pca else None,
            "tilt_channel": self._config.tilt_channel if self._pca else None,
        }

    def close(self) -> None:
        with self._lock:
            if self._pca is not None:
                self._pca.disable(self._config.pan_channel)
                self._pca.disable(self._config.tilt_channel)
            for servo in (self._pan_servo, self._tilt_servo):
                if servo is not None:
                    servo.detach(); servo.close()
