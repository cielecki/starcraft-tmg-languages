# StarCraft TMG — Language Versions

A community project to produce faithful **language versions** of the free print-and-play
materials for **StarCraft: The Tabletop Miniatures Game** (Archon Studio) — the rulebook,
unit packs, and cards.

**First target language: Polish (PL).** The pipeline is built language-agnostic, so other
languages (de / es / fr / ko / …) can follow without rework.

> Status: 🚧 early work-in-progress. See [Issues](../../issues) for the roadmap.

## Why this exists

Archon ships the SC:TMG materials in English only (the site's `?lang=pl` toggle still serves
the `_EN.pdf` files). This project translates them — with a twist: the goal is **terminology
fidelity to Blizzard's own official localizations** of StarCraft I and StarCraft II, so a Polish
player reads the exact unit / ability / resource names they already know from the video games,
not ad-hoc fan coinages.

## How it works (the pipeline)

```
  fetch sources ─▶ build glossary ─▶ extract text ─▶ translate (multi-pass,
  (PDFs + data)    (from official     to editable     glossary-constrained)
                    SC1/SC2 PL)        segments              │
                                                             ▼
                                          verify (glossary adherence,
                                          completeness, consistency)
                                                             │
                                                             ▼
                                              regenerate localized PDFs
```

Because the rulebook is ~128 pages, translation is **not** a single AI pass — it is chunked,
glossary-constrained, and put through automated verification passes before human sign-off.

## What's in this repo (and what isn't)

**Committed:** the tooling, the EN↔PL glossary, the translated text, and the build scripts.

**Not committed** (it's Blizzard / Archon IP): the source EN PDFs, raw extracted game strings,
and generated output PDFs. Run [`scripts/fetch_sources.py`](scripts/fetch_sources.py) to pull
the sources locally. See [`NOTICE.md`](NOTICE.md).

## Layout

| Path | What |
|------|------|
| `scripts/` | fetch sources, build glossary, translate, verify, generate PDFs |
| `sources/` | downloaded EN PDFs + game data (gitignored; `manifest.json` tracked) |
| `corpus/` | official SC1/SC2 PL string extractions → distilled glossary |
| `glossary/<lang>/` | the EN↔target term database + verifier rules |
| `translations/<lang>/` | per-document segmented text (source + translation) |
| `docs/` | [findings](docs/findings.md), [architecture](docs/architecture.md) |
| `.claude/` | AI setup (skills + conventions) for working in this repo |

## Disclaimer

Fan project. Not affiliated with or endorsed by Blizzard Entertainment or Archon Studio.
StarCraft® is a trademark of Blizzard Entertainment, Inc. See [`NOTICE.md`](NOTICE.md).
