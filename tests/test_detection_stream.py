import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from autocar.detection_stream import DetectionStream


class DetectionStreamTests(unittest.TestCase):
    def test_missing_model_fails_without_starting_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing_ncnn_model"
            config = SimpleNamespace(preview_model=str(missing), preview_image_size=640)
            stream = DetectionStream(config, camera=object())

            with self.assertRaisesRegex(RuntimeError, "preview model not found"):
                stream.set_enabled(True)

            status = stream.status()
            self.assertFalse(status["enabled"])
            self.assertFalse(status["running"])
            self.assertIn("preview model not found", status["error"])

    def test_disabled_stream_reports_raw_preview_state(self):
        config = SimpleNamespace(preview_model="unused", preview_image_size=640)
        stream = DetectionStream(config, camera=object())

        status = stream.set_enabled(False)

        self.assertFalse(status["enabled"])
        self.assertFalse(status["running"])
        self.assertEqual(status["fps"], 0.0)
        self.assertEqual(status["count"], 0)
        self.assertEqual(status["labels"], "")
        self.assertIsNone(status["error"])

    def test_ncnn_export_size_must_match_runtime_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model"
            model.mkdir()
            (model / "metadata.yaml").write_text("imgsz:\n- 320\n- 320\n", encoding="utf-8")
            config = SimpleNamespace(preview_model=str(model), preview_image_size=640)
            stream = DetectionStream(config, camera=object())

            with self.assertRaisesRegex(
                RuntimeError,
                "NCNN input mismatch: model=320x320, AUTOCAR_PREVIEW_IMGSZ=640",
            ):
                stream.set_enabled(True)

            self.assertFalse(stream.status()["enabled"])

    def test_configure_switches_to_installed_matching_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "model"
            model.mkdir()
            (model / "metadata.yaml").write_text("imgsz: [320, 320]\n", encoding="utf-8")
            config = SimpleNamespace(preview_model=str(model), preview_image_size=640)
            stream = DetectionStream(config, camera=object())

            result = stream.configure(str(model), 320)

            self.assertEqual(result["model"], str(model))
            self.assertEqual(result["imgsz"], 320)


if __name__ == "__main__":
    unittest.main()
