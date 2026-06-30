#!/usr/bin/env python3
"""Localize a card by editing the original PDF in place — faithful typography.

The SC:TMG cards are typeset in NOTO SANS CONDENSED (Regular/Medium/ExtraBold/Black) — a free,
Polish-capable font (the display titles use proprietary Gineso/Aviano, which we approximate with
Noto Black). So we redraw each translated span in the MATCHING Noto Condensed weight, at its
original position, preserving the layout exactly. Run scripts/build_fonts.py once to create the
weights under assets/fonts/.

Other principles (from the visual-bug passes):
  - Redact what we replace; reinsert collateral originals so nothing vanishes.
  - Don't redact the big stat NUMBERS (clip the tiny stat-label redaction above them) — a reinsert
    lands off their baked shadow and doubles glyphs (the "/" in 5/8). Numbers stay pristine.
  - Abilities = name + colour pills + body with BOLD keywords. Pills: translate, bold, centred.
    Body: reflow as rich text (insert_htmlbox) so keywords stay bold.
"""
import sys, fitz
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FDIR = ROOT / "assets/fonts"
FACE = {"reg": "NotoSansCond-Regular.ttf", "med": "NotoSansCond-Medium.ttf",
        "ext": "NotoSansCond-ExtraBold.ttf", "blk": "NotoSansCond-Black.ttf"}
FPATH = {k: str(FDIR / v) for k, v in FACE.items()}
FZ = {k: fitz.Font(fontfile=p) for k, p in FPATH.items()}
ARCHIVE = fitz.Archive(str(FDIR))
BODY_CSS = """
@font-face { font-family: NC; font-weight: 500; src: url("NotoSansCond-Medium.ttf"); }
@font-face { font-family: NC; font-weight: 800; src: url("NotoSansCond-ExtraBold.ttf"); }
* { font-family: NC; font-weight: 500; color: #000000; margin: 0; padding: 0; line-height: 1.0; }
b { font-weight: 800; }
"""

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
OVERRIDES = {(212, 543): "UDERZENIA"}  # "FOR STRIKE" -> "DLA UDERZENIA"
PILLS = {"ACTIVE", "PASSIVE", "1 PE"}

ABILITIES = [  # HTML body (bold keywords), reflowed clear of the header/pill line
    {"rect": [189, 476, 349, 497], "body": [196, 486, 346, 498], "rot": 0,
     "html": "<b>Działo glewii</b> tej jednostki zyskuje <b>WZMOCNIENIE RoA (1)</b>."},
    {"rect": [351, 476, 489, 497], "body": [358, 486, 487, 498], "rot": 0,
     "html": "Broń dystansowa <b>Działa glewii</b> tej jednostki zyskuje <b>ANTY-UNIK (2)</b>."},
    {"rect": [85, 313, 421, 348], "body": [88, 314, 320, 334], "rot": 180,
     "html": "Umieść żeton <b>Cienia</b> całkowicie w promieniu 12\" od dowolnego modelu tej jednostki. Na końcu rundy gracz kontrolujący może ustawić wszystkie modele w spójności, traktując żeton <b>Cienia</b> jako model prowadzący. Żeton ma <b>PRZEMIESZCZENIE</b>."},
    {"rect": [85, 352, 421, 376], "body": [88, 353, 320, 372], "rot": 180,
     "html": "Wszystkie bronie sojuszniczych jednostek atakujące wrogą jednostkę w promieniu 4\" od żetonu <b>Cienia</b> zyskują <b>PRECYZJĘ (1)</b>."},
]


def rgb(c):
    return ((c >> 16 & 255)/255, (c >> 8 & 255)/255, (c & 255)/255)


def pick(font):
    """Map a source font name to a Noto Condensed weight key."""
    f = font.lower()
    if "black" in f or "bla" in f or "aviano" in f or "gineso" in f:
        return "blk"
    if "extra" in f or "bol" in f:
        return "ext"
    if "medium" in f or "-md" in f or "geogro" in f:
        return "med"
    return "reg"


def in_rect(bb, r):
    cx, cy = (bb[0]+bb[2])/2, (bb[1]+bb[3])/2
    return r[0] <= cx <= r[2] and r[1] <= cy <= r[3]


def draw(page, s, text, key=None):
    key = key or pick(s["font"]); boxw = s["bb"][2]-s["bb"][0]; fs = s["sz"]
    while fs > 3.5 and FZ[key].text_length(text, fs) > boxw * 1.04:
        fs -= 0.25
    page.insert_text(fitz.Point(s["org"]), text, fontsize=fs, fontname=key, fontfile=FPATH[key],
                     color=rgb(s["c"]), rotate=0 if s["dir"] >= 0 else 180)


def draw_pill(page, s, text):
    x0, y0, x1, y1 = s["bb"]; w = x1-x0; fs = s["sz"]
    while fs > 3 and FZ["ext"].text_length(text, fs) > w * 0.98:
        fs -= 0.2
    tw = FZ["ext"].text_length(text, fs)
    x = x0 + (w-tw)/2 if s["dir"] >= 0 else x1 - (w-tw)/2
    page.insert_text((x, s["org"][1]), text, fontsize=fs, fontname="ext", fontfile=FPATH["ext"],
                     color=rgb(s["c"]), rotate=0 if s["dir"] >= 0 else 180)


def main(src="StarCraft-Protoss-P2P-Card-Sheets-A4_EN.pdf", page_no=0, lang="pl"):
    page_no = int(page_no)
    doc = fitz.open(ROOT / "sources/pdf" / src)
    page = doc[page_no]
    spans = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            dirx = round(l.get("dir", (1, 0))[0])
            for s in l.get("spans", []):
                if s["text"].strip():
                    spans.append({"t": s["text"].strip(), "bb": s["bbox"], "org": s["origin"],
                                  "c": s["color"], "sz": s["size"], "dir": dirx, "font": s["font"]})

    ab_rects = [a["rect"] for a in ABILITIES]
    targets = [s for s in spans if s["t"] in MAP]
    redact = [list(r) for r in ab_rects]
    for s in targets:
        x0, y0, x1, y1 = s["bb"]
        if s["sz"] < 5.5:  # tiny stat label over a big number -> don't reach the number
            y1 = y0 + (y1-y0)*0.45
        redact.append([x0, y0, x1, y1])
    collateral = [s for s in spans if s not in targets
                  and not any(in_rect(s["bb"], r) for r in ab_rects)
                  and any(fitz.Rect(s["bb"]).intersects(fitz.Rect(r)) for r in redact)]
    seen = set(); collateral = [s for s in collateral
                                if (s["t"], round(s["org"][0]), round(s["org"][1])) not in seen
                                and not seen.add((s["t"], round(s["org"][0]), round(s["org"][1])))]

    for r in redact:
        page.add_redact_annot(fitz.Rect(r))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                          text=fitz.PDF_REDACT_TEXT_REMOVE)

    for a in ABILITIES:
        page.insert_htmlbox(fitz.Rect(a["body"]), f'<div style="font-size:6.6pt">{a["html"]}</div>',
                            css=BODY_CSS, archive=ARCHIVE, rotate=a["rot"])
    for s in collateral:
        draw(page, s, s["t"])
    for s in targets:
        pl = OVERRIDES.get((round(s["bb"][0]), round(s["bb"][1]))) or MAP[s["t"]]
        draw_pill(page, s, pl) if s["t"] in PILLS else draw(page, s, pl)

    out = ROOT / f"build/{lang}/cards"; out.mkdir(parents=True, exist_ok=True)
    stem = f"{Path(src).stem}_p{page_no}_{lang}_inplace"
    pdf = out / f"{stem}.pdf"
    one = fitz.open(); one.insert_pdf(doc, from_page=page_no, to_page=page_no)
    one.save(pdf)
    fitz.open(pdf)[0].get_pixmap(dpi=200).save(out / f"{stem}.png")
    print(f"targets={len(targets)} collateral={len(collateral)} bodies={len(ABILITIES)} -> {pdf}")


if __name__ == "__main__":
    main(*(sys.argv[1:] or []))
