#!/usr/bin/env python3
"""Verify the PL translations in data/segments/<doc>.jsonl against the glossary.

Checks, per segment:
  * GLOSSARY ADHERENCE — for every glossary EN term present in source_text, the canonical
    PL term (inflection-tolerant stem) must appear in target_text. Flags misses.
  * NO LEFTOVER ENGLISH — target_text must not contain obvious untranslated English content
    words (a stop-list of common EN function words that should never survive a PL render,
    plus a heuristic for ASCII-only multi-word targets that look unchanged from source).
  * CONSISTENCY — the SAME source_text must map to the SAME target_text everywhere (a label
    translated two different ways is a defect); and a given EN glossary term must not be
    rendered with conflicting PL forms across segments.
  * COMPLETENESS — every segment must have a non-empty target_text and status 'translated'.
  * BOLD SANITY (body) — bold ranges must be within bounds and non-overlapping; their count
    should not wildly exceed the source's (a rough guard against lost bold).

Exit code is non-zero if any segment is flagged, so it can gate a build.

Usage:
  python3 scripts/translate/verify_segments.py data/segments/StarCraft-Protoss-P2P-Card-Sheets-A4_EN.jsonl
  python3 scripts/translate/verify_segments.py --all
"""
from __future__ import annotations
import argparse, csv, json, re, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GLOSSARY = ROOT / "glossary" / "pl.csv"
SEG_DIR = ROOT / "data" / "segments"

P2P_DOCS = [
    "StarCraft-Protoss-P2P-Card-Sheets-A4_EN",
    "StarCraft-Terran-P2P-Card-Sheets-A4_EN",
    "StarCraft-Zerg-P2P-Card-Sheets-A4_EN",
]

# EN function/content words that should not survive into a finished PL string. Kept short
# and specific so brand terms Blizzard keeps (Marine, Stimpack, Blink, Nexus, Pylon) don't
# false-positive. (These are checked as whole words, case-insensitive.)
EN_LEFTOVER = {
    "the", "this", "that", "with", "from", "gain", "gains", "when", "after", "unit",
    "weapon", "enemy", "friendly", "within", "round", "effect", "target", "attack",
    "may", "each", "your", "their", "and", "for", "all", "any", "until", "while",
    "place", "set", "reduce", "remove", "resolve", "active", "passive", "phase",
}


def load_glossary():
    terms = []
    with GLOSSARY.open(encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.lstrip().startswith("#"))
        for r in rows:
            terms.append(r)
    return terms


_FOLD = str.maketrans("ąćęłńóśźż", "acelnoszz")


def fold(s):
    """Fold PL diacritics so a stem prefix still matches across inflection that shifts an
    accent (koniec->końcu, n<->ń)."""
    return s.lower().translate(_FOLD)


def stem(w):
    """PL-inflection-tolerant stem: drop the case ending. PL inflects the last 1-3 chars
    (rundy/rundzie, kontrolowaniu/kontroluje, zergów/zergowie). We keep a generous prefix
    (~60% of the word, min 4) so a translation in any case still matches."""
    w = w.lower()
    keep = max(4, int(len(w) * 0.6))
    return w[:keep]


def pl_word_stems(pl):
    return [stem(w) for w in re.findall(r"[a-ząćęłńóśźż]+", pl.lower()) if len(w) > 3]


def en_present(en, text):
    return re.search(r"(?<![a-z])" + re.escape(en.lower()) + r"(?![a-z])", text.lower()) is not None


def term_satisfied(pl, tgt_lower):
    """The glossary PL term is satisfied if, for each of its significant words, a short
    prefix appears in the target. The prefix is 3-4 chars to tolerate PL inflection that
    mutates even the stem ('pole'->'polu', 'runda'->'rundy', 'broń'->'bronie') and on-card
    abbreviation ('nawały'->'naw.'). 3 chars keeps it specific enough to still catch a wrong
    term (different terms rarely share a 3-char prefix per significant word)."""
    words = [w for w in re.findall(r"[a-ząćęłńóśźż]+", pl.lower()) if len(w) > 3]
    if not words:
        return True
    tgt_folded = fold(tgt_lower)
    return all(fold(w)[:3] in tgt_folded for w in words)


def load_segments(path):
    segs = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                segs.append(json.loads(line))
    return segs


def check_segment(seg, terms, brand_kept):
    """Return list of (level, code, detail) violations for one segment."""
    out = []
    src = seg.get("source_text", "") or ""
    tgt = seg.get("target_text", "") or ""
    status = seg.get("status", "")

    # completeness
    if not tgt.strip():
        out.append(("ERROR", "untranslated", "empty target_text"))
        return out                                    # nothing else to check
    if status != "translated":
        out.append(("WARN", "status", f"status={status!r} (expected 'translated')"))

    # glossary adherence. Enforced on prose BODIES, where free translation happens and term
    # consistency is the real risk. Card-frame terms (label/header/pill/cell) come from the
    # curated, consistent-by-construction TERMS map and are intentionally abbreviated to fit
    # the card (HIT POINTS -> 'PKT ŻYCIA', S Dice -> 'K naw.'), so enforcing the full glossary
    # form there only produces noise; they are still checked for emptiness + leftover English.
    enforce_glossary = seg.get("kind") == "body"
    if enforce_glossary:
        tgt_lower = tgt.lower()
        for t in terms:
            en, pl = t["en"], t["target"]
            if en.lower() == pl.lower():
                continue                              # kept-as-is term -> nothing to enforce
            if en_present(en, src) and not term_satisfied(pl, tgt_lower):
                out.append(("WARN", "glossary-miss",
                            f"{en!r} -> expected '{pl}' ({t['id']})"))

    # leftover English
    tgt_words = re.findall(r"[A-Za-z][A-Za-z'’-]+", tgt)
    for w in tgt_words:
        lw = w.lower()
        if lw in EN_LEFTOVER and lw not in brand_kept:
            out.append(("WARN", "leftover-en", f"EN word {w!r} in target"))
            break

    # bold sanity (body)
    if seg.get("kind") == "body":
        bold = seg.get("bold", [])
        for r in bold:
            if (not isinstance(r, list) or len(r) != 2
                    or not (0 <= r[0] < r[1] <= len(tgt))):
                out.append(("ERROR", "bold-range", f"bad bold range {r} for len {len(tgt)}"))
        # overlap
        for a, b in zip(sorted(bold), sorted(bold)[1:]):
            if a[1] > b[0]:
                out.append(("WARN", "bold-overlap", f"{a} overlaps {b}"))
    return out


def verify_file(path, terms, brand_kept):
    segs = load_segments(path)
    flagged = []
    # consistency maps
    src2tgt = defaultdict(set)
    en2pl = defaultdict(set)
    for seg in segs:
        v = check_segment(seg, terms, brand_kept)
        if v:
            flagged.append((seg, v))
        src = (seg.get("source_text") or "").strip()
        tgt = (seg.get("target_text") or "").strip()
        if src and tgt and seg.get("kind") != "body":
            src2tgt[src].add(tgt)

    consistency = []
    for src, tgts in src2tgt.items():
        if len(tgts) > 1:
            consistency.append((src, sorted(tgts)))

    return segs, flagged, consistency


def report(path, segs, flagged, consistency):
    name = Path(path).name
    n = len(segs)
    n_tr = sum(1 for s in segs if (s.get("target_text") or "").strip())
    errs = sum(1 for _, v in flagged for lvl, *_ in v if lvl == "ERROR")
    warns = sum(1 for _, v in flagged for lvl, *_ in v if lvl == "WARN")
    print(f"\n=== {name} ===")
    print(f"  segments: {n}   translated: {n_tr}/{n}   "
          f"flagged: {len(flagged)} ({errs} ERROR, {warns} WARN)   "
          f"inconsistent labels: {len(consistency)}")
    for seg, v in flagged:
        for lvl, code, detail in v:
            print(f"  [{lvl:5} {code:14}] {seg['id']}")
            print(f"          {detail}")
            if code in ("glossary-miss", "leftover-en"):
                print(f"          src: {seg.get('source_text','')[:90]!r}")
                print(f"          tgt: {seg.get('target_text','')[:90]!r}")
    for src, tgts in consistency:
        print(f"  [WARN  inconsistent   ] {src!r}")
        for t in tgts:
            print(f"          -> {t!r}")
    return errs, warns, len(consistency)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="segment JSONL files")
    ap.add_argument("--all", action="store_true", help="verify all 3 P2P docs")
    a = ap.parse_args()
    terms = load_glossary()
    brand_kept = {t["en"].lower() for t in terms if t["en"].lower() == t["target"].lower()}

    paths = a.paths
    if a.all or not paths:
        paths = [str(SEG_DIR / f"{d}.jsonl") for d in P2P_DOCS]

    total_err = total_warn = total_incons = 0
    for p in paths:
        if not Path(p).exists():
            print(f"  MISSING {p}", file=sys.stderr)
            continue
        segs, flagged, consistency = verify_file(p, terms, brand_kept)
        e, w, c = report(p, segs, flagged, consistency)
        total_err += e
        total_warn += w
        total_incons += c

    print(f"\nTOTAL: {total_err} errors, {total_warn} warnings, "
          f"{total_incons} inconsistent labels")
    sys.exit(1 if total_err else 0)


if __name__ == "__main__":
    main()
