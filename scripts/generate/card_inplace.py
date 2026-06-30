#!/usr/bin/env python3
"""Card localization by EDITING THE ORIGINAL PDF in place (preserve the real card art/layout).

Text-only redaction removes the original glyphs (keeps all art); translated PL is re-inserted at
each span's origin, matching its colour, size, and rotation (the P2P sheet prints the card in two
orientations: dir(1,0) normal and dir(-1,0) = 180deg). Discrete labels are mapped EN->PL; numeric
stat values are left untouched. Wrapped ability body sentences are out of scope for this pass.
"""
import sys, fitz
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FONT = "/System/Library/Fonts/Supplemental/Arial Narrow.ttf"

# Discrete-label EN -> PL map (glossary-aligned). Keys matched on stripped text.
MAP = {
    "UNIT CARDS": "KARTY JEDNOSTEK", "PROTOSS FACTION": "FRAKCJA PROTOSÓW",
    "CORE": "PODSTAWOWA", "UPGRADE": "ULEPSZENIE", "U P G R A D E": "ULEPSZENIE",
    "COMBAT PHASE": "FAZA WALKI", "ASSAULT PHASE": "FAZA SZTURMU", "MOVEMENT PHASE": "FAZA RUCHU",
    "NAME": "NAZWA", "RNG": "ZAS", "Target": "Cel", "RoA": "SA", "Hit": "Traf",
    "Surge type": "Typ nawały", "S Dice": "K nawały", "Dmg": "Obr", "Keyword": "Słowo kl.",
    "STRIKE": "UDERZENIE", "GLAIVE CANNON": "DZIAŁO GLEWII", "ANTI-EVADE (1)": "ANTY-UNIK (1)",
    "PSIONIC TRANSFER:": "PSIONICZNY TRANSFER:", "PSIONIC PRESENCE:": "PSIONICZNA OBECNOŚĆ:",
    "RESONATING GLAIVES": "REZONUJĄCE GLEWIE", "ACTIVE": "AKTYWNA", "PASSIVE": "PASYWNA",
    "Ground": "Naziemny", "Light": "Lekki", "All": "Wsz.",
}


def textlen(s, fs):
    return fitz.get_text_length(s, fontname="helv", fontsize=fs)


def main(src="StarCraft-Protoss-P2P-Card-Sheets-A4_EN.pdf", page_no=0, lang="pl"):
    doc = fitz.open(ROOT / "sources/pdf" / src)
    page = doc[int(page_no)]
    spans = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            dirx = round(l.get("dir", (1, 0))[0])
            for s in l.get("spans", []):
                key = s["text"].strip()
                if key in MAP:
                    spans.append((s, MAP[key], dirx))
    # 1) erase only the matched glyphs, keep art
    for s, _, _ in spans:
        page.add_redact_annot(fitz.Rect(s["bbox"]))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                          text=fitz.PDF_REDACT_TEXT_REMOVE)
    # 2) reinsert PL at original origin/colour/size, matching rotation, shrink-to-fit
    n = 0
    for s, pl, dirx in spans:
        col = s["color"]; rgb = ((col >> 16 & 255)/255, (col >> 8 & 255)/255, (col & 255)/255)
        avail = s["bbox"][2] - s["bbox"][0]
        fs = s["size"]
        while fs > 4 and textlen(pl, fs) > avail * 1.02:
            fs -= 0.25
        rot = 0 if dirx >= 0 else 180
        page.insert_text(fitz.Point(s["origin"]), pl, fontsize=fs, fontfile=FONT,
                         fontname="F", color=rgb, rotate=rot)
        n += 1
    out = ROOT / f"build/{lang}/cards"; out.mkdir(parents=True, exist_ok=True)
    stem = f"{Path(src).stem}_p{page_no}_{lang}_inplace"
    pdf = out / f"{stem}.pdf"
    one = fitz.open(); one.insert_pdf(doc, from_page=int(page_no), to_page=int(page_no))
    one.save(pdf)
    fitz.open(pdf)[0].get_pixmap(dpi=180).save(out / f"{stem}.png")
    print(f"replaced {n} labels -> {pdf}")


if __name__ == "__main__":
    main(*(sys.argv[1:] or []))
