# 3 — Raspberry Pi einrichten

[← Kapitel 2](02-sdkarte.md) · [Übersicht](../README.md)

## Erster Start

Karte einlegen, Netzteil an `PWR IN`. **Das Stream Deck noch nicht anstecken** —
das kommt erst, wenn der Pi im Netz ist.

Der erste Start dauert mehrere Minuten: Das Dateisystem wird auf die volle
Kartengröße vergrößert, danach startet der Pi einmal neu.

### Was die grüne LED sagt

Der Zero hat nur eine LED, und ihre Bedeutung ist nicht offensichtlich:

| Verhalten | Bedeutung |
|---|---|
| unregelmäßiges Flackern | normaler Betrieb, Zugriffe auf die SD-Karte |
| **gleichmäßiges, regelmäßiges Blinken** | meist Bootschleife — fast immer **zu wenig Strom** |
| dauerhaft an | gebootet und im Leerlauf |
| aus | keine Stromversorgung, oder Karte nicht lesbar |

Bei gleichmäßigem Blinken zuerst das Netzteil tauschen, bevor man weitersucht.
Siehe [Kapitel 1](01-hardware.md#die-stromversorgung-ist-der-häufigste-fehler).

## Einrichtungsassistent

Wurde die `custom.toml` nicht verarbeitet — siehe
[Kapitel 2](02-sdkarte.md#was-mit-customtoml-nicht-funktioniert) —, fragt der Pi
auf der Konsole nach Benutzername und Passwort. Dafür braucht man Bildschirm
(Mini-HDMI) und Tastatur.

> **Tastaturlayout beachten.** Ohne angewandte `custom.toml` ist **US-Layout**
> aktiv. Auf einer deutschen Tastatur heißt das:
>
> | Zeichen | Taste |
> |---|---|
> | `#` | **Shift+3** — *nicht* die Taste, auf der `#` steht |
> | `y` / `z` | vertauscht |
> | `-` | die Taste, auf der `ß` steht |
>
> Bei einem Passwort, das man nicht sieht, ist das eine ergiebige Fehlerquelle.

## WLAN einrichten

```bash
sudo raspi-config nonint do_wifi_country DE
```

`raspi-config` ist normalerweise ein Menü; `nonint` ruft eine einzelne Funktion
direkt auf. `do_wifi_country` setzt die Regulierungsdomäne.

**Dieser Schritt ist nicht optional.** Ohne gesetztes Land bleibt das WLAN-Modul
gesperrt, weil die erlaubten Kanäle und Sendeleistungen vom Land abhängen. Der
Befehl trägt `cfg80211.ieee80211_regdom=DE` in `cmdline.txt` ein.

```bash
sudo nmcli device wifi connect '<WLAN-SSID>' password '<WLAN-PASSWORT>'
```

Raspberry Pi OS (Bookworm und neuer) nutzt **NetworkManager**; `nmcli` ist
dessen Kommandozeilenwerkzeug. Der Befehl legt ein Profil an, verbindet sich und
merkt sich die Verbindung dauerhaft.

> **Die einfachen Anführungszeichen sind wichtig.** Enthält die SSID ein
> Ausrufezeichen, deutet die interaktive Bash es sonst als History-Expansion und
> ersetzt es durch ein früheres Kommando. Innerhalb einfacher Anführungszeichen
> passiert das nicht. Dasselbe gilt für Passwörter mit `$`, `` ` `` oder `\`.

Der Pi Zero 2 W kann **nur 2,4 GHz**. Ein reines 5-GHz-Netz sieht er nicht.

Prüfen:

```bash
nmcli -t -f NAME,AUTOCONNECT connection show
hostname -I
```

Die erste Zeile bestätigt, dass die Verbindung automatisch wiederhergestellt
wird (`yes`). `hostname -I` gibt die aktuellen IP-Adressen aus.

## SSH aktivieren

```bash
sudo systemctl enable --now ssh
```

| Teil | Bedeutung |
|---|---|
| `enable` | beim Systemstart automatisch starten |
| `--now` | zusätzlich sofort starten |

Wurde die `ssh`-Flagdatei aus [Kapitel 2](02-sdkarte.md#ssh-vorab-aktivieren)
angelegt, läuft der Dienst bereits.

## Schlüssel hinterlegen

Vom Arbeitsrechner aus:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub <benutzer>@<pi-ip>
```

`ssh-copy-id` hängt den **öffentlichen** Schlüssel an `~/.ssh/authorized_keys`
auf dem Pi an und setzt die Rechte richtig. Der private Schlüssel bleibt, wo er
ist. Danach:

```bash
ssh -o BatchMode=yes <benutzer>@<pi-ip> 'echo OK'
```

`BatchMode=yes` unterbindet jede Passwortabfrage. Kommt `OK`, funktioniert die
Anmeldung per Schlüssel — sonst bricht der Befehl ab, statt still nach einem
Passwort zu fragen.

## Grundkonfiguration nachziehen

Was die `custom.toml` erledigt hätte:

```bash
sudo hostnamectl set-hostname icedeck
sudo sed -i 's/\braspberrypi\b/icedeck/g' /etc/hosts
```

`hostnamectl` setzt den Hostnamen dauerhaft. Die zweite Zeile zieht `/etc/hosts`
nach — sonst meldet jedes `sudo` die Warnung `unable to resolve host`, weil der
neue Name nirgends aufgelöst wird. `\b` sind Wortgrenzen, damit nur der
vollständige Name ersetzt wird.

```bash
sudo timedatectl set-timezone Europe/Berlin
sudo localectl set-keymap de
```

Zeitzone und Tastaturbelegung.

> **Die Zeitzone beeinflusst die Zeitrechnung von IceDeck nicht.** Die Bridge
> rechnet durchgehend in UTC (`datetime.now(timezone.utc)`), und Solidtime
> liefert UTC. Eine falsche Zeitzone macht nur die Logeinträge verwirrend.
> Richtig gehört sie trotzdem.

Prüfen:

```bash
timedatectl show -p Timezone --value
timedatectl show -p NTPSynchronized --value
```

Erwartet: `Europe/Berlin` und `yes`. Ohne Zeitsynchronisation stimmen die
berechneten Laufzeiten nicht, weil die Startzeit vom Server kommt und die
aktuelle Zeit vom Pi.

## Optional: `sudo` ohne Passwort

Für automatisierte Einrichtung praktisch:

```bash
echo "<benutzer> ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/010-icedeck-nopasswd
sudo chmod 440 /etc/sudoers.d/010-icedeck-nopasswd
sudo visudo -c
```

`visudo -c` prüft die Syntax **aller** sudoers-Dateien. Dieser Schritt ist
Pflicht: Eine fehlerhafte Datei sperrt `sudo` vollständig aus, und ohne `sudo`
lässt sie sich nicht mehr reparieren.

`chmod 440` ist ebenfalls Pflicht — `sudo` ignoriert Dateien mit zu weiten
Rechten.

> Diese Einstellung senkt die Sicherheit. Auf einem dedizierten Gerät im
> eigenen Netz ist sie vertretbar (Raspberry Pi OS hatte sie für den
> Standardbenutzer jahrelang voreingestellt), auf einem Mehrbenutzersystem
> nicht. Rückgängig: Datei löschen.

---

[Weiter: 4 — Die Bridge installieren →](04-bridge.md)
