#!/usr/bin/env python3
"""Minimal glossary verifier.

verify(en_text, pl_text, glossary) -> list of violations: for every glossary EN term that
appears in the source, check the canonical PL term (stem) appears in the translation.
Inflection-tolerant (matches on a stem), case-insensitive. This is the seed of issue #9.
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(lang="pl"):
    return json.loads((ROOT / f"glossary/{lang}/glossary.json").read_text())["terms"]


def stem(w):
    w = w.lower()
    return w[:max(4, len(w) - 2)]  # crude PL-inflection-tolerant stem


def verify(en_text, pl_text, terms):
    el, pl = en_text.lower(), pl_text.lower()
    out = []
    for t in terms:
        en = t["en"].lower()
        if re.search(r"(?<![a-z])" + re.escape(en) + r"(?![a-z])", el):
            # multiword PL: require every significant word's stem present
            words = [w for w in re.findall(r"[a-ząćęłńóśźż]+", t["pl"].lower()) if len(w) > 2]
            ok = all(stem(w) in pl for w in words) if words else True
            if not ok:
                out.append({"en": t["en"], "expected_pl": t["pl"], "id": t["id"]})
    return out


def _gather(obj, en=None, pl=None):
    en = [] if en is None else en
    pl = [] if pl is None else pl
    if isinstance(obj, dict):
        if "en" in obj and "pl" in obj and isinstance(obj["en"], str):
            en.append(obj["en"]); pl.append(obj["pl"])
        else:
            for v in obj.values():
                _gather(v, en, pl)
    elif isinstance(obj, list):
        for v in obj:
            _gather(v, en, pl)
    return en, pl


def main(path):
    terms = load()
    data = json.loads(Path(path).read_text())
    en, pl = _gather(data)
    v = verify(" \n".join(en), " \n".join(pl), terms)
    print(f"{path}: {len(en)} en/pl pairs, {len(v)} potential glossary misses")
    for x in v:
        print(f"   MISS  {x['en']} -> expected '{x['expected_pl']}' ({x['id']})")
    return v


if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(p)
