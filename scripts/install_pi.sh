#!/usr/bin/env bash
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then echo "請使用 sudo 執行此腳本" >&2; exit 1; fi
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# sudo keeps the invoking account in SUDO_USER; hostname is unrelated.
if [[ $# -gt 1 ]]; then echo "用法：sudo bash scripts/install.sh [執行帳號]" >&2; exit 1; fi
SERVICE_USER="${1:-${SUDO_USER:-}}"
if [[ -z "$SERVICE_USER" || "$SERVICE_USER" == root || ! "$SERVICE_USER" =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*\$?$ ]]; then
  echo "請由一般帳號使用 sudo 執行，或指定：sudo bash scripts/install.sh <既有非 root 帳號>" >&2
  exit 1
fi
ACCOUNT="$(getent passwd "$SERVICE_USER")" || { echo "找不到帳號：$SERVICE_USER" >&2; exit 1; }
IFS=: read -r _ _ SERVICE_UID _ _ SERVICE_HOME _ <<< "$ACCOUNT"
[[ "$SERVICE_UID" != 0 && "$SERVICE_HOME" == /* && "$SERVICE_HOME" != / ]] || { echo "帳號必須為非 root 且具有有效家目錄" >&2; exit 1; }
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
[[ "$SERVICE_GROUP" =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*\$?$ ]] || { echo "不支援的群組名稱" >&2; exit 1; }
RECORDINGS_DIR="$SERVICE_HOME/Videos/autocar"
echo "安裝帳號：$SERVICE_USER；主要群組：$SERVICE_GROUP；預設錄影：$RECORDINGS_DIR"
apt-get update
apt-get install -y python3-gpiozero python3-picamera2 python3-smbus python3-opencv python3-numpy python3-venv i2c-tools
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" /opt/autocar /opt/autocar/models "$RECORDINGS_DIR"
cp -a "$SOURCE_DIR/autocar" "$SOURCE_DIR/web" /opt/autocar/
DEVICE_GROUPS=""
for group in gpio i2c video render; do
  if getent group "$group" >/dev/null; then DEVICE_GROUPS+=" $group"; fi
done
sed -e "s/@AUTOCAR_USER@/$SERVICE_USER/g" \
    -e "s/@AUTOCAR_GROUP@/$SERVICE_GROUP/g" \
    -e "s/@AUTOCAR_DEVICE_GROUPS@/${DEVICE_GROUPS# }/g" \
    "$SOURCE_DIR/deploy/autocar.service" > /etc/systemd/system/autocar.service
chmod 0644 /etc/systemd/system/autocar.service
if [[ ! -f /etc/autocar.env ]]; then install -m 0644 "$SOURCE_DIR/deploy/autocar.env" /etc/autocar.env; fi
if grep -q '^AUTOCAR_RECORDINGS=' /etc/autocar.env; then
  echo "保留既有錄影路徑：$(grep '^AUTOCAR_RECORDINGS=' /etc/autocar.env)"
  echo "若更換服務帳號，請確認該目錄可寫入，或移除此設定以使用新帳號家目錄。"
fi
chown -R "$SERVICE_USER:$SERVICE_GROUP" /opt/autocar "$RECORDINGS_DIR"
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
systemctl enable autocar
systemctl restart autocar
systemctl is-active --quiet autocar
echo "AutoCAR 已啟動；Pi IP：$(hostname -I)"
echo "瀏覽器開啟 http://<Pi-IP>:<AUTOCAR_PORT>（預設 8000）；連接埠設定："
grep -E '^AUTOCAR_PORT=' /etc/autocar.env || true
echo "目前後端設定：$(grep -E '^AUTOCAR_(GPIO|GIMBAL)=' /etc/autocar.env | tr '\n' ' ')"
