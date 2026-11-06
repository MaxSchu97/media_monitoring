# Analyse

Auswertung der Startseiten-Snapshots aus `snapshot-pilot/data/`. Läuft lokal und nicht im stündlichen Workflow.

## Schritt 1: Bereinigung (`clean.py`)

```bash
pip install -r analysis/requirements.txt   # pandas, spaCy + deutsches Sprachmodell
python3 analysis/clean.py                  # schreibt nach analysis/output/ (nicht im Git)
```

| Datei | Eine Zeile = | Zweck |
|---|---|---|
| `output/articles.csv` | ein Artikel (einmalig, neuester Titel) | Themen lernen (NMF, PPMI, Clustering) |
| `output/appearances.csv` | ein Teaser in einem Snapshot | Prominenz (Stunde × Position) |
| `output/title_history.csv` | eine Überschriften-Version | geänderte Titel nachverfolgen |

Was entfernt bzw. umgebaut wird:
- **Promo/Service-Links** per URL (`/kaufberatung`, `/produkte`, `/podcast`, …)
- **Boilerplate-Teaser** („tagesschau in 100 Sekunden“, Titel in > 80 % aller Snapshots einer Zeitung)
- **Englische Überschriften** (bleiben in `appearances`, fehlen in `articles`)
- **Format-Labels** („Meinung : …“, „Eilmeldung …“) wandern in die Spalte `label`
- **Autorenzeilen, Lesezeit, „Zur Merkliste hinzufügen“** werden abgeschnitten
- **Text**: lemmatisiert (`Trumps → trump`), Stoppwörter raus → Spalte `text`

Beispiel `articles.csv`:

| source | label | title_clean | text |
|---|---|---|---|
| spiegel | eilmeldung | Trumps neuer Stabschef – Miller folgt auf Wiles | trump stabschef miller folgen wiles |
