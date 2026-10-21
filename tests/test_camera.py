import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from autocar.camera import CameraRecorder


class CameraEncoderTests(unittest.TestCase):
    def test_stop_targets_recording_encoder_and_preserves_preview(self):
        encoder = Mock()
        modules = {
            'picamera2': types.ModuleType('picamera2'),
            'picamera2.encoders': types.SimpleNamespace(H264Encoder=Mock(return_value=encoder)),
            'picamera2.outputs': types.SimpleNamespace(FileOutput=Mock()),
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, modules):
            recorder = CameraRecorder(Path(tmp))
            camera = recorder._camera = Mock()
            preview = recorder._jpeg_encoder = Mock()
            recorder.start()
            recorder.stop()
            camera.stop_encoder.assert_called_once_with(encoder)
            self.assertFalse(recorder.status()['recording'])
            self.assertTrue(recorder.status()['preview'])
            recorder.stop()
            self.assertEqual(camera.stop_encoder.call_count, 1)
            recorder.start()
            recorder.close()
            self.assertEqual(camera.stop_encoder.call_args_list[-1].args, (preview,))
            self.assertEqual(camera.stop_encoder.call_count, 3)
            camera.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
