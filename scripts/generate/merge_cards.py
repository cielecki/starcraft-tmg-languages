#!/usr/bin/env python3
"""Merge the per-page localized card PDFs (written by card_inplace.py to build/<lang>/cards/)
into one PDF per P2P sheet, plus a standalone single-card extract (the Adept = Protoss page 0).

Output -> build/<lang>/test/:
  Adept-PL.pdf          (Protoss sheet, page 0 only)
  Protoss-P2P-PL.pdf    (all Protoss pages, in order)
  Terran-P2P-PL.pdf     (all Terran pages)
  Zerg-P2P-PL.pdf       (all Zerg pages)

Reproducible: re-run card_inplace.py <sheet> all pl for each sheet first, then this.

Usage: python3 scripts/generate/merge_cards.py [lang]   (lang default 'pl')
"""
import re, sys
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[2]

SHEETS = {
    "Protoss-P2P": "StarCraft-Protoss-P2P-Card-Sheets-A4_EN",
    "Terran-P2P":  "StarCraft-Terran-P2P-Card-Sheets-A4_EN",
    "Zerg-P2P":    "StarCraft-Zerg-P2P-Card-Sheets-A4_EN",
}
# standalone single-card extracts: (output name, sheet stem, page index)
STANDALONE = [("Adept", "StarCraft-Protoss-P2P-Card-Sheets-A4_EN", 0)]


def page_pdfs(cards_dir, stem, lang):
    """All per-page PDFs for a sheet, sorted by page index."""
    pat = re.compile(rf"^{re.escape(stem)}_p(\d+)_{re.escape(lang)}_inplace\.pdf$")
    found = []
    for p in cards_dir.iterdir():
        m = pat.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    found.sort(key=lambda t: t[0])
    return found


def merge(out_path, page_paths):
    out = fitz.open()
    for _idx, p in page_paths:
        src = fitz.open(p)
        out.insert_pdf(src)
        src.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path, garbage=4, deflate=True)
    out.close()
    return out_path


def main():
    lang = sys.argv[1] if len(sys.argv) > 1 else "pl"
    cards = ROOT / f"build/{lang}/cards"
    test = ROOT / f"build/{lang}/test"
    if not cards.exists():
        sys.exit(f"no rendered pages at {cards} — run card_inplace.py <sheet> all {lang} first")

    for name, stem, pno in STANDALONE:
        pages = page_pdfs(cards, stem, lang)
        match = [(i, p) for (i, p) in pages if i == pno]
        if not match:
            print(f"[skip] {name}: page {pno} of {stem} not rendered")
            continue
        out = merge(test / f"{name}-PL.pdf", match)
        print(f"  {out.name}: page {pno} of {stem}  ({out.stat().st_size//1024} KiB)")

    for name, stem in SHEETS.items():
        pages = page_pdfs(cards, stem, lang)
        if not pages:
            print(f"[skip] {name}: no pages rendered for {stem}")
            continue
        out = merge(test / f"{name}-PL.pdf", pages)
        print(f"  {out.name}: {len(pages)} pages  ({out.stat().st_size//1024//1024} MiB)")


if __name__ == "__main__":
    main()
