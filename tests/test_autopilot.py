import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from autocar.autopilot import Autopilot
from autocar.config import Config
from autocar.perception import LaneObservation


class AutopilotTests(unittest.TestCase):
    def make(self, **changes):
        config = replace(Config(), lane_backend='opencv', lane_required=False,
                         traffic_required=False, **changes)
        pilot = Autopilot(config, Mock(), Mock())
        pilot._enabled = True
        return pilot

    def test_stop_during_inference_never_resumes_motor(self):
        pilot = self.make()
        entered, release = threading.Event(), threading.Event()
        def detect(frame):
            entered.set()
            release.wait(3)
            return LaneObservation(0, 1, 10, 10)
        with patch('autocar.autopilot.LaneDetector') as detector:
            detector.return_value.detect.side_effect = detect
            thread = threading.Thread(target=pilot._control_loop)
            pilot._threads = [thread]
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                pilot.stop()
                pilot.motor.drive_tank.assert_called_once_with(0, 0)
                with self.assertRaisesRegex(RuntimeError, 'still stopping'):
                    pilot.start()
            finally:
                release.set()
                thread.join(2)
            pilot.motor.drive_tank.assert_called_once_with(0, 0)

    def test_initialization_failure_stops_and_reports(self):
        pilot = self.make()
        with patch('autocar.autopilot.LaneDetector', side_effect=ValueError('bad model')):
            pilot._control_loop()
        self.assertFalse(pilot.status()['enabled'])
        self.assertIn('bad model', pilot.status()['error'])
        pilot.motor.drive_tank.assert_called_once_with(0, 0)

    def test_slow_lane_result_cannot_drive(self):
        pilot = self.make(watchdog_seconds=0.01)
        def detect(frame):
            time.sleep(0.02)
            return LaneObservation(0, 1, 10, 10)
        pilot.motor.drive_tank.side_effect = lambda *args: pilot._stop.set()
        with patch('autocar.autopilot.LaneDetector') as detector:
            detector.return_value.detect.side_effect = detect
            pilot._control_loop()
        pilot.motor.drive_tank.assert_called_once_with(0, 0)

    def test_same_frame_is_not_recounted_and_timestamp_is_capture_time(self):
        pilot = self.make(autonomous_model=str(Path(__file__)))
        pilot._frame, pilot._frame_sequence, pilot._frame_time = object(), 1, 123.0
        observed = threading.Event()
        def detect(frame):
            observed.set()
            return 'GREEN', 0.9
        with patch('autocar.autopilot.TrafficDetector') as detector:
            detector.return_value.detect.side_effect = detect
            thread = threading.Thread(target=pilot._traffic_loop)
            thread.start()
            try:
                self.assertTrue(observed.wait(2))
                time.sleep(0.05)
            finally:
                pilot._stop.set()
                thread.join(2)
            self.assertEqual(detector.return_value.detect.call_count, 1)
            self.assertEqual(pilot._traffic_updated, 123.0)

    def test_required_traffic_failure_stops_immediately(self):
        pilot = self.make(autonomous_model=str(Path(__file__)))
        pilot.config = replace(pilot.config, traffic_required=True)
        with patch('autocar.autopilot.TrafficDetector', side_effect=ValueError('bad traffic')):
            pilot._traffic_loop()
        self.assertFalse(pilot.status()['enabled'])
        pilot.motor.drive_tank.assert_called_once_with(0, 0)

    def test_yellow_does_not_reverse_inner_wheel(self):
        pilot = self.make()
        pilot._traffic, pilot._traffic_updated = 'YELLOW', time.monotonic()
        pilot.motor.drive_tank.side_effect = lambda *args: pilot._stop.set()
        with patch('autocar.autopilot.LaneDetector') as detector:
            detector.return_value.detect.return_value = LaneObservation(1000, 1, 1010, 10)
            pilot._control_loop()
        left, right = pilot.motor.drive_tank.call_args.args
        self.assertGreaterEqual(min(left, right), 0)


if __name__ == '__main__':
    unittest.main()
