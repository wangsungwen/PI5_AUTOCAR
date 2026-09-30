import cv2
import time
import threading
from flask import Flask, Response
from ultralytics import YOLO
from picamera2 import Picamera2
from libcamera import Transform

# ============================================================
# Configuration
# ============================================================

MODEL_PATH = "yolo26n_ncnn_model"

WIDTH = 640
HEIGHT = 480

IMGSZ = 640
CONF = 0.35

app = Flask(__name__)

# ============================================================
# YOLO26 NCNN
# ============================================================

print("[INFO] Loading YOLO26 NCNN...")

model = YOLO(MODEL_PATH)

print("[INFO] YOLO26 NCNN loaded.")

# ============================================================
# Picamera2 / OV5647
# ============================================================

print("[INFO] Starting OV5647...")

picam2 = Picamera2()

config = picam2.create_video_configuration(

    main={
        "size": (WIDTH, HEIGHT),
        "format": "RGB888"
    },

    # Camera physically installed upside-down
    transform=Transform(
        hflip=True,
        vflip=True
    ),

    buffer_count=4
)

picam2.configure(config)
picam2.start()

time.sleep(2)

print("[INFO] OV5647 started.")

# ============================================================
# Shared JPEG
# ============================================================

latest_jpeg = None
frame_lock = threading.Lock()


# ============================================================
# Camera + YOLO worker
# ============================================================

def detection_loop():

    global latest_jpeg

    print("[INFO] Detection worker started.")

    previous = time.perf_counter()

    while True:

        # --------------------------------------------
        # Picamera2 frame
        # --------------------------------------------

        frame = picam2.capture_array()

        # Picamera2 RGB -> OpenCV BGR
        frame = cv2.cvtColor(
            frame,
            cv2.COLOR_RGB2BGR
        )

        # --------------------------------------------
        # YOLO26 NCNN
        # --------------------------------------------

        start = time.perf_counter()

        result = model.predict(
            frame,
            imgsz=IMGSZ,
            conf=CONF,
            verbose=False
        )[0]

        inference_ms = (
            time.perf_counter() - start
        ) * 1000

        display = result.plot()

        # --------------------------------------------
        # FPS
        # --------------------------------------------

        now = time.perf_counter()

        dt = now - previous

        previous = now

        fps = 1.0 / dt if dt > 0 else 0

        # --------------------------------------------
        # Overlay
        # --------------------------------------------

        cv2.putText(
            display,
            "YOLO26 NCNN",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2
        )

        cv2.putText(
            display,
            f"FPS: {fps:.1f}",
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2
        )

        cv2.putText(
            display,
            f"Inference: {inference_ms:.1f} ms",
            (10, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2
        )

        cv2.putText(
            display,
            f"Objects: {len(result.boxes)}",
            (10, 120),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 0),
            2
        )

        # --------------------------------------------
        # JPEG
        # --------------------------------------------

        ok, jpeg = cv2.imencode(
            ".jpg",
            display,
            [cv2.IMWRITE_JPEG_QUALITY, 80]
        )

        if ok:

            with frame_lock:

                latest_jpeg = jpeg.tobytes()


# ============================================================
# MJPEG generator
# ============================================================

def generate():

    while True:

        with frame_lock:

            frame = latest_jpeg

        if frame is None:

            time.sleep(0.02)

            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame +
            b"\r\n"
        )


# ============================================================
# Web
# ============================================================

@app.route("/")
def index():

    return """
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<title>Pi 5 YOLO26</title>

<style>

body {
    margin: 0;
    background: #101010;
    color: white;
    font-family: Arial;
    text-align: center;
}

header {
    padding: 20px;
    background: #202020;
}

h1 {
    margin: 0;
}

.status {
    color: #4cff70;
    margin-top: 10px;
}

img {
    margin-top: 25px;
    width: 640px;
    max-width: 95%;
    border: 3px solid #555;
    border-radius: 10px;
}

.info {
    margin: 20px;
    color: #aaa;
}

</style>

</head>

<body>

<header>

<h1>
Raspberry Pi 5 × YOLO26
</h1>

<div class="status">
● OV5647 + YOLO26 NCNN
</div>

</header>

<img src="/video_feed">

<div class="info">

OV5647 → Picamera2 → YOLO26 NCNN → Flask → Browser

</div>

</body>

</html>
"""


@app.route("/video_feed")
def video_feed():

    return Response(

        generate(),

        mimetype=
        "multipart/x-mixed-replace; boundary=frame"
    )


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    worker = threading.Thread(
        target=detection_loop,
        daemon=True
    )

    worker.start()

    print()
    print("========================================")
    print(" Raspberry Pi 5 YOLO26")
    print(" OV5647 + NCNN + Flask")
    print("========================================")
    print(" http://192.168.1.110:5000")
    print("========================================")

    try:

        app.run(
            host="0.0.0.0",
            port=5000,
            threaded=True,
            debug=False,
            use_reloader=False
        )

    finally:

        picam2.stop()
