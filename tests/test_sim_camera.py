import tempfile
import unittest
from unittest.mock import Mock
from autocar.sim_camera import SimCamera


class SimCameraTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.camera = Mock()
        self.camera.status.return_value = {"recording": False}
        self.camera.start.return_value = {"file": "pi.h264"}
        self.sim = SimCamera(self.camera, "unused", self.directory.name)

    def test_start_stop_and_manifest(self):
        self.sim.request = Mock(side_effect=[
            {"connected": True, "recording": False},
            {"file": "ue4.avi", "started": 123}, {"recording": False}])
        session = self.sim.start()
        self.assertEqual(session["pi_file"], "pi.h264")
        self.assertTrue(self.sim.active)
        self.sim.stop()
        self.assertFalse(self.sim.active)
        self.assertEqual(len(list(self.sim.output_dir.glob("dual-*.json"))), 1)

    def test_remote_start_timeout_rolls_back_both(self):
        self.sim.request = Mock(side_effect=[
            {"connected": True, "recording": False}, RuntimeError("timeout"), {}])
        with self.assertRaises(RuntimeError):
            self.sim.start()
        self.camera.stop.assert_called_once()
        self.assertEqual(self.sim.request.call_args.args, ("/record/stop", True))
        self.assertFalse(self.sim.active)

    def test_stop_failure_is_retryable(self):
        self.sim.active = True
        self.sim.request = Mock(side_effect=RuntimeError("disconnected"))
        with self.assertRaises(RuntimeError):
            self.sim.stop()
        self.camera.stop.assert_called_once()
        self.assertTrue(self.sim.active)

    def test_existing_pi_recording_is_not_taken_over(self):
        self.camera.status.return_value = {"recording": True}
        with self.assertRaises(RuntimeError):
            self.sim.start()
        self.camera.start.assert_not_called()
