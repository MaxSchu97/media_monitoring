# Startseiten-Snapshot (Pilot)

Speichert stündlich die Startseite einer Zeitung (tagesschau, Spiegel, Zeit, FAZ, SZ, Welt; siehe `sources.json`) und liest die Teaser
mit ihren Sichtbarkeits-Signalen aus (Position, Überschriftsebene, Bild, Container).

## Einrichten auf GitHub (einmalig, ca. 5 Minuten)

1. Repo: https://github.com/MaxSchu97/media_monitoring (Skript in `snapshot-pilot/`, Workflow in `.github/workflows/snapshot.yml`).
   **Öffentlich** = unbegrenzte Actions-Minuten. **Privat** = 2.000 Freiminuten/Monat
   (der Pilot braucht ca. 24 Läufe × 30 Tage × ~1 Min ≈ 720 Min).
2. Den Inhalt dieses Ordners hochladen bzw. pushen:
   ```bash
   cd snapshot-pilot                 # in diesen Ordner wechseln
   git init -b main                  # neues Git-Repo anlegen
   git add .                         # alle Dateien vormerken
   git commit -m "Snapshot-Pilot"    # ersten Commit erstellen
   git remote add origin https://github.com/MaxSchu97/medienbias-snapshots.git
   git push -u origin main           # hochladen
   ```
3. Im Repo auf **Actions** gehen, den Workflow „Startseiten-Snapshot“ wählen und
   **Run workflow** klicken. Nach ca. 1 Minute liegt ein neuer Commit mit `data/` im Repo.
4. Ab dann läuft er automatisch jede Stunde um xx:17 UTC (oft 5–30 Min. später).

## Weitere Zeitung hinzufügen

In `sources.json` einen Eintrag ergänzen, **vorher robots.txt und AGB prüfen**:
```json
{ "name": "spiegel", "url": "https://www.spiegel.de/" }
```

## Ausgabe

| Datei | Inhalt |
|---|---|
| `data/teasers/tagesschau/2026-11.csv` | eine Zeile pro Teaser und Snapshot |
| `data/raw/tagesschau/2026-11-05/1817.html.gz` | gezipptes Original-HTML zum späteren Neu-Auswerten |

Beispielzeile:
```
snapshot_utc,source,position,heading_level,has_image,container,occurrences,title,url
2026-11-05T18:17:40Z,tagesschau,1,2,1,article.teaser.teaser--xl,2,Koalition streitet über Haushalt,https://www.tagesschau.de/...
```

## Lokal oder auf einem anderen Server ausführen

```bash
pip install -r requirements.txt   # Abhängigkeiten installieren
python3 snapshot.py               # einen Snapshot machen
# per cron stündlich (crontab -e):
# 17 * * * * cd /pfad/zu/snapshot-pilot && python3 snapshot.py
```

## Bekannte Grenzen

- GitHub-Cron ist unpünktlich und kann bei Last einzelne Läufe auslassen.
- Bei öffentlichen Repos pausiert GitHub den Zeitplan nach 60 Tagen ohne Aktivität.
  Die stündlichen Daten-Commits zählen als Aktivität.
- Die Teaser-Erkennung ist generisch. Für belastbare Prominenz-Scores braucht jede
  Zeitung eigene, dokumentierte Regeln (siehe Projektbeschreibung, Abschnitt 6).
- Rohdaten wachsen um ca. 30–50 MB pro Zeitung und Monat. Bei mehr als 5 Zeitungen
  die Roh-HTMLs besser auslagern (z. B. Cloudflare R2).
