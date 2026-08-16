# 7 — Fehlersuche

[← Kapitel 6](06-solidtime-api.md) · [Übersicht](../README.md)

## Wo anfangen

Die Kette hat fünf Glieder. Jedes lässt sich einzeln prüfen, und in dieser
Reihenfolge findet man den Fehler am schnellsten:

```mermaid
flowchart LR
    A["1 Strom"] --> B["2 Deck erkannt"] --> C["3 Bridge läuft"] --> D["4 MQTT"] --> E["5 Node-RED → Solidtime"]
```

| # | Prüfung | Erwartet |
|---|---|---|
| 1 | `vcgencmd get_throttled` | `throttled=0x0` |
| 2 | `lsusb \| grep 0fd9` | eine Zeile mit dem Deck |
| 3 | `systemctl status icedeck` | `active (running)` |
| 4 | `mosquitto_sub -t 'streamdeck/#' -v` | mindestens minütlich eine Nachricht |
| 5 | Node-RED-Log | keine Fehlermeldungen |

## Der Pi taucht nicht im Netz auf

**Zuerst die LED ansehen.** Gleichmäßiges, regelmäßiges Blinken heißt fast immer
zu wenig Strom — siehe [Kapitel 1](01-hardware.md). Ein Netzteil mit 2,5 A oder
mehr, und für den ersten Start das Deck abziehen.

Blinkt sie unregelmäßig oder leuchtet dauerhaft, läuft der Pi, ist aber nicht
erreichbar. Dann:

```bash
nmap -sn -n 192.168.1.0/24
```

`-sn` heißt „nur Erreichbarkeit prüfen, keine Ports scannen", `-n` unterdrückt
DNS-Auflösung. Das füllt nebenbei die ARP-Tabelle:

```bash
ip neigh | grep -iE 'b8:27:eb|dc:a6:32|e4:5f:01|d8:3a:dd|2c:cf:67'
```

Das sind die MAC-Präfixe der Raspberry Pi Foundation.

> **Bei geroutetem Netz funktioniert das nicht.** Liegt der Pi in einem anderen
> Subnetz, sieht man nur die MAC des Routers. Dann hilft die
> Dienst-Erkennung:
>
> ```bash
> avahi-browse -art | grep -i raspberrypi
> ```
>
> oder ein Blick in die DHCP-Leases des Routers.

Alternativ über den SSH-Banner suchen — nützlich, wenn man weiß, welche
Debian-Version das frische Image mitbringt:

```bash
for ip in $(nmap -p22 --open -n 192.168.1.0/24 | awk '/^Nmap scan report/{print $NF}'); do
  echo "$ip $(timeout 3 bash -c "exec 3<>/dev/tcp/$ip/22 && head -1 <&3")"
done
```

Ein frisch installiertes System fällt durch eine neuere OpenSSH-Version auf als
die gewachsenen Geräte im Netz.

**Wenn gar nichts hilft:** Mini-HDMI an einen Bildschirm. Das zeigt sofort, ob
der Pi überhaupt bootet, ob er im Einrichtungsassistenten hängt oder ob das
WLAN scheitert. Das spart oft eine halbe Stunde Netzwerkarchäologie.

## „Kein Stream Deck gefunden"

```bash
lsusb
```

Fehlt die Zeile mit `0fd9`:

| Ursache | Abhilfe |
|---|---|
| Deck an `PWR IN` statt `USB` | umstecken — `PWR IN` hat keine Datenleitungen |
| OTG-Adapter defekt oder ein reines Ladekabel | anderen Adapter probieren |
| zu wenig Strom | `vcgencmd get_throttled` prüfen |

Ist das Deck da, der Dienst kommt aber nicht heran:

```bash
ls -l /dev/hidraw0
```

Erwartet: `crw-rw----+ 1 root plugdev`. Steht dort `root root`, greift die
udev-Regel nicht:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Regeln gelten erst ab dem nächsten Anstecken. `udevadm trigger` simuliert das
für bereits angesteckte Geräte.

Fehlersuche in der Regelauswertung:

```bash
udevadm test /sys/class/hidraw/hidraw0
```

Zeigt Schritt für Schritt, welche Regeln greifen und welche Rechte gesetzt
werden.

## Tasten reagieren, aber nichts passiert

Zuerst feststellen, **wo** die Kette reißt.

```bash
mosquitto_sub -h <broker> -u <benutzer> -P <passwort> -t 'streamdeck/#' -v
```

Dann eine Taste drücken.

| Beobachtung | Bedeutet |
|---|---|
| keine Nachricht auf `streamdeck/button/n` | Die Bridge sieht den Druck nicht, oder MQTT ist nicht verbunden — Journal prüfen |
| `button/n` erscheint, aber kein neues `state` | Node-RED reagiert nicht — Flow und Node-RED-Log prüfen |
| beides erscheint, Deck ändert sich nicht | Die Bridge rendert nicht — Journal prüfen |

Zum Journal:

```bash
sudo journalctl -u icedeck -f
```

Ein Tastendruck erzeugt eine Zeile wie:

```
Taste 9 (Projekt J) gedrueckt -> streamdeck/button/9
```

## `EPROTO: wrong version number`

```
RequestError: write EPROTO … SSL routines:tls_validate_record_header:
wrong version number
```

Sieht nach TLS aus, ist aber keines. Ursache:

> Node-RED ersetzt `msg.headers` nach jeder Antwort durch die **Response-Header**
> des Servers. Wer die Header nur im ersten Knoten setzt, schickt ab dem zweiten
> Aufruf die Antwort-Header als Anfrage-Header — und der HTTP-Client verrennt
> sich bis in einen TLS-Versuch gegen einen Klartext-Port.

Abhilfe: in **jedem** Knoten vor dem Aufruf `msg.headers` neu setzen. Siehe
[Kapitel 5](05-nodered.md#die-falle-mit-den-headern).

Typisches Muster im Log: Der **erste** `GET` funktioniert, alle weiteren
scheitern. Genau das ist der Fingerabdruck dieses Fehlers.

## `HTTP 422 — The member id field is required`

Beim Schreiben wurde `user_id` statt `member_id` geschickt. Siehe
[Kapitel 6](06-solidtime-api.md#2-schreibend-braucht-es-member_id-nicht-user_id).

## Tagessumme bleibt auf 0:00

Erst prüfen, ob der Aufruf überhaupt durchgeht — im Node-RED-Log erscheint sonst:

```
Tagessumme nicht ermittelbar: HTTP …
```

Kommen Daten an, ist die Summe aber falsch, liegt es meist an der
Datumsgrenze. Prüfen, was der Flow als lokale Mitternacht errechnet, und
gegenrechnen:

```bash
python3 -c "
from datetime import datetime, timezone
import zoneinfo
b = datetime.now(timezone.utc).astimezone(zoneinfo.ZoneInfo('Europe/Berlin'))
m = b.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
print(m.strftime('%Y-%m-%dT%H:%M:%SZ'))
"
```

Und daran erinnern: `after`/`before` wirken **nicht**, nur `start` und `end`.

## Taste zeigt keine Zeit, obwohl gebucht wurde

Regulär. Die Bridge blendet die Zeit aus, wenn heute **nichts** auf dem Projekt
steht — sonst stünde auf jeder ungenutzten Taste `0:00`.

Ein Eintrag von unter einer Minute wird als `0:00` angezeigt, weil das Format
`H:MM` ist. Das sieht aus wie ein Fehler, ist aber der gewünschte Kompromiss:
Sekunden sind auf einer 72×72-Taste nicht lesbar und laden nur zum Draufstarren
ein.

## Tasten reagieren gar nicht mehr, Dienst laeuft aber (MiraBox)

Typisches Bild: Die Tastenbilder werden weiter gezeichnet, MQTT ist verbunden,
das Protokoll zeigt nichts Auffaelliges — aber kein Tastendruck kommt mehr an.

Das ist der Lesethread der MiraBox-Klasse, der an einer Geraetequittung
gestorben ist. IceDeck faengt das ab und startet den Thread notfalls neu; im
Protokoll steht dann:

```
Lesethread war tot und wurde neu gestartet
```

Fehlt beim Start die Zeile `Lesethread abgesichert (...)`, laeuft eine zu alte
Fassung der Bridge. Sofortige Abhilfe in jedem Fall:

```bash
sudo systemctl restart icedeck
```

Hintergrund in [Kapitel 9](09-mirabox.md#der-toedliche-lesefehler).

## Deck flackert, Pi startet neu

Unterspannung.

```bash
vcgencmd get_throttled
```

Alles außer `0x0` ist ein Befund. `0x10000` heißt „seit dem Start gab es
Unterspannung", auch wenn gerade alles stimmt. Abhilfe: stärkeres Netzteil,
kürzeres und dickeres Kabel, notfalls ein **aktiver** USB-OTG-Hub.

## Zustand stimmt nicht

Der Resync läuft alle 60 Sekunden — so lange kann es dauern, bis eine Änderung
aus dem Webinterface auf dem Deck ankommt. Tastendrücke wirken sofort.

Kommt der Zustand gar nicht mehr an, hilft ein Blick auf die retained-Nachricht:

```bash
mosquitto_sub -h <broker> -u <benutzer> -P <passwort> -t streamdeck/state -v -C 1
```

`-C 1` beendet nach der ersten Nachricht. Kommt sofort etwas, ist eine
retained-Nachricht vorhanden — die schickt der Broker unmittelbar nach dem
Abonnieren.

## Nach einem Neustart ist alles dunkel

```bash
systemctl is-enabled icedeck
```

Erwartet: `enabled`. Sonst:

```bash
sudo systemctl enable icedeck
```

Startet der Dienst und stirbt wieder, war das Deck beim Start noch nicht bereit.
Dann muss `StartLimitBurst=0` im Abschnitt **`[Unit]`** stehen — in `[Service]`
wird es ignoriert. Siehe [Kapitel 4](04-bridge.md#systemd).

---

[Weiter: 8 — Was schiefging →](08-lessons-learned.md)
