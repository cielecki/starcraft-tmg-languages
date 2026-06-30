# Findings — investigation log

Captured 2026-06-30 before building anything. These facts drive the architecture.

## Source assets (all English, free print-and-play)

From <https://starcraft-tmg.com/downloads> (base: `https://starcraft-tmg.com/files/downloads/`).
**No localized PDFs exist** — the `?lang=pl` (and de/es/fr/ko) toggle changes only site chrome;
every linked file is still `_EN.pdf`. ~23 PDFs total:

- **Core Rules Book** — `StarCraft-TMG_EN.pdf`, **128 pp**, 612×792 pt (US Letter), 15.7 MB.
- **Per-unit packs** (~16 pp each): Protoss (Adept, Artanis-H, Sentry, Stalker, Zealot),
  Terran (Goliath, Jim Raynor-RR, Marauder, Marine, Medic), Zerg (Hydralisk, Kerrigan-PK,
  Queen, Roach, Zergling). These are **assembly instructions + components sheets**, not the
  gameplay stat cards.
- **P2P card sheets** — `StarCraft-{Protoss,Terran,Zerg}-P2P-Card-Sheets-A4_EN.pdf` (the
  print-and-play playable cards).
- **Terrain** — `StarCraft-Terrain-Lost-Temple_EN.pdf`.
- **Starter sets** — `StarCraft-2P-Starter-Set-FE_EN.pdf`, `StarCraft-Protoss-Starter-Set-FE_EN.pdf`.
- **Promo** — `Zeratul Promo Manual.pdf`.

## Structured data (the bonus asset)

The official "Command Center" (army builder / map editor / rules ref) is a Firebase SPA whose
Firestore is **publicly readable over REST, no auth**. Project `starcrafttmgbeta`, **named**
database `starcrafttmgbeta` (not `(default)`):

```
https://firestore.googleapis.com/v1/projects/starcrafttmgbeta/databases/starcrafttmgbeta/documents/<collection>?pageSize=300
```

Collections of interest: `army_units`, `tactical_cards`, `faction_cards` (178), `rules_sections`,
`map_assets_terrain`, `map_backgrounds`, `saved_maps`. This gives much of the card/rules **text
as clean JSON** — far easier to translate than re-extracting from designed PDFs.

## PDF technical reality (this inverts the naive plan)

Naive assumption was "cards are easy to text-swap, the rulebook is the hard one." Inspection
(PyMuPDF) shows it's more nuanced:

- **Rulebook** — has a **real extractable text layer**, BUT:
  - Custom **subsetted** display fonts (`AvianoFutureBlack/Bold`, `Gineso-*` condensed family,
    `Geogrotesque`, `NotoSans-Condensed`, `Wingdings3` for icons). Subset tags (`ANSOEO+…`) mean
    each font carries only the glyphs used → **Polish diacritics (ą ć ę ł ń ó ś ź ż) are almost
    certainly absent** → in-place replacement renders tofu unless fonts are re-embedded.
  - Magazine layout, multi-column, dot-leader TOC, callout boxes. Text is **span-fragmented**
    (a sentence is many tiny positioned runs).
  - Polish runs ~10–20% longer than English → text **overflows** original span boxes.
  → In-place swap is fragile; a **structured rebuild** likely yields the clean result.
- **Unit packs / cards** — a **mix**: cover pages and card backs are **flattened raster images**
  (no text, no fonts — e.g. Marine pack page 0/1/14 are pure images); instruction/stat pages
  carry **live text over high-res (300 dpi) background images**. So text-swap works only on the
  live-text pages; baked-in art text needs rebuild or inpaint+overlay.

**Implication:** the PDF-generation subsystem needs (at least) two regimes — *card/template
rebuild* vs *rulebook structured rebuild* — and a spike to measure achievable fidelity for each.

## Toolchain available on this Mac

- Python: `fitz` (PyMuPDF) ✓, `PIL` ✓, `bs4`/`lxml` ✓; `reportlab` ✗, `cairosvg` ✗ (installable).
- HTML→PDF: **`prince`** ✓ (`/usr/local/bin/prince`, best CSS print fidelity), **`wkhtmltopdf`** ✓,
  **Google Chrome** ✓ (headless), **WeasyPrint** Python module ✓ (CLI not on PATH); `npx` ✓.
- Fonts: system has condensed grotesques usable as SC-display substitutes with full PL glyphs —
  `DIN Condensed`, `Arial Narrow`, `Impact`; good free matches to fetch: Oswald, Bebas Neue,
  Barlow Condensed, Teko. The Aviano/Gineso originals are subsetted in the PDF (not reusable);
  we substitute look-alikes and embed full glyph sets.

## Corpus decision

Maciej has **StarCraft I installed** and will **install StarCraft II** so we can extract the
official Polish strings (CASC). macOS CASC extraction tooling needs validation (spike). Hybrid
fallback: community sources (PL StarCraft wiki / Liquipedia) for breadth, upgraded to
game-extracted strings where it matters, each term tagged with source + confidence.

## Related local context

`apps/starcraft-tmg-ai` is a **separate** project (computer-vision board-state detection toward
an AI bot). It already holds a copy of the rulebook PDF and scraped game data, but its goals are
unrelated to localization. This repo is standalone.
