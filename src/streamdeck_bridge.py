#!/usr/bin/env python3
"""
Stream Deck <-> MQTT Bruecke.

Das Deck bleibt bewusst dumm: es meldet nur Tastendruecke per MQTT und rendert
den Zustand, den es per MQTT zurueckbekommt. Die gesamte Solidtime-Logik
(welches Projekt, Start/Stop/Wechsel) liegt in Node-RED - so muss hier nie ein
API-Token liegen und eine Umbelegung erfordert kein Anfassen des Pi.

Topics:
  raus:  streamdeck/button/<key>   {"key": 3, "event": "press"}
  rein:  streamdeck/state          {"active_key": 3,
                                    "started_at": "2026-08-15T09:00:00Z",
                                    "today_base_seconds": 12345}

active_key = null bedeutet: nichts laeuft.
today_base_seconds ist die Summe der heute bereits ABGESCHLOSSENEN Eintraege.
Die Zeit des laufenden Eintrags rechnet das Deck selbst dazu, damit die
Tagesanzeige ohne MQTT-Verkehr weiterlaeuft.
"""

import json
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager

# python-elgato-streamdeck nennt den Bildhelfer PILHelper, der MiraBox-faehige
# Fork python-streamdoeck nennt ihn NativeImageHelper. Die benutzten Funktionen
# heissen in beiden gleich, daher genuegt der Namenswechsel - so laeuft dieselbe
# Datei mit Elgato- und MiraBox-Geraeten.
try:
    from StreamDeck.ImageHelpers import PILHelper
except ImportError:
    from StreamDeck.ImageHelpers import NativeImageHelper as PILHelper

CONFIG_PATH = os.environ.get("SDB_CONFIG", "/etc/streamdeck-solidtime/config.json")

log = logging.getLogger("streamdeck-bridge")

state_lock = threading.Lock()
state = {
    "active_key": None,
    "started_at": None,
    "today_base_seconds": 0,
    "today_by_key": {},
}

_font_cache = {}


def load_config(path):
    with open(path) as fh:
        cfg = json.load(fh)
    # Tasten-Keys aus JSON sind Strings -> zu int normalisieren
    cfg["keys"] = {int(k): v for k, v in cfg.get("keys", {}).items()}
    return cfg


def load_font(size):
    if size not in _font_cache:
        for path in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ):
            if os.path.exists(path):
                _font_cache[size] = ImageFont.truetype(path, size)
                break
        else:
            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        log.warning("Zeitstempel unlesbar: %r", value)
        return None


def running_seconds(started_at):
    ts = parse_ts(started_at)
    if ts is None:
        return 0
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))


def hms(secs, force_hours=False):
    """'1:23' bzw. '2:05:09'; mit force_hours immer 'H:MM'."""
    h, rem = divmod(max(0, int(secs)), 3600)
    m, s = divmod(rem, 60)
    if force_hours:
        return f"{h}:{m:02d}"
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def laeuft_etwas(snapshot):
    """Laeuft ueberhaupt ein Eintrag?

    Bewusst an started_at festgemacht, nicht an active_key: ein Eintrag ohne
    Projekt (oder mit einem Projekt, das auf keiner Taste liegt) laeuft trotzdem
    und gehoert in die Tagessumme. active_key bleibt dabei None, weil keine
    Taste hervorzuheben ist.
    """
    return snapshot.get("started_at") is not None


def today_total(snapshot):
    """Heutige Gesamtzeit = abgeschlossene Eintraege + laufender Eintrag."""
    total = snapshot.get("today_base_seconds") or 0
    if laeuft_etwas(snapshot):
        total += running_seconds(snapshot.get("started_at"))
    return total


def key_total(snapshot, key):
    """Heutige Zeit auf DIESEM Projekt, ueber alle Eintraege des Tages.

    Node-RED liefert die abgeschlossenen Zeiten je Taste; laeuft die Taste
    gerade, kommt der laufende Abschnitt dazu. Ohne das zeigte eine Taste nur
    den aktuellen Abschnitt - bei mehrfach unterbrochener Arbeit am selben
    Projekt also viel zu wenig.
    """
    by_key = snapshot.get("today_by_key") or {}
    # JSON-Schluessel sind Strings, intern wird mit int gearbeitet
    total = by_key.get(str(key), by_key.get(key, 0)) or 0
    if snapshot.get("active_key") == key:
        total += running_seconds(snapshot.get("started_at"))
    return total


def render_key(deck, cfg, key, snapshot):
    entry = cfg["keys"].get(key)
    if entry is None:
        return PILHelper.to_native_key_format(deck, PILHelper.create_key_image(deck))

    # Anzeigetaste: heutige Arbeitszeit, kein Toggle
    if entry.get("type") == "today":
        image = PILHelper.create_key_image(deck, background=entry.get("color", "#16213e"))
        draw = ImageDraw.Draw(image)
        w, h = image.size
        laeuft = laeuft_etwas(snapshot)
        draw.text(
            (w / 2, h / 2 - 2),
            hms(today_total(snapshot), force_hours=True),
            font=load_font(20),
            anchor="mm",
            fill="#3ddc84" if laeuft else "#e8eaed",
        )
        draw.text(
            (w / 2, h - 5),
            entry.get("label", "Heute"),
            font=load_font(11),
            anchor="ms",
            fill="#9aa0a6",
        )
        return PILHelper.to_native_key_format(deck, image)

    # Projekttaste
    running = snapshot.get("active_key") == key
    icon = entry.get("icon")
    if icon and os.path.exists(icon):
        with Image.open(icon) as src:
            image = PILHelper.create_scaled_key_image(deck, src, margins=[0, 0, 18, 0])
    else:
        bg = entry.get("color_active", "#1f7a3d") if running else entry.get(
            "color", "#202020"
        )
        image = PILHelper.create_key_image(deck, background=bg)

    draw = ImageDraw.Draw(image)
    w, h = image.size

    # Heutige Zeit auf diesem Projekt - auch wenn der Timer gerade nicht laeuft,
    # damit man sieht, was heute schon drauf gebucht ist.
    heute = key_total(snapshot, key)
    if running:
        draw.rectangle([0, 0, w - 1, h - 1], outline="#3ddc84", width=3)
    if running or heute:
        draw.text(
            (w / 2, h - 4),
            hms(heute, force_hours=True),
            font=load_font(15),
            anchor="ms",
            fill="#3ddc84" if running else "#c8ccd0",
        )
        label_y = h - 20
    else:
        label_y = h - 5

    draw.text(
        (w / 2, label_y),
        entry.get("label", ""),
        font=load_font(12),
        anchor="ms",
        fill="#ffffff",
    )
    return PILHelper.to_native_key_format(deck, image)


def hat_seitenstreifen(deck):
    """MiraBox 293S hat drei zusaetzliche 80x80-Felder am Rand.

    Elgato-Geraete haben nichts dergleichen, und die Elgato-Bibliothek kennt
    die noetigen Funktionen nicht - beides wird hier geprueft, damit dieselbe
    Datei mit beiden Geraetefamilien laeuft.
    """
    return (
        getattr(deck, "SECONDARY_IMAGE_COUNT", 0) > 0
        and hasattr(deck, "set_secondary_image")
        and hasattr(PILHelper, "create_secondary_image")
    )


def render_secondary(deck, cfg, index, snapshot):
    """Feld 0 Uhrzeit, Feld 1 Tagessumme, Feld 2 Statusampel."""
    laeuft = laeuft_etwas(snapshot)
    image = PILHelper.create_secondary_image(deck, background="#14161c")
    draw = ImageDraw.Draw(image)
    w, h = image.size

    if index == 0:
        draw.text((w / 2, h / 2), datetime.now().strftime("%H:%M"),
                  font=load_font(24), anchor="mm", fill="#e8eaed")
    elif index == 1:
        draw.text((w / 2, h / 2 - 10), "HEUTE",
                  font=load_font(12), anchor="mm", fill="#9aa0a6")
        draw.text((w / 2, h / 2 + 12), hms(today_total(snapshot), force_hours=True),
                  font=load_font(22), anchor="mm",
                  fill="#3ddc84" if laeuft else "#e8eaed")
    else:
        r = 11
        draw.ellipse([w / 2 - r, h / 2 - r - 10, w / 2 + r, h / 2 + r - 10],
                     fill="#3ddc84" if laeuft else "#5f6368")
        draw.text((w / 2, h - 12), "laeuft" if laeuft else "gestoppt",
                  font=load_font(12), anchor="ms",
                  fill="#3ddc84" if laeuft else "#9aa0a6")

    return PILHelper.to_native_secondary_image_format(deck, image)


def redraw_secondary(deck, cfg):
    if not hat_seitenstreifen(deck):
        return
    with state_lock:
        snapshot = dict(state)
    with deck:
        for i in range(deck.SECONDARY_IMAGE_COUNT):
            try:
                deck.set_secondary_image(i, render_secondary(deck, cfg, i, snapshot))
            except Exception:
                log.warning("Seitenfeld %s liess sich nicht zeichnen", i, exc_info=True)


def redraw(deck, cfg):
    with state_lock:
        snapshot = dict(state)
    with deck:
        for key in range(deck.key_count()):
            deck.set_key_image(key, render_key(deck, cfg, key, snapshot))
    redraw_secondary(deck, cfg)


def on_key_press(client, cfg, key, pressed):
    entry = cfg["keys"].get(key)
    if not pressed or entry is None:
        return
    if entry.get("type") == "today":
        return  # Anzeigetaste loest nichts aus
    topic = f"{cfg['mqtt']['topic_prefix']}/button/{key}"
    log.info("Taste %s (%s) gedrueckt -> %s", key, entry.get("label", ""), topic)
    client.publish(topic, json.dumps({"key": key, "event": "press"}), qos=1)


def on_state_message(deck, cfg, msg):
    try:
        data = json.loads(msg.payload.decode())
    except (ValueError, UnicodeDecodeError):
        log.warning("Ungueltige State-Nachricht: %r", msg.payload[:120])
        return
    with state_lock:
        state["active_key"] = data.get("active_key")
        state["started_at"] = data.get("started_at")
        if "today_base_seconds" in data:
            state["today_base_seconds"] = data.get("today_base_seconds") or 0
        if "today_by_key" in data:
            state["today_by_key"] = data.get("today_by_key") or {}
    log.info("Neuer Zustand: %s", state)
    redraw(deck, cfg)


def ticker(deck, cfg, stop_event):
    """Haelt Laufzeit und Tagesanzeige aktuell, solange ein Timer laeuft."""
    while not stop_event.wait(10):
        with state_lock:
            running = laeuft_etwas(state)
        if running:
            redraw(deck, cfg)
        else:
            # Auch im Ruhezustand muss die Uhr auf dem Seitenstreifen
            # weiterlaufen. Nur die drei kleinen Felder neu zeichnen - alle
            # 15 Tastenbilder alle 10 s zu erneuern, waere auf einem Zero 2 W
            # unnoetige Dauerlast.
            redraw_secondary(deck, cfg)


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    cfg = load_config(CONFIG_PATH)

    decks = DeviceManager().enumerate()
    if not decks:
        log.error("Kein Stream Deck gefunden (USB gesteckt? udev-Regel aktiv?)")
        return 1

    deck = decks[0]
    deck.open()
    deck.reset()
    deck.set_brightness(cfg.get("brightness", 60))
    log.info("%s mit %d Tasten geoeffnet", deck.deck_type(), deck.key_count())

    mcfg = cfg["mqtt"]
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)  # paho >= 2.0
    except AttributeError:
        client = mqtt.Client()  # paho 1.x
    if mcfg.get("username"):
        client.username_pw_set(mcfg["username"], mcfg.get("password"))

    state_topic = f"{mcfg['topic_prefix']}/state"

    def on_connect(c, _u, _f, rc, _props=None):
        log.info("MQTT verbunden (rc=%s), abonniere %s", rc, state_topic)
        c.subscribe(state_topic, qos=1)

    client.on_connect = on_connect
    client.on_message = lambda c, u, msg: on_state_message(deck, cfg, msg)

    client.connect(mcfg["host"], mcfg.get("port", 1883), keepalive=30)
    client.loop_start()

    deck.set_key_callback(lambda d, key, pressed: on_key_press(client, cfg, key, pressed))
    redraw(deck, cfg)

    stop_event = threading.Event()
    threading.Thread(target=ticker, args=(deck, cfg, stop_event), daemon=True).start()

    def shutdown(signum, _frame):
        log.info("Signal %s - fahre herunter", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    stop_event.wait()

    client.loop_stop()
    client.disconnect()
    with deck:
        deck.reset()
        deck.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
