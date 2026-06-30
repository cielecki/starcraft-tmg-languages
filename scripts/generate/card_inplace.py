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

GENERALIZED (works on ANY P2P card sheet, not just the Adept):
  - Ability BLOCKS are auto-detected per page (detect_abilities): the header span is the anchor
    (NotoSans-CondensedExtraBold, UPPERCASE, ends ':', ~7pt — uniquely the ability name; every
    other colon-label uses a different font), the enclosing filled panel rect is the block, and
    its reading direction (front card dir=-1 rotated 180; back card dir=+1) gives the orientation.
  - Translations come from an EXTERNAL segments JSONL (data/segments/<doc>.jsonl), not hardcoded:
    labels/headers/pills/cells looked up by (doc, source_text)->target_text; BODIES by id
    "<doc>:p<page>:ability:<block_index>". Missing segment -> leave the original EN (never crash).
  - Layout TREATMENT (grow-into-free-space / centred-banner / fit-own-slot) is structural and stays
    keyed off the EN source text (PHASES/CENTERED) since it is language-independent.
"""
import sys, json, argparse, fitz
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

# ── Structural layout classes (EN-source-keyed, LANGUAGE-INDEPENDENT) ──────────────────────────
# These say HOW a span is laid out, not what it translates to. They recur on every sheet, so they
# stay hardcoded on the EN side while the actual translations come from the external segments JSONL.
OVERRIDES = {(212, 543): "UDERZENIA"}  # "FOR STRIKE" -> "DLA UDERZENIA" (positional disambig.)
PILLS = {"ACTIVE", "PASSIVE", "1 PE"}                         # ability mode pills -> draw_pill
# Genuinely centred in a box/banner -> container-fit. Everything else is LEFT-aligned and grows
# rightward into free space (centring a left-aligned bar label shoves it onto its icon, e.g. UPGRADE).
CENTERED = {"CORE", "DAMAGE DEALER"}
# Phase-bar / upgrade-bar labels: left-aligned, grow rightward into free bar space.
PHASES = {"COMBAT PHASE", "ASSAULT PHASE", "MOVEMENT PHASE", "ANY PHASE", "UPGRADE", "U P G R A D E"}


def is_header_span(s):
    """An ability HEADER: the unique NotoSans-CondensedExtraBold UPPERCASE colon-label (~7pt). Every
    OTHER colon-uppercase label on the sheet (COMBAT TAGS:, MISSION PARAMETERS:, GATHER ACTION: …)
    uses a different font (Geogrotesque-Md / CondensedBlack / CondensedBold), so this is exact."""
    t = s["t"]
    return ("CondensedExtraB" in s["font"] and t.endswith(":") and t == t.upper()
            and len(t) > 3 and any(c.isalpha() for c in t) and 5.5 < s["sz"] < 9)

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

def is_not_body(s):
    """True for spans that are drawn SEPARATELY (header / pill / phase label) and so must never be
    swept into a body's prose reflow. Replaces the old hardcoded NOT_BODY text set: the ability
    header is now recognised structurally (is_header_span), so this works for every sheet."""
    return is_header_span(s) or s["t"] in PILLS or s["t"] in PHASES


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
    bs = [s for s in spans if in_rect(s["bb"], block) and not is_not_body(s)]
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


def _ability_panel(page, hx, hy):
    """The filled vector panel that frames an ability block. Prefer the TIGHTEST filled rect whose
    centre region contains the header point — the grey #dadad9 sub-panel on side-by-side back-card
    abilities, or the white panel that wraps a full-width front-card ability. Excludes the
    page-background fill (huge) and skinny icon chips (too small)."""
    best = None
    for d in page.get_drawings():
        f = d.get("fill")
        if not f or d.get("type") not in ("f", "fs"):
            continue
        r = fitz.Rect(d["rect"])
        if not (r.x0-1 <= hx <= r.x1+1 and r.y0-1 <= hy <= r.y1+1):
            continue
        if not (40 < r.width < 360 and 14 < r.height < 70):     # panel-shaped, not bg / not a chip
            continue
        if best is None or r.get_area() < best.get_area():
            best = r
    return best


def detect_abilities(page, spans):
    """AUTO-DETECT the ability blocks on a page (replaces the hardcoded ABILITIES list).

    Anchor = the ability HEADER span (is_header_span). For each header: the block rect is the
    enclosing filled panel (grey or white); its reading direction gives the orientation
    (rot 180 for the upside-down front card dir=-1, rot 0 for the back card dir=+1). If no panel
    encloses the header, fall back to the bounding box of the header + same-orientation prose
    spans clustered just below it. Blocks are returned in reading order (front card first, then
    top-to-bottom, then left-to-right) so block_index is stable for the JSONL body id."""
    out = []
    for h in spans:
        if not is_header_span(h):
            continue
        hx, hy = (h["bb"][0]+h["bb"][2])/2, (h["bb"][1]+h["bb"][3])/2
        rot = 0 if h["dir"] >= 0 else 180
        panel = _ability_panel(page, hx, hy)
        if panel is not None:
            block = [panel.x0, panel.y0, panel.x1, panel.y1]
        else:                                                   # no filled panel -> span-bbox union
            near = [s for s in spans if s["dir"] == h["dir"]
                    and abs(s["bb"][0]-h["bb"][0]) < 240 and -2 <= (s["bb"][1]-h["bb"][1]) <= 26]
            xs = [v for s in near for v in (s["bb"][0], s["bb"][2])]
            ys = [v for s in near for v in (s["bb"][1], s["bb"][3])]
            block = [min(xs)-2, min(ys)-2, max(xs)+2, max(ys)+2]
        out.append({"block": block, "rot": rot, "header": h["t"],
                    "_sort": (0 if h["dir"] < 0 else 1, round(hy, 1), round(h["bb"][0], 1))})
    out.sort(key=lambda a: a["_sort"])
    for i, a in enumerate(out):
        a["index"] = i
        del a["_sort"]
    return out


def load_segments(path, doc):
    """Read a segments JSONL into two lookups. Missing file -> empty (engine falls back to EN).
      by_source[(doc, source_text)] = target_text   (labels / headers / pills / cells)
      by_id[id]                     = {target_text, bold}   (bodies, id '<doc>:p<page>:ability:<i>')
    Only rows with a non-empty target_text are indexed, so an untranslated row falls back to EN."""
    by_source, by_id = {}, {}
    p = Path(path)
    if not p.exists():
        return by_source, by_id
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        tgt = (r.get("target_text") or "").strip()
        if not tgt:
            continue
        if r.get("kind") == "body":
            by_id[r["id"]] = {"target_text": r["target_text"], "bold": r.get("bold") or []}
        else:
            by_source[(r.get("doc", doc), r.get("source_text", ""))] = r["target_text"]
    return by_source, by_id


def apply_bold(text, ranges):
    """Wrap explicit [start,end) char ranges of `text` in <b>…</b> (HTML-escaping the plain parts).
    Used for body segments whose bold spans are given as char ranges in the JSONL."""
    import html as _html
    if not ranges:
        return _html.escape(text)
    cuts = sorted(((max(0, a), min(len(text), b)) for a, b in ranges), key=lambda r: r[0])
    out, pos = [], 0
    for a, b in cuts:
        if b <= pos:
            continue
        a = max(a, pos)
        out.append(_html.escape(text[pos:a]))
        out.append("<b>" + _html.escape(text[a:b]) + "</b>")
        pos = b
    out.append(_html.escape(text[pos:]))
    return "".join(out)


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


def draw_pill(page, s, text, dx=0):
    x0, y0, x1, y1 = s["bb"]; w = x1-x0; fs = s["sz"]
    while fs > 3 and FZ["ext"].text_length(text, fs) > w * 0.98:
        fs -= 0.2
    tw = FZ["ext"].text_length(text, fs)
    x = x0 + (w-tw)/2 if s["dir"] >= 0 else x1 - (w-tw)/2
    page.insert_text((x+dx, s["org"][1]), text, fontsize=fs, fontname="ext", fontfile=FPATH["ext"],
                     color=rgb(s["c"]), rotate=0 if s["dir"] >= 0 else 180)


def doc_slug(src):
    """The <doc> key used in segment ids / lookups: the PDF stem (matches data/segments/<doc>.jsonl)."""
    return Path(src).stem


def render_page(src, page_no, lang, by_source, by_id, doc_key):
    """Localize ONE page in place and write the PDF + PNG. Returns a small stats dict."""
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
    abil = detect_abilities(page, spans)                        # AUTO-DETECT (was hardcoded ABILITIES)
    # Attach derived geometry + the PL body (from JSONL by id) to each detected block.
    derived = []
    for a in abil:
        g, bs = derive_body(spans, a["block"], a["rot"])
        seg = by_id.get(f"{doc_key}:p{page_no}:ability:{a['index']}")
        derived.append((a, g, bs, seg))
    # Only blocks WITH a translation are redrawn; the rest keep their EN prose untouched.
    body_ids = {id(s) for (_, _, bs, seg) in derived if seg for s in bs}

    def lookup(s):
        # A span is translatable only if the JSONL has its source_text. OVERRIDES is a POSITIONAL
        # disambiguation of an already-translated span (e.g. one specific "FOR" -> "DLA UDERZENIA"),
        # never a standalone source — so it only re-maps when by_source already matched.
        base = by_source.get((doc_key, s["t"]))
        if base is None:
            return None
        return OVERRIDES.get((round(s["bb"][0]), round(s["bb"][1]))) or base
    # A target is any span with a translation (and not consumed by an ability-body reflow).
    targets = [s for s in spans if lookup(s) is not None and id(s) not in body_ids]

    # Redact ONLY what we replace: translated labels + ability prose. NOT whole blocks — that would
    # catch phase-bar icons (e.g. the upgrade arrow) and redraw them in the wrong font.
    redact = []
    for s in targets:
        x0, y0, x1, y1 = s["bb"]
        if s["sz"] < 5.5:  # tiny stat label over a big number -> don't reach the number
            y1 = y0 + (y1-y0)*0.45
        redact.append([x0, y0, x1, y1])
    redact += [list(s["bb"]) for (_, _, bs, seg) in derived if seg for s in bs]
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

    n_bodies = 0
    for a, g, bs, seg in derived:                              # bodies (rich text -> bold keywords)
        if not g or not seg:                                   # no prose, or untranslated -> leave EN
            continue
        n_bodies += 1
        fs = g["fs"]; lh = max(1.0, g["spacing"]/fs)
        y0 = g["base1"] - FZ["med"].ascender*fs - (lh-1)*fs/2  # land line 1 on the original baseline
        bottom = g["last"]+fs+2
        if a["rot"] == 0:
            bottom = min(bottom, a["block"][3]-1)              # keep the body inside the panel
        lrect = (g["left"]-0.5, y0, g["right"]+1, bottom)
        if a["rot"] == 0:
            rect = fitz.Rect(lrect)
        else:                                                  # transform the logical rect to page
            cx, cy = (a["block"][0]+a["block"][2])/2, (a["block"][1]+a["block"][3])/2
            rect = fitz.Rect(2*cx-lrect[2], 2*cy-lrect[3], 2*cx-lrect[0], 2*cy-lrect[1])
        indent = g["start_x"] - g["left"] + 1.5*FZ["med"].text_length(" ", fs)
        body = seg["target_text"]
        inner = apply_bold(body, seg["bold"]) if seg["bold"] else auto_bold(body)
        html = (f'<div style="text-indent:{indent:.1f}pt;font-size:{fs:.1f}pt;'
                f'line-height:{lh:.3f}">{inner}</div>')
        page.insert_htmlbox(rect, html, css=BODY_CSS, archive=ARCHIVE, rotate=a["rot"])
    for s in collateral:
        draw(page, s, s["t"])
    for s in targets:
        pl = lookup(s)
        if s["t"] in PILLS:
            draw_pill(page, s, pl); continue
        if s["t"] in CENTERED:                                 # centred banner value -> fit the box
            fit = None
            if FZ[pick(s["font"])].text_length(pl, s["sz"]) > (s["bb"][2]-s["bb"][0])*1.12:
                c = find_container(conts, s["bb"])
                if c and c.width > (s["bb"][2]-s["bb"][0])*1.3:
                    fit = c
            draw(page, s, pl, fit=fit)
        elif s["t"] in PHASES or is_header_span(s):            # bar/header labels grow into free space
            av = avail_width(s, spans)
            c = find_container(conts, s["bb"])                 # but never past the bar/segment edge
            if c:
                av = min(av, (c.x1 - s["org"][0] - 2) if s["dir"] >= 0 else (s["org"][0] - c.x0 - 2))
            draw(page, s, pl, avail=av)
        else:                                                  # table cells / fixed slots -> fit own slot
            draw(page, s, pl)

    out = ROOT / f"build/{lang}/cards"; out.mkdir(parents=True, exist_ok=True)
    stem = f"{Path(src).stem}_p{page_no}_{lang}_inplace"
    pdf = out / f"{stem}.pdf"
    one = fitz.open(); one.insert_pdf(doc, from_page=page_no, to_page=page_no)
    one.save(pdf)
    fitz.open(pdf)[0].get_pixmap(dpi=200).save(out / f"{stem}.png")
    print(f"  p{page_no}: blocks={len(abil)} targets={len(targets)} collateral={len(collateral)} "
          f"bodies={n_bodies}/{len(abil)} -> {pdf.name}")
    return {"blocks": len(abil), "targets": len(targets), "bodies": n_bodies}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Localize a SC:TMG card sheet in place from a segments JSONL.")
    ap.add_argument("src", nargs="?", default="StarCraft-Protoss-P2P-Card-Sheets-A4_EN.pdf",
                    help="PDF filename under sources/pdf/")
    ap.add_argument("pages", nargs="?", default="0",
                    help="page index, range 'a-b', comma list, or 'all' (default 0)")
    ap.add_argument("lang", nargs="?", default="pl")
    ap.add_argument("--segments", default=None,
                    help="segments JSONL (default data/segments/<doc>.jsonl)")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    src, lang = args.src, args.lang
    doc_key = doc_slug(src)
    seg_path = Path(args.segments) if args.segments else (ROOT / "data/segments" / f"{doc_key}.jsonl")
    by_source, by_id = load_segments(seg_path, doc_key)
    if not by_source and not by_id:
        print(f"[warn] no segments at {seg_path} — EN fallback (nothing will be translated)")

    n_pages = fitz.open(ROOT / "sources/pdf" / src).page_count
    spec = args.pages.strip().lower()
    if spec == "all":
        pages = list(range(n_pages))
    elif "," in spec:
        pages = [int(x) for x in spec.split(",") if x.strip() != ""]
    elif "-" in spec:
        a, b = spec.split("-"); pages = list(range(int(a), int(b)+1))
    else:
        pages = [int(spec)]

    print(f"{doc_key}  segments={seg_path.name}  ({len(by_source)} labels, {len(by_id)} bodies)")
    for p in pages:
        render_page(src, p, lang, by_source, by_id, doc_key)


if __name__ == "__main__":
    main()
