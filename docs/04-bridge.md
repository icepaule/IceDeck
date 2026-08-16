# 4 — Die Bridge installieren

[← Kapitel 3](03-raspberry-pi.md) · [Übersicht](../README.md)

Die Bridge ist der Python-Dienst auf dem Pi. Sie tut genau zwei Dinge:

1. Tastendruck erkannt → Nachricht auf `streamdeck/button/<n>` veröffentlichen
2. Zustand auf `streamdeck/state` empfangen → Tastenbilder neu zeichnen

Mehr nicht. Kein API-Token, keine Projektkenntnis, kein Gedächtnis.

## Dateien auf den Pi bringen

```bash
rsync -a src/ <benutzer>@<pi-ip>:~/icedeck/
```

`rsync -a` überträgt rekursiv und erhält Rechte, Zeitstempel und Symlinks.
Alternativ `git clone` direkt auf dem Pi.

## Installation

```bash
ssh <benutzer>@<pi-ip> 'bash ~/icedeck/install.sh'
```

> Der Pfad muss vollständig sein. Ein `ssh host 'bash install.sh'` schlägt fehl,
> weil das Arbeitsverzeichnis einer SSH-Sitzung das Heimatverzeichnis ist, nicht
> das Projektverzeichnis.

Was das Skript im Einzelnen macht:

### Systempakete

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev libhidapi-libusb0 \
                        libjpeg-dev zlib1g-dev fonts-dejavu-core
```

| Paket | Wofür |
|---|---|
| `python3-venv` | virtuelle Umgebungen |
| `python3-dev` | Header, falls ein Paket kompiliert werden muss |
| `libhidapi-libusb0` | **die zentrale Bibliothek** — spricht mit HID-Geräten über libusb |
| `libjpeg-dev`, `zlib1g-dev` | Bildformate für Pillow |
| `fonts-dejavu-core` | die Schrift für die Tastenbeschriftung |

`libhidapi-libusb0` ist der Kern. `python-elgato-streamdeck` ist nur eine
Hülle darum; ohne diese Bibliothek findet es kein Gerät.

Wichtig ist die **libusb**-Variante, nicht `libhidapi-hidraw0`. Die
libusb-Variante beansprucht das Gerät exklusiv und ist für das Stream Deck die
zuverlässigere Wahl.

### Virtuelle Umgebung

```bash
sudo mkdir -p /opt/icedeck /etc/icedeck/icons
sudo cp streamdeck_bridge.py /opt/icedeck/
sudo python3 -m venv /opt/icedeck/venv
sudo /opt/icedeck/venv/bin/pip install --upgrade pip
sudo /opt/icedeck/venv/bin/pip install streamdeck pillow paho-mqtt
```

Ein venv statt systemweiter Pakete, damit Aktualisierungen des Systems die
Anwendung nicht stören — und umgekehrt. Unter Debian 12 und neuer verweigern
sich systemweite `pip`-Installationen ohnehin (`externally-managed-environment`).

Auf ARM64 kommen die Pakete als fertige Rad-Dateien von
[piwheels](https://www.piwheels.org/); nichts muss kompiliert werden.

| Paket | Rolle |
|---|---|
| `streamdeck` | Gerät finden, Tastenbilder setzen, Tastendrücke lesen |
| `pillow` | die Tastenbilder zeichnen |
| `paho-mqtt` | MQTT-Client |

### Konfiguration

```bash
sudo cp config.example.json /etc/icedeck/config.json
sudo chmod 600 /etc/icedeck/config.json
sudo chown <benutzer> /etc/icedeck/config.json
```

`chmod 600` ist nötig, weil die Datei das MQTT-Passwort enthält. Nur der
Eigentümer darf lesen und schreiben.

Danach anpassen:

```jsonc
{
  "brightness": 60,
  "mqtt": {
    "host": "mqtt.example.lan",
    "port": 1883,
    "topic_prefix": "streamdeck",
    "username": "…",
    "password": "…"
  },
  "keys": {
    "0": { "label": "Projekt A", "color": "#0b83d9", "color_active": "#1f7a3d" },
    "4": { "label": "Heute",     "color": "#16213e", "type": "today" }
  }
}
```

| Feld | Bedeutung |
|---|---|
| `brightness` | Helligkeit 0–100 |
| `topic_prefix` | Präfix beider Topics; muss zum Node-RED-Flow passen |
| `label` | Beschriftung auf der Taste |
| `color` | Hintergrund im Ruhezustand |
| `color_active` | Hintergrund, während der Timer läuft |
| `type: "today"` | macht die Taste zur **Tagesanzeige** — sie löst nichts aus |
| `icon` | optionaler Pfad zu einem PNG statt einer Farbfläche |

> **Die Schlüssel sind 0-basiert.** Die Taste oben links ist `0`, nicht `1`. Auf
> einem 15-Tasten-Deck läuft die Zählung zeilenweise von `0` bis `14`.

### udev-Regel

```bash
sudo cp 99-streamdeck.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Inhalt der Regel:

```
SUBSYSTEM=="usb",    ATTRS{idVendor}=="0fd9", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0fd9", MODE="0660", GROUP="plugdev", TAG+="uaccess"
```

Ohne diese Regel gehören die Gerätedateien `root:root` mit Rechten `0600` — der
Dienst käme nur als root heran, was für ein Programm mit Netzwerkzugriff
unnötig ist.

| Bestandteil | Bedeutung |
|---|---|
| `ATTRS{idVendor}=="0fd9"` | trifft alle Elgato-Geräte |
| `MODE="0660"` | Eigentümer und Gruppe dürfen lesen und schreiben |
| `GROUP="plugdev"` | Gruppe für Wechseldatenträger und angesteckte Geräte |
| `TAG+="uaccess"` | zusätzlich Zugriff für den lokal angemeldeten Benutzer |

Beide Zeilen werden gebraucht: Die Bibliothek greift über `libusb` zu (Subsystem
`usb`), manche Pfade laufen über `hidraw`.

```bash
sudo usermod -aG plugdev <benutzer>
```

Fügt den Benutzer der Gruppe hinzu. **Das wirkt nicht in laufenden Sitzungen** —
Gruppen werden bei der Anmeldung ausgewertet. Für den Dienst ist das egal, weil
die systemd-Unit `SupplementaryGroups=plugdev` setzt.

Kontrolle:

```bash
ls -l /dev/hidraw0
```

Erwartet: `crw-rw----+ 1 root plugdev …`. Das `+` am Ende zeigt an, dass eine
zusätzliche ACL gesetzt ist — das ist `uaccess`.

### systemd

```bash
sudo cp icedeck.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable icedeck.service
sudo systemctl start icedeck
```

`daemon-reload` ist nötig, damit systemd die neue Unit einliest. `enable` sorgt
für den Start beim Booten, `start` startet sofort.

Die wichtigsten Zeilen der Unit:

```ini
[Unit]
After=network-online.target
StartLimitBurst=0

[Service]
Restart=always
RestartSec=5
SupplementaryGroups=plugdev
Environment=SDB_CONFIG=/etc/icedeck/config.json
```

| Zeile | Warum |
|---|---|
| `After=network-online.target` | erst starten, wenn das WLAN steht |
| `StartLimitBurst=0` | Neustartbegrenzung **aus** — sonst gibt systemd nach fünf Versuchen auf |
| `Restart=always` | auch nach sauberem Beenden neu starten |
| `RestartSec=5` | fünf Sekunden Pause zwischen den Versuchen |
| `SupplementaryGroups=plugdev` | Gerätezugriff ohne root |

> `StartLimitBurst` gehört in modernen systemd-Versionen in den Abschnitt
> **`[Unit]`**, nicht `[Service]`. An der falschen Stelle wird die Einstellung
> stillschweigend ignoriert.
>
> Ohne sie hat der Dienst ein unangenehmes Verhalten: Ist das Deck beim
> Systemstart noch nicht bereit, scheitern fünf Versuche in kurzer Folge, und
> systemd gibt endgültig auf. Der Dienst wäre dauerhaft tot, obwohl das Deck
> Sekunden später verfügbar wäre.

## Prüfen

```bash
sudo systemctl status icedeck
sudo journalctl -u icedeck -f
```

Erwartete Ausgabe:

```
Stream Deck Original mit 15 Tasten geoeffnet
MQTT verbunden (rc=Success), abonniere streamdeck/state
```

Bleibt die erste Zeile aus, findet die Bibliothek das Deck nicht — dann
[Kapitel 7](07-fehlersuche.md).

## Ohne Dienst testen

```bash
sudo systemctl stop icedeck
SDB_CONFIG=/etc/icedeck/config.json /opt/icedeck/venv/bin/python /opt/icedeck/streamdeck_bridge.py
```

Läuft im Vordergrund mit sichtbarer Ausgabe. Abbruch mit `Strg+C`. Nützlich beim
Anpassen der Tastenbilder — allerdings braucht die Sitzung dann selbst
`plugdev`-Rechte, was nach `usermod` eine Neuanmeldung erfordert.

## Wie die Bridge rechnet

Zwei Entwurfsentscheidungen, die nicht offensichtlich sind:

**Die Tagessumme hängt an `started_at`, nicht an `active_key`.** Ein laufender
Eintrag ohne Projekt — oder mit einem Projekt, das auf keiner Taste liegt — hat
`active_key: null`, weil keine Taste hervorzuheben ist. Er läuft aber trotzdem
und gehört in die Tagessumme. Würde man `active_key` abfragen, fiele solche Zeit
still aus der Anzeige.

**Node-RED liefert nur die abgeschlossenen Zeiten**, die laufende addiert die
Bridge selbst. Dadurch tickt die Anzeige weiter, ohne dass jede Sekunde eine
MQTT-Nachricht nötig wäre. Ein Timer zeichnet alle zehn Sekunden neu, solange
etwas läuft.

---

[Weiter: 5 — Node-RED einrichten →](05-nodered.md)
