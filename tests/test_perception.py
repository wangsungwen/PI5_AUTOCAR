import unittest

from autocar.perception import PIDController, TrafficStateFilter


class TrafficStateFilterTests(unittest.TestCase):
    def test_green_requires_repeated_votes(self):
        filter_ = TrafficStateFilter(5, 3)
        self.assertEqual(filter_.update("GREEN"), "NONE")
        self.assertEqual(filter_.update("GREEN"), "NONE")
        self.assertEqual(filter_.update("GREEN"), "GREEN")

    def test_red_stops_immediately(self):
        filter_ = TrafficStateFilter(5, 3)
        self.assertEqual(filter_.update("RED"), "RED")
        self.assertEqual(filter_.update("GREEN"), "RED")
        self.assertEqual(filter_.update("GREEN"), "RED")
        self.assertEqual(filter_.update("GREEN"), "GREEN")


class PIDControllerTests(unittest.TestCase):
    def test_output_is_bounded(self):
        pid = PIDController(kp=1.0, ki=1.0, kd=1.0, max_output=0.35)
        self.assertLessEqual(abs(pid.update(1000, now=pid.previous_time + 0.1)), 0.35)


if __name__ == "__main__":
    unittest.main()
