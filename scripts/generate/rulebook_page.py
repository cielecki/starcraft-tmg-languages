#!/usr/bin/env python3
"""Generate a localized rulebook page via in-place region-reflow (Spike A approach).

For each translated region: erase its bbox by painting the region background (keeps images
and vector art), then reflow the PL text with insert_textbox (wrap + shrink-to-fit) in a
PL-glyph font. Input: translations/<lang>/rulebook/p<N>.json. Output: build/<lang>/... (gitignored).
"""
import json, sys, fitz
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REG = "/System/Library/Fonts/Supplemental/Arial Narrow.ttf"
BOLD = "/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf"


def fit(page, rect, text, size, color, align, fontfile):
    fs = size
    while fs >= 5:
        rc = page.insert_textbox(rect, text, fontsize=fs, fontname="F", fontfile=fontfile,
                                 color=tuple(color), align=align)
        if rc >= 0:
            return fs
        fs -= 0.25
    # last resort: insert anyway (clipped)
    page.insert_textbox(rect, text, fontsize=5, fontname="F", fontfile=fontfile,
                        color=tuple(color), align=align)
    return None


def main(lang="pl", page_no=6):
    spec = json.loads((ROOT / f"translations/{lang}/rulebook/p{page_no}.json").read_text())
    src = ROOT / "sources/pdf" / spec["doc"]
    doc = fitz.open(src)
    page = doc[spec["page"]]
    # 1) erase ONLY the text glyphs in each region — keep line-art + images, paint no fill.
    #    (Painting a flat fill left grey patches because the page background is a full-page image.)
    for r in spec["regions"]:
        page.add_redact_annot(fitz.Rect(r["bbox"]))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                          text=fitz.PDF_REDACT_TEXT_REMOVE)
    # 2) reflow PL into each region
    for r in spec["regions"]:
        ff = BOLD if r.get("bold") else REG
        fs = fit(page, fitz.Rect(r["bbox"]), r["pl"], r.get("size", 8.5),
                 r.get("color", [1, 1, 1]), r.get("align", 0), ff)
        print(f"  {r['id']:12s} -> fontsize {fs}")
    out = ROOT / f"build/{lang}/rulebook"
    out.mkdir(parents=True, exist_ok=True)
    pdf = out / f"p{page_no}_{lang}.pdf"
    # keep only this page
    one = fitz.open(); one.insert_pdf(doc, from_page=spec["page"], to_page=spec["page"])
    one.save(pdf)
    png = out / f"p{page_no}_{lang}.png"
    fitz.open(pdf)[0].get_pixmap(dpi=140).save(png)
    print("wrote", pdf, "and", png)


if __name__ == "__main__":
    main(*(sys.argv[1:] or []))
