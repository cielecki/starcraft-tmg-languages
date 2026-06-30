# Spike A — PDF round-trip fidelity (result)

Date: 2026-06-30. Question: can we regenerate localized PDFs acceptably, and how — per document
type? Tested on **rulebook page 6** (designed two-column page) and **Protoss P2P card sheet
page 0** (unit cards). Throwaway code in scratch; sample renders not committed (Archon artwork).

## Verdict: viable. The right approach is **different per document type** — and it's the
**opposite** of the naive assumption ("cards easy, rulebook hard").

### Rulebook → in-place region-reflow ✅ (recommended)
- **Erase** original text by painting the *sampled local background* over each text region, with
  PyMuPDF redaction `apply_redactions(images=PDF_REDACT_IMAGE_NONE)` so images/vector graphics
  survive. The rulebook's text sits on **flat-colour panels**, so the erase is **clean** — the
  dark panels, coloured callout boxes, the board diagram, and the FRONTLINES sidebar were all
  preserved intact.
- **Re-typeset** translated Polish into each region with `insert_textbox` (word-wrap +
  shrink-to-fit), using a Polish-glyph font. Proven: the two body columns reflowed into clean,
  wrapped Polish (`Bitwa w StarCraft…`, `Następnie gracze…`) at 8.5 pt, and all headers swapped
  with correct diacritics (`CZĘŚĆ 1 / NAUKA GRY`, `PRZYKŁAD ROZGRYWKI: PIERWSZE RUNDY`,
  `POWRÓT DO SPISU TREŚCI`, `Karta taktyczna/frakcji/specjalna`).
- **Why in-place beats rebuild here:** it preserves the entire bespoke design for free. A
  from-scratch rebuild would have to recreate every panel, gradient, icon, and diagram.
- **Remaining work (not a blocker):** model *all* text regions per page (columns, boxes,
  captions) — not just one band — and feed real translations. Page layouts repeat across page
  families, so region templates are reusable. Volume (128 pp) is handled by the translation
  pipeline, not this step.
- **Failure mode to avoid:** naive *per-span* re-insertion does **not** reflow → longer Polish
  overflows/overlaps (seen in the first attempt). Always erase+reflow at the **region** level.

### Cards → template rebuild from structured data ✅ (recommended), NOT in-place
- In-place on cards is **fragile**: backgrounds are **gradients/art** (erase leaves seams) and
  the stat/ability boxes are **tight** (longer Polish overflows). The card-sheet in-place attempt
  was visibly messy.
- But the card **content already exists as clean JSON** in the public Command Center Firestore:
  `army_units` (26), `tactical_cards` (37), `faction_cards` (180). So bind translated fields into
  an **HTML/CSS card template** (SC card frame + unit art) and render via Prince/Chrome. Clean,
  reflow-friendly, zero erase artifacts, and trivially multi-language.

## Fonts
- The PDF's SC display fonts (Aviano/Gineso) are **subsetted** → no Polish glyphs → not reusable.
- Substituting a Polish-capable font works (proved with Arial Narrow). For production, use SC-style
  look-alikes with full glyph coverage: **Oswald / Bebas Neue / Barlow Condensed / DIN Condensed**,
  embedded as full subsets.

## Toolchain (all present on this Mac)
- In-place: **PyMuPDF (`fitz`)**.
- Rebuild HTML→PDF: **Prince** (best print CSS), **Chrome headless**, **WeasyPrint**.

## Impact on the architecture
- Subsystem 4 (PDF generation) splits cleanly: **cards = template rebuild from Firestore JSON**;
  **rulebook/manuals = in-place region-reflow**. Resolves the "rebuild vs in-place" open question.
