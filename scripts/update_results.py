"""
Tour de France 2026 — automatic results updater.

Runs from GitHub Actions each evening in July. For every stage that has
finished, it reads the winner from ProCyclingStats, maps the name to the
exact spelling used in the app's rider list, and writes it into the same
Firestore document the app reads (tdf2026_results/main).

When the final stage (21) is done it also fills in the final yellow / green /
polka-dot / white jerseys, the GC podium, the "beat Pogačar?" outcome and
Pogačar's stage-win count. All of that is best-effort and wrapped so one
failure never stops the rest; the in-app Results desk (PIN 2468) stays as a
manual override for anything the bot gets wrong or can't read.
"""

import os
import json
import unicodedata

import firebase_admin
from firebase_admin import credentials, firestore

YEAR = 2026
RACE = f"race/tour-de-france/{YEAR}"

# Canonical spellings — these MUST match the dropdown values in index.html
# so that scoring (a simple lowercase compare) lines up.
RIDERS = [
    "Tadej Pogačar", "Jonas Vingegaard", "Remco Evenepoel", "Isaac del Toro",
    "Juan Ayuso", "Paul Seixas", "Florian Lipowitz", "Primož Roglič",
    "Tobias Johannessen", "Matteo Jorgenson", "Cian Uijtdebroeks",
    "Kévin Vauquelin", "Tom Pidcock", "Carlos Rodríguez", "Felix Gall",
    "Lenny Martínez", "Ben Healy", "Valentin Paret-Peintre", "Santiago Buitrago",
    "Michael Storer", "Mathieu van der Poel", "Julian Alaphilippe",
    "Marc Hirschi", "Neilson Powless", "Romain Grégoire", "Quinn Simmons",
    "Michael Matthews", "Tim Merlier", "Jonathan Milan", "Mads Pedersen",
    "Jasper Philipsen", "Paul Magnier", "Biniam Girmay", "Olav Kooij",
    "Bryan Coquard", "Søren Wærenskjold", "Kaden Groves", "Arnaud De Lie",
    "Dylan Groenewegen", "Jonas Abrahamsen", "Magnus Cort Nielsen",
]


def _strip(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def _tokens(s):
    return {tok for tok in _strip(s).replace(",", " ").split() if tok}


CANON = [(r, _tokens(r)) for r in RIDERS]
POGACAR = "Tadej Pogačar"


def to_canon(pcs_name):
    """Map a PCS name (often 'POGAČAR Tadej') to our canonical spelling."""
    if not pcs_name:
        return ""
    tk = _tokens(pcs_name)
    for name, ts in CANON:               # exact token-set match
        if ts == tk:
            return name
    for name, ts in CANON:               # one is a subset of the other
        if ts & tk and (ts <= tk or tk <= ts):
            return name
    # Not in our list (a random breakaway winner): best-effort First Last.
    parts = pcs_name.split()
    surnames = [p for p in parts if p.isupper()]
    firsts = [p for p in parts if not p.isupper()]
    ordered = firsts + [p.title() for p in surnames]
    return " ".join(ordered) if ordered else pcs_name.title()


def _winner_name(row):
    return row.get("rider_name") or row.get("rider") or ""


def stage_winner(n):
    try:
        from procyclingstats import Stage
        res = Stage(f"{RACE}/stage-{n}").results()
        if not res:
            return ""
        return to_canon(_winner_name(res[0]))
    except Exception as e:
        print(f"stage {n}: no result yet ({e})")
        return ""


def classification_top(path, count=1):
    """Return the top `count` riders of a final classification page."""
    try:
        from procyclingstats import Stage
        res = Stage(f"{RACE}/{path}").results()
        return [to_canon(_winner_name(r)) for r in res[:count]]
    except Exception as e:
        print(f"classification '{path}' not read ({e})")
        return []


def main():
    sa_raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")
    if not sa_raw:
        raise SystemExit("FIREBASE_SERVICE_ACCOUNT secret is missing.")
    cred = credentials.Certificate(json.loads(sa_raw))
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    # 1) Stage winners (the daily, reliable part)
    winners = {}
    for n in range(1, 22):
        w = stage_winner(n)
        if w:
            winners[str(n)] = w
            print(f"stage {n}: {w}")

    payload = {}
    if winners:
        payload["stageWinners"] = winners

    # 2) End of race: fill final classifications + tiebreak
    if winners.get("21"):
        gc = classification_top("gc", 3)
        if len(gc) >= 1:
            payload["yellow"] = gc[0]
            payload["beatPog"] = "no" if to_canon(POGACAR) == gc[0] else "yes"
        if len(gc) >= 3:
            payload["gc2"], payload["gc3"] = gc[1], gc[2]

        for field, path in (("green", "points"), ("polka", "kom"), ("white", "youth")):
            top = classification_top(path, 1)
            if top:
                payload[field] = top[0]

        payload["pogWins"] = sum(1 for v in winners.values() if v == to_canon(POGACAR))

    if payload:
        db.collection("tdf2026_results").document("main").set(payload, merge=True)
        print("written:", json.dumps(payload, ensure_ascii=False))
    else:
        print("nothing to write yet (no finished stages found)")


if __name__ == "__main__":
    main()
