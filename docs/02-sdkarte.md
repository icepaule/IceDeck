# 2 — SD-Karte sichern und beschreiben

[← Kapitel 1](01-hardware.md) · [Übersicht](../README.md)

Dieses Kapitel beschreibt zwei Dinge: wie man eine **vorhandene** Karte sichert,
bevor man sie überschreibt, und wie man **Raspberry Pi OS** aufspielt.

Wer eine frische Karte nimmt, springt direkt zu
[Image aufspielen](#image-aufspielen).

---

## Karte identifizieren

```bash
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT
```

`lsblk` listet alle Blockgeräte. Die Spalten zeigen Name, Größe, Dateisystem,
Bezeichnung und Einhängepunkt. Eine Raspberry-Pi-Karte erkennt man an zwei
Partitionen: eine kleine `vfat` mit Label `bootfs` und eine große `ext4` mit
`rootfs`.

> **Diesen Schritt nicht überspringen.** Alles Folgende schreibt roh auf ein
> Blockgerät. Ein Tippfehler im Gerätenamen zerstört die falsche Platte, ohne zu
> fragen. `/dev/mmcblk0` ist typischerweise ein interner Kartenleser,
> `/dev/sdb` ein USB-Adapter — verlassen sollte man sich darauf nicht.

Falls die Karte automatisch eingehängt wurde, erst aushängen:

```bash
sudo umount /dev/mmcblk0p1 /dev/mmcblk0p2
```

Solange eine Partition eingehängt ist, schreibt der Kernel im Hintergrund
weiter, und ein Abbild würde inkonsistent.

---

## Vorhandene Karte sichern

### Warum nicht einfach `dd`

Der übliche Ratschlag lautet:

```bash
sudo dd if=/dev/mmcblk0 of=backup.img bs=4M     # NICHT empfohlen
```

Das liest **jeden** Block, auch die leeren. Bei einer 58-GB-Karte, von der
7 GB belegt sind, dauert das an einem langsamen Leser leicht neun Stunden und
erzeugt eine 58 GB große Datei.

### Besser: `e2image`

`e2image` kennt das ext4-Dateisystem und liest nur belegte Blöcke:

```bash
sudo /sbin/e2image -ra -p /dev/mmcblk0p2 /pfad/zum/backup/p2-rootfs.img
```

| Teil | Bedeutung |
|---|---|
| `-r` | Rohformat schreiben, kein `e2image`-Eigenformat — das Ergebnis lässt sich direkt zurückspielen und einhängen |
| `-a` | auch die Dateidaten mitnehmen, nicht nur die Metadaten |
| `-p` | Fortschritt anzeigen |

Das Ergebnis ist eine **sparse-Datei**: nominell so groß wie die Partition,
tatsächlich belegt sie nur die echten Daten. Der Unterschied ist sichtbar:

```bash
du -sh --apparent-size p2-rootfs.img   # 58G  (scheinbare Größe)
du -sh p2-rootfs.img                   # 7.1G (tatsächlich belegt)
```

### Boot-Partition und Partitionstabelle

Die kleine FAT-Partition kennt `e2image` nicht — hier ist `dd` richtig, denn sie
ist ohnehin winzig:

```bash
sudo dd if=/dev/mmcblk0p1 bs=4M | zstd -T0 -o p1-bootfs.img.zst
```

`zstd` komprimiert im Vorbeigehen, `-T0` nutzt alle CPU-Kerne.

Dazu die Partitionstabelle, ohne die sich das Abbild nicht sinnvoll
zurückspielen lässt:

```bash
sudo /sbin/sfdisk -d /dev/mmcblk0 > partitionstabelle.sfdisk
```

`sfdisk -d` gibt die Tabelle als Text aus. Zurückgespielt wird sie später mit
`sfdisk /dev/mmcblk0 < partitionstabelle.sfdisk`.

### Prüfsummen

```bash
sha256sum p1-bootfs.img.zst p2-rootfs.img partitionstabelle.sfdisk > SHA256SUMS
```

> **Achtung:** Die Prüfsumme über die 58-GB-sparse-Datei liest alle 58 GB, auch
> die Löcher. Das dauert mehrere Minuten und läuft in manchen Umgebungen in
> einen Timeout. Das ist kein Fehler, nur Geduld.

Ein fertiges Skript für den ganzen Ablauf liegt unter
[`tools/sd-backup.sh`](../tools/sd-backup.sh).

### Backup prüfen, bevor man das Original zerstört

Drei Prüfungen, von schnell nach gründlich:

```bash
sha256sum -c SHA256SUMS
```

Vergleicht die Prüfsummen. Erwartet: dreimal `OK`.

```bash
sudo /sbin/dumpe2fs -h p2-rootfs.img
```

`dumpe2fs -h` zeigt nur den Superblock. Interessant sind `Filesystem state:
clean` und plausible Werte bei `Block count` und `Free blocks`.

```bash
sudo /sbin/fsck.ext4 -fn p2-rootfs.img
```

| Schalter | Bedeutung |
|---|---|
| `-f` | Prüfung erzwingen, auch wenn das Dateisystem als sauber markiert ist |
| `-n` | **nichts reparieren**, alle Fragen mit „nein" beantworten |

`-n` ist entscheidend: Ohne diesen Schalter würde `fsck` das Abbild verändern.

Und schließlich der Inhalt:

```bash
sudo mount -o ro,noload,loop p2-rootfs.img /mnt/pruefen
sudo cat /mnt/pruefen/etc/hostname
sudo umount /mnt/pruefen
```

> **`ro` allein genügt nicht.** Hat das Dateisystem ein unabgeschlossenes
> Journal — etwa weil die Karte im laufenden Betrieb gezogen wurde —, spielt der
> Kernel es beim Einhängen ab und **schreibt dabei**, trotz `ro`. Im Log steht
> dann:
>
> ```
> EXT4-fs (loop0): recovery required on readonly filesystem
> EXT4-fs (loop0): write access will be enabled during recovery
> ```
>
> `noload` unterbindet das Abspielen des Journals. Nur damit ist das Einhängen
> wirklich schreibfrei. Alternativ `norecovery`, dasselbe unter anderem Namen.

---

## Image aufspielen

### Herunterladen und prüfen

```bash
cd ~/pi-os
wget https://downloads.raspberrypi.com/raspios_lite_arm64/images/…/….img.xz
wget https://downloads.raspberrypi.com/raspios_lite_arm64/images/…/….img.xz.sha256
sha256sum -c ….img.xz.sha256
```

Erwartet: `OK`. Ein beschädigter Download führt sonst zu einem Fehlerbild, das
wie ein Hardwaredefekt aussieht.

**Lite** genügt — eine grafische Oberfläche wird nicht gebraucht und kostet auf
dem Zero nur Ressourcen. **arm64** ist richtig, weil der Zero 2 W einen
Cortex-A53 hat.

### Schreiben

```bash
xzcat ~/pi-os/….img.xz | sudo dd of=/dev/mmcblk0 bs=4M conv=fsync status=progress
```

| Teil | Bedeutung |
|---|---|
| `xzcat` | entpackt nach stdout, ohne das entpackte Abbild zwischenzuspeichern |
| `of=/dev/mmcblk0` | Ziel ist das **ganze Gerät**, nicht eine Partition |
| `bs=4M` | 4-MB-Blöcke; deutlich schneller als die Vorgabe von 512 Byte |
| `conv=fsync` | am Ende alles physisch schreiben, bevor `dd` zurückkehrt |
| `status=progress` | Fortschritt anzeigen |

`conv=fsync` ist wichtiger, als es aussieht. Ohne diesen Schalter meldet `dd`
Vollzug, während noch Daten im Schreibcache liegen. Zieht man die Karte dann,
ist sie unvollständig.

Danach:

```bash
sudo sync
sudo partprobe /dev/mmcblk0
lsblk -o NAME,SIZE,FSTYPE,LABEL /dev/mmcblk0
```

`sync` leert alle Puffer. `partprobe` weist den Kernel an, die Partitionstabelle
neu einzulesen — sonst kennt er noch die alte Aufteilung. `lsblk` bestätigt das
Ergebnis: eine `vfat` mit `bootfs` und eine `ext4` mit `rootfs`.

Die Root-Partition ist zunächst nur rund 2 GB groß. Sie wächst beim ersten Start
automatisch auf die volle Kartengröße.

---

## SSH vorab aktivieren

```bash
sudo mount /dev/mmcblk0p1 /mnt/boot
sudo touch /mnt/boot/ssh
sudo sync
sudo umount /mnt/boot
```

Eine leere Datei namens `ssh` auf der Boot-Partition schaltet den SSH-Server
beim ersten Start ein. Zuständig ist `sshswitch.service`, das die Datei danach
löscht. Ist die Datei nach dem ersten Start weg, hat der Mechanismus gegriffen.

## Was mit `custom.toml` **nicht** funktioniert

Der Raspberry Pi Imager legt üblicherweise eine `custom.toml` auf der
Boot-Partition ab, die Benutzer, WLAN, Hostname und Zeitzone vorkonfiguriert.
Man kann diese Datei auch von Hand schreiben — **sie wird dann aber unter
Umständen ignoriert.**

Ob der Mechanismus im verwendeten Image überhaupt vorhanden ist, prüft man so:

```bash
ls -l /usr/lib/raspberrypi-sys-mods/firstboot
cat /boot/firmware/cmdline.txt
```

Verarbeitet wird `custom.toml` nur, wenn **beides** zutrifft:

1. das Skript `/usr/lib/raspberrypi-sys-mods/firstboot` existiert, **und**
2. `cmdline.txt` ruft es auf, per `init=/usr/lib/raspberrypi-sys-mods/firstboot`
   oder `systemd.run=`

In dem hier verwendeten Image (Trixie, Mitte 2026) traf **keines von beidem** zu.
Das Paket `raspberrypi-sys-mods` lieferte nur `imager_custom`, und `cmdline.txt`
enthielt lediglich:

```
console=serial0,115200 console=tty1 root=PARTUUID=… rootfstype=ext4 fsck.repair=yes rootwait resize
```

Kein `init=`, kein `systemd.run=`. Die `custom.toml` lag unberührt auf der Karte,
und beim Start erschien der interaktive Einrichtungsassistent.

> **Merke:** Eine `custom.toml` allein reicht nicht. Entweder man benutzt den
> Raspberry Pi Imager, der `cmdline.txt` passend mitschreibt, oder man
> konfiguriert nach dem ersten Start von Hand — siehe
> [Kapitel 3](03-raspberry-pi.md).
>
> Die `ssh`-Flagdatei ist davon **nicht** betroffen; sie wird von einem eigenen
> Dienst verarbeitet und wirkt zuverlässig.

---

[Weiter: 3 — Raspberry Pi einrichten →](03-raspberry-pi.md)
