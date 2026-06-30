#!/usr/bin/env python3
"""Apply the curated PL translations to data/segments/<doc>.jsonl.

This is the deterministic *application* layer of the multi-pass pipeline. The actual
translation reasoning was done by hand (glossary-constrained); this script holds the
authored mappings and writes them into every matching segment so identical source strings
translate IDENTICALLY everywhere (consistency by construction). Three layers:

  1. KEEP — pure stat/number/dimension labels and brand tokens kept verbatim in PL SC2
     (Marine, Stimpack, Blink, Nexus, Pylon, Hydralisk, Zergling, …, and all numerics).
  2. TERMS — a curated EN->PL dictionary for labels / headers (ability & weapon names) /
     pills / cells, grounded in glossary/pl.csv and the official Blizzard PL strings.
  3. BODIES — per-ability prose translations keyed by source_text, with target bold ranges
     recomputed from the PL equivalents of the source-bold fragments.

Run after extract_segments.py; verify with verify_segments.py.

Usage:
  python3 scripts/translate/translate_segments.py --all
  python3 scripts/translate/translate_segments.py data/segments/<doc>.jsonl
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEG_DIR = ROOT / "data" / "segments"
HERE = Path(__file__).resolve().parent
TERM_FILES = [HERE / "pl_terms.json", HERE / "pl_headers.json"]
BODY_FILES = [HERE / "pl_bodies.json", HERE / "pl_bodies2.json", HERE / "pl_bodies3.json",
              HERE / "pl_bodies4.json", HERE / "pl_bodies5.json"]

P2P_DOCS = [
    "StarCraft-Protoss-P2P-Card-Sheets-A4_EN",
    "StarCraft-Terran-P2P-Card-Sheets-A4_EN",
    "StarCraft-Zerg-P2P-Card-Sheets-A4_EN",
]

# Source strings kept verbatim (already valid PL or pure data). A string is KEEP if it
# matches this regex (numbers, dice, dimensions, ranges, modifiers, lone punctuation).
KEEP_RE = re.compile(
    r"""^(
        [-+]?\d+([./-]\d+)?\+?         # 1  2+  5/8  4-6  1-1  +2  100MM(no) ...
        | \d+(MM|mm)                   # 40MM 100MM
        | \d+×\d+˝?                    # 36×36˝
        | [Øו’'\".:,!?()\[\]\s/–—-]+   # symbols / punctuation only (incl. bare dash)
        | [XD]\d+(\+\d+)?              # D3 D3+1 X
        | \d+\s*PE | \d+\s*CP | \d+\s*BM   # numeric pills handled in TERMS, keep numeric
    )$""",
    re.VERBOSE,
)


def is_keep(text: str) -> bool:
    t = text.strip()
    return bool(KEEP_RE.match(t))


def load_json(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


BOLD_MARK = re.compile(r"\*\*(.+?)\*\*")


def parse_bold_markup(marked):
    """Body translations are authored with **...** around the fragments to render bold.
    This strips the markers and returns (clean_text, [[start,end],...]) char ranges in the
    clean text. Authoring with inline markers keeps target bold ranges correct by
    construction (no hand-counted offsets)."""
    out = []
    ranges = []
    pos = 0
    i = 0
    while i < len(marked):
        m = BOLD_MARK.match(marked, i)
        if m:
            frag = m.group(1)
            out.append(frag)
            ranges.append([pos, pos + len(frag)])
            pos += len(frag)
            i = m.end()
        else:
            out.append(marked[i])
            pos += 1
            i += 1
    return "".join(out), ranges


def translate_file(path, terms, bodies):
    out = []
    n_done = n_keep = n_term = n_body = n_miss = 0
    misses = []
    with Path(path).open(encoding="utf-8") as f:
        segs = [json.loads(l) for l in f if l.strip()]
    for seg in segs:
        src = seg["source_text"]
        kind = seg["kind"]
        tgt = None
        bold = seg.get("bold", [])

        if kind == "body":
            rec = bodies.get(src)
            if rec is not None:
                # rec may be a plain string with **bold** markup, or {"target_text", "bold"}
                if isinstance(rec, str):
                    tgt, bold = parse_bold_markup(rec)
                else:
                    raw = rec["target_text"]
                    if "**" in raw:
                        tgt, bold = parse_bold_markup(raw)
                    else:
                        tgt, bold = raw, rec.get("bold", [])
                n_body += 1
        else:
            if src in terms:
                tgt = terms[src]
                n_term += 1
            elif is_keep(src):
                tgt = src
                n_keep += 1

        if tgt is None:
            n_miss += 1
            misses.append((kind, src))
            seg["target_text"] = ""
            seg["status"] = "new"
        else:
            seg["target_text"] = tgt
            seg["bold"] = bold
            seg["status"] = "translated"
            n_done += 1
        out.append(seg)

    with Path(path).open("w", encoding="utf-8") as f:
        for seg in out:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
    return {"path": Path(path).name, "total": len(out), "done": n_done, "keep": n_keep,
            "term": n_term, "body": n_body, "miss": n_miss, "misses": misses}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--show-misses", action="store_true", help="list untranslated sources")
    a = ap.parse_args()
    terms = {}
    for tf in TERM_FILES:
        for k, v in load_json(tf).items():
            if not k.startswith("_"):
                terms[k] = v
    bodies = {}
    for bf in BODY_FILES:
        for k, v in load_json(bf).items():
            if not k.startswith("_"):
                bodies[k] = v
    paths = a.paths or [str(SEG_DIR / f"{d}.jsonl") for d in P2P_DOCS]
    grand_miss = []
    for p in paths:
        if not Path(p).exists():
            print(f"  MISSING {p}", file=sys.stderr)
            continue
        r = translate_file(p, terms, bodies)
        print(f"{r['path']}: {r['done']}/{r['total']} translated "
              f"(term={r['term']} keep={r['keep']} body={r['body']}) miss={r['miss']}")
        grand_miss += r["misses"]
    if a.show_misses and grand_miss:
        seen = set()
        print("\n=== untranslated sources ===")
        for kind, src in grand_miss:
            k = (kind, src)
            if k in seen:
                continue
            seen.add(k)
            print(f"  [{kind}] {src!r}")
    print(f"\nTOTAL untranslated: {len(grand_miss)} ({len(set(grand_miss))} unique)")


if __name__ == "__main__":
    main()
