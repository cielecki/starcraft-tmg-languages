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
# distinct FAMILIES (not font-weight) — PyMuPDF's HTML engine won't pick @font-face by weight
BODY_CSS = """
@font-face { font-family: NCr; src: url("NotoSansCond-Medium.ttf"); }
@font-face { font-family: NCb; src: url("NotoSansCond-ExtraBold.ttf"); }
* { font-family: NCr; color: #000000; margin: 0; padding: 0; line-height: 1.2; }
b { font-family: NCb; }
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
# Genuinely centred in a box/banner -> container-fit. Everything else is LEFT-aligned and grows
# rightward into free space (centring a left-aligned bar label shoves it onto its icon, e.g. UPGRADE).
CENTERED = {"CORE", "DAMAGE DEALER"}
HEADERS = {"RESONATING GLAVES:", "GUIDANCE:", "PSIONIC TRANSFER:", "PSIONIC PRESENCE:"}
PHASES = {"COMBAT PHASE", "ASSAULT PHASE", "MOVEMENT PHASE", "ANY PHASE", "UPGRADE", "U P G R A D E"}
NOT_BODY = HEADERS | PILLS | PHASES                            # drawn separately; never body prose

# Glossary KEYWORDS — bolded automatically wherever they occur in a body (the source bolds these
# game terms; deriving from a keyword list instead of hand-marking <b> means we never miss one).
# Longest-first so multi-word terms win. As the real glossary grows this list comes from it.
KEYWORDS = [
    'całkowicie w promieniu 12"', 'w promieniu 4"', 'WZMOCNIENIE RoA (1)', 'ANTY-UNIK (2)',
    'model prowadzący', 'Na końcu rundy', 'PRECYZJĘ (1)', 'Działo glewii', 'Działa glewii',
    'PRZEMIESZCZENIE', 'sojuszniczych', 'spójności', 'bronie', 'wrogą', 'Cienia', 'Cień',
]


def auto_bold(text):
    ph = []
    for kw in KEYWORDS:
        if kw in text:
            text = text.replace(kw, f"\x00{len(ph)}\x01"); ph.append(kw)
    for i, kw in enumerate(ph):
        text = text.replace(f"\x00{i}\x01", f"<b>{kw}</b>")
    return text

# block = full ability rect (redacted to clear original). body = reflow rect (starts on the header
# line). indent = first-line indent (pt) so the body begins AFTER the header+pills, then wraps full
# width below — matching the original. rot 180 (front) keeps indent 0 (rotated-flow indent is wrong-side).
# Only the structural facts: which rect is an ability block, its orientation, and the PL body
# (bold keywords marked). The body's geometry — baseline, start-after-pills, wrap width, line
# spacing — is DERIVED from the original body spans (derive_body), not hand-measured.
ABILITIES = [  # plain PL text; bold is applied automatically from KEYWORDS (no hand-marked <b>)
    {"block": [189, 476, 349, 497], "rot": 0,
     "body": "Działo glewii tej jednostki zyskuje WZMOCNIENIE RoA (1)."},
    {"block": [351, 476, 489, 497], "rot": 0,
     "body": "Broń dystansowa Działa glewii tej jednostki zyskuje ANTY-UNIK (2)."},
    {"block": [85, 313, 421, 348], "rot": 180,
     "body": "Umieść żeton Cienia całkowicie w promieniu 12\" od dowolnego modelu tej jednostki. Na końcu rundy gracz kontrolujący może ustawić wszystkie modele tej jednostki w spójności, traktując żeton Cienia jako model prowadzący. Żeton Cienia ma PRZEMIESZCZENIE."},
    {"block": [85, 352, 421, 376], "rot": 180,
     "body": "Wszystkie bronie sojuszniczych jednostek atakujące wrogą jednostkę w promieniu 4\" od żetonu Cienia zyskują PRECYZJĘ (1)."},
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


def avail_width(s, spans):
    """Free space in the reading direction up to the next span on the same line (so a longer PL
    label grows into empty bar space instead of shrinking or centring onto an icon)."""
    x0, y0, x1, y1 = s["bb"]; cy = (y0+y1)/2
    if s["dir"] >= 0:
        edges = [o["bb"][0] for o in spans if o is not s
                 and abs((o["bb"][1]+o["bb"][3])/2-cy) < 4 and o["bb"][0] >= x1-0.5]
        return (min(edges) if edges else x1+110) - s["org"][0] - 1
    edges = [o["bb"][2] for o in spans if o is not s
             and abs((o["bb"][1]+o["bb"][3])/2-cy) < 4 and o["bb"][2] <= x0+0.5]
    return s["org"][0] - (max(edges) if edges else x0-110) - 1


def to_logical(x, y, block, rot):
    """Map a page point into the body's reading frame (identity for rot 0; 180deg about the block
    centre for the upside-down front card) so one derivation handles both orientations."""
    if rot == 0:
        return x, y
    cx, cy = (block[0]+block[2])/2, (block[1]+block[3])/2
    return 2*cx - x, 2*cy - y


def derive_body(spans, block, rot):
    """Read the original body's layout (baseline, start-after-pills, wrap width, line spacing) from
    its prose spans, in the reading frame, so the PL reflow matches the original by construction."""
    bs = [s for s in spans if in_rect(s["bb"], block) and s["t"] not in NOT_BODY]
    if not bs:
        return None, []
    L = []
    for s in bs:
        lx, ly = to_logical(s["org"][0], s["org"][1], block, rot)
        ax, _ = to_logical(s["bb"][0], s["bb"][1], block, rot)
        bx, _ = to_logical(s["bb"][2], s["bb"][3], block, rot)
        L.append((lx, ly, max(ax, bx), s["sz"]))               # logical origin x/y, right edge, size
    base1 = min(p[1] for p in L)
    top = [p for p in L if p[1]-base1 < 1.5]
    rest = [p for p in L if p[1]-base1 >= 1.5]
    bl = sorted({round(p[1], 1) for p in L})
    sizes = sorted(p[3] for p in L)
    g = {
        "start_x": min(p[0] for p in top), "right": max(p[2] for p in L),
        "left": min((p[0] for p in rest), default=min(p[0] for p in top)),
        "base1": base1, "last": max(p[1] for p in L), "fs": sizes[len(sizes)//2],
        "spacing": (bl[1]-bl[0]) if len(bl) > 1 else sizes[len(sizes)//2]*1.2,
    }
    return g, bs


def containers(page):
    """Filled banner-ish shapes, for fitting a value that overflows its original (shorter) slot."""
    out = []
    for d in page.get_drawings():
        if d.get("fill") and d.get("type") in ("f", "fs"):
            r = fitz.Rect(d["rect"])
            if 14 < r.width < 130 and 8 < r.height < 32:
                out.append(r)
    return out


def find_container(conts, bb):
    cand = [r for r in conts if r.x0 <= bb[0]+1 and r.x1 >= bb[2]-1
            and r.y0 <= bb[1]+2 and r.y1 >= bb[3]-2]
    return min(cand, key=lambda r: r.width*r.height) if cand else None


def draw(page, s, text, key=None, fit=None, avail=None):
    key = key or pick(s["font"]); rot = 0 if s["dir"] >= 0 else 180
    if fit is not None:                       # PL overflows its slot -> fill + centre the container
        fs = s["sz"]
        while fs > 3.5 and FZ[key].text_length(text, fs) > fit.width*0.92:
            fs -= 0.25
        while FZ[key].text_length(text, fs+0.25) < fit.width*0.86 and fs < fit.height*0.82:
            fs += 0.25
        tw = FZ[key].text_length(text, fs)
        page.insert_text((fit.x0 + (fit.width-tw)/2, fit.y0 + fit.height/2 + fs*0.34), text,
                         fontsize=fs, fontname=key, fontfile=FPATH[key], color=rgb(s["c"]), rotate=rot)
        return
    boxw = s["bb"][2]-s["bb"][0]; bound = max(boxw*1.04, avail) if avail else boxw*1.04; fs = s["sz"]
    while fs > 3.5 and FZ[key].text_length(text, fs) > bound:
        fs -= 0.25
    page.insert_text(fitz.Point(s["org"]), text, fontsize=fs, fontname=key, fontfile=FPATH[key],
                     color=rgb(s["c"]), rotate=rot)


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

    conts = containers(page)
    abil = [(a, *derive_body(spans, a["block"], a["rot"])) for a in ABILITIES]
    body_ids = {id(s) for (_, _, bs) in abil for s in bs}
    # a span inside an ability body is never a standalone target (even if it matches MAP, e.g. "All"
    # -> "Wsz."): the body reflow handles it. Otherwise it gets drawn twice.
    targets = [s for s in spans if s["t"] in MAP and id(s) not in body_ids]

    # Redact ONLY what we replace: translated labels + ability prose. NOT whole blocks — that would
    # catch phase-bar icons (e.g. the upgrade arrow) and redraw them in the wrong font.
    redact = []
    for s in targets:
        x0, y0, x1, y1 = s["bb"]
        if s["sz"] < 5.5:  # tiny stat label over a big number -> don't reach the number
            y1 = y0 + (y1-y0)*0.45
        redact.append([x0, y0, x1, y1])
    redact += [list(s["bb"]) for (_, _, bs) in abil for s in bs]
    collateral, seen = [], set()
    for s in spans:
        if s in targets or id(s) in body_ids:
            continue
        if any(ord(c) > 0x2000 for c in s["t"]):               # symbols/icons -> leave to the art
            continue
        if not any(fitz.Rect(s["bb"]).intersects(fitz.Rect(r)) for r in redact):
            continue
        k = (s["t"], round(s["org"][0]), round(s["org"][1]))
        if k not in seen:
            seen.add(k); collateral.append(s)

    for r in redact:
        page.add_redact_annot(fitz.Rect(r))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                          text=fitz.PDF_REDACT_TEXT_REMOVE)

    for a, g, bs in abil:                                      # bodies (rich text -> bold keywords)
        if not g:
            continue
        fs = g["fs"]; lh = max(1.0, g["spacing"]/fs)
        y0 = g["base1"] - FZ["med"].ascender*fs - (lh-1)*fs/2  # land line 1 on the original baseline
        lrect = (g["left"]-0.5, y0, g["right"]+1, g["last"]+fs+2)
        if a["rot"] == 0:
            rect = fitz.Rect(lrect)
        else:                                                  # transform the logical rect to page
            cx, cy = (a["block"][0]+a["block"][2])/2, (a["block"][1]+a["block"][3])/2
            rect = fitz.Rect(2*cx-lrect[2], 2*cy-lrect[3], 2*cx-lrect[0], 2*cy-lrect[1])
        indent = g["start_x"] - g["left"] + 1.5*FZ["med"].text_length(" ", fs)  # gap after the pills
        html = (f'<div style="text-indent:{indent:.1f}pt;font-size:{fs:.1f}pt;'
                f'line-height:{lh:.3f}">{auto_bold(a["body"])}</div>')
        page.insert_htmlbox(rect, html, css=BODY_CSS, archive=ARCHIVE, rotate=a["rot"])
    for s in collateral:
        draw(page, s, s["t"])
    for s in targets:
        pl = OVERRIDES.get((round(s["bb"][0]), round(s["bb"][1]))) or MAP[s["t"]]
        if s["t"] in PILLS:
            draw_pill(page, s, pl); continue
        if s["t"] in CENTERED:                                 # centred banner value -> fit the box
            fit = None
            if FZ[pick(s["font"])].text_length(pl, s["sz"]) > (s["bb"][2]-s["bb"][0])*1.12:
                c = find_container(conts, s["bb"])
                if c and c.width > (s["bb"][2]-s["bb"][0])*1.3:
                    fit = c
            draw(page, s, pl, fit=fit)
        else:                                                  # left-aligned -> grow into free space
            av = avail_width(s, spans)
            c = find_container(conts, s["bb"])                 # but never past the bar/segment edge
            if c:
                av = min(av, (c.x1 - s["org"][0] - 2) if s["dir"] >= 0 else (s["org"][0] - c.x0 - 2))
            draw(page, s, pl, avail=av)

    out = ROOT / f"build/{lang}/cards"; out.mkdir(parents=True, exist_ok=True)
    stem = f"{Path(src).stem}_p{page_no}_{lang}_inplace"
    pdf = out / f"{stem}.pdf"
    one = fitz.open(); one.insert_pdf(doc, from_page=page_no, to_page=page_no)
    one.save(pdf)
    fitz.open(pdf)[0].get_pixmap(dpi=200).save(out / f"{stem}.png")
    print(f"targets={len(targets)} collateral={len(collateral)} bodies={len(ABILITIES)} -> {pdf}")


if __name__ == "__main__":
    main(*(sys.argv[1:] or []))
