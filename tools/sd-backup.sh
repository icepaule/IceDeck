#!/bin/bash
# Dateisystembewusstes Backup einer Raspberry-Pi-SD-Karte.
#
# Liest mit e2image nur die belegten Bloecke der ext4-Partition statt aller
# Bloecke. Bei einer 58-GB-Karte mit 7 GB Inhalt ist das rund achtmal schneller
# als ein dd ueber das ganze Geraet.
#
#   ./sd-backup.sh /dev/mmcblk0 ~/sd-backup
#
# Erzeugt im Zielverzeichnis:
#   partitionstabelle.sfdisk   Partitionstabelle als Text
#   p1-bootfs.img.zst          Boot-Partition, komprimiert
#   p2-rootfs.img              Root-Partition als sparse-Datei
#   SHA256SUMS                 Pruefsummen
#
# Hintergrund: docs/02-sdkarte.md

set -euo pipefail

DEV="${1:?Aufruf: $0 <geraet> <zielverzeichnis>   z.B. $0 /dev/mmcblk0 ~/backup}"
ZIEL="${2:?Aufruf: $0 <geraet> <zielverzeichnis>}"

[ -b "$DEV" ] || { echo "ABBRUCH: $DEV ist kein Blockgeraet"; exit 1; }

# Eingehaengte Partitionen wuerden ein inkonsistentes Abbild ergeben.
if mount | grep -q "^$DEV"; then
    echo "ABBRUCH: $DEV ist eingehaengt. Erst aushaengen:"
    mount | grep "^$DEV" | awk '{print "  sudo umount " $1}'
    exit 1
fi

# Systemdatentraeger niemals anfassen.
if lsblk -no MOUNTPOINT "$DEV" | grep -qE '^/(|boot|home)$'; then
    echo "ABBRUCH: $DEV traegt Systemverzeichnisse"; exit 1
fi

mkdir -p "$ZIEL"
cd "$ZIEL"

echo "== Partitionstabelle =="
sudo /sbin/sfdisk -d "$DEV" > partitionstabelle.sfdisk
cat partitionstabelle.sfdisk

echo
echo "== Boot-Partition (dd + zstd) =="
# Klein und FAT - hier ist dd richtig, e2image kann kein FAT.
sudo dd if="${DEV}p1" bs=4M status=progress | zstd -T0 -f -o p1-bootfs.img.zst

echo
echo "== Root-Partition (e2image) =="
# -r Rohformat (direkt zurueckspielbar), -a mit Dateidaten, -p Fortschritt
sudo /sbin/e2image -ra -p "${DEV}p2" p2-rootfs.img
sudo chown "$(id -un)" p2-rootfs.img

echo
echo "== Groessen =="
echo "  scheinbar: $(du -sh --apparent-size p2-rootfs.img | cut -f1)"
echo "  belegt:    $(du -sh p2-rootfs.img | cut -f1)"

echo
echo "== Pruefsummen (dauert, es werden alle Bloecke gelesen) =="
sha256sum p1-bootfs.img.zst p2-rootfs.img partitionstabelle.sfdisk > SHA256SUMS
cat SHA256SUMS

cat <<'EOF'

== Fertig ==

Vor dem Ueberschreiben der Karte pruefen:

  sha256sum -c SHA256SUMS
  sudo /sbin/dumpe2fs -h p2-rootfs.img      # 'Filesystem state: clean'
  sudo /sbin/fsck.ext4 -fn p2-rootfs.img    # -n repariert nichts

Inhaltliche Stichprobe - ro,noload ist Pflicht, sonst spielt der Kernel
ein offenes Journal ab und SCHREIBT dabei trotz ro:

  sudo mount -o ro,noload,loop p2-rootfs.img /mnt
  sudo cat /mnt/etc/hostname
  sudo umount /mnt

Zurueckspielen:

  sudo /sbin/sfdisk /dev/XXX < partitionstabelle.sfdisk
  zstdcat p1-bootfs.img.zst | sudo dd of=/dev/XXXp1 bs=4M conv=fsync
  sudo dd if=p2-rootfs.img of=/dev/XXXp2 bs=4M conv=fsync status=progress
EOF
