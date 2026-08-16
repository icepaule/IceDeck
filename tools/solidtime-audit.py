#!/usr/bin/env python3
"""
Findet Zeiteintraege ohne Projekt und ordnet sie auf Wunsch zu.

Standardmaessig wird NUR GELESEN und eine Liste ausgegeben. Geschrieben wird
erst mit --anwenden, und auch dann nur, was in einer Zuordnungsdatei ausdruecklich
steht - geraten wird nie.

Beispiele:

    # Ueberblick verschaffen
    export SOLIDTIME_URL=http://solidtime.example.lan:8000
    export SOLIDTIME_TOKEN=...
    ./solidtime-audit.py --org <ORG-ID> --user <USER-ID> --von 2025-01-01 --bis 2026-01-01

    # Zuordnungsvorlage schreiben lassen, von Hand pruefen, dann anwenden
    ./solidtime-audit.py --org ... --user ... --von 2025-01-01 --bis 2026-01-01 \
        --vorlage zuordnung.json
    ./solidtime-audit.py --org ... --user ... --member <MEMBER-ID> \
        --von 2025-01-01 --bis 2026-01-01 --zuordnung zuordnung.json --anwenden

Hintergrund zu den API-Eigenheiten: docs/06-solidtime-api.md
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

LIMIT = 500  # harte Obergrenze der API


def api(method, url, token, body=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            roh = resp.read()
            return resp.status, (json.loads(roh) if roh else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def monate(von, bis):
    """Zerlegt einen Zeitraum in Monatsfenster.

    Noetig, weil die API weder Blaettern noch mehr als 500 Treffer kann:
    'page' wird ignoriert, 'limit' ist gedeckelt. Nur 'start' und 'end' wirken.
    """
    a = datetime.strptime(von, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    e = datetime.strptime(bis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    while a < e:
        nxt = (a.replace(day=28) + timedelta(days=8)).replace(day=1)
        yield a, min(nxt, e)
        a = nxt


def hole_eintraege(basis, org, user, token, von, bis):
    """Holt alle Eintraege im Zeitraum, ueber Monatsfenster, dedupliziert."""
    alle = {}
    for a, e in monate(von, bis):
        q = urllib.parse.urlencode({
            "limit": LIMIT,
            "user_id": user,
            "start": a.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": e.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        st, d = api("GET", f"{basis}/api/v1/organizations/{org}/time-entries?{q}", token)
        if st != 200 or not isinstance(d, dict):
            print(f"  ! {a:%Y-%m}: HTTP {st}", file=sys.stderr)
            continue
        treffer = d.get("data", [])
        if len(treffer) >= LIMIT:
            print(f"  ! {a:%Y-%m}: {LIMIT} Treffer - Fenster moeglicherweise zu gross",
                  file=sys.stderr)
        for r in treffer:
            alle[r["id"]] = r
    return list(alle.values())


def hms(sek):
    sek = int(sek or 0)
    return f"{sek // 3600}:{sek % 3600 // 60:02d}"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--org", required=True, help="Organisations-ID")
    p.add_argument("--user", required=True, help="eigene user_id")
    p.add_argument("--member", help="eigene member_id (nur fuer --anwenden noetig)")
    p.add_argument("--von", required=True, metavar="JJJJ-MM-TT")
    p.add_argument("--bis", required=True, metavar="JJJJ-MM-TT")
    p.add_argument("--vorlage", metavar="DATEI",
                   help="Zuordnungsvorlage schreiben (Beschreibung -> Projekt-ID)")
    p.add_argument("--zuordnung", metavar="DATEI",
                   help="ausgefuellte Zuordnungsdatei")
    p.add_argument("--anwenden", action="store_true",
                   help="Aenderungen wirklich schreiben")
    a = p.parse_args()

    basis = os.environ.get("SOLIDTIME_URL", "").rstrip("/")
    token = os.environ.get("SOLIDTIME_TOKEN", "")
    if not basis or not token:
        sys.exit("SOLIDTIME_URL und SOLIDTIME_TOKEN muessen gesetzt sein.")

    st, pj = api("GET", f"{basis}/api/v1/organizations/{a.org}/projects?limit=200", token)
    if st != 200:
        sys.exit(f"Projekte nicht abrufbar: HTTP {st}")
    projekte = {x["id"]: x["name"].strip() for x in pj["data"]}

    print(f"Hole Eintraege {a.von} bis {a.bis} ...", file=sys.stderr)
    ent = hole_eintraege(basis, a.org, a.user, token, a.von, a.bis)
    ohne = sorted([r for r in ent if not r["project_id"]], key=lambda x: x["start"])

    print(f"\nEintraege gesamt: {len(ent)}")
    print(f"davon ohne Projekt: {len(ohne)}"
          f"  ({sum(r['duration'] or 0 for r in ohne) / 3600:.1f} h)\n")
    if not ohne:
        return

    namen = {n.lower(): i for i, n in projekte.items()}
    vorschlag = {}
    for r in ohne:
        b = (r["description"] or "").strip()
        genau = namen.get(b.lower())
        aehnlich = [i for i, n in projekte.items()
                    if b and (b.lower() in n.lower() or n.lower() in b.lower())]
        ziel = genau or (aehnlich[0] if len(aehnlich) == 1 else None)
        hinweis = ("= " + projekte[ziel]) if ziel else (
            "? mehrdeutig: " + ", ".join(projekte[i] for i in aehnlich[:3])
            if aehnlich else "? kein Treffer")
        print(f"  {r['start'][:16].replace('T', ' ')}  {hms(r['duration']):>6}"
              f"  {b[:38]:38s}  {hinweis}")
        if b:
            vorschlag.setdefault(b, ziel)

    if a.vorlage:
        json.dump(vorschlag, open(a.vorlage, "w"), indent=2, ensure_ascii=False)
        print(f"\nVorlage geschrieben: {a.vorlage}")
        print("Bitte pruefen. null-Werte werden uebersprungen, nicht geraten.")
        return

    if not a.anwenden:
        print("\nNur gelesen. Zum Schreiben: --zuordnung DATEI --anwenden")
        return

    if not a.zuordnung or not a.member:
        sys.exit("--anwenden verlangt --zuordnung und --member.")

    zuord = json.load(open(a.zuordnung))
    sicherung = a.zuordnung + ".vorher.json"
    json.dump(ohne, open(sicherung, "w"), indent=2, ensure_ascii=False)
    print(f"\nIst-Zustand gesichert: {sicherung}\n")

    ok = uebersprungen = fehler = 0
    for r in ohne:
        ziel = zuord.get((r["description"] or "").strip())
        if not ziel:
            uebersprungen += 1
            continue
        # Alle Felder mitgeben - ein PUT ersetzt den Datensatz, ein Teil-Update
        # wuerde Beschreibung, Tags und billable leeren.
        body = {
            "member_id": a.member,
            "start": r["start"],
            "end": r["end"],
            "project_id": ziel,
            "task_id": r.get("task_id"),
            "description": r.get("description") or "",
            "billable": bool(r.get("billable")),
            "tags": r.get("tags") or [],
        }
        st, err = api("PUT",
                      f"{basis}/api/v1/organizations/{a.org}/time-entries/{r['id']}",
                      token, body)
        if st == 200:
            ok += 1
            print(f"  200  {r['start'][:16]}  -> {projekte.get(ziel, ziel)}")
        else:
            fehler += 1
            print(f"  {st}  {r['start'][:16]}  {err}")

    print(f"\ngeaendert: {ok}, uebersprungen: {uebersprungen}, fehlgeschlagen: {fehler}")


if __name__ == "__main__":
    main()
