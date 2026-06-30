#!/usr/bin/env python3
"""Programmatic text-overlap linter for localized card PDFs — the acceptance gate.

Text-on-text overlap is unreadable and must not be INTRODUCED by localization. It's detectable
without vision from the output PDF's own text geometry. Refinements over naive span-bbox:

  1. Glyph-band, not full bbox. A span's bbox spans ascender→descender (em height), so two stacked
     lines "overlap" in the blank leading even when the ink doesn't. We inset each box to its core
     ink band along the CROSS axis of the reading direction (so it works for 0/90/180/270 cards),
     which removes line-spacing false positives and leaves only real ink collisions. This is the
     cheap PRE-FILTER (a candidate pair = two ink-band boxes that intersect).
  2. TRUE RENDERED-INK collision (the final test, default on; --no-ink falls back to box-only).
     Ink-band boxes still over-report: two boxes can overlap where the actual glyphs don't touch.
     For each candidate pair we re-render each span's glyphs ALONE — at its own origin / size /
     rotation, in the MATCHING Noto weight (the engine's pick()/FPATH) — into the pair's small
     union clip at high DPI, get a boolean ink mask per span, dilate ~1px for AA tolerance, and
     keep the pair ONLY if the two masks actually touch on at least a few pixels. Applied to BOTH
     PL and EN candidates so the INTRODUCED delta stays ink-accurate. Per-span masks are cached
     per page; only candidate pairs are rendered, over their small clips, so it stays fast.
  3. Parity with the source, not absolute zero. The original EN cards have intentional overlaps
     (emboss duplicates, stat number/label stacking). The goal is to match the ORIGINAL's overlap
     rate, so we report EN vs PL vs INTRODUCED (PL overlaps with no counterpart in EN). Introduced
     is the defect count to drive to 0.
  4. PILL-INTRUSION (a separate defect class). Pills are the small filled colour badges that mark
     an ability mode (blue #36a9e0, green #3fa435, red #cd1619). A defect is EXTERNAL text whose
     glyph ink enters a pill rect — a body line crossing the badge. This is caught from the pill
     RECT + the intruding text alone, NOT from any pill-label span, because an intrusion typically
     SUPPRESSES the pill's own label from rendering. We separate the pill's OWN centred label (a
     short span mostly contained + centred in the rect) from an intruder (ink in the rect belonging
     to a span that extends well beyond it) and flag only the intruders.

Exit code is non-zero iff introduced > 0 OR pill-intrusions > 0 (this is the gate).

Usage: python3 scripts/lint_overlaps.py <pl_pdf> [...]  [--source-dir sources/pdf]
                                        [--raw] [--json] [--no-ink] [--dpi N]
"""
import sys, os, json, argparse, fitz
import numpy as np
from itertools import combinations
from pathlib import Path

# Reuse the ENGINE's font mapping so the re-render matches what was actually drawn.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate.card_inplace import pick, FPATH        # noqa: E402

TOP, BOT = 0.16, 0.18        # ink-band inset (fraction of cross-axis), drops leading/descender space
INK_DPI = 200                # re-render DPI for the glyph-collision test
INK_MIN_TOUCH = 3            # min touching (dilated) pixels to count as a real ink collision

# Pill (ability-mode badge) fill colours, as 0..1 RGB, with a match tolerance.
PILL_COLOURS = {
    "blue":  (0x36/255, 0xa9/255, 0xe0/255),     # #36a9e0
    "green": (0x3f/255, 0xa4/255, 0x35/255),     # #3fa435
    "red":   (0xcd/255, 0x16/255, 0x19/255),     # #cd1619
}
PILL_TOL = 0.06
PILL_W = (9.0, 26.0)         # small filled badge width range (pt)
PILL_H = (5.5, 12.0)         # and height range (pt)


def span_code(line):
    """Reading-direction code (0/90/180/270) from the line's unit dir vector — matches the engine."""
    dx, dy = line.get("dir", (1, 0))
    if abs(dx) >= abs(dy):
        return 0 if dx >= 0 else 180
    return 90 if dy < 0 else 270


def units(page):
    """Per-span records with the ink-band rect (inset on the cross axis of the reading direction)
    plus everything the re-render needs (text, origin, size, font, dir code, full bbox)."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            code = span_code(l)
            for s in l.get("spans", []):
                t = s["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = s["bbox"]; w, h = x1-x0, y1-y0
                if w <= 0 or h <= 0:
                    continue
                if code in (0, 180):                         # horizontal text -> inset vertically
                    r = fitz.Rect(x0, y0+TOP*h, x1, y1-BOT*h)
                else:                                        # vertical text -> inset horizontally
                    r = fitz.Rect(x0+TOP*w, y0, x1-BOT*w, y1)
                out.append({"r": r, "t": t, "bb": s["bbox"], "org": s["origin"],
                            "sz": s["size"], "font": s["font"], "code": code})
    return out


def overlap_ratio(a, b):
    inter = a & b
    if inter.is_empty or inter.width <= 0 or inter.height <= 0:
        return 0.0, 0.0
    ia = inter.width*inter.height
    return ia / (min(a.width*a.height, b.width*b.height) or 1e-9), ia


# ── true rendered-ink collision ────────────────────────────────────────────────────────────────
def _dilate(m):
    """1-pixel dilation (4-neighbourhood) — antialias tolerance so glyphs that visually kiss count."""
    out = m.copy()
    out[1:, :] |= m[:-1, :]; out[:-1, :] |= m[1:, :]
    out[:, 1:] |= m[:, :-1]; out[:, :-1] |= m[:, 1:]
    return out


def _span_ink_mask(page_size, sp, clip, dpi):
    """Re-render ONE span's glyphs alone (matching Noto weight + size + rotation) into `clip` and
    return a boolean dark-pixel mask in that clip's pixel frame. The same origin/rotate convention
    the engine drew with, so two spans rendered into the same clip collide exactly as on the page."""
    key = pick(sp["font"])
    tmp = fitz.open()
    pg = tmp.new_page(width=page_size[0], height=page_size[1])
    pg.insert_text(fitz.Point(sp["org"]), sp["t"], fontsize=sp["sz"], fontname=key,
                   fontfile=FPATH[key], color=(0, 0, 0), rotate=sp["code"])
    pix = pg.get_pixmap(dpi=dpi, clip=clip, colorspace=fitz.csGRAY, alpha=False)
    if pix.width == 0 or pix.height == 0:
        return np.zeros((1, 1), dtype=bool)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return arr < 128


def _ink_collides(page_size, a, b, dpi, cache):
    """True iff the two spans' re-rendered glyph masks actually touch (≥ INK_MIN_TOUCH px after a
    1-px dilation), rendered into their shared small union clip. Masks cached per (id, clip)."""
    clip = (fitz.Rect(a["bb"]) | fitz.Rect(b["bb"])) + (-2, -2, 2, 2)
    ckey = (round(clip.x0, 1), round(clip.y0, 1), round(clip.x1, 1), round(clip.y1, 1))
    ma = cache.get((id(a), ckey))
    if ma is None:
        ma = _span_ink_mask(page_size, a, clip, dpi); cache[(id(a), ckey)] = ma
    mb = cache.get((id(b), ckey))
    if mb is None:
        mb = _span_ink_mask(page_size, b, clip, dpi); cache[(id(b), ckey)] = mb
    if ma.shape != mb.shape or not ma.any() or not mb.any():
        return False, 0
    touch = int((_dilate(ma) & _dilate(mb)).sum())
    return touch >= INK_MIN_TOUCH, touch


def lint_page(page, min_ratio, min_area, ink, dpi):
    """Candidate pairs = ink-band boxes intersect (cheap). If `ink`, keep only those whose actual
    re-rendered glyphs collide. Returns the kept hits."""
    u = units(page)
    page_size = (page.rect.width, page.rect.height)
    cache = {}
    hits = []
    for a, b in combinations(u, 2):
        ratio, ia = overlap_ratio(a["r"], b["r"])
        if ratio < min_ratio or ia < min_area:
            continue
        if ink:
            ok, touch = _ink_collides(page_size, a, b, dpi, cache)
            if not ok:
                continue
        hits.append({"a": a["t"], "b": b["t"], "ratio": round(ratio, 2),
                     "union": a["r"] | b["r"],
                     "bbox_a": [round(v, 1) for v in a["r"]],
                     "bbox_b": [round(v, 1) for v in b["r"]]})
    return hits


# ── pill-intrusion detection ─────────────────────────────────────────────────────────────────────
def _colour_name(fill):
    for name, ref in PILL_COLOURS.items():
        if all(abs(fill[i]-ref[i]) < PILL_TOL for i in range(3)):
            return name
    return None


def find_pills(page):
    """Small filled colour badges (ability-mode pills). Returns [(rect, colour_name)]."""
    pills = []
    for d in page.get_drawings():
        fill = d.get("fill")
        if not fill or d.get("type") not in ("f", "fs"):
            continue
        name = _colour_name(fill)
        if not name:
            continue
        r = fitz.Rect(d["rect"])
        if PILL_W[0] <= r.width <= PILL_W[1] and PILL_H[0] <= r.height <= PILL_H[1]:
            pills.append((r, name))
    return pills


def _is_own_label(sp, pill):
    """The pill's OWN centred label: a short span MOSTLY CONTAINED in the pill rect and roughly
    centred within it (so it doesn't extend appreciably past any edge). Anything else whose ink
    enters the rect is external."""
    bb = fitz.Rect(sp["bb"])
    inter = bb & pill
    if inter.is_empty or bb.get_area() <= 0:
        return False
    contained = inter.get_area() / bb.get_area()
    if contained < 0.75:                         # extends well beyond the pill -> not its label
        return False
    # centred: span centre near pill centre on both axes (allow generous slack for AA / kerning)
    pcx, pcy = (pill.x0+pill.x1)/2, (pill.y0+pill.y1)/2
    scx, scy = (bb.x0+bb.x1)/2, (bb.y0+bb.y1)/2
    return abs(scx-pcx) <= pill.width*0.5+2 and abs(scy-pcy) <= pill.height*0.5+2


def pill_intrusions(page, dpi):
    """External text whose GLYPH INK enters a pill rect (a body line crossing the badge). Detected
    from the pill rect + the intruding span alone — independent of whether the pill's own label
    rendered (intrusions tend to suppress it). For each pill: skip its own centred label, then for
    every other span whose bbox crosses the pill, re-render that span's glyphs alone clipped to the
    pill rect; if any dark pixels land inside, it's an intruder. One record PER PILL (the worst
    intruder), keyed by the pill rect, so EN parity can subtract a pill that is ALSO crossed in EN
    (the colour-coded COMBAT-ROLE banner strip and the stat-token row are crossed identically in the
    EN source — original, not our defect — while a PL body line reflowed onto an ability badge is
    introduced)."""
    pills = find_pills(page)
    if not pills:
        return []
    u = units(page)
    page_size = (page.rect.width, page.rect.height)
    out = []
    for pill, colour in pills:
        own = [sp for sp in u if _is_own_label(sp, pill)]
        best = None
        for sp in u:
            if sp in own:
                continue
            bb = fitz.Rect(sp["bb"])
            inter = bb & pill
            if inter.is_empty or inter.width <= 0 or inter.height <= 0:
                continue
            # a true intruder extends well beyond the pill (a real body/label line, not a stray
            # fragment that happens to sit inside) — require it to stick out past the rect somewhere
            extends = (bb.x0 < pill.x0-1 or bb.x1 > pill.x1+1
                       or bb.y0 < pill.y0-1 or bb.y1 > pill.y1+1)
            if not extends:
                continue
            ink = int(_span_ink_mask(page_size, sp, pill, dpi).sum())
            if ink < 2:                          # no real glyph ink inside the badge
                continue
            if best is None or ink > best["ink_px"]:
                best = {"text": sp["t"], "colour": colour,
                        "pill": [round(v, 1) for v in pill],
                        "ink_px": ink,
                        "span_bbox": [round(v, 1) for v in sp["bb"]]}
        if best is not None:
            out.append(best)
    return out


def _pill_key(rec):
    """Pill identity for EN parity — its rect rounded to the integer point (the print sheets reuse
    the same pill grid on EN and PL, so a crossed pill matches by location)."""
    return tuple(round(v) for v in rec["pill"])


def pill_intrusions_introduced(pl_recs, en_recs):
    """Drop any PL pill-intrusion whose pill is ALSO crossed in EN (banner / stat-token strips that
    overlap identically in the source). What remains = PL-introduced pill intrusions."""
    en_pills = {_pill_key(r) for r in en_recs}
    return [r for r in pl_recs if _pill_key(r) not in en_pills]


# ── EN parity ──────────────────────────────────────────────────────────────────────────────────
def en_source_for(pl_pdf, source_dir):
    base = os.path.basename(pl_pdf)
    for suf in ("_PL.pdf", "_pl.pdf"):
        if base.endswith(suf):
            return os.path.join(source_dir, base[:-len(suf)] + "_EN.pdf")
    return None


def matches(u, en_hits):
    """An overlap is intentional (already in EN) if an EN overlap sits at the same place."""
    return any((u & e["union"]).width > 0 and overlap_ratio(u, e["union"])[0] > 0.4 for e in en_hits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--min-ratio", type=float, default=0.18)
    ap.add_argument("--min-area", type=float, default=1.5)     # pt^2
    ap.add_argument("--source-dir", default="sources/pdf")
    ap.add_argument("--raw", action="store_true")              # don't subtract source
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-ink", action="store_true",
                    help="fast box-only mode — skip the rendered-ink collision verification")
    ap.add_argument("--dpi", type=int, default=INK_DPI, help="DPI for the ink-collision re-render")
    a = ap.parse_args()
    ink = not a.no_ink

    report = {}
    grand = {"en": 0, "pl": 0, "introduced": 0, "pills": 0}
    for pdf in a.pdfs:
        doc = fitz.open(pdf)
        en = None if a.raw else (lambda s: fitz.open(s) if s and os.path.exists(s) else None)(
            en_source_for(pdf, a.source_dir))
        pages = {}
        pill_pages = {}
        tot = {"en": 0, "pl": 0, "introduced": 0, "pills": 0}
        for i, page in enumerate(doc):
            pl_hits = lint_page(page, a.min_ratio, a.min_area, ink, a.dpi)
            tot["pl"] += len(pl_hits)
            en_hits = (lint_page(en[i], a.min_ratio, a.min_area, ink, a.dpi)
                       if (en and i < en.page_count) else [])
            tot["en"] += len(en_hits)
            intro = [h for h in pl_hits if not matches(h["union"], en_hits)] if en else pl_hits
            for h in intro:
                h.pop("union", None)
            if intro:
                pages[i] = intro; tot["introduced"] += len(intro)

            pl_pi = pill_intrusions(page, a.dpi)
            en_pi = (pill_intrusions(en[i], a.dpi) if (en and i < en.page_count) else [])
            pi = pill_intrusions_introduced(pl_pi, en_pi) if en else pl_pi
            if pi:
                pill_pages[i] = pi; tot["pills"] += len(pi)
        report[pdf] = {"pages": pages, "pill_pages": pill_pages, "totals": tot}
        for k in grand:
            grand[k] += tot[k]

    if a.json:
        for v in report.values():
            for p in v["pages"].values():
                for h in p:
                    h.pop("union", None)
        print(json.dumps({"report": report, "grand": grand}, ensure_ascii=False, indent=2,
                         default=str))
    else:
        mode = "box-only" if a.no_ink else f"ink@{a.dpi}dpi"
        for pdf, v in report.items():
            t = v["totals"]
            print(f"\n{os.path.basename(pdf)}: INTRODUCED={t['introduced']}  PILL-INTRUSIONS={t['pills']}"
                  f"  (EN={t['en']} PL={t['pl']})")
            for pg in sorted(v["pages"]):
                hits = v["pages"][pg]
                print(f"  p{pg} text-on-text: {len(hits)}")
                for h in hits[:5]:
                    print(f"      [{h['ratio']:.2f}] {h['a']!r:30.30} ⨯ {h['b']!r:30.30}")
                if len(hits) > 5:
                    print(f"      … +{len(hits)-5} more")
            for pg in sorted(v["pill_pages"]):
                pis = v["pill_pages"][pg]
                print(f"  p{pg} pill-intrusions: {len(pis)}")
                for h in pis[:5]:
                    print(f"      [{h['colour']:5}] {h['text']!r:40.40} into {h['pill']}")
                if len(pis) > 5:
                    print(f"      … +{len(pis)-5} more")
        print(f"\nGRAND ({mode}): INTRODUCED={grand['introduced']}  PILL-INTRUSIONS={grand['pills']}"
              f"  (EN baseline={grand['en']}, PL total={grand['pl']})")
    sys.exit(1 if (grand["introduced"] or grand["pills"]) else 0)


if __name__ == "__main__":
    main()
