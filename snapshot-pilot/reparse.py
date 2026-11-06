#!/usr/bin/env python3
"""
Erzeugt alle Teaser-CSVs neu aus den gespeicherten Roh-HTMLs.

Wozu: Wenn die Teaser-Erkennung in snapshot.py verbessert wird, sollen auch die
alten Snapshots mit den neuen Regeln ausgewertet werden, damit alle Daten vergleichbar sind.

    python3 reparse.py
"""
import gzip
import json
import shutil

import snapshot as s

sources = {x["name"]: x for x in json.loads((s.BASE_DIR / "sources.json").read_text(encoding="utf-8"))}

# Alte CSVs komplett löschen, sie werden gleich neu geschrieben.
shutil.rmtree(s.DATA_DIR / "teasers", ignore_errors=True)

for raw in sorted((s.DATA_DIR / "raw").glob("*/*/*.html.gz")):
    name, day, hhmm = raw.parent.parent.name, raw.parent.name, raw.name[:4]
    if name not in sources:
        continue  # Zeitung wurde aus sources.json entfernt
    src = sources[name]
    # Dateiname 1646.html.gz am 2026-11-06 -> Zeitstempel 2026-11-06T16:46:00Z
    stamp = f"{day}T{hhmm[:2]}:{hhmm[2:]}:00Z"
    rows = s.extract_teasers(gzip.open(raw).read(), src["url"], name, stamp, src.get("scope", "main"))
    s.append_csv(s.DATA_DIR / "teasers" / name / f"{day[:7]}.csv", rows)
    print(f"{raw.relative_to(s.DATA_DIR)}: {len(rows)} Teaser")
