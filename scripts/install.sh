#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! UV_BIN="$(command -v uv)"; then
  echo "uv is required to run the system service. Install it, then rerun this script." >&2
  exit 1
fi

echo "Installing udev rule (sudo)…"
sudo cp udev/99-e400plus.rules /etc/udev/rules.d/
sudo udevadm control --reload || true
sudo udevadm trigger || true

mkdir -p "$HOME/.config/e400plus"
if [[ ! -f "$HOME/.config/e400plus/config.yaml" ]]; then
  cat > "$HOME/.config/e400plus/config.yaml" <<'YAML'
celsius: true
interval_ms: 500
metrics_cache_ms: 1000
show_cpu_temp: true
show_cpu_usage: true
show_gpu_temp: true
show_gpu_usage: false
mock: false
YAML
fi

echo "Installing and starting systemd service (sudo)…"
SERVICE_RENDERED="$(mktemp)"
trap 'rm -f "$SERVICE_RENDERED"' EXIT
awk -v uv_bin="$UV_BIN" '
  /^ExecStart=/ {
    print "ExecStart=" uv_bin " run --script scripts/e400plus-daemon.py"
    next
  }
  { print }
' systemd/e400plus.service > "$SERVICE_RENDERED"
sudo install -m 0644 "$SERVICE_RENDERED" /etc/systemd/system/e400plus.service
sudo systemctl daemon-reload
sudo systemctl enable --now e400plus.service

echo
echo "Done. Try:"
echo "  systemctl status e400plus.service"
echo "  journalctl -u e400plus.service -f"
