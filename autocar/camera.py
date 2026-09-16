from __future__ import annotations

import io
import logging
import threading
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger(__name__)


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame: bytes | None = None
        self.condition = threading.Condition()

    def write(self, buf: bytes) -> int:
        with self.condition:
            self.frame = bytes(buf)
            self.condition.notify_all()
        return len(buf)


class CameraRecorder:
    """One Picamera2 instance shared by live preview and H.264 recording."""

    def __init__(self, output_dir: Path, rotate_180: bool = True, camera_index: int = 0):
        self._dir = output_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._rotate_180 = rotate_180
        self._camera_index = camera_index
        self._lock = threading.RLock()
        self._camera = None
        self._jpeg_encoder = None
        self._stream_output = StreamingOutput()
        self._recording = False
        self._file: Path | None = None
        self._error: str | None = None

    def _ensure_camera(self) -> None:
        if self._camera is not None:
            return
        try:
            from picamera2 import Picamera2
            from picamera2.encoders import MJPEGEncoder
            from picamera2.outputs import FileOutput
            from libcamera import Transform

            camera = Picamera2(self._camera_index)
            config = camera.create_video_configuration(
                main={"size": (1280, 720), "format": "YUV420"},
                lores={"size": (640, 360), "format": "YUV420"},
                encode="main",
                buffer_count=6,
                transform=Transform(hflip=self._rotate_180, vflip=self._rotate_180),
            )
            camera.configure(config)
            camera.start()
            jpeg_encoder = MJPEGEncoder(bitrate=3_000_000)
            camera.start_encoder(jpeg_encoder, FileOutput(self._stream_output), name="lores")
            self._camera = camera
            self._jpeg_encoder = jpeg_encoder
            self._error = None
            LOG.info("Pi Camera preview started")
        except Exception as exc:
            self._error = str(exc)
            LOG.exception("Unable to start Pi Camera")
            raise RuntimeError(f"無法啟動 Pi Camera：{exc}") from exc

    def ensure_preview(self) -> None:
        with self._lock:
            self._ensure_camera()

    def wait_for_frame(self, previous: bytes | None, timeout: float = 5.0) -> bytes | None:
        self.ensure_preview()
        with self._stream_output.condition:
            if self._stream_output.frame is previous:
                self._stream_output.condition.wait(timeout)
            return self._stream_output.frame

    def capture_bgr(self):
        """Return one BGR frame for perception without creating another camera instance."""
        with self._lock:
            self._ensure_camera()
            frame = self._camera.capture_array("main")
        try:
            import cv2
            return cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)
        except ImportError:
            # Raspberry Pi OS always provides NumPy with Picamera2.  Keep a
            # dependency-light fallback so lane-only mode works before the
            # optional OpenCV package is installed.
            import numpy as np

            rows, width = frame.shape[:2]
            height = rows * 2 // 3
            flat = frame.reshape(-1)
            y = flat[: height * width].reshape(height, width).astype(np.float32)
            quarter = height * width // 4
            u = flat[height * width: height * width + quarter].reshape(height // 2, width // 2)
            v = flat[height * width + quarter:].reshape(height // 2, width // 2)
            u = np.repeat(np.repeat(u, 2, axis=0), 2, axis=1).astype(np.float32) - 128.0
            v = np.repeat(np.repeat(v, 2, axis=0), 2, axis=1).astype(np.float32) - 128.0
            c = np.maximum(y - 16.0, 0.0)
            blue = 1.164 * c + 2.018 * u
            green = 1.164 * c - 0.391 * u - 0.813 * v
            red = 1.164 * c + 1.596 * v
            return np.clip(np.stack((blue, green, red), axis=2), 0, 255).astype(np.uint8)

    def start(self) -> dict:
        with self._lock:
            if self._recording:
                return self.status()
            self._ensure_camera()
            from picamera2.encoders import H264Encoder
            from picamera2.outputs import FileOutput

            self._file = self._dir / f"autocar-{datetime.now():%Y%m%d-%H%M%S}.h264"
            self._camera.start_encoder(
                H264Encoder(bitrate=6_000_000), FileOutput(str(self._file)), name="main"
            )
            self._recording = True
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            if self._recording and self._camera is not None:
                self._camera.stop_encoder("main")
            self._recording = False
            return self.status()

    def close(self) -> None:
        with self._lock:
            self.stop()
            if self._camera is not None:
                if self._jpeg_encoder is not None:
                    self._camera.stop_encoder("lores")
                self._camera.stop()
                self._camera.close()
            self._camera = None
            self._jpeg_encoder = None

    def status(self) -> dict:
        return {
            "recording": self._recording,
            "preview": self._camera is not None,
            "file": str(self._file) if self._file else None,
            "error": self._error,
        }
