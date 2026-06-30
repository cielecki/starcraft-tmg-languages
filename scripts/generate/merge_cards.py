#!/usr/bin/env python3
"""Build the final localized card sheets: ONE connected PDF per army, mirroring the source.

Pipeline (fully reproducible from committed text + fetched sources):
  1. render every page of each army sheet in place  (card_inplace.py <sheet> all <lang>)
  2. merge the per-page PDFs into one PDF per army    (this script)

Output -> build/<lang>/  (default build/pl/), containing EXACTLY the three final sheets and
nothing else — one per army, named like the EN source with the language suffix:
  StarCraft-Protoss-P2P-Card-Sheets-A4_PL.pdf
  StarCraft-Terran-P2P-Card-Sheets-A4_PL.pdf
  StarCraft-Zerg-P2P-Card-Sheets-A4_PL.pdf

The per-page working PDFs/PNGs live in build/<lang>/cards/ (intermediate, gitignored); this
script reads them, writes the three merged sheets, and PRUNES build/<lang>/ of everything that
is not one of those three final files (the old per-page clutter, test/ extracts, the standalone
Adept file) so the output directory only ever holds the deliverables.

Usage:
  python3 scripts/generate/merge_cards.py [lang]          # merge already-rendered pages (lang=pl)
  python3 scripts/generate/merge_cards.py [lang] --render  # render all pages first, then merge
"""
import re
import shutil
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[2]

# EN source stem  ->  final PL name keeps the same stem with the EN-suffix swapped for the lang.
SHEETS = [
    "StarCraft-Protoss-P2P-Card-Sheets-A4_EN",
    "StarCraft-Terran-P2P-Card-Sheets-A4_EN",
    "StarCraft-Zerg-P2P-Card-Sheets-A4_EN",
]


def final_name(stem, lang):
    """EN source stem -> final per-army PDF name: ...-A4_EN -> ...-A4_<LANG> (e.g. _PL)."""
    base = stem[:-3] if stem.endswith("_EN") else stem
    return f"{base}_{lang.upper()}.pdf"


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


def render_all(lang):
    """Render every page of every army sheet in place (so the merge has fresh inputs)."""
    sys.path.insert(0, str(ROOT / "scripts" / "generate"))
    import card_inplace
    for stem in SHEETS:
        src = f"{stem}.pdf"
        n_pages = fitz.open(ROOT / "sources/pdf" / src).page_count
        print(f"rendering {stem}: {n_pages} pages")
        card_inplace.main([src, "all", lang])


def main():
    args = [a for a in sys.argv[1:]]
    do_render = "--render" in args
    args = [a for a in args if not a.startswith("--")]
    lang = args[0] if args else "pl"

    if do_render:
        render_all(lang)

    cards = ROOT / f"build/{lang}/cards"
    out_dir = ROOT / f"build/{lang}"
    if not cards.exists():
        sys.exit(f"no rendered pages at {cards} — run with --render, or "
                 f"`card_inplace.py <sheet> all {lang}` for each sheet first")

    finals = set()
    for stem in SHEETS:
        pages = page_pdfs(cards, stem, lang)
        if not pages:
            print(f"[skip] {stem}: no pages rendered")
            continue
        out = merge(out_dir / final_name(stem, lang), pages)
        finals.add(out.name)
        print(f"  {out.name}: {len(pages)} pages  ({out.stat().st_size//1024//1024} MiB)")

    # PRUNE: the output dir must hold ONLY the three final sheets (+ the _unfit.txt report). Remove
    # the per-page working dir, any old test/ extracts, the standalone Adept file, and anything else.
    keep = finals | {"_unfit.txt"}            # the unfit-bodies report is a deliverable, not clutter
    for child in out_dir.iterdir():
        if child.name in keep:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    print(f"\n{out_dir}/ now contains: {sorted(keep & {c.name for c in out_dir.iterdir()})}")


if __name__ == "__main__":
    main()
