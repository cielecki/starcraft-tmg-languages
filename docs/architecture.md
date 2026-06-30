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

**Realized (P2P card sheets).** The pipeline above is implemented in `scripts/translate/` and the
glossary in `glossary/pl.csv` (214 EN→PL term pairs):
- `extract_segments.py` — deterministic segmenter: one record per translatable unit
  (`kind` ∈ label/header/pill/cell/body), written to `data/segments/<doc>.jsonl`. Ability **bodies**
  carry `id` = `"<doc>:p<page>:ability:<block_index>"`, the source-bold char ranges in `bold`, and
  **`header_source`** = the EN ability-header the body belongs to (see the alignment note below).
- `translate_segments.py` — glossary-constrained PL fill of `target_text`.
- `verify_segments.py` — glossary-adherence + consistency checks over the filled segments.
- The three real P2P sheets (`StarCraft-{Protoss,Terran,Zerg}-P2P-Card-Sheets-A4_EN.jsonl`,
  3920 segments) are the committed target side; the layout engine (subsystem 4) consumes them.

**Body-alignment contract (extractor ↔ layout engine).** The extractor and the in-place layout
engine **detect ability blocks by different signals** (extractor: grey `#dadad9` panel + 4-orientation
transform; engine: ExtraBold `…:` header font), so their block ORDER — and thus a body's positional
`block_index` — can disagree. Matching a PL body to an ability by `block_index` alone would land it on
the WRONG ability. The robust key is therefore the **EN ability header** (`header_source`): it is
stable and language-independent. The engine matches each detected block's header to the body's
`header_source` (exact, then unique-substring for multi-span header splits like
`KINETIC FOAM:` ⊂ `VETERAN OF KINETIC FOAM:`), and only falls back to the positional `block_index`
when no header key is usable (a pre-`header_source` JSONL, or a page with a duplicate header). Labels
/ headers / pills / cells stay matched by `(doc, source_text)`, which is already order-independent.

### 4. PDF generation  (`scripts/generate/`, output → `build/` gitignored)
Strategy decided by **[Spike A](spike-pdf.md)** — per document type:
- **Rulebook / manuals → in-place region-reflow:** erase each text region by painting the sampled
  flat background (PyMuPDF redaction, `images=PDF_REDACT_IMAGE_NONE` keeps art), then reflow
  translated PL into the region with `insert_textbox` (wrap + shrink-to-fit) in a PL-glyph font.
  Preserves the bespoke design (panels, boxes, diagrams) for free. Region-level, never per-span.
- **Cards → in-place faithful-typography reflow (`scripts/generate/card_inplace.py`).** The
  original "template rebuild" plan was superseded: the cards are typeset in **Noto Sans Condensed**
  (free, PL-capable), so we redraw each translated span in the matching Noto weight at its original
  position — exact layout, no rebuild. The engine **auto-detects** ability blocks (the unique
  `NotoSans-CondensedExtraBold` UPPERCASE colon-header is the anchor; orientation from reading
  direction — front card rotated 180°, back card upright), **derives** each body's geometry from the
  original prose spans (baseline / wrap-width / line-spacing / start-after-pills), and reflows the PL
  body as rich text so bold game-terms stay bold. Works on every race's P2P unit-card pages.
  - **Translations come from a segments JSONL**, NOT hardcoded: `data/segments/<doc>.jsonl`
    (`--segments` CLI arg, default by PDF stem). Labels/headers/pills/cells looked up by
    `(doc, source_text)→target_text`; ability bodies by id `"<doc>:p<page>:ability:<block_index>"`
    (block_index = ability reading order) → `target_text` + `bold` ([[start,end],…] char ranges).
    A missing segment falls back to leaving the original EN — never crashes.
  - **CLI:** `python3 scripts/generate/card_inplace.py <pdf> <pages> <lang> [--segments PATH]` where
    `<pages>` is `N` / `a-b` / `c,d,e` / `all`. A development **fixture** lives at
    `data/segments/<doc>.fixture.jsonl` (generated by `scripts/generate/make_fixture.py` from the
    old hardcoded Adept data) so the engine renders the Adept pixel-identically without the real JSONL.
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
- ~~Achievable rulebook fidelity (rebuild vs in-place)?~~ → resolved by [Spike A](spike-pdf.md):
  rulebook = in-place region-reflow, cards = template rebuild.
- CASC extraction on macOS — which tool works? (Spike B, in progress)
- Commit boundary for intermediate files containing EN source text (currently: keep EN source
  local, commit target text + glossary).
- Which documents are in v1 scope (rulebook + 3 P2P card sheets first?).
