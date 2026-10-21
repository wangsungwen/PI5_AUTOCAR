"""Loopback SSH proxy and coordinated Pi/UE4 recording."""
import json
import threading
import time
import urllib.request
from pathlib import Path


class SimCamera:
    def __init__(self, camera, token_path, output_dir):
        self.camera = camera
        self.token_path = Path(token_path)
        self.output_dir = Path(output_dir)
        self.lock = threading.RLock()
        self.active = False
        self.session = None

    def request(self, path, post=False):
        try:
            token = self.token_path.read_text().strip()
            req = urllib.request.Request("http://127.0.0.1:8089"+path,
                data=b"{}" if post else None, headers={"Authorization": "Bearer "+token})
            with urllib.request.urlopen(req, timeout=2) as response:
                data = response.read()
            return data if path.startswith("/frame") else json.loads(data)
        except Exception as exc:
            raise RuntimeError("UE4 影像橋接未連線，請啟動 Windows start_cockpit.cmd") from exc

    def status(self):
        try:
            remote = self.request("/status")
        except RuntimeError as exc:
            remote = {"connected": False, "recording": False, "error": str(exc)}
        with self.lock:
            return {"remote": remote, "dual_recording": self.active,
                    "session": self.session, "pi": self.camera.status()}

    def start(self, source="fpv"):
        if source not in ("fpv", "hood", "road"):
            raise ValueError("不支援的 UE4 視角")
        with self.lock:
            if self.active:
                return self.session
            if self.camera.status()["recording"]:
                raise RuntimeError("請先停止現有 Pi 錄影，再啟動同步側錄")
            remote = self.request("/status")
            if not remote["connected"] or remote["recording"]:
                raise RuntimeError("UE4 未就緒或已有錄影，請先停止錄影")
            started = time.time()
            try:
                pi = self.camera.start()
                remote = self.request("/record/start/"+source, True)
            except Exception:
                self.camera.stop()
                # A timed-out POST may still have started the remote recorder.
                try:
                    self.request("/record/stop", True)
                except RuntimeError:
                    pass
                raise
            self.session = {"requested_at": started, "pi_file": pi["file"],
                            "ue4_file": remote["file"], "ue4_started": remote["started"],
                            "ue4_camera": source}
            self.active = True
            return self.session

    def stop(self):
        with self.lock:
            errors = []
            try:
                self.camera.stop()
            except Exception as exc:
                errors.append(str(exc))
            try:
                self.request("/record/stop", True)
            except RuntimeError as exc:
                errors.append(str(exc))
            if errors:
                # Keep stop available for retry; do not claim both have stopped.
                raise RuntimeError("；".join(errors))
            self.active = False
            if self.session:
                self.session["stopped_at"] = time.time()
                self.output_dir.mkdir(parents=True, exist_ok=True)
                path = self.output_dir / f"dual-{int(self.session['requested_at']*1000)}.json"
                path.write_text(json.dumps(self.session, ensure_ascii=False, indent=2))
            return self.session
