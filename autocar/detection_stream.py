from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter
from pathlib import Path

LOG = logging.getLogger(__name__)


class DetectionStream:
    """Lazy YOLO-annotated MJPEG source sharing the project's camera."""

    def __init__(self, config, camera):
        self.config, self.camera = config, camera
        self._model = config.preview_model
        self._image_size = config.preview_image_size
        self._condition = threading.Condition()
        self._start_lock = threading.Lock()
        self._stop = threading.Event()
        self._enabled = False
        self._thread: threading.Thread | None = None
        self._frame: bytes | None = None
        self._sequence = 0
        self._fps = 0.0
        self._count = 0
        self._labels = ""
        self._error: str | None = None
        self._runtime_ready = False

    @staticmethod
    def _resolve_model(path_value: str) -> Path:
        path = Path(path_value)
        return path if path.is_absolute() else Path(__file__).resolve().parent.parent / path

    @staticmethod
    def _export_size(model_path: Path) -> tuple[int, int] | None:
        metadata_path = model_path / "metadata.yaml"
        if not metadata_path.is_file():
            return None
        lines = metadata_path.read_text(encoding="utf-8").splitlines()
        values: list[int] = []
        for index, line in enumerate(lines):
            match = re.match(r"^(\s*)imgsz\s*:\s*(.*)$", line)
            if match is None:
                continue
            values.extend(int(value) for value in re.findall(r"\d+", match.group(2)))
            if not values:
                base_indent = len(match.group(1))
                for following in lines[index + 1 :]:
                    if not following.strip():
                        continue
                    indent = len(following) - len(following.lstrip())
                    if indent <= base_indent and not following.lstrip().startswith("-"):
                        break
                    values.extend(int(value) for value in re.findall(r"\d+", following))
                    if len(values) >= 2:
                        break
            break
        if not values:
            return None
        return (values[0], values[0]) if len(values) == 1 else tuple(values[:2])

    @classmethod
    def _validate_export_size(cls, model_path: Path, configured_size: int) -> None:
        sizes = cls._export_size(model_path)
        if sizes is None:
            return
        if any(size != configured_size for size in sizes):
            shape = "x".join(str(size) for size in sizes)
            raise RuntimeError(
                f"NCNN input mismatch: model={shape}, "
                f"AUTOCAR_PREVIEW_IMGSZ={configured_size}"
            )

    def ensure_started(self) -> None:
        with self._condition:
            if not self._enabled:
                raise RuntimeError("preview inference disabled")
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            model_path = self._resolve_model(self._model)
            if not model_path.exists():
                self._error = f"preview model not found: {model_path}"
                raise RuntimeError(self._error)
            self._stop.clear()
            self._error = None
            self._thread = threading.Thread(
                target=self._run,
                args=(model_path, self._image_size),
                daemon=True,
                name="preview-inference",
            )
            self._thread.start()

    def set_enabled(self, enabled: bool) -> dict:
        """Enable or stop preview inference without stopping the shared camera."""
        if enabled:
            model_path = self._resolve_model(self._model)
            if not model_path.exists():
                with self._condition:
                    self._error = f"preview model not found: {model_path}"
                raise RuntimeError(self._error)
            try:
                self._validate_export_size(model_path, self._image_size)
                self.preload_runtime()
            except Exception as exc:
                with self._condition:
                    self._error = f"inference runtime unavailable: {exc}"
                raise RuntimeError(self._error) from exc
            with self._condition:
                self._enabled = True
            try:
                self.ensure_started()
            except Exception:
                with self._condition:
                    self._enabled = False
                raise
        else:
            self._stop_worker()
            with self._condition:
                self._enabled = False
                self._frame = None
                self._fps = 0.0
                self._count = 0
                self._labels = ""
                self._error = None
                self._condition.notify_all()
        return self.status()

    def preload_runtime(self) -> None:
        """Load AI native libraries before Picamera2 opens its native stack."""
        if self._runtime_ready:
            return
        # PyTorch must be first on Pi 5. Opening Picamera2 before this can load
        # a conflicting BLAS provider and make libtorch_cpu.so miss sbgemm_.
        import torch  # noqa: F401
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        import ultralytics  # noqa: F401
        import ncnn  # noqa: F401
        self._runtime_ready = True

    def profiles(self) -> list[dict]:
        """Return installed NCNN directories whose metadata declares a square input."""
        models_dir = Path(__file__).resolve().parent.parent / "models"
        candidates = list(models_dir.iterdir()) if models_dir.is_dir() else []
        current = self._resolve_model(self._model)
        if current not in candidates:
            candidates.append(current)
        profiles = []
        for path in candidates:
            if not path.is_dir():
                continue
            sizes = self._export_size(path)
            if sizes is None or sizes[0] != sizes[1]:
                continue
            try:
                model = str(path.relative_to(Path(__file__).resolve().parent.parent))
            except ValueError:
                model = str(path)
            profiles.append({"model": model, "imgsz": sizes[0], "name": f"{path.name} ({sizes[0]}×{sizes[0]})"})
        return sorted(profiles, key=lambda item: (item["imgsz"], item["model"]))

    def configure(self, model: str, image_size: int) -> dict:
        with self._condition:
            if self._enabled:
                raise RuntimeError("請先關閉視覺推論再切換模型")
        requested = {"model": str(model), "imgsz": int(image_size)}
        if requested not in ({"model": p["model"], "imgsz": p["imgsz"]} for p in self.profiles()):
            raise RuntimeError("模型或固定尺寸不在可用的 NCNN 設定檔中")
        model_path = self._resolve_model(requested["model"])
        self._validate_export_size(model_path, requested["imgsz"])
        with self._condition:
            self._model = requested["model"]
            self._image_size = requested["imgsz"]
            self._error = None
        return self.status()

    def _stop_worker(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _run(self, model_path: Path, image_size: int) -> None:
        try:
            import cv2
            from ultralytics import YOLO

            model = YOLO(str(model_path))
            previous = time.monotonic()
            smoothed_fps = 0.0
            LOG.info("YOLO preview enabled: %s", model_path)
            while not self._stop.is_set():
                frame = self.camera.capture_bgr()
                result = model.predict(
                    frame,
                    imgsz=image_size,
                    conf=self.config.preview_confidence,
                    max_det=self.config.preview_max_detections,
                    verbose=False,
                )[0]
                annotated = result.plot()
                now = time.monotonic()
                instant_fps = 1.0 / max(now - previous, 1e-4)
                previous = now
                smoothed_fps = instant_fps if not smoothed_fps else (
                    smoothed_fps * 0.85 + instant_fps * 0.15
                )
                labels = [] if result.boxes is None else [
                    str(model.names[int(box.cls[0])]) for box in result.boxes
                ]
                cv2.putText(
                    annotated,
                    f"FPS {smoothed_fps:.1f}",
                    (14, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 120),
                    2,
                    cv2.LINE_AA,
                )
                ok, encoded = cv2.imencode(
                    ".jpg",
                    annotated,
                    [cv2.IMWRITE_JPEG_QUALITY, self.config.preview_jpeg_quality],
                )
                if not ok:
                    continue
                counts = Counter(labels)
                with self._condition:
                    self._frame = encoded.tobytes()
                    self._sequence += 1
                    self._fps = smoothed_fps
                    self._count = len(labels)
                    self._labels = ", ".join(
                        f"{name} x{count}" for name, count in counts.items()
                    )
                    self._error = None
                    self._condition.notify_all()
        except Exception as exc:
            LOG.exception("YOLO preview stopped")
            with self._condition:
                self._error = str(exc)
                # Return the shared endpoint to raw-camera mode.  Keeping this
                # true would route every new browser request to a dead worker.
                self._enabled = False
                self._condition.notify_all()

    def wait_for_frame(self, sequence: int, timeout: float = 5.0) -> tuple[bytes | None, int]:
        with self._condition:
            if not self._enabled:
                raise RuntimeError("preview inference disabled")
        self.ensure_started()
        with self._condition:
            self._condition.wait_for(
                lambda: self._sequence != sequence or self._error is not None,
                timeout=timeout,
            )
            if self._error and self._frame is None:
                raise RuntimeError(self._error)
            return self._frame, self._sequence

    def status(self) -> dict:
        with self._condition:
            return {
                "enabled": self._enabled,
                "running": self._thread is not None and self._thread.is_alive(),
                "fps": round(self._fps, 1),
                "count": self._count,
                "labels": self._labels,
                "model": self._model,
                "imgsz": self._image_size,
                "profiles": self.profiles(),
                "runtime_ready": self._runtime_ready,
                "error": self._error,
            }

    def close(self) -> None:
        self._stop_worker()
