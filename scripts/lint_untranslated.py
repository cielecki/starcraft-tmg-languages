#!/usr/bin/env python3
"""Untranslated-leftover gate for localized card PDFs.

A localization defect we can catch WITHOUT vision: an output span whose text is still the EN
SOURCE of a segment that DOES have a (different) translation. If `data/segments/<doc>.jsonl` says
`source_text = "GLAIVE STRIKE"` → `target_text = "UDERZ. GLEWIĄ"`, then a "GLAIVE STRIKE" span left
in the PL PDF means the engine failed to translate that unit — the segment lookup missed. We flag
every such leftover; the gate target is 0.

Why "different target" is the test: a segment whose target EQUALS its source is a KEEP token (a
number, a brand name, a dimension like 6") — those are SUPPOSED to appear verbatim in the output and
are not defects. Only a source that maps to a genuinely different PL string is a leftover when it
survives in the output.

Per-orientation note: spans are read in any of the 4 print orientations; we compare the stripped
span text against the segment source set, so rotation is irrelevant (the text is the same string).

Exit code is non-zero iff any untranslated leftover is found (this is a gate).

Usage:
  python3 scripts/lint_untranslated.py build/pl/*.pdf
  python3 scripts/lint_untranslated.py build/pl/StarCraft-Protoss-...A4_PL.pdf --segments-dir data/segments
                                       [--lang pl] [--json]
"""
import sys, os, json, argparse, fitz
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def en_doc_key(pl_pdf, lang):
    """The segments-JSONL doc key for a PL output PDF: swap the _<LANG> suffix back to _EN.
    e.g. StarCraft-Protoss-...-A4_PL.pdf -> StarCraft-Protoss-...-A4_EN (the JSONL stem)."""
    stem = Path(pl_pdf).stem
    suf = f"_{lang.upper()}"
    if stem.endswith(suf):
        stem = stem[:-len(suf)]
    return stem + "_EN"


def load_translatable_sources(seg_path):
    """Map source_text -> target_text for segments whose target DIFFERS from the source (i.e. a real
    translation, not a verbatim KEEP token). These are the strings that must NOT survive in the PL
    output. Only non-empty targets count (an untranslated row has no expected PL form to check).

    A source is EXCLUDED when the SAME string is also a legitimate `target_text` somewhere — e.g. a
    two-line card title 'TERRAN ARMED / FORCES' localised as 'SIŁY ZBROJNE / TERRAN' makes 'TERRAN'
    both a source (→ 'TERRANIE') and a valid PL output (of 'FORCES'). Such a string in the output is
    ambiguous, not provably a leftover, so we don't flag it (no false positive on a real PL token)."""
    out = {}
    targets = set()
    p = Path(seg_path)
    if not p.exists():
        return out
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        src = (r.get("source_text") or "").strip()
        tgt = (r.get("target_text") or "").strip()
        rows.append((src, tgt))
        if tgt:
            targets.add(tgt)
    for src, tgt in rows:
        if not src or not tgt:
            continue
        if src == tgt:                       # KEEP token (number / brand / dimension) — verbatim, OK
            continue
        if src in targets:                   # also a valid PL output of another segment — ambiguous
            continue
        out[src] = tgt
    return out


def page_span_texts(page):
    """All stripped non-empty span texts on a page (any orientation)."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                t = s["text"].strip()
                if t:
                    out.append((t, [round(v, 1) for v in s["bbox"]]))
    return out


def lint_pdf(pl_pdf, seg_dir, lang):
    doc_key = en_doc_key(pl_pdf, lang)
    seg_path = Path(seg_dir) / f"{doc_key}.jsonl"
    sources = load_translatable_sources(seg_path)
    leftovers = {}
    if not sources:
        return {"doc": doc_key, "seg_path": str(seg_path), "have_segments": False,
                "leftovers": leftovers, "total": 0}
    doc = fitz.open(pl_pdf)
    total = 0
    for i, page in enumerate(doc):
        hits = []
        for t, bb in page_span_texts(page):
            if t in sources:
                hits.append({"text": t, "expected": sources[t], "bbox": bb})
        if hits:
            leftovers[i] = hits
            total += len(hits)
    return {"doc": doc_key, "seg_path": str(seg_path), "have_segments": True,
            "leftovers": leftovers, "total": total}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--segments-dir", default=str(ROOT / "data" / "segments"))
    ap.add_argument("--lang", default="pl")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    report = {}
    grand = 0
    for pdf in a.pdfs:
        r = lint_pdf(pdf, a.segments_dir, a.lang)
        report[pdf] = r
        grand += r["total"]

    if a.json:
        print(json.dumps({"report": report, "grand": grand}, ensure_ascii=False, indent=2))
    else:
        for pdf, r in report.items():
            name = os.path.basename(pdf)
            if not r["have_segments"]:
                print(f"\n{name}: [no segments at {r['seg_path']}] — skipped")
                continue
            print(f"\n{name}: UNTRANSLATED-LEFTOVERS={r['total']}")
            for pg in sorted(r["leftovers"]):
                hits = r["leftovers"][pg]
                print(f"  p{pg}: {len(hits)}")
                for h in hits[:8]:
                    print(f"      {h['text']!r:30.30} should be {h['expected']!r}")
                if len(hits) > 8:
                    print(f"      … +{len(hits)-8} more")
        print(f"\nGRAND: UNTRANSLATED-LEFTOVERS={grand}")
    sys.exit(1 if grand else 0)


if __name__ == "__main__":
    main()
