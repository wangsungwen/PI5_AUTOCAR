#!/usr/bin/env bash
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then echo "請使用 sudo 執行此腳本" >&2; exit 1; fi
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
apt-get update
apt-get install -y python3-gpiozero python3-picamera2 python3-smbus python3-opencv python3-numpy python3-venv i2c-tools
install -d -o rpi5 -g rpi5 /opt/autocar /opt/autocar/models /home/rpi5/Videos/autocar
cp -a "$SOURCE_DIR/autocar" "$SOURCE_DIR/web" /opt/autocar/
install -m 0644 "$SOURCE_DIR/deploy/autocar.service" /etc/systemd/system/autocar.service
if [[ ! -f /etc/autocar.env ]]; then install -m 0644 "$SOURCE_DIR/deploy/autocar.env" /etc/autocar.env; fi
chown -R rpi5:rpi5 /opt/autocar /home/rpi5/Videos/autocar
if [[ ! -x /opt/autocar-venv/bin/python ]]; then
  python3 -m venv --system-site-packages /opt/autocar-venv
fi
AVAILABLE_KB="$(df -Pk / | awk 'NR == 2 {print $4}')"
if [[ "$AVAILABLE_KB" -lt 2097152 ]]; then
  echo "警告：根目錄可用空間低於 2 GiB，安裝 AI runtime 可能失敗" >&2
  df -h /
fi
/opt/autocar-venv/bin/pip install --upgrade pip
/opt/autocar-venv/bin/pip install --upgrade --force-reinstall --no-cache-dir numpy scipy
/opt/autocar-venv/bin/pip install --upgrade --force-reinstall --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
# CPU PyTorch 已安裝後，不可對 Ultralytics 使用 --force-reinstall，否則
# pip 可能從 PyPI 重新解析成含 CUDA 的 torch，耗盡 Pi 的磁碟空間。
/opt/autocar-venv/bin/pip install --upgrade --upgrade-strategy only-if-needed --no-cache-dir "ultralytics>=8.3" ncnn

verify_ai_runtime() {
  /opt/autocar-venv/bin/python - <<'PY'
import cv2
import numpy
import torch
import torchvision
import ultralytics
import ncnn

if torch.cuda.is_available():
    raise RuntimeError("Pi 5 應使用 CPU PyTorch，但目前 runtime 回報 CUDA 可用")

print(
    "AutoCAR AI runtime ready:",
    f"numpy={numpy.__version__}",
    f"torch={torch.__version__}",
    f"torchvision={torchvision.__version__}",
    f"opencv={cv2.__version__}",
    f"ncnn={getattr(ncnn, '__version__', 'installed')}",
    f"ultralytics={ultralytics.__version__}",
    "cuda=False",
)
PY
}

if ! verify_ai_runtime; then
  echo "AI runtime 載入失敗，重新安裝 NumPy/SciPy 與 CPU PyTorch 後再驗證" >&2
  /opt/autocar-venv/bin/pip install --upgrade --force-reinstall --no-cache-dir numpy scipy
  /opt/autocar-venv/bin/pip install --upgrade --force-reinstall --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
  verify_ai_runtime
fi
systemctl daemon-reload
systemctl enable --now autocar
echo "AutoCAR 已啟動：http://$(hostname -I | awk '{print $1}'):8000"
echo "目前後端設定：$(grep -E '^AUTOCAR_(GPIO|GIMBAL)=' /etc/autocar.env | tr '\n' ' ')"
