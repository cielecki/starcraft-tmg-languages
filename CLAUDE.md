# CLAUDE.md — StarCraft TMG language versions

AI working notes for this repo. Read [docs/architecture.md](docs/architecture.md) and
[docs/findings.md](docs/findings.md) before substantive work.

## What this is
A language-agnostic localization pipeline for the free print-and-play **StarCraft: The Tabletop
Miniatures Game** (Archon Studio) materials. **Polish is the first target.** Terminology must
match Blizzard's **official PL localizations of StarCraft I/II** — player familiarity over literal
translation.

## Hard rules
- **Never commit copyrighted binaries or bulk source text.** Source PDFs, raw game-string dumps,
  and generated output PDFs are gitignored. Commit only: tooling, the glossary (term pairs), and
  translated target text. Keep EN source text local (under `sources/`), commit the target side.
- **Translation is multi-pass, never one-shot.** The rulebook is 128 pp. Extract → chunk →
  glossary-constrained translate → automated verify → human review. Re-translate only failing segments.
- **The glossary is the source of truth for terms.** Every translation pass is constrained by it
  and checked against it by the verifier before being considered done.
- **Language-agnostic.** Anything PL-specific lives under a `<lang>/` path; code takes a `lang` param.

## Source endpoints (see docs/findings.md for detail)
- PDFs: `https://starcraft-tmg.com/files/downloads/<name>_EN.pdf` (list in `scripts/fetch_sources.py`).
- Firestore (public, no auth): project+db `starcrafttmgbeta`, collections `army_units`,
  `tactical_cards`, `faction_cards`, `rules_sections`, `map_assets_terrain`, …

## Conventions
- Python scripts in `scripts/`; prefer stdlib + already-present libs (`fitz`, `PIL`, `bs4`).
  HTML→PDF: Prince (best), Chrome headless, or WeasyPrint.
- Intermediate translation format: JSON Lines, one record per segment
  (`id, doc, page, source_text, target_text, status, notes`).
- Glossary record: `{ id, en, target, category, source, confidence, notes }`.

## Workflow / commits
- Personal project; commit to `main` is fine. Keep commits scoped per subsystem/issue.
- Work is tracked in GitHub Issues (milestones M1–M5). Reference issues in commits.

## Fonts
SC display fonts (Aviano/Gineso) are subsetted in the PDFs and lack PL glyphs — do not try to
reuse them. Substitute PL-capable look-alikes (Oswald / Bebas Neue / Barlow Condensed / DIN
Condensed) and embed full glyph sets.
