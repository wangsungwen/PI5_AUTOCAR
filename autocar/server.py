from __future__ import annotations

import json
import logging
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .camera import CameraRecorder
from .config import CONFIG
from .motor import MotorController
from .gimbal import GimbalController
from .autopilot import Autopilot
from .detection_stream import DetectionStream

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
MOTOR = MotorController(CONFIG)
CAMERA = CameraRecorder(CONFIG.recordings_dir, CONFIG.camera_rotate_180, CONFIG.camera_index)
GIMBAL = GimbalController(CONFIG)
AUTOPILOT = Autopilot(CONFIG, MOTOR, CAMERA)
DETECTION = DetectionStream(CONFIG, CAMERA)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def _json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        # Prevent an old index.html and a new app.js (or vice versa) from being
        # mixed after a Pi/service restart.
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def _body(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(size) or b"{}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/status":
            self._json(200, {"vehicle": MOTOR.status(), "camera": CAMERA.status(), "detection": DETECTION.status(), "gimbal": GIMBAL.status(), "autopilot": AUTOPILOT.status()})
        elif path == "/api/camera/stream":
            if DETECTION.status()["enabled"]:
                self._detection_stream()
            else:
                self._camera_stream()
        else:
            super().do_GET()

    def _camera_stream(self) -> None:
        try:
            CAMERA.ensure_preview()
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()
            previous = None
            while True:
                frame = CAMERA.wait_for_frame(previous)
                if frame is None or frame is previous:
                    continue
                previous = frame
                self.wfile.write(b"--FRAME\r\nContent-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except RuntimeError as exc:
            logging.warning("Camera stream unavailable: %s", exc)

    def _detection_stream(self) -> None:
        try:
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()
            sequence = -1
            while True:
                frame, current = DETECTION.wait_for_frame(sequence)
                if frame is None or current == sequence:
                    continue
                sequence = current
                self.wfile.write(b"--FRAME\r\nContent-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except RuntimeError as exc:
            logging.warning("Detection stream unavailable: %s", exc)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/vehicle/enable":
                body = self._body()
                if not bool(body.get("enabled")):
                    AUTOPILOT.stop()
                result = MOTOR.set_enabled(bool(body.get("enabled")))
            elif path == "/api/vehicle/heartbeat":
                result = MOTOR.heartbeat()
            elif path == "/api/vehicle/drive":
                if AUTOPILOT.status()["enabled"]:
                    AUTOPILOT.stop()
                result = MOTOR.drive(str(self._body().get("direction", "stop")))
            elif path == "/api/autopilot/enable":
                enabled = bool(self._body().get("enabled"))
                detection_was_enabled = DETECTION.status()["enabled"]
                if enabled:
                    DETECTION.set_enabled(True)
                try:
                    result = AUTOPILOT.set_enabled(enabled)
                except Exception:
                    if enabled and not detection_was_enabled:
                        DETECTION.set_enabled(False)
                    raise
            elif path == "/api/detection/enable":
                enabled = bool(self._body().get("enabled"))
                if not enabled and AUTOPILOT.status()["enabled"]:
                    raise RuntimeError("自動駕駛運行中不可關閉視覺推論")
                result = DETECTION.set_enabled(enabled)
            elif path == "/api/detection/configure":
                if AUTOPILOT.status()["enabled"]:
                    raise RuntimeError("自動駕駛運行中不可切換推論模型")
                body = self._body()
                result = DETECTION.configure(str(body.get("model", "")), int(body.get("imgsz", 0)))
            elif path == "/api/camera/start":
                result = CAMERA.start()
            elif path == "/api/camera/stop":
                result = CAMERA.stop()
            elif path == "/api/gimbal/move":
                body = self._body()
                result = GIMBAL.move(str(body.get("axis")), int(body.get("delta", 0)))
            elif path == "/api/gimbal/center":
                result = GIMBAL.center()
            else:
                self._json(404, {"error": "not found"}); return
            self._json(200, result)
        except (ValueError, RuntimeError) as exc:
            self._json(409, {"error": str(exc)})
        except Exception:
            logging.exception("Request failed")
            self._json(500, {"error": "internal error; check service log"})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        # This must happen before the first browser request opens Picamera2.
        DETECTION.preload_runtime()
        logging.info("AI runtime preloaded before camera initialization")
    except Exception:
        # Manual driving and raw preview remain usable if the optional runtime
        # is broken; the detection endpoint will return the detailed error.
        logging.exception("AI runtime preload failed; inference will be unavailable")
    server = ThreadingHTTPServer((CONFIG.host, CONFIG.port), Handler)
    logging.info("AutoCAR Web UI: http://%s:%d", CONFIG.host, CONFIG.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        AUTOPILOT.close()
        DETECTION.close()
        MOTOR.close()
        GIMBAL.close()
        CAMERA.close()
        server.server_close()


if __name__ == "__main__":
    main()
