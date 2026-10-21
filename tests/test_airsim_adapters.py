"""Unit tests for the AirSim bridge; no simulator or airsim package required."""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _install_fake_airsim():
    """Minimal stand-in for the airsim module (types only)."""
    module = types.ModuleType("airsim")

    class CarControls:
        def __init__(self, throttle=0, steering=0, brake=0):
            self.throttle, self.steering, self.brake = throttle, steering, brake
            self.manual_gear = 0

        def set_throttle(self, value, forward):
            self.throttle = abs(value) if forward else -abs(value)
            self.manual_gear = 0 if forward else -1

    class ImageType:
        Scene = 0

    module.CarControls = CarControls
    module.ImageType = ImageType
    module.ImageRequest = lambda *a: a
    sys.modules["airsim"] = module


_install_fake_airsim()
from sim_airsim.adapters import AirSimCamera, AirSimLink, AirSimMotor  # noqa: E402


class FakeClient:
    def __init__(self, speed=0.0, width=4, height=2):
        self.speed, self.width, self.height = speed, width, height
        self.controls = None

    def getCarState(self, vehicle):
        return types.SimpleNamespace(speed=self.speed)

    def setCarControls(self, controls, vehicle):
        self.controls = controls

    def simGetImages(self, requests, vehicle):
        data = bytes(range(self.width * self.height * 3))
        return [types.SimpleNamespace(width=self.width, height=self.height, image_data_uint8=data)]


class MotorMappingTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.motor = AirSimMotor(AirSimLink(client=self.client))

    def test_disabled_motor_rejects_motion(self):
        with self.assertRaises(RuntimeError):
            self.motor.drive_tank(0.4, 0.4)

    def test_zero_command_brakes(self):
        self.motor.drive_tank(0, 0)
        self.assertEqual(self.client.controls.brake, 1.0)
        self.assertEqual(self.client.controls.throttle, 0.0)

    def test_left_faster_steers_right(self):
        self.motor.set_enabled(True)
        self.motor.drive_tank(0.42 + 0.2, 0.42 - 0.2)
        self.assertGreater(self.client.controls.steering, 0)
        self.assertGreater(self.client.controls.throttle, 0)

    def test_pid_full_scale_is_full_lock(self):
        command = self.motor.tank_to_controls(0.42 + 0.35, 0.42 - 0.35, speed=0)
        self.assertAlmostEqual(command["steering"], 1.0)

    def test_overspeed_brakes(self):
        command = self.motor.tank_to_controls(0.2, 0.2, speed=5.0)  # target 1.2 m/s
        self.assertGreater(command["brake"], 0)
        self.assertEqual(command["throttle"], 0)

    def test_reverse(self):
        self.motor.set_enabled(True)
        self.motor.drive_tank(-0.3, -0.3)
        self.assertLess(self.client.controls.throttle, 0)


class CameraTest(unittest.TestCase):
    def test_frame_shape_and_swap(self):
        link = AirSimLink(client=FakeClient(width=4, height=2))
        frame = AirSimCamera(link, max_fps=0).capture_bgr()
        self.assertEqual(frame.shape, (2, 4, 3))
        swapped = AirSimCamera(link, swap_rb=True, max_fps=0).capture_bgr()
        self.assertEqual(int(swapped[0, 0, 0]), int(frame[0, 0, 2]))

    def test_empty_image_raises(self):
        link = AirSimLink(client=FakeClient(width=0, height=0))
        with self.assertRaises(RuntimeError):
            AirSimCamera(link, retries=2, max_fps=0).capture_bgr()


if __name__ == "__main__":
    unittest.main()
