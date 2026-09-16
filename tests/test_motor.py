import time
import unittest
from unittest.mock import Mock, patch

from autocar.config import Config
from autocar.motor import MotorController


class MotorTests(unittest.TestCase):
    def setUp(self):
        self.car = MotorController(Config(gpio_backend="mock", manual_speed=50,
            manual_speed_step=5, manual_steering_step=5, manual_steering_max=45,
            watchdog_seconds=0.15, direction_change_delay=0))
        self.addCleanup(self.car.close)

    def test_enable_starts_all_wheels_and_duplicate_enable_preserves_speed(self):
        self.assertEqual(self.car.status()["speed_percent"], 0)
        self.assertEqual(set(self.car.set_enabled(True)["wheel_pwm"].values()), {50})
        self.car.drive("forward")
        self.assertEqual(self.car.set_enabled(True)["speed_percent"], 55)

    def test_speed_steps_saturate_without_reverse(self):
        self.car.set_enabled(True)
        for _ in range(30):
            self.car.drive("forward")
        self.assertEqual(set(self.car.status()["wheel_pwm"].values()), {100})
        for _ in range(30):
            self.car.drive("backward")
        self.assertEqual(set(self.car.status()["wheel_pwm"].values()), {0})
        self.assertEqual(self.car.status()["direction"], "stop")

    def test_steering_accumulates_and_speed_changes_all_wheels(self):
        self.car.set_enabled(True)
        self.car.drive("left")
        previous = self.car.drive("left")
        self.assertEqual(previous["steering_degrees"], -10)
        wheels = previous["wheel_pwm"]
        self.assertEqual(wheels["A"], wheels["C"])
        self.assertEqual(wheels["B"], wheels["D"])
        self.assertLess(wheels["A"], wheels["B"])
        faster = self.car.drive("forward")
        for wheel in wheels:
            self.assertGreater(faster["wheel_pwm"][wheel], wheels[wheel])
        slower = self.car.drive("backward")
        self.assertEqual(slower["wheel_pwm"], wheels)
        for _ in range(30):
            self.car.drive("right")
        self.assertEqual(self.car.status()["steering_degrees"], 45)
        self.assertGreater(self.car.status()["wheel_pwm"]["A"], self.car.status()["wheel_pwm"]["B"])
        self.assertEqual(set(self.car.drive("center")["wheel_pwm"].values()), {50})

    def test_stop_disable_and_heartbeat_never_restart(self):
        self.car.set_enabled(True)
        self.car.drive("left")
        self.car.drive("stop")
        self.assertEqual(self.car.heartbeat()["wheel_pwm"], dict.fromkeys("ABCD", 0))
        self.assertEqual(self.car.status()["steering_degrees"], 0)
        self.assertEqual(self.car.drive("forward")["speed_percent"], 5)
        self.car.set_enabled(False)
        with self.assertRaises(RuntimeError):
            self.car.drive("forward")

    def test_heartbeat_preserves_state_and_timeout_stops(self):
        self.car.set_enabled(True)
        before = self.car.drive("left")
        for _ in range(5):
            time.sleep(0.05)
            self.assertEqual(self.car.heartbeat(), before)
        deadline = time.monotonic() + 1
        while self.car.status()["direction"] != "stop" and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(self.car.heartbeat()["speed_percent"], 0)

    def test_autopilot_enable_has_no_forward_start_and_no_manual_keepalive(self):
        self.car.set_enabled(True, start_manual=False)
        self.assertEqual(set(self.car.status()["wheel_pwm"].values()), {0})
        self.car.drive_tank(0.2, 0.4)
        timestamp = self.car._last_command
        self.car.heartbeat()
        self.assertEqual(timestamp, self.car._last_command)
        self.assertEqual(self.car.status()["wheel_pwm"], {"A":20,"B":40,"C":20,"D":40})

    def test_pca_channels_and_forward_polarities_match_reference(self):
        self.car._pca = Mock()
        self.car._motor_d1, self.car._motor_d2 = Mock(), Mock()
        self.car.set_enabled(True)
        self.assertEqual({c.args for c in self.car._pca.set_duty_cycle.call_args_list},
                         {(0,50),(5,50),(6,50),(11,50)})
        self.assertEqual({c.args for c in self.car._pca.set_level.call_args_list},
                         {(2,False),(1,True),(3,True),(4,False),(8,True),(7,False)})
        self.car._motor_d1.off.assert_called()
        self.car._motor_d2.on.assert_called()
        self.car.drive("left")
        self.car.drive("stop")
        self.assertEqual({c.args for c in self.car._pca.set_duty_cycle.call_args_list[-4:]},
                         {(0,0),(5,0),(6,0),(11,0)})


if __name__ == "__main__":
    unittest.main()
