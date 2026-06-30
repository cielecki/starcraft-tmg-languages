#!/usr/bin/env python3
"""Card localization by EDITING THE ORIGINAL PDF in place (preserve the real card art/layout).

Two mechanisms, both text-only-redaction based (keep all art):
  - MAP: discrete labels -> reinsert PL at the original span's origin/colour/size/rotation.
  - REGIONS: wrapped ability bodies -> redact the box, reflow the full PL sentence with
    insert_textbox (wrap + shrink-to-fit), matching rotation.
The P2P sheet prints the card double-sided: the front is rotated 180deg (dir(-1,0)), the back
is normal (dir(1,0)). Numeric stat values are left untouched.
"""
import sys, fitz
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FONT = "/System/Library/Fonts/Supplemental/Arial Narrow.ttf"

MAP = {
    # headers / identity
    "PROTOSS FACTION": "FRAKCJA PROTOSÓW", "UNIT CARDS": "KARTY JEDNOSTEK",
    "PROTOSS": "PROTOSI", "CORE": "PODSTAWOWA", "DAMAGE DEALER": "ZADAJĄCY OBRAŻENIA",
    "COMBAT ROLE:": "ROLA BOJOWA:", "ARMY SLOT:": "SLOT ARMII:",
    "CLOSE COMBAT": "WALKA WRĘCZ", "RANGED COMBAT": "WALKA DYST.",
    "COMBAT TAGS:": "CECHY BOJOWE:", "BIOLOGICAL, LIGHT, GROUND": "BIOLOGICZNY, LEKKI, NAZIEMNY",
    # phases / badges
    "COMBAT PHASE": "FAZA WALKI", "ASSAULT PHASE": "FAZA SZTURMU",
    "MOVEMENT PHASE": "FAZA RUCHU", "ANY PHASE": "DOWOLNA FAZA",
    "UPGRADE": "ULEPSZENIE", "U P G R A D E": "ULEPSZENIE",
    "ACTIVE": "AKTYWNA", "PASSIVE": "PASYWNA", "1 PE": "1 EP",
    # stat labels
    "SIZE": "ROZMIAR", "HIT POINTS": "PKT ŻYCIA", "EVADE": "UNIK", "ARMOUR": "PANCERZ",
    "SPEED": "SZYBKOŚĆ", "SHIELD": "OSŁONA", "MODELS / SUPPLY": "MODELE / ZAOPATRZ.",
    # attack-table headers
    "NAME": "NAZWA", "RNG": "ZAS", "Target": "Cel", "RoA": "SA", "Hit": "Traf",
    "Surge type": "Typ naw.", "S Dice": "K naw.", "Dmg": "Obr", "Keyword": "Słowo kl.",
    # attack-table cells
    "STRIKE": "UDERZENIE", "GLAIVE STRIKE": "UDERZ. GLEWIĄ", "GLAIVE CANNON": "DZIAŁO GLEWII",
    "Ground": "Naziem.", "Light": "Lekki", "All": "Wsz.",
    "PIERCE Light (2)": "PRZEBICIE Lekki (2)", "ANTI-EVADE (1)": "ANTY-UNIK (1)",
}

# Phase labels can sit INSIDE a body region (front card) — always re-insert them so a full-width
# redaction doesn't drop them.
PHASES = {"COMBAT PHASE", "ASSAULT PHASE", "MOVEMENT PHASE", "ANY PHASE"}

# Wrapped ability bodies: redact the box + reflow the full PL (header included). Body reflows into
# `textrect` (which avoids the phase-label column); `bbox` is the full area to erase.
REGIONS = [
    # FRONT (rotated 180) — Psionic abilities. x capped before the phase-label column (~322).
    {"bbox": [85, 313, 421, 348], "textrect": [85, 313, 322, 348], "rot": 180,
     "pl": "PSIONICZNY TRANSFER (Aktywna, 1 EP): Umieść żeton Cienia całkowicie w promieniu 12\" od dowolnego modelu tej jednostki. Na końcu rundy gracz kontrolujący może ustawić wszystkie modele tej jednostki w spójności, traktując żeton Cienia jako model prowadzący. Żeton Cienia ma PRZEMIESZCZENIE."},
    {"bbox": [85, 352, 421, 376], "textrect": [85, 352, 322, 376], "rot": 180,
     "pl": "PSIONICZNA OBECNOŚĆ (Pasywna): Wszystkie bronie sojuszniczych jednostek atakujące wrogą jednostkę w promieniu 4\" od żetonu Cienia tej jednostki zyskują PRECYZJĘ (1)."},
    # BACK (normal) — upgrades. Header on the same row as the body; phase/UPGRADE label is above.
    {"bbox": [193, 476, 349, 497], "rot": 0,
     "pl": "REZONUJĄCE GLEWIE (Aktywna, 1 EP): Działo glewii tej jednostki zyskuje WZMOCNIENIE RoA (1)."},
    {"bbox": [356, 476, 489, 497], "rot": 0,
     "pl": "NAPROWADZANIE (Pasywna): Broń dystansowa Działa glewii tej jednostki zyskuje ANTY-UNIK (2)."},
]


def textlen(s, fs):
    return fitz.get_text_length(s, fontname="helv", fontsize=fs)


def in_region(bb):
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    for r in REGIONS:
        x0, y0, x1, y1 = r["bbox"]
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            return True
    return False


def main(src="StarCraft-Protoss-P2P-Card-Sheets-A4_EN.pdf", page_no=0, lang="pl"):
    doc = fitz.open(ROOT / "sources/pdf" / src)
    page = doc[int(page_no)]
    labels = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            dirx = round(l.get("dir", (1, 0))[0])
            for s in l.get("spans", []):
                key = s["text"].strip()
                if key in MAP and (key in PHASES or not in_region(s["bbox"])):
                    labels.append((s, MAP[key], dirx))
    # 1) erase: region boxes + matched discrete labels (text-only, keep art)
    for r in REGIONS:
        page.add_redact_annot(fitz.Rect(r["bbox"]))
    for s, _, _ in labels:
        page.add_redact_annot(fitz.Rect(s["bbox"]))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                          text=fitz.PDF_REDACT_TEXT_REMOVE)
    # 2) reflow ability bodies
    for r in REGIONS:
        rect = fitz.Rect(r.get("textrect", r["bbox"]))
        fs = 7.0
        while fs > 3.5:
            rc = page.insert_textbox(rect, r["pl"], fontsize=fs, fontname="F", fontfile=FONT,
                                     color=(0, 0, 0), align=0, rotate=r["rot"])
            if rc >= 0:
                break
            fs -= 0.25
    # 3) discrete labels
    for s, pl, dirx in labels:
        col = s["color"]; rgb = ((col >> 16 & 255)/255, (col >> 8 & 255)/255, (col & 255)/255)
        avail = s["bbox"][2] - s["bbox"][0]
        fs = s["size"]
        while fs > 4 and textlen(pl, fs) > avail * 1.03:
            fs -= 0.25
        page.insert_text(fitz.Point(s["origin"]), pl, fontsize=fs, fontfile=FONT, fontname="F",
                         color=rgb, rotate=0 if dirx >= 0 else 180)
    out = ROOT / f"build/{lang}/cards"; out.mkdir(parents=True, exist_ok=True)
    stem = f"{Path(src).stem}_p{page_no}_{lang}_inplace"
    pdf = out / f"{stem}.pdf"
    one = fitz.open(); one.insert_pdf(doc, from_page=int(page_no), to_page=int(page_no))
    one.save(pdf)
    fitz.open(pdf)[0].get_pixmap(dpi=200).save(out / f"{stem}.png")
    print(f"replaced {len(labels)} labels + {len(REGIONS)} body regions -> {pdf}")


if __name__ == "__main__":
    main(*(sys.argv[1:] or []))
