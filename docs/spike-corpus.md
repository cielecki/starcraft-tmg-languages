# Spike B — Blizzard PL corpus extraction (result)

Date: 2026-06-30. Question: can we extract the **official Polish** in-game strings from the
installed games to seed the glossary, on macOS? **Yes — for both games.**

## Outcome
- **Both StarCraft Remastered and StarCraft II ship full official Polish text.** (SC1R is *not*
  English-only, as feared.)
- Extracted on macOS by building **Ladislav Zezula's CascLib** from source + a ~40-line C
  extractor. No pip/npm CASC binding works; CascLib has its own HTTP client (no libcurl needed).
  No system installs beyond what was already present (cmake, clang, zlib).

## Where the Polish strings live

| Game | Path inside CASC (backslash-separated) | Format |
|------|----------------------------------------|--------|
| **SC1 Remastered** | `locales\plPL\Assets\rez\stat_txt.xml` (~178 KB) | XML `<string><id>..</id><value>name\000subtitle\000category</value></string>` |
| **SC2** | `mods\<mod>.sc2mod\plpl.sc2data\localizeddata\GameStrings.txt` | `Key=Value`, UTF-8 BOM. Richest: `liberty.sc2mod` (914 KB), `void.sc2mod` (LotV), `core.sc2mod`, `swarm.sc2mod` |

## Key gotchas (cost real time — don't rediscover)
- **cmake 4.x** dropped `<3.5` compat → CascLib configure fails unless you pass
  `-DCMAKE_POLICY_VERSION_MINIMUM=3.5`.
- **Local installs may be enUS-only at extraction time.** Non-English locales exist in the CASC
  *manifest* (name+size) but data blocks can be `avail=0` (not downloaded). Two fixes:
  1. **CascLib online mode** — fetches the exact file from Blizzard's CDN (byte-exact to the
     manifest; read-only, same data the patcher pulls). Used here for the plPL files.
  2. Or set the Blizzard client game language to **Polski** (Battle.net → game → Settings) and
     re-run; the plPL blocks become `avail=1` for purely-local extraction.
- **Alignment:** SC2 = join EN/PL on the `Key`. SC1 = **positional** pairing (identical 1551-entry
  ordering; split `<value>` on literal `\000`) — the PL file's ids use a hyphen (`..STRING-N`)
  where EN uses underscore (`..STRING_N`), so don't id-join.
- **Glossary hygiene:** (a) SC2 PL keeps gameplay anglicisms untranslated (Blink, Stimpack, Yamato
  Gun, Hydralisk, Mutalisk, Thor); (b) values may carry a `///` separator for grammatical variants
  (`Cyklon /// Cyclone`); (c) strip SC2 markup tags `<c>`, `<n/>`, `<d .../>` from values.

## Sample of verified EN→PL terms

| EN | PL | Game | | EN | PL | Game |
|----|----|------|-|----|----|------|
| Stalker | Tropiciel | SC2 | | Sentry | Wartownik | SC2 |
| Marauder | Maruder | SC2 | | Zealot | Zelota | SC2 |
| Immortal | Nieśmiertelny | SC2 | | Adept | Adept | SC2 |
| Battlecruiser | Krążownik | SC2 | | Disruptor | Destabilizator | SC2 |
| Reaper | Żniwiarz | SC2 | | Colossus | Kolos | SC2 |
| Drone | Robotnica | SC2 | | Probe | Próbnik | SC2 |
| Overlord | Nadrządca | SC2 | | Void Ray | Promień otchłani | SC2 |
| SCV | ERK | SC2 | | Medivac | Prom medyczny | SC2 |
| Roach | Karakan | SC2 | | Minerals | Minerały | SC2 |
| Vespene Gas | Wespan | SC2 | | Marine / Zergling / Hydralisk | (unchanged) | SC2 |
| Protoss Carrier | Lotniskowiec protosów | SC1 | | Zerg Overlord | Nadrządca zergów | SC1 |
| Terran Siege Tank | Czołg oblężniczy terran | SC1 | | Protoss Dragoon | Dragon protosów | SC1 |

(SC1 uses race-suffixed names — "… terran/protosów/zergów"; SC2 uses bare unit names. The
glossary needs to reconcile the two registers — see issue #8.)

## Repeatable recipe
1. Build CascLib + extractors once: `scripts/corpus/build.sh`.
2. **List** to find a file: `casc_list "<storage>" "gamestrings.txt"` (SC2) / `"stat_txt.xml"` (SC1).
3. **Extract** local-first, else online:
   - local (data on disk): `casc_grab "<storage>" "<exact\path>" <outdir>`
   - online (plPL not downloaded): `casc_online <cache_dir> s1|s2 eu|us "<exact\path>" <outdir>`
     — use a fully-qualified path filter so substring matching doesn't drag in mutator mods.
4. **Align** EN↔PL (SC2 by key, SC1 positional) → distil to `glossary/pl/` (issue #8).

## Artifacts (in gitignored `corpus/raw/`)
`sc1_stat_txt_{plPL,enUS}.xml`, `sc2_{liberty,void}_plPL.txt` + enUS for core/liberty/void/swarm,
and `glossary_sc1_en_pl.csv` (1775 rows) + `glossary_sc2_en_pl.csv` (1341 rows). Raw strings stay
local (bulk Blizzard text); only the curated glossary gets committed.
