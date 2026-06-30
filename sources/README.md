# sources/ — fetched on demand (gitignored)

This directory holds the **source material** the pipeline operates on. Its binary contents are
**not committed** (Blizzard / Archon IP — see `../NOTICE.md`). Only `manifest.json` and this
README are tracked.

Populate it locally:

```bash
python3 scripts/fetch_sources.py        # downloads PDFs + Firestore JSON
```

Layout after fetch:

```
sources/
  manifest.json        # tracked: url, file, sha256, bytes, pages per asset
  pdf/                 # gitignored: the EN PDFs
  firestore/           # gitignored: army_units.json, tactical_cards.json, ...
```
