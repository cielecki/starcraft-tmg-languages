#!/usr/bin/env python3
"""Generate the DEVELOPMENT FIXTURE segments JSONL for the Protoss P2P card sheet, page 0 (Adept),
from the original hardcoded MAP/ABILITIES that card_inplace.py used to carry inline.

This is ONLY a fixture — the real data/segments/<doc>.jsonl is produced by a separate translation
pipeline. The fixture lets card_inplace.py be developed/tested against the EXACT schema while
reproducing today's Adept output byte-for-byte.

Output: data/segments/StarCraft-Protoss-P2P-Card-Sheets-A4_EN.fixture.jsonl

Schema (one JSON object per line):
  {id, doc, page, kind(label|header|pill|cell|body), source_text(EN), target_text(PL),
   bold([[start,end],...] char ranges in target_text), status, notes}
Lookup contract (card_inplace.load_segments):
  - label/header/pill/cell : by (doc, source_text) -> target_text
  - body                   : by id "<doc>:p<page>:ability:<block_index>" -> target_text + bold
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = "StarCraft-Protoss-P2P-Card-Sheets-A4_EN"
PAGE = 0

# ── The original hardcoded translation data (lifted verbatim from card_inplace.py @ 2703341) ──────
MAP = {
    "PROTOSS FACTION": "FRAKCJA PROTOSÓW", "UNIT CARDS": "KARTY JEDNOSTEK",
    "PROTOSS": "PROTOSI", "CORE": "PODSTAWOWA", "DAMAGE DEALER": "ZADAJĄCY OBRAŻENIA",
    "COMBAT ROLE:": "ROLA BOJOWA:", "ARMY SLOT:": "SLOT ARMII:",
    "CLOSE COMBAT": "WALKA WRĘCZ", "RANGED COMBAT": "WALKA DYST.",
    "COMBAT TAGS:": "CECHY BOJOWE:", "BIOLOGICAL, LIGHT, GROUND": "BIOLOGICZNY, LEKKI, NAZIEMNY",
    "COMBAT PHASE": "FAZA WALKI", "ASSAULT PHASE": "FAZA SZTURMU",
    "MOVEMENT PHASE": "FAZA RUCHU", "ANY PHASE": "DOWOLNA FAZA",
    "UPGRADE": "ULEPSZENIE", "U P G R A D E": "ULEPSZENIE",
    "ACTIVE": "AKTYWNA", "PASSIVE": "PASYWNA", "1 PE": "1 EP",
    "SIZE": "ROZMIAR", "HIT POINTS": "PKT ŻYCIA", "EVADE": "UNIK", "ARMOUR": "PANCERZ",
    "SPEED": "SZYBKOŚĆ", "SHIELD": "OSŁONA", "MODELS / SUPPLY": "MODELE / ZAOPATRZ.",
    "NAME": "NAZWA", "RNG": "ZAS", "Target": "Cel", "RoA": "SA", "Hit": "Traf",
    "Surge type": "Typ naw.", "S Dice": "K naw.", "Dmg": "Obr", "Keyword": "Słowo kl.",
    "STRIKE": "UDERZENIE", "GLAIVE STRIKE": "UDERZ. GLEWIĄ", "GLAIVE CANNON": "DZIAŁO GLEWII",
    "Ground": "Naziem.", "Light": "Lekki", "All": "Wsz.",
    "PIERCE Light (2)": "PRZEBICIE Lekki (2)", "ANTI-EVADE (1)": "ANTY-UNIK (1)", "FOR": "DLA",
    "RESONATING GLAVES:": "REZONUJĄCE GLEWIE:", "GUIDANCE:": "NAPROWADZANIE:",
    "PSIONIC TRANSFER:": "PSIONICZNY TRANSFER:", "PSIONIC PRESENCE:": "PSIONICZNA OBECNOŚĆ:",
}

# Bodies are listed in card_inplace's detect_abilities reading order:
#   index 0,1 = front card (rot 180, top): PSIONIC TRANSFER, PSIONIC PRESENCE
#   index 2,3 = back  card (rot 0,  bottom-left->right): RESONATING GLAVES, GUIDANCE
# (detect_abilities sorts front-first, then by y, then by x — this matches.)
BODIES = [
    ("PSIONIC TRANSFER",                                                   # ability 0 (front, left/upper)
     "Umieść żeton Cienia całkowicie w promieniu 12\" od dowolnego modelu tej jednostki. "
     "Na końcu rundy gracz kontrolujący może ustawić wszystkie modele tej jednostki w spójności, "
     "traktując żeton Cienia jako model prowadzący. Żeton Cienia ma PRZEMIESZCZENIE."),
    ("PSIONIC PRESENCE",                                                   # ability 1 (front, lower)
     "Wszystkie bronie sojuszniczych jednostek atakujące wrogą jednostkę w promieniu 4\" "
     "od żetonu Cienia zyskują PRECYZJĘ (1)."),
    ("RESONATING GLAVES",                                                  # ability 2 (back, left)
     "Działo glewii tej jednostki zyskuje WZMOCNIENIE RoA (1)."),
    ("GUIDANCE",                                                           # ability 3 (back, right)
     "Broń dystansowa Działa glewii tej jednostki zyskuje ANTY-UNIK (2)."),
]

# The KEYWORDS list card_inplace used for auto-bold; we PRE-COMPUTE the resulting char ranges so the
# fixture carries explicit `bold` (the real schema), and the engine renders identically.
KEYWORDS = [
    'całkowicie w promieniu 12"', 'w promieniu 4"', 'WZMOCNIENIE RoA (1)', 'ANTY-UNIK (2)',
    'model prowadzący', 'Na końcu rundy', 'PRECYZJĘ (1)', 'Działo glewii', 'Działa glewii',
    'PRZEMIESZCZENIE', 'sojuszniczych', 'spójności', 'bronie', 'wrogą', 'Cienia', 'Cień',
]

# Source EN bodies (only used as `source_text` for the body rows; not load-bearing for rendering).
SOURCE_BODIES = {
    "PSIONIC TRANSFER": "Place a Shadow token completely within 12\" of any model in this Unit. "
        "At the end of the round, the controlling player may place all models in this Unit in "
        "coherency, treating the Shadow token as the leader model. The Shadow token has DISPLACEMENT.",
    "PSIONIC PRESENCE": "All allied Units' weapons attacking an enemy Unit within 4\" of the Shadow "
        "token gain PRECISION (1).",
    "RESONATING GLAVES": "This Unit's Glaive Cannon gains BUFF RoA (1).",
    "GUIDANCE": "This Unit's ranged Glaive Cannon weapon gains ANTI-EVADE (2).",
}


def bold_ranges(text):
    """Reproduce card_inplace.auto_bold's keyword bolding as explicit [start,end) char ranges,
    using the SAME placeholder pass (longest-first, non-overlapping, first occurrence wins)."""
    sentinel_text = text
    placed = []  # (placeholder_index, keyword)
    for kw in KEYWORDS:
        if kw in sentinel_text:
            sentinel_text = sentinel_text.replace(kw, f"\x00{len(placed)}\x01")
            placed.append(kw)
    # Walk sentinel_text, mapping placeholders back to ranges in the ORIGINAL text positions.
    ranges, out_pos = [], 0
    i = 0
    while i < len(sentinel_text):
        ch = sentinel_text[i]
        if ch == "\x00":
            j = sentinel_text.index("\x01", i)
            idx = int(sentinel_text[i+1:j])
            kw = placed[idx]
            ranges.append([out_pos, out_pos+len(kw)])
            out_pos += len(kw)
            i = j+1
        else:
            out_pos += 1
            i += 1
    return ranges


# Classify each MAP key into a schema kind.
PILLS = {"ACTIVE", "PASSIVE", "1 PE"}
HEADER_KEYS = {"RESONATING GLAVES:", "GUIDANCE:", "PSIONIC TRANSFER:", "PSIONIC PRESENCE:"}
# Attack-table column headers + cell values.
CELL_KEYS = {"NAME", "RNG", "Target", "RoA", "Hit", "Surge type", "S Dice", "Dmg", "Keyword",
             "STRIKE", "GLAIVE STRIKE", "GLAIVE CANNON", "Ground", "Light", "All",
             "PIERCE Light (2)", "ANTI-EVADE (1)", "FOR"}


def kind_of(en):
    if en in PILLS:
        return "pill"
    if en in HEADER_KEYS:
        return "header"
    if en in CELL_KEYS:
        return "cell"
    return "label"


def main():
    rows = []
    n = 0
    for en, pl in MAP.items():
        k = kind_of(en)
        rows.append({"id": f"{DOC}:p{PAGE}:{k}:{n}", "doc": DOC, "page": PAGE, "kind": k,
                     "source_text": en, "target_text": pl, "bold": [],
                     "status": "fixture", "notes": "generated from hardcoded MAP @ 2703341"})
        n += 1
    for idx, (hdr, pl) in enumerate(BODIES):
        rows.append({"id": f"{DOC}:p{PAGE}:ability:{idx}", "doc": DOC, "page": PAGE, "kind": "body",
                     "source_text": SOURCE_BODIES.get(hdr, ""), "target_text": pl,
                     "bold": bold_ranges(pl), "status": "fixture",
                     "notes": f"ability '{hdr}'; bold ranges pre-computed from KEYWORDS auto-bold"})

    out = ROOT / "data/segments" / f"{DOC}.fixture.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} segments ({len(MAP)} labels + {len(BODIES)} bodies) -> {out}")


if __name__ == "__main__":
    main()
