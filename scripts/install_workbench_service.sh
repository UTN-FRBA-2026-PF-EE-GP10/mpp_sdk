#!/usr/bin/env bash
# Install (or remove) a systemd service that starts the workbench server at
# boot, so the bench can be used from a phone with no PC.
#
#   scripts/install_workbench_service.sh            # install, enable, start
#   scripts/install_workbench_service.sh --remove   # stop, disable, delete
#
# Run it on the host SBC as the user that owns the checkout. It asks for
# sudo once. The unit is written from this checkout's location, so no path
# or user name is stored in the repo.
set -euo pipefail

name=mpp-workbench
unit=/etc/systemd/system/$name.service

if [[ ${1:-} == --remove ]]; then
  sudo systemctl disable --now "$name.service" 2>/dev/null || true
  sudo rm -f "$unit"
  sudo systemctl daemon-reload
  echo "removed $name.service"
  exit 0
fi

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
user=$(id -un)
uv=$(command -v uv || true)
[[ -n $uv ]] || uv=$HOME/.local/bin/uv
[[ -x $uv ]] || { echo "uv not found - install it first" >&2; exit 1; }

sudo tee "$unit" > /dev/null <<UNIT
[Unit]
Description=mpp-sdk workbench server (curve tracer and MPPT runs)
Wants=network-online.target
After=network-online.target
# Keep retrying forever: the SPI device or the network can be late at boot.
StartLimitIntervalSec=0

[Service]
User=$user
WorkingDirectory=$repo
ExecStart=$uv run mpp-sdk curve-tracer-web
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5
# SIGTERM to uv only; uv passes it on to the server. The server then ends
# any live run through its zero-duty path before it exits.
KillMode=mixed
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now "$name.service"
echo "installed $name.service - open http://<host-ip>:8000/ (first start can take a minute)"
