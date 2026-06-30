# Architecture — language-agnostic localization pipeline

Polish is the first target; every component takes `lang` as a parameter so other languages reuse
the same machinery. Design favors small, independently-testable units with clear interfaces.

## Subsystems

### 1. Acquisition & scaffolding
- `scripts/fetch_sources.py` — download all EN PDFs + Firestore collections into `sources/`
  (gitignored), write a tracked `sources/manifest.json` (url, filename, sha256, bytes, pages).
- Repo conventions, CLAUDE.md, license/NOTICE, this doc.
- **Interface out:** local source files + manifest.

### 2. Glossary / corpus  (`corpus/`, `glossary/<lang>/`)
- Extract official **SC1 + SC2 PL** strings (CASC) → `corpus/raw/` (gitignored).
- Distill into `glossary/pl/glossary.json`: records of
  `{ id, en, target, category(unit|ability|resource|faction|keyword|ui), source, confidence, notes }`.
- A **verifier** library: given source EN + candidate translation, flag terms that diverge from
  the canonical target (missing/forbidden/inconsistent) → machine-checkable.
- **Interface out:** `lookup(en) -> target`, `verify(en, translated) -> [violations]`.

### 3. Translation pipeline  (`translations/<lang>/`)
- **Extract** each document → segmented editable intermediate (JSON Lines: one record per text
  segment with `id, doc, page, source_text, context`), so the long rulebook is addressable in
  chunks. Cards/rules prefer the Firestore JSON over PDF extraction where possible.
- **Translate** in chunks, **glossary-constrained** (the glossary is injected into each prompt;
  not a single one-shot pass over 128 pp).
- **Verify** passes (automated, repeatable): glossary adherence, completeness (no dropped
  segments), consistency (same EN term → same target across the corpus), length/overflow budget,
  optional back-translation sanity. Failures route specific segments back for re-translation.
- **Human review** gate before a document is marked done.
- **Interface out:** `translations/pl/<doc>.jsonl` (source+target per segment), status-tracked.

### 4. PDF generation  (`scripts/generate/`, output → `build/` gitignored)
- **Cards/templates:** rebuild from structured fields over the original art (or live-text swap
  where the PDF allows), with full-glyph fonts.
- **Rulebook:** structured rebuild (HTML/CSS → PDF via Prince/Chrome/WeasyPrint) reconstructing
  the layout, OR in-place font-fixed swap — **the spike decides** which is viable per fidelity bar.
- **Font strategy:** substitute SC display fonts (Aviano/Gineso) with PL-glyph-capable
  look-alikes (Oswald/Bebas/Barlow Condensed/DIN), embed full subsets.
- **Interface out:** localized PDFs, reproducible from committed text + fetched sources.

### 5. AI setup  (`.claude/`)
- Skills wrapping subsystems 2–4 (e.g. `build-glossary`, `translate-doc`, `verify-translation`,
  `generate-pdf`) + CLAUDE.md conventions so the long, multi-pass work is resumable/automatable.

## Build order

1. **Acquire + scaffold** (this repo).
2. **Spike A — PDF round-trip:** 1 rulebook page + 1 card, in-place vs rebuild → pick fidelity strategy.
3. **Spike B — Glossary bootstrap:** validate SC1/SC2 PL extraction on macOS → tiny EN→PL set.
4. **Glossary** (PL) — full extraction + dictionary + verifier.
5. **Translation pipeline** — extract → translate → verify → review (rulebook + cards).
6. **PDF generation** — per spike outcome, cards then rulebook.

Spikes A and B are independent and can run in parallel; both gate the full design.

## Open questions (tracked as issues)
- Achievable rulebook fidelity (rebuild vs in-place)?
- CASC extraction on macOS — which tool works?
- Commit boundary for intermediate files containing EN source text (currently: keep EN source
  local, commit target text + glossary).
- Which documents are in v1 scope (rulebook + 3 P2P card sheets first?).
