#!/bin/bash
# Installation auf dem Raspberry Pi. Ausfuehren als der User, unter dem der
# Dienst spaeter laufen soll (in icedeck.service als User eintragen), mit sudo-Rechten.
set -euo pipefail

APP=/opt/icedeck
CFG=/etc/icedeck
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "==> Systempakete"
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev libhidapi-libusb0 libjpeg-dev zlib1g-dev fonts-dejavu-core

echo "==> Anwendung nach $APP"
sudo mkdir -p "$APP" "$CFG/icons"
sudo cp "$SRC/streamdeck_bridge.py" "$APP/"

echo "==> Virtualenv"
sudo python3 -m venv "$APP/venv"
sudo "$APP/venv/bin/pip" install --upgrade pip
sudo "$APP/venv/bin/pip" install streamdeck pillow paho-mqtt

echo "==> Konfiguration"
if [ ! -f "$CFG/config.json" ]; then
  sudo cp "$SRC/config.example.json" "$CFG/config.json"
  sudo chmod 600 "$CFG/config.json"
  sudo chown "$USER" "$CFG/config.json"
  echo "    $CFG/config.json angelegt - MQTT-Zugangsdaten und Tasten eintragen!"
else
  echo "    $CFG/config.json existiert bereits, bleibt unveraendert"
fi

echo "==> udev-Regel"
sudo cp "$SRC/99-streamdeck.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "==> Benutzer in Gruppe plugdev"
sudo usermod -aG plugdev "$USER"

echo "==> systemd"
sudo cp "$SRC/icedeck.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable icedeck.service

cat <<EOF

Fertig. Naechste Schritte:
  1. $CFG/config.json anpassen (MQTT-Host, Zugangsdaten, Tastenbelegung)
  2. Stream Deck einmal ab- und wieder anstecken (udev-Regel)
  3. sudo systemctl start icedeck
  4. journalctl -u icedeck -f

Test ohne Dienst:
  SDB_CONFIG=$CFG/config.json $APP/venv/bin/python $APP/streamdeck_bridge.py
EOF
