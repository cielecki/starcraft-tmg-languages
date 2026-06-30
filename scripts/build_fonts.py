#!/usr/bin/env python3
"""Build the Noto Sans Condensed static weights the cards use (Regular/Medium/ExtraBold/Black).

The SC:TMG cards are typeset in Noto Sans Condensed (a free, Polish-capable font). We instance the
exact weights at width=75 (Condensed) from Google's Noto Sans variable font so Polish text matches
the original typography. OFL-licensed -> the instances are committed under assets/fonts/.
"""
import urllib.request, tempfile
from pathlib import Path
from fontTools import ttLib
from fontTools.varLib.instancer import instantiateVariableFont

VAR_URL = "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans%5Bwdth%2Cwght%5D.ttf"
WEIGHTS = {"Regular": 400, "Medium": 500, "ExtraBold": 800, "Black": 900}
OUT = Path(__file__).resolve().parents[1] / "assets/fonts"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.gettempdir()) / "NotoSans-var.ttf"
    if not tmp.exists():
        urllib.request.urlretrieve(VAR_URL, tmp)
    for name, wght in WEIGHTS.items():
        f = ttLib.TTFont(tmp)
        instantiateVariableFont(f, {"wght": wght, "wdth": 75}, inplace=True)
        dst = OUT / f"NotoSansCond-{name}.ttf"
        f.save(dst)
        print("wrote", dst.name)


if __name__ == "__main__":
    main()
