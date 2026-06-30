#!/usr/bin/env python3
"""Card localization by editing the original PDF in place — faithful version.

Principles learned from the visual-bug pass:
  - Redaction by a span's bbox can catch an OVERLAPPING neighbour (stat label rects overlap the
    big stat-value glyphs). So: redact what we replace, then reinsert EVERY removed span — the
    translated ones as PL, the collateral ones (e.g. stat numbers) as their original text.
  - Abilities are structured (name + colour-coded pills + wrapped body). Keep the pills on their
    coloured backgrounds (translate in place); reflow only the body sentence, with padding, and
    draw the header/pills ON TOP so the body never covers them.
  - The card prints double-sided: back is normal (dir(1,0)), front is 180deg (dir(-1,0)).

Note on shadows: the card's subtle text drop-shadows are part of the original ART (kept via
text-only redaction), so they stay correct. "Orphan" shadows only appear if text is deleted
without reinsertion (the stat-number regression) — collateral reinsertion prevents that.
"""
import sys, fitz
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FONT = "/System/Library/Fonts/Supplemental/Arial Narrow.ttf"

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
    # ability headers (kept in place; bodies reflow separately)
    "RESONATING GLAVES:": "REZONUJĄCE GLEWIE:", "GUIDANCE:": "NAPROWADZANIE:",
    "PSIONIC TRANSFER:": "PSIONICZNY TRANSFER:", "PSIONIC PRESENCE:": "PSIONICZNA OBECNOŚĆ:",
}

# Position-keyed overrides (round(x0),round(y0)) -> PL, for context-dependent grammar.
OVERRIDES = {(212, 543): "UDERZENIA"}  # "FOR STRIKE" -> "DLA UDERZENIA" (genitive)

# Ability bodies: redact the whole block rect, reflow the PL body into `body` (padded, clear of
# the header/pill line); header+pills are reinserted on top via MAP. rot: 0 normal, 180 front.
ABILITIES = [
    {"rect": [189, 476, 349, 497], "body": [197, 486, 345, 497], "rot": 0,
     "pl": "Działo glewii tej jednostki zyskuje WZMOCNIENIE RoA (1)."},
    {"rect": [351, 476, 489, 497], "body": [359, 486, 486, 497], "rot": 0,
     "pl": "Broń dystansowa Działa glewii zyskuje ANTY-UNIK (2)."},
    {"rect": [85, 313, 421, 348], "body": [88, 314, 320, 333], "rot": 180,
     "pl": "Umieść żeton Cienia całkowicie w promieniu 12\" od dowolnego modelu tej jednostki. Na końcu rundy gracz kontrolujący może ustawić wszystkie modele w spójności, traktując żeton Cienia jako model prowadzący. Żeton ma PRZEMIESZCZENIE."},
    {"rect": [85, 352, 421, 376], "body": [88, 353, 320, 371], "rot": 180,
     "pl": "Wszystkie bronie sojuszniczych jednostek atakujące wrogą jednostkę w promieniu 4\" od żetonu Cienia zyskują PRECYZJĘ (1)."},
]


def tl(s, fs):
    return fitz.get_text_length(s, fontname="helv", fontsize=fs)


def rgb(c):
    return ((c >> 16 & 255)/255, (c >> 8 & 255)/255, (c & 255)/255)


def center_in(bb, rect):
    cx, cy = (bb[0]+bb[2])/2, (bb[1]+bb[3])/2
    return rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]


def draw_label(page, origin, text, size, color, dirx, boxw):
    fs = size
    while fs > 3.5 and tl(text, fs) > boxw * 1.04:
        fs -= 0.25
    page.insert_text(fitz.Point(origin), text, fontsize=fs, fontfile=FONT, fontname="F",
                     color=color, rotate=0 if dirx >= 0 else 180)


def main(src="StarCraft-Protoss-P2P-Card-Sheets-A4_EN.pdf", page_no=0, lang="pl"):
    doc = fitz.open(ROOT / "sources/pdf" / src)
    page = doc[int(page_no)]
    spans = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            dirx = round(l.get("dir", (1, 0))[0])
            for s in l.get("spans", []):
                if s["text"].strip():
                    spans.append({"t": s["text"].strip(), "bb": s["bbox"], "org": s["origin"],
                                  "c": s["color"], "sz": s["size"], "dir": dirx})

    ab_rects = [a["rect"] for a in ABILITIES]
    targets = [s for s in spans if s["t"] in MAP]
    redact = [s["bb"] for s in targets] + ab_rects
    # collateral: non-target spans, not inside an ability, whose bbox is caught by a redact rect
    collateral = []
    for s in spans:
        if s in targets:
            continue
        if any(center_in(s["bb"], r) for r in ab_rects):
            continue  # body fragment -> handled by reflow
        if any(fitz.Rect(s["bb"]).intersects(fitz.Rect(r)) for r in redact):
            collateral.append(s)

    for r in redact:
        page.add_redact_annot(fitz.Rect(r))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                          text=fitz.PDF_REDACT_TEXT_REMOVE)

    # 1) ability bodies (drawn first, under the header/pills)
    for a in ABILITIES:
        rect = fitz.Rect(a["body"]); fs = 6.5
        while fs > 3.0:
            if page.insert_textbox(rect, a["pl"], fontsize=fs, fontname="F", fontfile=FONT,
                                   color=(0, 0, 0), align=0, rotate=a["rot"]) >= 0:
                break
            fs -= 0.25
    # 2) collateral originals (stat numbers etc.) — keep them
    for s in collateral:
        draw_label(page, s["org"], s["t"], s["sz"], rgb(s["c"]), s["dir"], s["bb"][2]-s["bb"][0])
    # 3) translated labels + pills + headers, on top
    for s in targets:
        pl = OVERRIDES.get((round(s["bb"][0]), round(s["bb"][1]))) or MAP[s["t"]]
        draw_label(page, s["org"], pl, s["sz"], rgb(s["c"]), s["dir"], s["bb"][2]-s["bb"][0])

    out = ROOT / f"build/{lang}/cards"; out.mkdir(parents=True, exist_ok=True)
    stem = f"{Path(src).stem}_p{page_no}_{lang}_inplace"
    pdf = out / f"{stem}.pdf"
    one = fitz.open(); one.insert_pdf(doc, from_page=int(page_no), to_page=int(page_no))
    one.save(pdf)
    fitz.open(pdf)[0].get_pixmap(dpi=200).save(out / f"{stem}.png")
    print(f"targets={len(targets)} collateral={len(collateral)} bodies={len(ABILITIES)} -> {pdf}")


if __name__ == "__main__":
    main(*(sys.argv[1:] or []))
