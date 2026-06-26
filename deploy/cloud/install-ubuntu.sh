#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_DIR="${APP_DIR:-/opt/atri-qq-bot}"

echo "[atri] Installing Atri QQ bot to ${APP_DIR}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run with sudo: sudo bash deploy/cloud/install-ubuntu.sh"
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip rsync

mkdir -p "${APP_DIR}"
rsync -a --delete \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude ".pytest_cache" \
  --exclude "*.log" \
  "${PROJECT_DIR}/" "${APP_DIR}/"

cd "${APP_DIR}"
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev]"

if [[ ! -f ".env" ]]; then
  cp deploy/cloud/cloud.env.example .env
  echo "[atri] Created ${APP_DIR}/.env. Edit OWNER_QQ and model settings before first use."
fi

cp deploy/cloud/atri-qq-bot.service /etc/systemd/system/atri-qq-bot.service
systemctl daemon-reload
systemctl enable atri-qq-bot

echo "[atri] Installed. Useful commands:"
echo "  sudo systemctl start atri-qq-bot"
echo "  sudo systemctl status atri-qq-bot"
echo "  sudo journalctl -u atri-qq-bot -f"
echo
echo "[atri] NapCat must connect to ws://127.0.0.1:8765/onebot on the same server."
