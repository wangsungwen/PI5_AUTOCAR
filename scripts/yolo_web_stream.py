from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PAGE = """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>YOLO26 - Raspberry Pi 5</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #091019; color: #edf5ff; }
    main { width: min(1100px, 100%); margin: auto; padding: 18px; }
    header { display: flex; align-items: end; justify-content: space-between; gap: 16px; }
    h1 { margin: 0; font-size: clamp(1.35rem, 4vw, 2rem); }
    p { margin: .35rem 0 1rem; color: #9db0c7; }
    .badge { padding: .4rem .75rem; border-radius: 999px; background: #17334a; color: #69d6ff; }
    .badge.bad { background: #4a1d24; color: #ff9aa8; }
    .frame { overflow: hidden; border: 1px solid #25384b; border-radius: 14px; background: #020509; }
    img { display: block; width: 100%; height: auto; aspect-ratio: 4/3; object-fit: contain; }
    .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 12px; }
    .stat { padding: 12px 14px; border: 1px solid #25384b; border-radius: 12px; background: #101b27; }
    .stat small { display: block; color: #8ea2b8; }
    .stat strong { display: block; margin-top: 4px; overflow-wrap: anywhere; }
    @media (max-width: 650px) { .stats { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main>
    <header><div><h1>YOLO26 即時辨識</h1><p>Raspberry Pi 5 · NCNN</p></div><span id="state" class="badge">連線中</span></header>
    <div class="frame"><img src="/stream.mjpg" alt="YOLO26 即時辨識畫面"></div>
    <div class="stats">
      <div class="stat"><small>串流速度</small><strong id="fps">-- FPS</strong></div>
      <div class="stat"><small>偵測數量</small><strong id="count">--</strong></div>
      <div class="stat"><small>辨識內容</small><strong id="labels">等待影像</strong></div>
    </div>
  </main>
  <script>
    async function update() {
      try {
        const r = await fetch('/api/status', {cache: 'no-store'});
        const s = await r.json();
        document.querySelector('#state').textContent = s.error ? '錯誤' : '即時';
        document.querySelector('#state').classList.toggle('bad', Boolean(s.error));
        document.querySelector('#fps').textContent = s.fps.toFixed(1) + ' FPS';
        document.querySelector('#count').textContent = s.count;
        document.querySelector('#labels').textContent = s.error || s.labels || '無物件';
      } catch (_) {
        document.querySelector('#state').textContent = '離線';
        document.querySelector('#state').classList.add('bad');
      }
    }
    setInterval(update, 1000); update();
  </script>
</body>
</html>""".encode("utf-8")


class SharedFrame:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.jpeg: bytes | None = None
        self.sequence = 0
        self.status = {"fps": 0.0, "count": 0, "labels": "", "error": None}

    def publish(self, jpeg: bytes, fps: float, labels: list[str]) -> None:
        with self.condition:
            self.jpeg = jpeg
            self.sequence += 1
            counts = Counter(labels)
            label_text = ", ".join(f"{name} x{count}" for name, count in counts.items())
            self.status = {
                "fps": fps,
                "count": len(labels),
                "labels": label_text,
                "error": None,
            }
            self.condition.notify_all()

    def fail(self, message: str) -> None:
        with self.condition:
            self.status = {**self.status, "error": message}
            self.condition.notify_all()


def inference_loop(args: argparse.Namespace, shared: SharedFrame, stop: threading.Event) -> None:
    camera = None
    try:
        import cv2
        from libcamera import Transform
        from picamera2 import Picamera2
        from ultralytics import YOLO

        logging.info("Loading model: %s", args.model)
        model = YOLO(args.model)
        camera = Picamera2(args.camera)
        config = camera.create_video_configuration(
            main={"size": (args.width, args.height), "format": "RGB888"},
            buffer_count=4,
            transform=Transform(hflip=args.rotate_180, vflip=args.rotate_180),
        )
        camera.configure(config)
        camera.start()
        logging.info("Camera %d started at %dx%d", args.camera, args.width, args.height)

        smoothed_fps = 0.0
        previous = time.perf_counter()
        while not stop.is_set():
            frame = camera.capture_array()
            result = model.predict(
                frame,
                imgsz=args.imgsz,
                conf=args.conf,
                max_det=args.max_det,
                verbose=False,
            )[0]

            annotated = result.plot()
            now = time.perf_counter()
            instant_fps = 1.0 / max(now - previous, 1e-6)
            previous = now
            smoothed_fps = instant_fps if smoothed_fps == 0 else 0.85 * smoothed_fps + 0.15 * instant_fps

            labels = []
            if result.boxes is not None:
                labels = [model.names[int(box.cls[0])] for box in result.boxes]

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
                ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality]
            )
            if ok:
                shared.publish(encoded.tobytes(), smoothed_fps, labels)
    except Exception as exc:
        logging.exception("Inference stream stopped")
        shared.fail(str(exc))
    finally:
        if camera is not None:
            try:
                camera.stop()
                camera.close()
            except Exception:
                logging.exception("Unable to close camera cleanly")


def make_handler(shared: SharedFrame):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE)
            elif path == "/api/status":
                with shared.condition:
                    payload = json.dumps(shared.status, ensure_ascii=False).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", payload)
            elif path == "/stream.mjpg":
                self._stream()
            elif path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            else:
                self._send(404, "text/plain; charset=utf-8", "Not found".encode())

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            sequence = -1
            try:
                while True:
                    with shared.condition:
                        shared.condition.wait_for(
                            lambda: shared.sequence != sequence or shared.status["error"], timeout=5
                        )
                        if shared.status["error"] and shared.jpeg is None:
                            return
                        jpeg, sequence = shared.jpeg, shared.sequence
                    if jpeg is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                    self.wfile.write(jpeg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, fmt: str, *values: object) -> None:
            logging.info("%s - %s", self.client_address[0], fmt % values)

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YOLO26 NCNN browser stream for Raspberry Pi 5")
    parser.add_argument("--model", default="yolo26n_ncnn_model")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--max-det", type=int, default=20)
    parser.add_argument("--jpeg-quality", type=int, default=75)
    parser.add_argument(
        "--no-rotate-180",
        dest="rotate_180",
        action="store_false",
        help="Disable the default 180-degree camera rotation",
    )
    parser.set_defaults(rotate_180=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    shared = SharedFrame()
    stop = threading.Event()
    server = Server((args.host, args.port), make_handler(shared))
    web_worker = threading.Thread(
        target=server.serve_forever, daemon=True, name="web-server"
    )
    web_worker.start()
    logging.info("Open http://<Raspberry-Pi-IP>:%d on Windows", args.port)
    try:
        # Keep the complete Picamera2/NCNN lifecycle on the process main
        # thread.  Both rely on native ARM libraries and some combinations
        # are unstable when initialized and executed from a worker thread.
        inference_loop(args, shared, stop)
        while shared.status["error"] and not stop.wait(1):
            pass
    except KeyboardInterrupt:
        logging.info("Stopping")
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        web_worker.join(timeout=5)


if __name__ == "__main__":
    main()
