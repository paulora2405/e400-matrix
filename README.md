# darkFlash EXPLORE E400 / E400 Plus — Linux matrix display

Simple Linux tool that drives the **USB HID matrix panel** on the darkFlash
EXPLORE E400 and E400 Plus air coolers. The vendor only ships a Windows app;
this reimplements the HID protocol and streams CPU/GPU stats from Linux.

## Features

- Detect the cooler (`0513:2007` HID)
- Push one frame or run a background daemon; host metrics are cached independently of frame interval (one second by default)
- Pick which metrics the panel rotates (CPU/GPU temp & usage)
- °C / °F
- Tiny local web UI
- Mock mode for dry-runs without hardware

`interval_ms` controls how often the display receives a frame. Set
`metrics_cache_ms` in the YAML configuration to choose how long CPU/GPU metric
samples are reused (default: `1000`).

ARGB fan lighting is unchanged — that still goes through your motherboard’s
5V ARGB header.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# dry-run without the cooler
python -m e400plus encode --demo
python -m e400plus web --mock --port 43127
```

With the cooler connected:

```bash
# optional: install udev rule so you don't need root
sudo cp udev/99-e400plus.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger

python -m e400plus detect
python -m e400plus sensors
python -m e400plus daemon -v
# or
python -m e400plus web --host 127.0.0.1 --port 43127
```

## CLI

| Command | Purpose |
|---------|---------|
| `detect` | List matching HID devices |
| `sensors` | List hwmon temps + current readings |
| `encode` | Build a 64-byte payload (no device I/O) |
| `push` | Send one stats frame |
| `daemon` | Stream frames (~500 ms default) |
| `config` | Show / write `~/.config/e400plus/config.yaml` |
| `web` | Open the control UI |

## Systemd (optional)

The example service runs the PEP 723 `uv` script at
`scripts/e400plus-daemon.py`; it creates and manages its own environment, so a
project `.venv` is not required. It runs as `paulo` from
`~/.local/share/air-cooler-e400-matrix` and reads
`~/.config/e400plus/config.yaml`; update the username and `uv` path if needed.

```bash
./scripts/install.sh
```

The installer adds the udev rule, creates a default config if needed, renders
the service with the detected `uv` path, then enables and starts it. It prompts
for `sudo`; install `uv` first. Check its state with
`systemctl status e400plus.service`.

## Protocol

See [docs/PROTOCOL.md](docs/PROTOCOL.md) and
[docs/REVERSE-ENGINEERING.md](docs/REVERSE-ENGINEERING.md).

Summary: HID VID:PID `0513:2007`, 64-byte payload headed by `00 01 02`, then
packed metric bytes matching the Windows `SendValueArray` layout.

## Status

Protocol recovered from the official Windows driver package. **Verify against
your hardware** — this environment could not talk to a physical E400 Plus.
If `lsusb` shows a different ID, tell the tool with config/`--path` or patch
the constants in `e400plus/__init__.py`.

## License

MIT
