# 6 — Die Solidtime-API

[← Kapitel 5](05-nodered.md) · [Übersicht](../README.md)

Alle Angaben hier wurden **gegen eine laufende Instanz geprüft**, nicht aus der
Dokumentation abgeschrieben. Das ist wichtig, weil die mitgelieferte
`openapi.json` an mehreren Stellen nicht stimmt.

Basis: `http://<host>:8000/api/v1`
Header: `Authorization: Bearer <token>`, `Accept: application/json`

## Die Aufrufe

| Zweck | Aufruf | Erfolg |
|---|---|---|
| Laufender Eintrag | `GET /organizations/{org}/time-entries?active=true` | 200 |
| Einträge ab Datum | `GET /organizations/{org}/time-entries?start=<ISO>&user_id=<uid>` | 200 |
| Starten | `POST /organizations/{org}/time-entries` | 201 |
| Stoppen | `PUT /organizations/{org}/time-entries/{id}` | 200 |
| Löschen | `DELETE /organizations/{org}/time-entries/{id}` | 204 |
| Projekte | `GET /organizations/{org}/projects?limit=200` | 200 |

## Vier Fallen

### 1. Der Pfad heißt `organizations`, im Plural

Die `openapi.json` nennt `/v1/organization/{organization}/time-entries` — im
**Singular**. Dieser Pfad liefert 404. Richtig ist `organizations`.

### 2. Schreibend braucht es `member_id`, nicht `user_id`

Lesend liefert die API `user_id` in jedem Eintrag zurück. Schickt man dieselbe
Kennung beim Schreiben, kommt:

```
HTTP 422  {"message":"The member id field is required."}
```

`member_id` ist die Mitgliedschaft einer Person **in einer bestimmten
Organisation**. Wer in zwei Organisationen ist, hat eine `user_id`, aber zwei
`member_id`. Beim Lesen ist die Person gemeint, beim Schreiben die
Mitgliedschaft.

### 3. `after` und `before` werden ignoriert

Die `openapi.json` dokumentiert beide als Datumsfilter. Die Instanz **ignoriert
sie stillschweigend** und liefert die ungefilterte Liste — was besonders
unangenehm ist, weil kein Fehler auftritt. Man bekommt plausibel aussehende
Daten, die schlicht falsch sind.

Was tatsächlich wirkt:

| Parameter | Wirkung |
|---|---|
| `start` | Untergrenze, **größer oder gleich** |
| `end` | Obergrenze |

### 4. Blättern gibt es nicht

- `page` wird ignoriert — jede „Seite" liefert dieselben Datensätze
- `limit` ist hart gedeckelt: `The limit field must not be greater than 500.`
- sortiert wird **absteigend** nach `start`

Wer mehr als 500 Einträge braucht, muss über Zeitfenster gehen:

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json' \
  "$BASE/organizations/$ORG/time-entries?limit=500&user_id=$UID&start=2025-03-01T00:00:00Z&end=2025-04-01T00:00:00Z"
```

Monatsfenster funktionieren in der Praxis gut. Ergebnisse anschließend über die
`id` deduplizieren, weil sich Fenster an den Rändern überlappen können.

## Die eigenen IDs ermitteln

### Organisationen und `member_id`

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json' \
  "$BASE/users/me/memberships" | python3 -m json.tool
```

Liefert je Organisation `organization.id`, `organization.name` und die eigene
`membership.id` — das ist die gesuchte `member_id`.

### Eigene `user_id`

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json' \
  "$BASE/users/me" | python3 -m json.tool
```

### Projekte

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json' \
  "$BASE/organizations/$ORG/projects?limit=200" \
| python3 -c "
import sys, json
for p in sorted(json.load(sys.stdin)['data'], key=lambda x: x['name'].lower()):
    print(p['id'], '|', p['name'])
"
```

> **Namen sind nicht eindeutig.** In der hier verwendeten Instanz gab es zwei
> Projekte namens `Projekt G` und zwei namens `Projekt H`. Wer nach Namen zuordnet,
> trifft womöglich das falsche.
>
> Ein brauchbares Kriterium ist die Buchungshistorie: Zählt man die Einträge je
> Projekt-ID, ist das mit 131 Buchungen offensichtlich das gemeinte, das mit
> null Buchungen eine Karteileiche. Wo auch das nicht hilft: nachfragen, nicht
> raten.

## Beispiele

### Laufenden Eintrag holen

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json' \
  "$BASE/organizations/$ORG/time-entries?active=true"
```

```json
{
  "data": [{
    "id": "…",
    "start": "2026-08-16T07:11:29Z",
    "end": null,
    "duration": 0,
    "description": "Beispiel",
    "project_id": null,
    "user_id": "…",
    "billable": false,
    "type": "work"
  }],
  "meta": { "total": 1 }
}
```

`project_id: null` ist möglich und völlig regulär: ein Eintrag ohne Projekt.
IceDeck kann ihn keiner Taste zuordnen (`active_key` bleibt `null`), zählt ihn
aber in der Tagessumme mit.

### Timer starten

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  "$BASE/organizations/$ORG/time-entries" \
  -d '{
    "member_id":   "'"$MEMBER"'",
    "start":       "2026-08-16T09:00:00Z",
    "end":         null,
    "project_id":  "'"$PROJEKT"'",
    "description": "Projekt A",
    "billable":    false
  }'
```

Erwartet: **201**. `end: null` markiert den Eintrag als laufend. Zeitstempel
sekundengenau in UTC mit `Z`.

### Timer stoppen

```bash
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  "$BASE/organizations/$ORG/time-entries/$ID" \
  -d '{
    "member_id": "'"$MEMBER"'",
    "start":     "2026-08-16T09:00:00Z",
    "end":       "2026-08-16T09:30:00Z"
  }'
```

Erwartet: **200**, `duration` wird serverseitig berechnet.

> **`start` muss mitgeschickt werden**, obwohl sich daran nichts ändert. Ein
> `PUT` ohne `start` wird abgewiesen.

### Einen Eintrag ändern, ohne etwas zu verlieren

`PUT` ersetzt den Datensatz. Wer nur `project_id` schickt, **leert damit
Beschreibung, Tags und `billable`**. Also immer alle Felder mitgeben:

```bash
curl -s -X PUT … -d '{
  "member_id":   "…",
  "start":       "…",
  "end":         "…",
  "project_id":  "…",
  "task_id":     null,
  "description": "unveränderter Text",
  "billable":    false,
  "tags":        []
}'
```

Genau dieser Fall tritt beim nachträglichen Zuordnen von Projekten auf — siehe
[`tools/solidtime-audit.py`](../tools/solidtime-audit.py).

## Testen, ohne Schaden anzurichten

Der vollständige Zyklus lässt sich gefahrlos prüfen, wenn man hinterher
aufräumt:

1. `POST` mit `end: null` → 201, Eintrag läuft
2. `GET ?active=true` → findet ihn
3. `PUT` mit `end` → 200, Dauer berechnet
4. `DELETE` → 204, Eintrag weg

Sinnvoll ist eine eindeutige Beschreibung wie `__icedeck_test`, nach der man
anschließend suchen kann, um sicherzugehen, dass nichts übrig bleibt.

> **Zwei Vorsichtsmaßnahmen.** Ein Test-`POST` **stoppt einen bereits laufenden
> Timer**, wenn der Flow beteiligt ist — vorher fragen, ob gerade etwas läuft.
> Und in **allen** Organisationen aufräumen, nicht nur in der getesteten.

---

[Weiter: 7 — Fehlersuche →](07-fehlersuche.md)
