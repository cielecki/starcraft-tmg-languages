#!/usr/bin/env python3
"""Programmatic overlap linter for localized card PDFs — the acceptance gate.

Text-on-text overlap is unreadable and must NEVER ship. It's detectable without vision: two drawn
text spans whose bounding boxes intersect significantly are a defect. This reads the OUTPUT PDF's
own text geometry (every span the engine drew — labels, pills, reflowed bodies) and reports any
pair that collides. Bboxes are axis-aligned in page space, so rotation (0/90/180/270) is handled
for free. Exit code is non-zero if any overlap is found, so it can gate CI / the build.

Usage: python3 scripts/lint_overlaps.py <pdf> [<pdf> ...]  [--min-ratio 0.30] [--json]
"""
import sys, json, argparse, fitz
from itertools import combinations


def spans(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                t = s["text"].strip()
                if t:
                    out.append((fitz.Rect(s["bbox"]), t))
    return out


def overlap_ratio(a, b):
    inter = a & b
    if inter.is_empty or inter.width <= 0 or inter.height <= 0:
        return 0.0, 0.0
    ia = inter.width * inter.height
    smaller = min(a.width*a.height, b.width*b.height) or 1e-9
    return ia / smaller, ia


def lint_page(page, min_ratio, min_area):
    sp = spans(page)
    hits = []
    for (ra, ta), (rb, tb) in combinations(sp, 2):
        ratio, ia = overlap_ratio(ra, rb)
        if ratio >= min_ratio and ia >= min_area:
            hits.append({"a": ta, "b": tb, "ratio": round(ratio, 2), "union": ra | rb,
                         "bbox_a": [round(v, 1) for v in ra], "bbox_b": [round(v, 1) for v in rb]})
    return hits


def en_source_for(pl_pdf, source_dir):
    """Map build/<lang>/<Name>_PL.pdf -> sources/pdf/<Name>_EN.pdf so we can subtract the original's
    intentional overlaps (emboss duplicates, stat number/label stacking) and flag only NEW ones."""
    import os
    base = os.path.basename(pl_pdf)
    for suf in ("_PL.pdf", "_pl.pdf"):
        if base.endswith(suf):
            return os.path.join(source_dir, base[:-len(suf)] + "_EN.pdf")
    return None


def iou(a, b):
    inter = a & b
    if inter.is_empty:
        return 0.0
    ia = inter.width*inter.height
    ua = a.width*a.height + b.width*b.height - ia
    return ia/ua if ua else 0.0


def introduced(pl_hits, en_hits):
    """A PL overlap is INTRODUCED (our bug) if no EN overlap sits at the same place (union IoU>0.4)."""
    out = []
    for h in pl_hits:
        if not any(iou(h["union"], e["union"]) > 0.4 for e in en_hits):
            out.append(h)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--min-ratio", type=float, default=0.30)   # intersection / smaller-span area
    ap.add_argument("--min-area", type=float, default=2.0)     # pt^2, ignore sub-pixel touches
    ap.add_argument("--source-dir", default="sources/pdf")     # to subtract the EN's own overlaps
    ap.add_argument("--raw", action="store_true")              # don't subtract source (show all)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    report, total = {}, 0
    for pdf in a.pdfs:
        doc = fitz.open(pdf)
        en = None
        if not a.raw:
            src = en_source_for(pdf, a.source_dir)
            try:
                en = fitz.open(src) if src else None
            except Exception:
                en = None
        pages = {}
        for i, page in enumerate(doc):
            hits = lint_page(page, a.min_ratio, a.min_area)
            if en is not None and i < en.page_count:
                hits = introduced(hits, lint_page(en[i], a.min_ratio, a.min_area))
            for h in hits:
                h.pop("union", None)
            if hits:
                pages[i] = hits
                total += len(hits)
        report[pdf] = pages

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for pdf, pages in report.items():
            name = pdf.split("/")[-1]
            n = sum(len(h) for h in pages.values())
            print(f"\n{name}: {n} overlap(s) on {len(pages)} page(s)")
            for pg in sorted(pages):
                print(f"  p{pg}: {len(pages[pg])} overlap(s)")
                for h in pages[pg][:6]:
                    print(f"      [{h['ratio']:.2f}] {h['a']!r:32.32} ⨯ {h['b']!r:32.32}")
                if len(pages[pg]) > 6:
                    print(f"      … +{len(pages[pg])-6} more")
        print(f"\nTOTAL: {total} text-on-text overlaps")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
