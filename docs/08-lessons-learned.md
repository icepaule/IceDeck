# 8 — Was schiefging

[← Kapitel 7](07-fehlersuche.md) · [Übersicht](../README.md)

Diese Seite sammelt die Fehler dieses Projekts. Nicht aus Zerknirschung, sondern
weil jeder davon leicht ein zweites Mal passiert — und weil die meisten
Anleitungen nur den Weg zeigen, der am Ende funktioniert hat.

## Hardware

### Der Rechner-USB-Port als Netzteil

Der Zero hing zum Einrichten am USB-Port eines NUC. Der liefert 0,5 bis 0,9 A;
Zero und Deck zusammen brauchen rund 1 A. Ergebnis: Bootschleife, gleichmäßig
blinkende grüne LED, im Netz nie auffindbar.

Gesucht wurde in dieser Reihenfolge: WLAN-Konfiguration, Image, SD-Karte,
Netzwerksegmentierung. Der Strom kam zuletzt — dabei war er die Ursache.

**Merke:** Bei gleichmäßig blinkender LED zuerst das Netzteil tauschen. Das
kostet zwei Minuten und schließt die häufigste Ursache aus.

### Zwei Hosts an einem Kabel

Der Versuch, den Zero über sein `USB`-Port mit dem Rechner zu verbinden, um
„irgendwie draufzukommen", kann nicht funktionieren: Beide Seiten sind
USB-**Hosts**. Ohne den Gadget-Modus (`dtoverlay=dwc2` plus `g_ether`) entsteht
keine Verbindung — und der belegt genau den Port, den das Deck braucht.

## Provisionierung

### `custom.toml` wird nicht immer gelesen

Eine von Hand geschriebene `custom.toml` auf der Boot-Partition blieb wirkungslos:
kein Benutzer, kein WLAN, kein Hostname, Zeitzone `Europe/London`. Beim Start kam
der interaktive Einrichtungsassistent.

Die Ursache zeigte sich erst nach dem Anmelden:

```bash
$ ls -l /usr/lib/raspberrypi-sys-mods/firstboot
ls: cannot access '…/firstboot': No such file or directory

$ cat /boot/firmware/cmdline.txt
console=serial0,115200 … rootwait resize
```

Das Skript, das `custom.toml` verarbeitet, war im Image gar nicht enthalten, und
`cmdline.txt` rief auch nichts dergleichen auf. Die Datei lag unberührt herum.

Die `ssh`-Flagdatei wirkte dagegen — sie wird von `sshswitch.service` verarbeitet,
einem unabhängigen Mechanismus. Dieser Unterschied ist ein guter Indikator: Wenn
`ssh` verschwunden ist, aber `custom.toml` noch daliegt, ist genau das passiert.

**Merke:** Entweder den Raspberry Pi Imager benutzen, der `cmdline.txt` passend
mitschreibt, oder nach dem ersten Start von Hand konfigurieren. Eine `custom.toml`
allein ist keine Garantie.

## Datensicherung

### `mount -o ro` schreibt trotzdem

Um den Inhalt einer SD-Karte anzusehen, wurde sie schreibgeschützt eingehängt.
Im Kernel-Log stand danach:

```
EXT4-fs (mmcblk0p2): recovery required on readonly filesystem
EXT4-fs (mmcblk0p2): write access will be enabled during recovery
EXT4-fs (mmcblk0p2): recovery complete
```

Die Karte war im laufenden Betrieb gezogen worden, das Journal war offen, und
der Kernel spielte es beim Einhängen ab — **schreibend**, trotz `ro`.

**Merke:** Für wirklich schreibfreies Einhängen `ro,noload` (oder `norecovery`)
benutzen. `ro` allein bezieht sich auf den Zugriff durch Anwendungen, nicht auf
die Journalwiederherstellung.

### Neun Stunden für 49 GB Nichts

Ein `dd` über die ganze 58-GB-Karte war nach 40 Minuten bei 8 %. Hochgerechnet:
neun Stunden — für ein Dateisystem, von dem 7 GB belegt waren.

`e2image -ra` liest nur belegte Blöcke und war in gut einer Stunde fertig, bei
einer sparse-Datei von 7,1 GB tatsächlicher Größe.

**Merke:** Für ext4 ist `e2image -ra` fast immer die bessere Wahl. `dd` ist
richtig für die kleine FAT-Boot-Partition und für Datenträger, deren Dateisystem
man nicht kennt.

### Voreilige Verdächtigung der Hardware

Als die Lesegeschwindigkeit von 5,6 auf 2,2 MB/s fiel, lag der Verdacht auf einer
sterbenden Karte. Ein Blick ins Kernel-Log zeigte aber eine gesunde Karte
(`ultra high speed SDR104 SDXC`) ohne einen einzigen I/O-Fehler. Die Ursache war
Last auf dem Host.

**Merke:** Erst `dmesg` lesen, dann die Hardware verdächtigen.

## Node-RED

### Header werden nach jeder Antwort überschrieben

Der teuerste Fehler des Projekts. `msg.headers` wurde einmal in `Vorbereiten`
gesetzt; alle Folgeknoten übernahmen stillschweigend die **Response-Header** der
vorigen Antwort. Sichtbar wurde das als:

```
RequestError: write EPROTO … wrong version number
```

Also eine TLS-Meldung — bei einer reinen HTTP-Verbindung. Die Suche lief
zunächst in Richtung Zertifikate und Proxy-Einstellungen.

Der Fingerabdruck ist eindeutig, wenn man ihn kennt: **Der erste Aufruf
funktioniert, alle weiteren scheitern.**

**Merke:** In Ketten mehrerer `http request`-Knoten die Header vor **jedem**
Aufruf neu setzen.

### Der Konfigurationspfad des Home-Assistant-Addons

Gesucht wurde unter `addon_configs/`, tatsächlich heißt das Verzeichnis
`app_configs/`. Dazu kommt, dass Node-RED nicht `settings.js` direkt liest,
sondern `/etc/node-red/config.js`, die `/config/settings.js` in der ersten Zeile
per `require` einbindet.

**Merke:** `docker exec <container> head -1 /etc/node-red/config.js` klärt in
einer Sekunde, ob die eigene `settings.js` überhaupt gelesen wird.

## Anwendungslogik

### Zeit ohne Projekt fiel aus der Anzeige

`today_total()` addierte die laufende Zeit nur, wenn `active_key` gesetzt war.
Ein laufender Eintrag **ohne Projekt** hat aber `active_key: null` — er ließ sich
keiner Taste zuordnen. Folge: Die Tagesanzeige unterschlug diese Zeit stillschweigend.

Aufgefallen ist das nur, weil zufällig ein solcher Eintrag lief. Ohne echte Daten
wäre der Fehler unentdeckt geblieben.

**Merke:** „Läuft etwas?" und „Welche Taste ist hervorzuheben?" sind **zwei
verschiedene Fragen**. Die erste hängt an `started_at`, die zweite an
`active_key`.

### Projekttasten zeigten nur den laufenden Abschnitt

Wer vormittags dreimal zwischen Projekten wechselt, hat drei Einträge auf
demselben Projekt. Die Taste zeigte nur den letzten — also ein paar Minuten,
obwohl zwei Stunden gebucht waren.

Behoben durch `today_by_key`: Node-RED liefert die abgeschlossenen Zeiten je
Taste, die Bridge addiert den laufenden Abschnitt.

**Merke:** Bei Zeiterfassung ist fast immer die **Tagessumme** gemeint, nicht
der aktuelle Abschnitt.

### Ein zu weiter Fang verschiebt den Ausfall nur

Die Bibliothek warf bei einer Befehlsquittung einen `KeyError`, der den
Lesethread beendete: Dienst lief weiter, Tasten stumm. Die Abhilfe fing
daraufhin **jede** Ausnahme ab und gab `None` zurück.

Als sich das Gerät später neu am USB-Bus anmeldete, war der Zugriff ungültig
und **jeder** Lesevorgang scheiterte. Der Fang verschluckte auch das: rund 17
Fehler je Sekunde, über tausend Protokollzeilen je Minute — und die Tasten
blieben trotzdem stumm.

Aus einem toten Thread war ein leer drehender geworden. Von außen sehen beide
identisch aus.

**Merke:** Vor jedem `except Exception` die Frage stellen, ob der Zustand nach
dem Fang wirklich wieder gesund ist. Trifft das nicht zu, ist Weitermachen die
falsche Antwort — dann gehört der Ausfall **sichtbar** gemacht oder der Prozess
beendet, damit ein Neustart greift. Hier: `KeyError` verschlucken,
Transportfehler zählen und ab zehn in Folge aufgeben.

Erwähnenswert ist auch, wie der Fehler auffiel — nicht durch eine Meldung,
sondern beim Nachsehen im Protokoll aus einem ganz anderen Anlass. Ein
Ausfall, der nichts meldet, wird nicht gefunden, sondern gestolpert.

### `StartLimitBurst` im falschen Abschnitt

Stand in `[Service]`, gehört in `[Unit]`. Dort wird es stillschweigend ignoriert.
Die Auswirkung zeigt sich nur im Grenzfall: Ist das Deck beim Systemstart noch
nicht bereit, gibt systemd nach fünf Versuchen endgültig auf — der Dienst bleibt
tot, obwohl das Deck Sekunden später da wäre.

## Zusammenarbeit

### Farbwert statt Projekt-ID

Beim Ausfüllen der Tastenbelegung wurde einmal ein **Farbwert** an die Stelle
einer Projekt-ID kopiert. Der Flow hätte einen Timer auf ein nicht existierendes
Projekt gestartet.

**Merke:** IDs nach dem Eintragen gegen die API prüfen, nicht nur gegen das Auge.

### Doppelte Projektnamen

Zwei Projekte hießen `Projekt G`, zwei `Projekt H`. Nach Namen zuzuordnen hätte in
die Irre geführt. Ein Fall ließ sich über die Buchungshistorie klären (131
Buchungen gegen null), beim anderen half nur nachfragen.

**Merke:** Bei Mehrdeutigkeit nachfragen. Eine falsche Zuordnung in der
Zeiterfassung fällt erst bei der Abrechnung auf.

## Offen

- **Icons aus dem Windows-Profil übernehmen.** Eine `.streamDeckProfile`-Datei
  ist ein ZIP-Archiv; die PNGs liegen zusätzlich unter
  `%APPDATA%\Elgato\StreamDeck\ProfilesV2\`. Die Bridge unterstützt bereits ein
  `icon`-Feld je Taste.
- **Mehrere Organisationen.** Der Flow arbeitet mit genau einer. Für mehrere
  müsste die Tastenbelegung die Organisation mitführen.
- **Rückmeldung bei Fehlern auf dem Deck.** Scheitert ein API-Aufruf, merkt man
  es derzeit nur im Node-RED-Log. Ein roter Rahmen auf der betroffenen Taste
  wäre besser.
- **Tastendrücke puffern.** Ist der Broker nicht erreichbar — Funkloch, Hotspot
  aus, Tunnel im Aufbau —, geht der Druck verloren. Sichtbar ist das nur daran,
  dass sich das Tastenbild nicht ändert. Bewusst nicht nachgerüstet: Ein
  nachgesendeter Start mit falschem Zeitstempel wäre schlimmer als ein
  verlorener Druck, den man sofort bemerkt. Für längeren Betrieb außer Haus
  wäre ein Puffer **mit Originalzeitstempel** aber sinnvoll.
- **Warum sich das Gerät neu am USB anmeldet, ist ungeklärt.** Die
  Stromversorgung war es nachweislich nicht. Nach dem Neustecken von Kabel und
  OTG-Adapter trat es nicht mehr auf, ein Beweis ist das aber nicht.

---

[Weiter: 9 — MiraBox statt Elgato →](09-mirabox.md)
