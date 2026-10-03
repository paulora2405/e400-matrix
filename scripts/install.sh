#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
pip install -e .

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

echo
echo "Done. Try:"
echo "  source .venv/bin/activate"
echo "  python -m e400plus detect"
echo "  python -m e400plus daemon -v"
echo "  python -m e400plus web --port 43127"
