#!/usr/bin/env python3
"""Programmatic text-overlap linter for localized card PDFs — the acceptance gate.

Text-on-text overlap is unreadable and must not be INTRODUCED by localization. It's detectable
without vision from the output PDF's own text geometry. Two refinements over naive span-bbox:

  1. Glyph-band, not full bbox. A span's bbox spans ascender→descender (em height), so two stacked
     lines "overlap" in the blank leading even when the ink doesn't. We inset each box to its core
     ink band along the CROSS axis of the reading direction (so it works for 0/90/180/270 cards),
     which removes line-spacing false positives and leaves only real ink collisions.
  2. Parity with the source, not absolute zero. The original EN cards have intentional overlaps
     (emboss duplicates, stat number/label stacking). The goal is to match the ORIGINAL's overlap
     rate, so we report EN vs PL vs INTRODUCED (PL overlaps with no counterpart in EN). Introduced
     is the defect count to drive to 0; exit code is non-zero iff introduced > 0.

Usage: python3 scripts/lint_overlaps.py <pl_pdf> [...]  [--source-dir sources/pdf] [--raw] [--json]
"""
import sys, os, json, argparse, fitz
from itertools import combinations

TOP, BOT = 0.16, 0.18   # ink-band inset (fraction of cross-axis), drops leading/descender space


def units(page):
    """Per-span ink-band rects, inset on the cross axis of the text's reading direction."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            dx, dy = l.get("dir", (1, 0))
            for s in l.get("spans", []):
                t = s["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = s["bbox"]; w, h = x1-x0, y1-y0
                if w <= 0 or h <= 0:
                    continue
                if abs(dx) >= abs(dy):                       # horizontal text -> inset vertically
                    r = fitz.Rect(x0, y0+TOP*h, x1, y1-BOT*h)
                else:                                        # vertical text -> inset horizontally
                    r = fitz.Rect(x0+TOP*w, y0, x1-BOT*w, y1)
                out.append((r, t))
    return out


def overlap_ratio(a, b):
    inter = a & b
    if inter.is_empty or inter.width <= 0 or inter.height <= 0:
        return 0.0, 0.0
    ia = inter.width*inter.height
    return ia / (min(a.width*a.height, b.width*b.height) or 1e-9), ia


def lint_page(page, min_ratio, min_area):
    u = units(page); hits = []
    for (ra, ta), (rb, tb) in combinations(u, 2):
        ratio, ia = overlap_ratio(ra, rb)
        if ratio >= min_ratio and ia >= min_area:
            hits.append({"a": ta, "b": tb, "ratio": round(ratio, 2), "union": ra | rb,
                         "bbox_a": [round(v, 1) for v in ra], "bbox_b": [round(v, 1) for v in rb]})
    return hits


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
    a = ap.parse_args()

    report, grand = {}, {"en": 0, "pl": 0, "introduced": 0}
    for pdf in a.pdfs:
        doc = fitz.open(pdf)
        en = None if a.raw else (lambda s: fitz.open(s) if s and os.path.exists(s) else None)(
            en_source_for(pdf, a.source_dir))
        pages, tot = {}, {"en": 0, "pl": 0, "introduced": 0}
        for i, page in enumerate(doc):
            pl_hits = lint_page(page, a.min_ratio, a.min_area)
            tot["pl"] += len(pl_hits)
            en_hits = lint_page(en[i], a.min_ratio, a.min_area) if (en and i < en.page_count) else []
            tot["en"] += len(en_hits)
            intro = [h for h in pl_hits if not matches(h["union"], en_hits)] if en else pl_hits
            for h in intro:
                h.pop("union", None)
            if intro:
                pages[i] = intro; tot["introduced"] += len(intro)
        report[pdf] = {"pages": pages, "totals": tot}
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
        for pdf, v in report.items():
            t = v["totals"]
            print(f"\n{os.path.basename(pdf)}: INTRODUCED={t['introduced']}  (EN={t['en']} PL={t['pl']})")
            for pg in sorted(v["pages"]):
                hits = v["pages"][pg]
                print(f"  p{pg}: {len(hits)}")
                for h in hits[:5]:
                    print(f"      [{h['ratio']:.2f}] {h['a']!r:30.30} ⨯ {h['b']!r:30.30}")
                if len(hits) > 5:
                    print(f"      … +{len(hits)-5} more")
        print(f"\nGRAND: INTRODUCED={grand['introduced']}  (EN baseline={grand['en']}, PL total={grand['pl']})")
    sys.exit(1 if grand["introduced"] else 0)


if __name__ == "__main__":
    main()
