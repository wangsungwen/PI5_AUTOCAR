from __future__ import annotations

import math
import threading
import time

from .config import Config


class PCA9685:
    MODE1 = 0x00
    PRESCALE = 0xFE
    LED0_ON_L = 0x06

    def __init__(self, bus_number: int, address: int, frequency: int = 50):
        try:
            import smbus
        except ImportError as exc:
            raise RuntimeError("python3-smbus is not installed") from exc
        self.address = address
        self.frequency = frequency
        self._bus = smbus.SMBus(bus_number)
        self._lock = threading.RLock()
        self._write(self.MODE1, 0x00)
        self.set_frequency(frequency)

    def _write(self, register: int, value: int) -> None:
        self._bus.write_byte_data(self.address, register, value)

    def _read(self, register: int) -> int:
        return self._bus.read_byte_data(self.address, register)

    def set_frequency(self, frequency: int) -> None:
        with self._lock:
            prescale = int(math.floor(25_000_000.0 / 4096.0 / frequency - 1.0 + 0.5))
            old_mode = self._read(self.MODE1)
            self._write(self.MODE1, (old_mode & 0x7F) | 0x10)
            self._write(self.PRESCALE, prescale)
            self._write(self.MODE1, old_mode)
            time.sleep(0.005)
            self._write(self.MODE1, old_mode | 0x80)
            self.frequency = frequency

    def set_pwm(self, channel: int, on: int, off: int) -> None:
        if not 0 <= channel <= 15:
            raise ValueError("PCA9685 channel must be 0..15")
        off = max(0, min(4095, int(off)))
        base = self.LED0_ON_L + 4 * channel
        with self._lock:
            self._write(base, on & 0xFF)
            self._write(base + 1, on >> 8)
            self._write(base + 2, off & 0xFF)
            self._write(base + 3, off >> 8)

    def set_duty_cycle(self, channel: int, duty: float) -> None:
        self.set_pwm(channel, 0, int(max(0, min(100, duty)) * 4095 / 100.0))

    def set_level(self, channel: int, high: bool) -> None:
        self.set_pwm(channel, 0, 4095 if high else 0)

    def set_servo_angle(self, channel: int, angle: float, minimum: float, maximum: float) -> None:
        angle = max(minimum, min(maximum, angle))
        ratio = (angle - minimum) / (maximum - minimum)
        pulse_us = 500.0 + ratio * 2000.0
        ticks = round(pulse_us * 4096.0 * self.frequency / 1_000_000.0)
        self.set_pwm(channel, 0, ticks)

    def disable(self, channel: int) -> None:
        self.set_pwm(channel, 0, 0)


_instances: dict[tuple[int, int], PCA9685] = {}
_instances_lock = threading.Lock()


def get_pca9685(config: Config) -> PCA9685:
    key = (config.i2c_bus, config.pca9685_address)
    with _instances_lock:
        if key not in _instances:
            _instances[key] = PCA9685(*key, frequency=50)
        return _instances[key]
