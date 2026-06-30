#!/usr/bin/env python3
"""Generate a localized unit card by rebuilding from structured data (Spike A approach).

Reads a translated card JSON (translations/<lang>/cards/<id>.json), renders an HTML/CSS card
template, and produces a PDF via Prince (offline, honours @page size). No erase artifacts.
"""
import json, subprocess, sys, html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def esc(s):
    return html.escape(str(s))


def render_html(c):
    stats = "".join(
        f'<div class="stat"><span class="sl">{esc(s["label_pl"])}</span>'
        f'<span class="sv">{esc(s["value"])}</span></div>' for s in c["stats"])
    sq = c["squadProfile"]
    sq_head = "".join(f"<th>{esc(h)}</th>" for h in sq["header_pl"])
    sq_rows = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>"
                      for row in sq["rows"])
    ups = "".join(
        f'<div class="up"><div class="un">{esc(u["name"]["pl"])}'
        f'<span class="um">{esc(u["meta_pl"])}</span></div>'
        f'<div class="ud">{esc(u["desc"]["pl"])}</div></div>' for u in c["upgrades"])
    return f"""<!doctype html><html lang="pl"><head><meta charset="utf-8"><style>
@page {{ size: 72mm 108mm; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: "Arial Narrow","DIN Condensed Bold",sans-serif;
        background:#0c1426; color:#e8ecf4; width:72mm; height:108mm; }}
.card {{ height:108mm; display:flex; flex-direction:column; }}
.band {{ background:#f0c419; color:#0c1426; font-weight:bold; letter-spacing:.5px;
         font-size:8pt; padding:2mm 3mm; display:flex; justify-content:space-between; }}
.name {{ font-size:17pt; font-weight:bold; color:#f0c419; padding:2mm 3mm 0; letter-spacing:.5px; }}
.sub {{ font-size:7.5pt; color:#9fb0c8; padding:0 3mm 1.5mm; }}
.stats {{ display:flex; flex-wrap:wrap; gap:1mm; padding:1mm 3mm; }}
.stat {{ background:#16213c; border:.3mm solid #2a3a5c; border-radius:1mm; padding:.6mm 1.6mm;
         display:flex; flex-direction:column; align-items:center; min-width:11mm; }}
.sl {{ font-size:5.6pt; color:#9fb0c8; text-transform:uppercase; }}
.sv {{ font-size:10pt; font-weight:bold; color:#fff; }}
table {{ width:calc(100% - 6mm); margin:1mm 3mm; border-collapse:collapse; font-size:6.6pt; }}
th {{ background:#1c2a4a; color:#f0c419; }}
th,td {{ border:.25mm solid #2a3a5c; padding:.5mm; text-align:center; }}
.ups {{ padding:1mm 3mm 2mm; overflow:hidden; }}
.up {{ margin-bottom:1.4mm; }}
.un {{ font-size:7.6pt; font-weight:bold; color:#f0c419; border-bottom:.25mm solid #2a3a5c; }}
.um {{ font-size:5.6pt; color:#9fb0c8; font-weight:normal; float:right; }}
.ud {{ font-size:6.4pt; color:#d4ddec; line-height:1.18; }}
</style></head><body><div class="card">
  <div class="band"><span>{esc(c["faction"]["pl"])}</span><span>{esc(c["unitType"]["pl"])}</span></div>
  <div class="name">{esc(c["name"]["pl"])}</div>
  <div class="sub">{esc(c["tags"]["pl"])}</div>
  <div class="stats">{stats}</div>
  <table><tr>{sq_head}</tr>{sq_rows}</table>
  <div class="ups">{ups}</div>
</div></body></html>"""


def main(lang="pl", card_id="adept"):
    c = json.loads((ROOT / f"translations/{lang}/cards/{card_id}.json").read_text())
    out = ROOT / f"build/{lang}/cards"; out.mkdir(parents=True, exist_ok=True)
    htmlf = out / f"{card_id}_{lang}.html"; pdf = out / f"{card_id}_{lang}.pdf"
    htmlf.write_text(render_html(c), encoding="utf-8")
    r = subprocess.run(["prince", str(htmlf), "-o", str(pdf)], capture_output=True, text=True)
    if r.returncode != 0:
        print("prince error:", r.stderr[:400]); sys.exit(1)
    import fitz
    fitz.open(pdf)[0].get_pixmap(dpi=200).save(out / f"{card_id}_{lang}.png")
    print("wrote", pdf)


if __name__ == "__main__":
    main(*(sys.argv[1:] or []))
