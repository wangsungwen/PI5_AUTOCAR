#!/usr/bin/env bash
set -Eeuo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run with sudo bash'; exit 1; }
[[ $(systemctl show autocar -p WorkingDirectory --value) == /opt/autocar ]] || { echo 'Unexpected service directory; no changes made'; exit 1; }
[[ -x /opt/autocar-venv/bin/python ]] || { echo 'Missing Python runtime'; exit 1; }
work=$(mktemp -d /tmp/autocar-update.XXXXXX)
backup=/opt/autocar-backup-$(date +%Y%m%d-%H%M%S)
files=(autocar/config.py autocar/motor.py autocar/autopilot.py autocar/server.py web/app.js web/index.html web/style.css)
curl --connect-timeout 10 --max-time 60 -fsS http://192.168.0.134:8765/update.tar.gz -o "$work/update.tar.gz"
curl --connect-timeout 10 --max-time 10 -fsS http://192.168.0.134:8765/update.sha256 -o "$work/update.sha256"
cd "$work"
sha256sum --check update.sha256
mkdir stage
tar -xzf update.tar.gz -C stage
cd stage
AUTOCAR_GPIO=mock AUTOCAR_GIMBAL=mock /opt/autocar-venv/bin/python -m unittest discover -s tests -v
/opt/autocar-venv/bin/python -m compileall -q autocar
for file in "${files[@]}"; do [[ -f /opt/autocar/$file && ! -L /opt/autocar/$file ]]; done
mkdir -p "$backup/autocar" "$backup/web"
for file in "${files[@]}"; do cp -a "/opt/autocar/$file" "$backup/$file"; done
restore() {
    trap - ERR
    echo "Update failed; restoring backup: $backup"
    systemctl stop autocar || true
    for file in "${files[@]}"; do cp -a "$backup/$file" "/opt/autocar/$file"; done
    systemctl start autocar || true
    journalctl -u autocar -n 30 --no-pager
    exit 1
}
trap restore ERR
systemctl stop autocar
for file in "${files[@]}"; do cat "$work/stage/$file" > "/opt/autocar/$file"; done
systemctl start autocar
port=$(sed -n 's/^AUTOCAR_PORT=//p' /etc/autocar.env | tail -n 1)
port=${port:-8000}
ready=0
for attempt in $(seq 1 45); do
    if curl --max-time 2 -fsS "http://127.0.0.1:$port/api/status" -o "$work/status.json"; then ready=1; break; fi
    sleep 2
done
[[ $ready == 1 ]]
/opt/autocar-venv/bin/python - "$work/status.json" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))['vehicle']
assert not s['enabled'], s
assert s['speed_percent']==0 and s['steering_degrees']==0, s
assert set(s['wheel_pwm'])==set('ABCD'), s
print('Updated motor API verified; vehicle remains disabled:',s)
PY
systemctl is-active --quiet autocar
trap - ERR
echo "UPDATE_OK Backup: $backup"
echo "Open http://192.168.0.160:$port and refresh the page."
