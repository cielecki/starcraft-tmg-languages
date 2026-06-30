#!/usr/bin/env python3
"""Fetch all StarCraft TMG English source materials into sources/ (gitignored).

Downloads:
  - the free print-and-play EN PDFs from starcraft-tmg.com
  - the publicly-readable Command Center Firestore collections (card/rules text as JSON)

Writes a tracked sources/manifest.json (url, file, sha256, bytes, pages). Re-running skips
files already present unless --force.

Usage:
  python3 scripts/fetch_sources.py            # fetch everything
  python3 scripts/fetch_sources.py --force    # re-download
  python3 scripts/fetch_sources.py --pdf-only # skip Firestore
"""
from __future__ import annotations
import argparse, hashlib, json, sys, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "sources"
PDF_DIR = SRC / "pdf"
FS_DIR = SRC / "firestore"

PDF_BASE = "https://starcraft-tmg.com/files/downloads/"
PDFS = [
    "StarCraft-TMG_EN.pdf",                       # 128pp core rulebook
    # Per-unit packs (assembly + components)
    "StarCraft-Terran-Marine_EN.pdf", "StarCraft-Terran-Marauder_EN.pdf",
    "StarCraft-Terran-Medic_EN.pdf", "StarCraft-Terran-Goliath_EN.pdf",
    "StarCraft-Terran-JimRaynor-RR_EN.pdf",
    "StarCraft-Protoss-Zealot_EN.pdf", "StarCraft-Protoss-Stalker_EN.pdf",
    "StarCraft-Protoss-Adept_EN.pdf", "StarCraft-Protoss-Sentry_EN.pdf",
    "StarCraft-Protoss-Artanis-H_EN.pdf",
    "StarCraft-Zerg-Zergling_EN.pdf", "StarCraft-Zerg-Roach_EN.pdf",
    "StarCraft-Zerg-Hydralisk_EN.pdf", "StarCraft-Zerg-Queen_EN.pdf",
    "StarCraft-Zerg-Kerrigan-PK_EN.pdf",
    # Playable print-and-play card sheets
    "StarCraft-Terran-P2P-Card-Sheets-A4_EN.pdf",
    "StarCraft-Protoss-P2P-Card-Sheets-A4_EN.pdf",
    "StarCraft-Zerg-P2P-Card-Sheets-A4_EN.pdf",
    # Terrain / starters / promo
    "StarCraft-Terrain-Lost-Temple_EN.pdf",
    "StarCraft-2P-Starter-Set-FE_EN.pdf",
    "StarCraft-Protoss-Starter-Set-FE_EN.pdf",
    "Zeratul Promo Manual.pdf",
]

FS_PROJECT = FS_DB = "starcrafttmgbeta"
FS_BASE = (f"https://firestore.googleapis.com/v1/projects/{FS_PROJECT}"
           f"/databases/{FS_DB}/documents/")
FS_COLLECTIONS = ["army_units", "tactical_cards", "faction_cards", "rules_sections",
                  "map_assets_terrain", "map_backgrounds", "saved_maps"]

UA = {"User-Agent": "Mozilla/5.0 (sctmg-languages fetcher)"}


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def page_count(path: Path) -> int | None:
    try:
        import fitz
        with fitz.open(path) as d:
            return d.page_count
    except Exception:
        return None


def fetch_pdfs(force: bool) -> list[dict]:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for name in PDFS:
        dest = PDF_DIR / name
        url = PDF_BASE + urllib.parse.quote(name)
        if dest.exists() and not force:
            data = dest.read_bytes()
            print(f"  skip   {name} (exists)")
        else:
            print(f"  get    {name}")
            try:
                data = get(url)
            except Exception as e:
                print(f"  FAIL   {name}: {e}", file=sys.stderr)
                continue
            dest.write_bytes(data)
        out.append({"type": "pdf", "url": url, "file": f"pdf/{name}",
                    "bytes": len(data), "sha256": sha256(data),
                    "pages": page_count(dest)})
    return out


def fetch_firestore(force: bool) -> list[dict]:
    FS_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for col in FS_COLLECTIONS:
        dest = FS_DIR / f"{col}.json"
        url = f"{FS_BASE}{col}?pageSize=400"
        if dest.exists() and not force:
            data = dest.read_bytes()
            print(f"  skip   firestore/{col} (exists)")
        else:
            print(f"  get    firestore/{col}")
            try:
                data = get(url)
            except Exception as e:
                print(f"  FAIL   firestore/{col}: {e}", file=sys.stderr)
                continue
            dest.write_bytes(data)
        try:
            n = len(json.loads(data).get("documents", []))
        except Exception:
            n = None
        out.append({"type": "firestore", "url": url, "file": f"firestore/{col}.json",
                    "bytes": len(data), "sha256": sha256(data), "documents": n})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--pdf-only", action="store_true")
    a = ap.parse_args()
    SRC.mkdir(parents=True, exist_ok=True)
    print("Fetching PDFs:")
    manifest = fetch_pdfs(a.force)
    if not a.pdf_only:
        print("Fetching Firestore collections:")
        manifest += fetch_firestore(a.force)
    (SRC / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"\nWrote {SRC/'manifest.json'} ({len(manifest)} assets).")


if __name__ == "__main__":
    main()
