#!/usr/bin/env python3
"""
Startseiten-Snapshot für das Medienbias-Monitoring (Pilot).

Was das Skript bei jedem Aufruf macht:
  1. Liest die Liste der Zeitungen aus sources.json.
  2. Prüft für jede Zeitung die robots.txt. Ist der Abruf dort verboten, wird übersprungen.
  3. Lädt die Startseite herunter.
  4. Speichert das Roh-HTML gezippt, damit man später mit besseren Regeln neu auswerten kann:
       data/raw/<zeitung>/<JJJJ-MM-TT>/<HHMM>.html.gz
  5. Liest aus dem HTML alle Teaser (verlinkte Überschriften) mit ihren Sichtbarkeits-Signalen
     und hängt sie an eine Monats-CSV an:
       data/teasers/<zeitung>/<JJJJ-MM>.csv

Das Skript hängt nicht von GitHub ab. Es läuft genauso per cron auf einem Mac,
einem Raspberry Pi oder einer Oracle-VM:
    python3 snapshot.py
"""

import csv
import gzip
import json
import sys
import time
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Ordner, in dem dieses Skript liegt. Alle Pfade werden relativ dazu gebaut,
# damit es egal ist, aus welchem Verzeichnis man das Skript startet.
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Ehrlicher User-Agent: Die Redaktion sieht in ihren Logs, wer abruft und warum.
USER_AGENT = (
    "MedienbiasMonitor/0.1 (Forschungs-Pilot; stuendlicher Startseiten-Snapshot; "
    "+https://github.com/MaxSchu97)"
)

# Teaser-Texte kürzer als das sind meist Menüpunkte ("Politik", "Login") und keine Artikel.
MIN_TEASER_CHARS = 25

CSV_FIELDS = [
    "snapshot_utc",   # Zeitpunkt des Abrufs, z. B. 2026-11-05T18:07:12Z
    "source",         # Kürzel der Zeitung, z. B. tagesschau
    "position",       # Reihenfolge im HTML: 1 = ganz oben
    "heading_level",  # 1-6 für h1-h6, leer wenn der Teaser in keiner Überschrift steht
    "has_image",      # 1, wenn im Teaser-Container ein Bild steckt
    "container",      # Tag + CSS-Klassen des umgebenden Blocks (Hinweis auf Hero, Liste, Kachel)
    "occurrences",    # wie oft derselbe Link auf der Seite vorkommt
    "title",          # sichtbarer Teaser-Text
    "url",            # absoluter Link zum Artikel
]


def allowed_by_robots(url: str) -> bool:
    """Fragt die robots.txt der Domain, ob unser User-Agent diese URL abrufen darf."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    try:
        resp = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=20)
    except requests.RequestException as exc:
        # Ohne robots.txt-Antwort rufen wir lieber nicht ab.
        print(f"  robots.txt nicht erreichbar ({exc}), überspringe.")
        return False
    if resp.status_code == 404:
        return True  # keine robots.txt = keine Einschränkung
    if resp.status_code >= 400:
        print(f"  robots.txt antwortet mit HTTP {resp.status_code}, überspringe.")
        return False
    rp.parse(resp.text.splitlines())
    return rp.can_fetch(USER_AGENT, url)


def heading_level(link) -> str:
    """Überschriftsebene eines Links: steckt er in einem <h2>, oder steckt ein <h3> in ihm?"""
    # Fall 1: <h2><a href="...">Titel</a></h2>
    parent_heading = link.find_parent(["h1", "h2", "h3", "h4", "h5", "h6"])
    if parent_heading:
        return parent_heading.name[1]
    # Fall 2: <a href="..."><h3>Titel</h3></a>
    child_heading = link.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    if child_heading:
        return child_heading.name[1]
    return ""


def teaser_container(link):
    """Nächster umgebender Block, der typischerweise einen Teaser umschließt."""
    return link.find_parent(["article", "li", "section", "div"])


def describe(tag) -> str:
    """Kurzbeschreibung eines Containers, z. B. 'article.teaser.teaser--hero'."""
    if tag is None:
        return ""
    classes = tag.get("class") or []
    return ".".join([tag.name] + classes[:3])


def extract_teasers(html: bytes, page_url: str, source: str, snapshot_utc: str) -> list[dict]:
    """Findet alle Artikel-Links der Startseite und sammelt pro Link die Sichtbarkeits-Signale."""
    soup = BeautifulSoup(html, "html.parser")
    home_host = urlparse(page_url).netloc

    rows: dict[str, dict] = {}  # URL -> Zeile, damit jeder Artikel nur einmal zählt
    position = 0
    for link in soup.find_all("a", href=True):
        url = urljoin(page_url, link["href"]).split("#")[0]
        if urlparse(url).netloc != home_host:
            continue  # externe Links (Werbung, Social Media) ignorieren
        title = " ".join(link.get_text(" ", strip=True).split())
        if len(title) < MIN_TEASER_CHARS:
            continue

        if url in rows:
            # Gleicher Artikel ein zweites Mal (z. B. Bild-Link + Text-Link):
            # Position bleibt die erste, aber wir merken uns die Mehrfachnennung
            # und übernehmen das stärkere Signal (höhere Überschrift, Bild).
            row = rows[url]
            row["occurrences"] += 1
            lvl = heading_level(link)
            if lvl and (not row["heading_level"] or lvl < row["heading_level"]):
                row["heading_level"] = lvl
            continue

        position += 1
        container = teaser_container(link)
        has_image = bool(link.find("img") or (container and container.find(["img", "picture"])))
        rows[url] = {
            "snapshot_utc": snapshot_utc,
            "source": source,
            "position": position,
            "heading_level": heading_level(link),
            "has_image": int(has_image),
            "container": describe(container),
            "occurrences": 1,
            "title": title[:300],
            "url": url,
        }
    return list(rows.values())


def append_csv(path: Path, rows: list[dict]) -> None:
    """Hängt Zeilen an die Monats-CSV an und schreibt beim ersten Mal die Kopfzeile."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def snapshot_source(source: dict, now: datetime) -> bool:
    """Ein Snapshot für eine Zeitung. Gibt True zurück, wenn er geklappt hat."""
    name, url = source["name"], source["url"]
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{name}] {url}")

    if not allowed_by_robots(url):
        print("  laut robots.txt nicht erlaubt oder nicht prüfbar, kein Abruf.")
        return False

    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  Abruf fehlgeschlagen: {exc}")
        return False
    # Rohe Bytes statt resp.text: BeautifulSoup erkennt die Zeichenkodierung
    # selbst aus dem <meta charset>, sonst werden Umlaute bei manchen Servern zu "Ã¼".
    html = resp.content

    # Roh-HTML gezippt sichern (Faktor ca. 5-8 kleiner).
    raw_path = DATA_DIR / "raw" / name / now.strftime("%Y-%m-%d") / f"{now:%H%M}.html.gz"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(raw_path, "wb") as f:
        f.write(html)

    rows = extract_teasers(html, url, name, stamp)
    append_csv(DATA_DIR / "teasers" / name / f"{now:%Y-%m}.csv", rows)
    print(f"  {len(html) // 1024} KB HTML, {len(rows)} Teaser gespeichert.")
    return True


def main() -> int:
    sources = json.loads((BASE_DIR / "sources.json").read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    ok = 0
    for i, source in enumerate(sources):
        if i:
            time.sleep(2)  # kurze Pause zwischen den Verlagen, um höflich zu bleiben
        ok += snapshot_source(source, now)
    print(f"Fertig: {ok}/{len(sources)} Zeitungen erfolgreich.")
    # Exit-Code 1, wenn gar nichts geklappt hat. Dann wird der GitHub-Lauf rot und du bekommst eine Mail.
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
