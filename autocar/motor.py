from __future__ import annotations

import logging
import threading
import time
from typing import Literal

from .config import Config
from .pca9685 import get_pca9685

Direction = Literal["forward", "backward", "left", "right", "stop"]
VALID_DIRECTIONS = {"forward", "backward", "left", "right", "stop"}
LOG = logging.getLogger(__name__)


class MotorController:
    def __init__(self, config: Config):
        self._config = config
        self._lock = threading.RLock()
        if not (0 <= config.manual_speed <= 100 and 0 < config.manual_speed_step <= 100
                and 0 < config.manual_steering_step <= config.manual_steering_max <= 90):
            raise ValueError("invalid manual speed or steering configuration")
        self._closed = threading.Event()
        self._speed = 0
        self._steering = 0
        self._left_command = self._right_command = 0.0
        self._enabled = False
        self._direction: Direction = "stop"
        self._last_command = time.monotonic()
        self._left = self._right = None
        self._motor_d1 = self._motor_d2 = None
        self._pca = None
        if config.gpio_backend == "pca9685":
            from gpiozero import OutputDevice

            self._pca = get_pca9685(config)
            self._motor_d1 = OutputDevice(25)
            self._motor_d2 = OutputDevice(24)
            self._stop_hardware()
            LOG.info("Four-motor PCA9685 backend enabled at 0x%02x", config.pca9685_address)
        elif config.gpio_backend == "gpiozero":
            from gpiozero import Motor

            self._left = Motor(forward=config.left_forward, backward=config.left_backward)
            self._right = Motor(forward=config.right_forward, backward=config.right_backward)
            LOG.info("Legacy two-motor GPIO backend enabled")
        else:
            LOG.warning("Motor controller is running in mock mode")
        threading.Thread(target=self._watchdog, daemon=True, name="motor-watchdog").start()

    def set_enabled(self, enabled: bool, *, start_manual: bool = True) -> dict:
        with self._lock:
            was_enabled = self._enabled
            self._enabled = enabled
            if not enabled:
                self._apply("stop")
            elif start_manual and not was_enabled:
                self._speed = self._config.manual_speed
                self._steering = 0
                self._last_command = time.monotonic()
                self._apply_manual()
            elif not start_manual:
                self._apply("stop")
            return self.status()

    def heartbeat(self) -> dict:
        """Keep manual motion alive without repeating incremental commands."""
        with self._lock:
            if self._enabled and self._direction != "auto":
                self._last_command = time.monotonic()
            return self.status()

    def drive(self, direction: str) -> dict:
        if direction not in VALID_DIRECTIONS | {"center"}:
            raise ValueError("unsupported direction")
        with self._lock:
            if direction != "stop" and not self._enabled:
                raise RuntimeError("vehicle is disabled")
            self._last_command = time.monotonic()
            if direction == "stop":
                self._apply("stop")
            else:
                if direction == "forward":
                    self._speed = min(100, self._speed + self._config.manual_speed_step)
                elif direction == "backward":
                    self._speed = max(0, self._speed - self._config.manual_speed_step)
                elif direction == "left":
                    self._steering = max(-self._config.manual_steering_max,
                                         self._steering - self._config.manual_steering_step)
                elif direction == "right":
                    self._steering = min(self._config.manual_steering_max,
                                        self._steering + self._config.manual_steering_step)
                else:
                    self._steering = 0
                self._apply_manual()
            return self.status()

    def _apply_manual(self) -> None:
        # Differential steering: inner wheels slow down, all wheels stay forward.
        # This angle is a command scale, not a measured heading or servo angle.
        turn = self._steering / self._config.manual_steering_max
        left = self._speed / 100 * (1 + min(0, turn) * 0.8)
        right = self._speed / 100 * (1 - max(0, turn) * 0.8)
        self._direction = ("stop" if not self._speed else
                           "left" if turn < 0 else "right" if turn > 0 else "forward")
        self._write_tank(left, right)

    def drive_tank(self, left: float, right: float) -> dict:
        """Drive each side independently with normalized commands (-1.0..1.0).

        This is the continuous control surface used by lane-following PID.  Manual
        incremental commands use drive() instead.
        """
        left = max(-1.0, min(1.0, float(left)))
        right = max(-1.0, min(1.0, float(right)))
        with self._lock:
            if (left or right) and not self._enabled:
                raise RuntimeError("vehicle is disabled")
            self._last_command = time.monotonic()
            self._direction = "stop" if left == 0 and right == 0 else "auto"  # type: ignore[assignment]
            self._speed = 0
            self._steering = 0
            self._write_tank(left, right)
            return self.status()

    def _write_tank(self, left: float, right: float) -> None:
        if self._left_command * left < 0 or self._right_command * right < 0:
            self._stop_hardware()
            for motor in (self._left, self._right):
                if motor is not None:
                    motor.stop()
            time.sleep(max(0.0, self._config.direction_change_delay))
        self._left_command, self._right_command = left, right
        if self._pca is not None:
            self._drive_four_tank(left, right)
        elif self._left is not None and self._right is not None:
            self._drive_gpio_motor(self._left, left)
            self._drive_gpio_motor(self._right, right)
        else:
            LOG.debug("mock tank drive: left=%.3f right=%.3f", left, right)

    @staticmethod
    def _drive_gpio_motor(motor, command: float) -> None:
        if command > 0:
            motor.forward(command)
        elif command < 0:
            motor.backward(abs(command))
        else:
            motor.stop()

    def _drive_four_tank(self, left: float, right: float) -> None:
        # Reference wiring: A/C are left and B/D are right.
        if left == 0 and right == 0:
            self._stop_hardware()
            return
        self._motor_a(left >= 0, round(abs(left) * 100))
        self._motor_c(left >= 0, round(abs(left) * 100))
        self._motor_b(right >= 0, round(abs(right) * 100))
        self._motor_d(right >= 0, round(abs(right) * 100))

    def _apply(self, direction: Direction) -> None:
        assert direction == "stop"
        self._speed = self._steering = 0
        self._direction = "stop"
        self._write_tank(0, 0)

    def _motor_a(self, forward: bool, speed: int) -> None:
        self._pca.set_level(2, not forward); self._pca.set_level(1, forward)
        self._pca.set_duty_cycle(0, speed)

    def _motor_b(self, forward: bool, speed: int) -> None:
        self._pca.set_level(3, forward); self._pca.set_level(4, not forward)
        self._pca.set_duty_cycle(5, speed)

    def _motor_c(self, forward: bool, speed: int) -> None:
        self._pca.set_level(8, forward); self._pca.set_level(7, not forward)
        self._pca.set_duty_cycle(6, speed)

    def _motor_d(self, forward: bool, speed: int) -> None:
        if forward:
            self._motor_d1.off(); self._motor_d2.on()
        else:
            self._motor_d1.on(); self._motor_d2.off()
        self._pca.set_duty_cycle(11, speed)

    def _stop_hardware(self) -> None:
        if self._pca is not None:
            for channel in (0, 5, 6, 11):
                self._pca.set_duty_cycle(channel, 0)
        if self._motor_d1 is not None:
            self._motor_d1.off(); self._motor_d2.off()

    def _watchdog(self) -> None:
        while not self._closed.wait(0.1):
            with self._lock:
                if self._direction != "stop" and time.monotonic() - self._last_command > self._config.watchdog_seconds:
                    LOG.warning("Drive watchdog timeout; stopping")
                    self._apply("stop")

    def status(self) -> dict:
        with self._lock:
            left, right = round(self._left_command * 100, 1), round(self._right_command * 100, 1)
            return {"enabled": self._enabled, "direction": self._direction,
                    "backend": self._config.gpio_backend,
                    "speed_percent": self._speed,
                    "steering_degrees": self._steering,
                    "speed_step": self._config.manual_speed_step,
                    "steering_step": self._config.manual_steering_step,
                    "steering_max": self._config.manual_steering_max,
                    "wheel_pwm": {"A": left, "B": right, "C": left, "D": right}}

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            self._enabled = False
            self._apply("stop")
            for motor in (self._left, self._right):
                if motor is not None:
                    motor.close()
            for output in (self._motor_d1, self._motor_d2):
                if output is not None:
                    output.close()
