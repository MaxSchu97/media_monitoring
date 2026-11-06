#!/usr/bin/env python3
"""
Bereinigung der Teaser-Daten als Vorstufe für die Themen-Analyse (NMF / PPMI / Clustering).

Eingabe:  ../snapshot-pilot/data/teasers/<zeitung>/<JJJJ-MM>.csv  (eine Zeile = ein Teaser in einem Snapshot)
Ausgabe:  output/appearances.csv   alle Auftritte (Stunde × Position), für Prominenz-Auswertungen
          output/articles.csv      jeder Artikel genau einmal, mit bereinigtem Text, fürs Themen-Lernen
          output/title_history.csv alle Überschriften-Versionen von Artikeln, deren Titel sich geändert hat

Aufruf (aus dem Repo-Hauptordner):
    pip install -r analysis/requirements.txt
    python3 analysis/clean.py

Die Schritte entsprechen der Checkliste:
  A. Zeilen-Filter: Promo-Links, wiederkehrende Nicht-Artikel, englische Überschriften
  B. Titel säubern: Rubrik-Präfix abtrennen, lemmatisieren, Stoppwörter entfernen
  C. Zwei Tabellen: Artikel einmalig (Themen lernen) vs. alle Auftritte (Prominenz)
"""

import glob
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import spacy

BASE_DIR = Path(__file__).resolve().parent
TEASER_GLOB = str(BASE_DIR.parent / "snapshot-pilot" / "data" / "teasers" / "*" / "*.csv")
OUT_DIR = BASE_DIR / "output"

# --- A1: Links, die keine redaktionellen Nachrichtenartikel sind -----------------------------
# Treffer irgendwo im URL-Pfad, z. B. https://www.welt.de/kaufberatung/... oder /podcast/...
PROMO_URL = re.compile(
    r"/(kaufberatung|produkte|shop|angebote?|gutschein|advertorial|anzeige|podcasts?|"
    r"newsletter|abo|plus/abo|spiele|raetsel|rätsel|horoskop)(/|$|-)",
    re.IGNORECASE,
)

# --- A2: wiederkehrende Nicht-Artikel ----------------------------------------------------------
# Titel, die (fast) in jedem Snapshot einer Zeitung auftauchen, sind Navigation/Service.
BOILERPLATE_SHARE = 0.8       # Titel in > 80 % der Snapshots einer Zeitung = Boilerplate
BOILERPLATE_MIN_SNAPSHOTS = 10  # Regel erst anwenden, wenn genug Snapshots da sind
# Bekannte Fälle, die schon jetzt (mit wenigen Snapshots) raus sollen:
BOILERPLATE_TITLES = {
    "tagesschau in 100 sekunden",
    "alle artikel zu diesem thema",
    "ihr tägliches extra bei spiegel+",
}

# --- A3: englische Überschriften erkennen ------------------------------------------------------
# Einfache Heuristik: mindestens 2 typisch englische Funktionswörter im Titel.
EN_WORDS = {"the", "and", "of", "to", "is", "for", "with", "why", "how", "what", "are", "a", "in", "on"}

# --- B4: Rubrik-Präfixe ------------------------------------------------------------------------
# Titel haben oft die Form "Präfix : eigentliche Überschrift" (FAZ, SZ, Welt).
# Steht im Präfix ein reines Format-Label, wird es in die Spalte "label" verschoben.
# Andere Präfixe (z. B. FAZ "Kongress-Untersuchungen") tragen Themen-Info und bleiben im Text.
KICKER = re.compile(r"^\s*(.{0,60}?)\s+:\s+(.+)$")
FORMAT_LABELS = {
    "meinung", "kommentar", "kolumne", "analyse", "interview", "podcast", "live", "liveblog",
    "eilmeldung", "exklusiv", "ressort", "reportage", "essay", "gastbeitrag", "video", "quiz",
}
# Label direkt am Titelanfang ohne Doppelpunkt, z. B. Spiegel "Eilmeldung Trumps neuer Stabschef ..."
LEADING_LABEL = re.compile(r"^(eilmeldung|exklusiv|liveblog|live|meinung)\s+", re.IGNORECASE)

# Anhängsel, die nicht zur Überschrift gehören (v. a. Spiegel):
#   "... Eine Kolumne von Hasnain Kazim 5 Min Zur Merkliste hinzufügen" -> "..."
NOISE_PATTERNS = [
    re.compile(r"\s*Zur Merkliste hinzufügen\s*$"),
    re.compile(r"\s*\d+\s*Min\s*$"),
    # Autorenzeile: "Ein Kommentar von ...", "Der SPIEGEL-Leitartikel von ..." bis zum Ende
    re.compile(r"\s*(Ein|Eine|Der|Die|Das)\s+[\wÄÖÜäöüß-]*\s*(Kommentar|Kolumne|Leitartikel|Analyse|"
               r"Essay|Interview|Gastbeitrag|Podcast|Newsletter)\s+von\s+.+$"),
    # "... Von Christoph Schult" am Ende: "Von" + 1-4 großgeschriebene Namenswörter
    # auch mehrere Autoren: "Von Felix Dachsel, Andreas Niesmann und Anna Reimann"
    re.compile(r"\s+Von\s+(?:[A-ZÄÖÜ][\wäöüß.-]+,?\s*){1,4}(?:(?:und\s+)?(?:[A-ZÄÖÜ][\wäöüß.-]+,?\s*){1,4}){0,4}$"),
]
BULLET = re.compile(r"^[\s•·|–-]+")

# --- B6: eigene Stoppwörter (zusätzlich zur spaCy-Liste) ----------------------------------------
# Wörter, die überall vorkommen und kein Thema anzeigen. Liste wächst mit der Zeit.
EXTRA_STOPWORDS = {
    "neu", "zwei", "drei", "sagen", "jetzt", "mehr", "geben", "gehen", "kommen", "machen",
    "sollen", "wollen", "lassen", "sehen", "stehen", "bleiben", "werden", "heute", "immer",
    "erst", "wieder", "schon", "beim", "ganz", "warum", "wer", "was", "wie", "wo",
}

# spaCy nur mit dem Nötigsten laden (Parser/NER brauchen wir nicht, das spart viel Zeit)
NLP = spacy.load("de_core_news_sm", disable=["parser", "ner"])
STOPWORDS = NLP.Defaults.stop_words | EXTRA_STOPWORDS


def normalize_url(url: str) -> str:
    """URL ohne ?query und #fragment, damit Tracking-Parameter keinen 'neuen' Artikel erzeugen."""
    parts = urlsplit(str(url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def split_kicker(title: str) -> tuple[str, str]:
    """
    Trennt Format-Labels vom Titel.
    Beispiele:
      "Meinung : Donald Trump hat sein Gespür ..."  -> ("meinung", "Donald Trump hat sein Gespür ...")
      "Kongress-Untersuchungen : Die Demokraten ..." -> ("", "Kongress-Untersuchungen Die Demokraten ...")
      ": Warum in Mississippi ..."                   -> ("", "Warum in Mississippi ...")
    """
    title = str(title).strip()
    # Autorenzeilen, Lesezeit, "Merkliste" entfernen (mehrmals, weil sie hintereinander stehen)
    for _ in range(3):
        for pat in NOISE_PATTERNS:
            title = pat.sub("", title).strip()
    label = ""
    m = KICKER.match(title)
    if m:
        kicker, rest = m.group(1).strip(), m.group(2).strip()
        # "Deutschland Liveblog" -> letztes Wort "liveblog" ist das Format-Label
        words = kicker.lower().split()
        if kicker.lower().startswith("the atlantic"):
            # SZ übernimmt Texte von "The Atlantic": Partner-Inhalt als Label, nicht als Thema
            label = "the atlantic"
            title = rest
        elif words and words[-1] in FORMAT_LABELS:
            label = words[-1]
            # Rest des Präfixes ("Deutschland") ist Themen-Info und bleibt im Text
            topic_part = " ".join(kicker.split()[:-1])
            title = f"{topic_part} {rest}".strip()
        else:
            title = f"{kicker} {rest}".strip()
    elif title.startswith(":"):
        title = title.lstrip(": ").strip()   # SZ: leeres Präfix
    m2 = LEADING_LABEL.match(title)
    if m2 and not label:
        label = m2.group(1).lower()
        title = title[m2.end():].strip()
    title = BULLET.sub("", title).strip()   # Spiegel: "meinung • Antisemitismusvorwürfe ..."
    return label, title


def is_english(title: str) -> bool:
    """True, wenn mindestens 2 typisch englische Funktionswörter vorkommen."""
    words = re.findall(r"[a-z]+", title.lower())
    return sum(w in EN_WORDS for w in words) >= 2


def lemmatize(texts: list[str]) -> list[str]:
    """
    Titel -> bereinigte Token-Folge (Leerzeichen-getrennt), z. B.
      "Trumps neuer Stabschef – Miller folgt auf Wiles" -> "trump stabschef miller folgen wiles"
    """
    out = []
    for doc in NLP.pipe(texts, batch_size=256):
        tokens = []
        for tok in doc:
            if tok.is_punct or tok.is_space:
                continue
            # Eigennamen kennt das kleine Modell schlecht ("Wiles" -> "wile"), daher Originalform
            lemma = (tok.text if tok.pos_ == "PROPN" else tok.lemma_).lower().strip()
            # Unbekannte Wörter "lemmatisiert" das Modell oft nur durch Abschneiden des s
            # ("Wiles" -> "wile"). Dann Originalform behalten; echte Genitive fängt der
            # Merge-Schritt unten ab ("krawalls" -> "krawall", falls "krawall" vorkommt).
            if tok.text.lower().endswith("s") and lemma == tok.text.lower()[:-1]:
                lemma = tok.text.lower()
            # Zahlen nur behalten, wenn sie an einem Wort hängen ("1,5-grad"), nicht "2026" allein
            if not re.search(r"[a-zäöüß]", lemma):
                continue
            if len(lemma) < 3 or lemma in STOPWORDS:
                continue
            tokens.append(lemma)
        out.append(tokens)
    # Genitiv-s bei Namen vereinheitlichen: "trumps" -> "trump", aber nur wenn "trump" auch
    # allein im Korpus vorkommt ("wiles" bleibt "wiles", weil es kein "wile" gibt)
    vocab = {t for toks in out for t in toks}
    merge = {t: t[:-1] for t in vocab if t.endswith("s") and len(t) > 4 and t[:-1] in vocab}
    return [" ".join(merge.get(t, t) for t in toks) for toks in out]


def main() -> None:
    files = sorted(glob.glob(TEASER_GLOB))
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    n_start = len(df)
    df["url"] = df["url"].map(normalize_url)
    stats = {}  # wie viele Zeilen welcher Filter entfernt, für die Ausgabe am Ende

    # A1: Promo/Commerce/Service-Links
    promo = df["url"].map(lambda u: bool(PROMO_URL.search(u)))
    stats["promo_url"] = int(promo.sum())
    df = df[~promo]

    # A2: wiederkehrende Nicht-Artikel (bekannte Titel + "in > 80 % der Snapshots")
    title_key = df["title"].str.lower().str.strip()
    known = title_key.isin(BOILERPLATE_TITLES)
    n_snaps = df.groupby("source")["snapshot_utc"].transform("nunique")
    share = df.groupby(["source", title_key])["snapshot_utc"].transform("nunique") / n_snaps
    recurring = (n_snaps >= BOILERPLATE_MIN_SNAPSHOTS) & (share > BOILERPLATE_SHARE)
    stats["boilerplate"] = int((known | recurring).sum())
    df = df[~(known | recurring)].copy()

    # B4: Format-Label abtrennen
    split = df["title"].map(split_kicker)
    df["label"] = split.map(lambda x: x[0])
    df["title_clean"] = split.map(lambda x: x[1])

    # A3: Sprache markieren (englische Zeilen bleiben in appearances, fliegen aber aus articles)
    df["lang"] = df["title_clean"].map(lambda t: "en" if is_english(t) else "de")

    # C9: appearances = alle Auftritte, für Prominenz (Stunde × Position)
    df = df.sort_values(["source", "snapshot_utc", "position"])
    appearances = df[["snapshot_utc", "source", "position", "heading_level", "has_image",
                      "container", "occurrences", "label", "lang", "url"]]

    # C10: Überschriften-Historie (nur Artikel, deren Titel sich im Lauf der Zeit geändert hat)
    versions = df.drop_duplicates(["url", "title"])[["url", "source", "snapshot_utc", "title"]]
    changed = versions["url"].duplicated(keep=False)
    title_history = versions[changed].sort_values(["url", "snapshot_utc"])

    # C8: articles = jeder Artikel einmal, mit dem NEUESTEN Titel
    grp = df.groupby("url")
    articles = grp.agg(
        source=("source", "first"),
        first_seen=("snapshot_utc", "min"),
        last_seen=("snapshot_utc", "max"),
        n_snapshots=("snapshot_utc", "nunique"),   # wie viele Stunden auf der Startseite
        best_position=("position", "min"),         # höchste Platzierung (1 = ganz oben)
        n_title_versions=("title", "nunique"),
    ).reset_index()
    latest = df.sort_values("snapshot_utc").groupby("url").last()
    articles = articles.join(latest[["title", "title_clean", "label", "lang"]], on="url")
    articles = articles[articles["lang"] == "de"].copy()

    # B5-7: lemmatisieren + Stoppwörter, nur auf den einmaligen Artikeln (spart Rechenzeit)
    articles["text"] = lemmatize(articles["title_clean"].tolist())
    articles = articles[articles["text"].str.len() > 0]

    OUT_DIR.mkdir(exist_ok=True)
    appearances.to_csv(OUT_DIR / "appearances.csv", index=False)
    articles.to_csv(OUT_DIR / "articles.csv", index=False)
    title_history.to_csv(OUT_DIR / "title_history.csv", index=False)

    print(f"Eingelesen:            {n_start} Teaser-Zeilen aus {len(files)} Dateien")
    print(f"  entfernt Promo-URL:  {stats['promo_url']}")
    print(f"  entfernt Boilerplate:{stats['boilerplate']:>5}")
    print(f"appearances.csv:       {len(appearances)} Zeilen")
    print(f"articles.csv:          {len(articles)} einmalige deutsche Artikel")
    print(f"  davon mit Label:     {(articles['label'] != '').sum()}  {articles['label'].value_counts().to_dict()}")
    print(f"  englisch entfernt:   {(df.drop_duplicates('url')['lang'] == 'en').sum()}")
    print(f"title_history.csv:     {title_history['url'].nunique()} Artikel mit geändertem Titel")


if __name__ == "__main__":
    main()
