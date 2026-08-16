# 9 — MiraBox Stream Dock statt Elgato

[← Kapitel 8](08-lessons-learned.md) · [Übersicht](../README.md)

IceDeck läuft auch mit einem **MiraBox Stream Dock**. Getestet mit dem
**293S** — dieselbe Bridge, derselbe Node-RED-Flow, dieselbe Tastenbelegung.

## „Elgato-kompatibel" stimmt nicht, wie man denkt

MiraBox bewirbt seine Geräte als Elgato-kompatibel. Gemeint ist die
**Plugin-Ebene der Windows-Software** — die kann Elgato-Plugins laden.

Auf USB-Ebene ist **nichts** kompatibel:

| | Elgato Original V2 | MiraBox 293S |
|---|---|---|
| USB-Kennung | `0fd9:006d` | `5548:6670` |
| Tastenbild | 72×72 | 85×85 |
| Drehung | 0° | 90° |
| Protokoll | Elgato | eigenes |

`python-elgato-streamdeck` findet ein MiraBox-Gerät nicht einmal. Der Beleg
liegt in den Projekten selbst: Es gibt einen eigenen Fork der Bibliothek nur für
MiraBox, ein Projekt namens „reverse-engineered communication protocol" und
einen offenen Pull Request, der 293S-Unterstützung nachrüstet.

Was rettet: Das **293S hat 15 Tasten in 5×3** — exakt dieselbe Geometrie wie das
Elgato-Modell. Tastenbelegung und Flow bleiben unverändert.

## Was zu tun ist

### 1. Die passende Bibliothek

[`python-streamdoeck`](https://github.com/StreamDoeck/python-streamdoeck) kennt
beide Gerätefamilien. In eine **getrennte** Umgebung installieren, damit die
laufende Installation unangetastet bleibt:

```bash
sudo mkdir -p /opt/icedeck-mirabox && sudo chown "$USER" /opt/icedeck-mirabox
python3 -m venv /opt/icedeck-mirabox/venv
/opt/icedeck-mirabox/venv/bin/pip install --upgrade pip
sudo apt-get install -y git
/opt/icedeck-mirabox/venv/bin/pip install \
    "git+https://github.com/StreamDoeck/python-streamdoeck.git" pillow paho-mqtt
```

`git` wird gebraucht, weil das Paket nicht auf PyPI liegt und pip es klonen muss.

### 2. Der fehlende-Assets-Fehler

> **Ohne diesen Schritt lässt sich die Bibliothek gar nicht benutzen.**

Im gebauten Paket **fehlen die Dateien `Assets/black-*.jpg`**. Jedes
Gerätemodul lädt sie beim Import, deshalb scheitert schon `import`:

```
FileNotFoundError: .../StreamDeck/ImageHelpers/../../Assets/black-85x85.jpg
```

Der Pfad zeigt eine Ebene **über** dem Paket — die Dateien gehören nach
`site-packages/Assets/`, nicht nach `site-packages/StreamDeck/Assets/`.

Es sind schlichte schwarze Flächen, also selbst erzeugen:

```bash
/opt/icedeck-mirabox/venv/bin/python - <<'EOF'
import os
from PIL import Image
ziel = "/opt/icedeck-mirabox/venv/lib/python3.13/site-packages/Assets"
os.makedirs(ziel, exist_ok=True)
for g in ["100x100", "120x120", "120x800", "126x126", "176x112", "248x58",
          "64x64", "72x72", "80x80", "85x85", "96x96"]:
    w, h = map(int, g.split("x"))
    Image.new("RGB", (w, h), (0, 0, 0)).save(f"{ziel}/black-{g}.jpg", "JPEG", quality=95)
EOF
```

**Diese Krücke überlebt kein Update der Bibliothek.** Nach jedem `pip install
--upgrade` neu anlegen.

### 3. udev-Regel

[`src/99-mirabox.rules`](../src/99-mirabox.rules) deckt alle vier bekannten
Hersteller-IDs ab:

| ID | Modelle |
|---|---|
| `0x5500` | Stream Dock 293 |
| `0x5548` | Stream Dock 293S |
| `0x6602` | Stream Dock N4 |
| `0x6603` | Stream Dock N3, N4EN |

```bash
sudo cp src/99-mirabox.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 4. Eine Zeile im Code

Der Fork nennt den Bildhelfer `NativeImageHelper` statt `PILHelper`. Die
benutzten Funktionen heißen identisch, es genügt ein toleranter Import — so
läuft **dieselbe Datei** mit beiden Gerätefamilien:

```python
try:
    from StreamDeck.ImageHelpers import PILHelper
except ImportError:
    from StreamDeck.ImageHelpers import NativeImageHelper as PILHelper
```

### 5. Umschalten ohne Rückbau

Statt die Unit zu ändern, eine Ergänzungsdatei anlegen:

```bash
sudo mkdir -p /etc/systemd/system/icedeck.service.d
sudo tee /etc/systemd/system/icedeck.service.d/10-mirabox.conf >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/opt/icedeck-mirabox/venv/bin/python /opt/icedeck-mirabox/streamdeck_bridge.py
EOF
sudo systemctl daemon-reload && sudo systemctl restart icedeck
```

Die leere `ExecStart=`-Zeile ist Pflicht: Ohne sie **ergänzt** systemd den
Befehl, statt ihn zu ersetzen, und die Unit wird ungültig.

Zurück zur Originalbibliothek:

```bash
sudo rm /etc/systemd/system/icedeck.service.d/10-mirabox.conf
sudo systemctl daemon-reload && sudo systemctl restart icedeck
```

## Der Seitenstreifen

Das 293S hat neben den 15 Tasten einen schmalen Streifen an der Seite. Die
Messung am Gerät ergab:

| | |
|---|---|
| Felder | **drei**, je 80×80, senkrecht gestapelt |
| Geräte-IDs | `0x10`, `0x11`, `0x12` |
| Drehung | 90° |
| Eingabe | **keine** — reine Anzeige, kein Taster |

Die Abstände zwischen den Feldern entstehen in der Firmware. Ein viertes Feld
gibt es nicht; die drei Kennungen sind fest verdrahtet.

IceDeck zeigt dort Uhrzeit, Tagessumme und eine Statusampel. Die Bridge prüft
vorher, ob das Gerät den Streifen hat **und** ob die Bibliothek die nötigen
Funktionen kennt — an einem Elgato wird der Teil übersprungen:

```python
def hat_seitenstreifen(deck):
    return (
        getattr(deck, "SECONDARY_IMAGE_COUNT", 0) > 0
        and hasattr(deck, "set_secondary_image")
        and hasattr(PILHelper, "create_secondary_image")
    )
```

Im Ruhezustand zeichnet der Timer **nur** diese drei Felder neu, damit die Uhr
weiterläuft. Alle 15 Tastenbilder alle zehn Sekunden zu erneuern wäre auf einem
Zero 2 W unnötige Dauerlast.

## Hintergrundbild: möglich, aber nicht empfohlen

Das 293S hat **ein einziges LCD**; die 15 „Tasten" sind Ausschnitte darauf.
`set_screen_image()` bemalt die gesamte Fläche, `set_key_image()` überschreibt
danach die einzelnen Bereiche. Ein Hintergrund bleibt also nur in den **Lücken
zwischen den Tasten** sichtbar — und nur, solange kein `reset()` läuft.

Die Messwerte:

| | |
|---|---|
| Format | **rohe RGB-Pixel**, nicht JPEG — trotz gegenteiliger Angabe im Code |
| Größe | **480×854** (1.229.760 Bytes). 854×480 wird abgelehnt. |
| Dauer | rund 9,5 Sekunden Übertragung |

Der interne Befehl heißt `CRT_LOG`. Die Hersteller-Software nutzt dieselbe
Fläche für Wallpaper und animierte Hintergründe.

**Zwei Fallstricke:**

Der dokumentierte Weg über `to_native_screen_format()` scheitert mit
`bytearray index out of range`. `set_screen_image` vertauscht Bytes im
Dreierschritt (RGB→BGR) — eine JPEG-Länge ist selten durch 3 teilbar. Das
verrät zugleich, dass rohe Pixel erwartet werden.

Schwerwiegender: Während der Übertragung **stirbt der Lesethread** mit
`KeyError: 0` in `_read_control_states`. Danach meldet keine Taste mehr etwas.
Offenbar wird die Bestätigung des Bildbefehls als Tastenereignis fehlgedeutet.

Für einen kosmetischen Hintergrund ist das ein schlechtes Geschäft: Die
Zeiterfassung würde stumm. Wer es trotzdem will, sollte das Bild **einmal beim
Dienststart** setzen — nach `reset()`, vor den Tastenbildern — und den
Lesefehler abfangen.

## Bekannte Einschränkungen

- Die 293S-Unterstützung nennt sich im Quelltext selbst „non-official"
- Die fehlenden Assets müssen nach jedem Bibliotheks-Update neu angelegt werden
- `set_screen_image` ist praktisch unbenutzbar, solange der Lesethread daran stirbt
- Ob andere Modelle (293, N3, N4) laufen, wurde nicht geprüft — die Bibliothek
  kennt sie, getestet wurde nur das 293S

---

[← Zurück zur Übersicht](../README.md)
