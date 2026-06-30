#!/usr/bin/env python3
"""Extract translatable segments from a StarCraft TMG P2P card-sheet PDF.

Deterministic segmentation: every translatable text unit becomes exactly one segment.
Output is one JSON object per line (JSONL) at data/segments/<doc>.jsonl.

Segment kinds (`kind`):
  label   — card-frame labels: stat labels (HIT POINTS, ARMOUR, ...), UI labels
            (COMBAT ROLE:, ARMY SLOT:, COMBAT TAGS:), section banners (UNIT CARDS,
            PROTOSS FACTION). One per span.
  header  — ability headers (RESONATING GLAVES:, GUIDANCE:), phase-bar labels
            (COMBAT PHASE, MOVEMENT PHASE, UPGRADE), weapon-table titles (STRIKE,
            GLAIVE CANNON). One per span (multi-span headers are merged).
  pill    — ability cost/type chips: ACTIVE, PASSIVE, REACTION, "1 PE", "1 CP".
            One per span.
  cell    — table cells: column headers (NAME, RNG, Target, RoA, Hit, Surge type,
            S Dice, Dmg, Keyword) and weapon / squad-profile value cells. One per span.
  body    — one ability's wrapped prose: the prose spans inside an ability block that
            are NOT the header and NOT a pill, joined in reading order by single spaces.
            `bold` carries char ranges of the source-bold fragments (mapped to target on
            translation). Body id = "<doc>:p<page>:ability:<block_index>".

Design notes
------------
* Cards are physically rotated on the print sheet: front cards read upside-down
  (line dir == -1), backs read normally (dir == +1); some sheets carry dir == 0
  (tactical/faction card faces). We segment in each span's own reading frame.
* Bold is derived from the SOURCE font weight: NotoSans-Condensed{ExtraB,Black,Bold}
  are bold; {Medium,Regular,Italic} are regular (see IS_BOLD_FONT).
* Ability bodies are span-fragmented (a sentence is many positioned runs, each run a
  uniform weight). We reconstruct reading order, join by single spaces, and record the
  char ranges that were bold.

Usage:
  python3 scripts/translate/extract_segments.py sources/pdf/StarCraft-Protoss-P2P-Card-Sheets-A4_EN.pdf
  python3 scripts/translate/extract_segments.py --all      # all 3 P2P sheets in the manifest
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = ROOT / "sources" / "pdf"
OUT_DIR = ROOT / "data" / "segments"

P2P_SHEETS = [
    "StarCraft-Protoss-P2P-Card-Sheets-A4_EN.pdf",
    "StarCraft-Terran-P2P-Card-Sheets-A4_EN.pdf",
    "StarCraft-Zerg-P2P-Card-Sheets-A4_EN.pdf",
]

# --- font weight -> bold -----------------------------------------------------
BOLD_FONTS = {"NotoSans-CondensedExtraB", "NotoSans-CondensedBlack", "NotoSans-CondensedBold"}
PROSE_FONTS = {  # fonts a body sentence is set in (any weight, incl. italic)
    "NotoSans-CondensedMedium", "NotoSans-CondensedRegular",
    "NotoSans-CondensedBold", "NotoSans-CondensedExtraB",
    "NotoSans-CondensedBlack", "NotoSans-CondensedItalic",
}
# the colophon / copyright / version runs we never translate
SKIP_RE = re.compile(r"^(©|v ?\d|May \d|WIP$)")
# pure symbol / icon spans (Wingdings, arrows, bullets) -> not text
def is_symbol(t: str) -> bool:
    return all(ord(c) > 0x2000 or c in "·×—–…" for c in t) and bool(t)


def is_bold_font(font: str) -> bool:
    return font in BOLD_FONTS


# --- pill / header / label recognisers --------------------------------------
PILL_WORDS = {"ACTIVE", "PASSIVE", "REACTION"}
PILL_COST_RE = re.compile(r"^[X0-9]+ (PE|CP|BM)$")          # "1 PE", "2 CP", "X CP"
PHASE_WORDS = {"COMBAT PHASE", "ASSAULT PHASE", "MOVEMENT PHASE", "ANY PHASE",
               "UPGRADE", "U P G R A D E"}
# fixed table column headers (always cells)
COLUMN_HEADERS = {"NAME", "RNG", "Target", "RoA", "Hit", "Surge type",
                  "S Dice", "Dmg", "Keyword"}
# fixed card-frame stat / UI labels (always labels, never body)
STAT_LABELS = {"HIT POINTS", "ARMOUR", "ARMOR", "EVADE", "SIZE", "SPEED", "SHIELD",
               "MODELS / SUPPLY", "HP"}
UI_LABELS = {"COMBAT ROLE:", "ARMY SLOT:", "COMBAT TAGS:", "CLOSE COMBAT",
             "RANGED COMBAT", "UNIT CARDS", "TACTICAL CARDS", "FACTION CARDS",
             "SCENARIO CARDS - MISSION & DEPLOYMENT", "fold here", "SUPPLY",
             "MODELS / SUPPLY"}
FACTION_BANNER_RE = re.compile(r"^(PROTOSS|TERRAN|ZERG) FACTION$")
CARD_TYPE_BANNER = {"TACTICAL CARD", "FACTION CARD", "SPECIAL CARD", "UNIT CARD"}


def header_text_endswith_colon(font: str, text: str) -> bool:
    return font in ("NotoSans-CondensedExtraB",) and text.rstrip().endswith(":")


# --- geometry helpers --------------------------------------------------------
def span_dir(line) -> int:
    """Reading-direction code from the line's unit dir vector:
       0   -> (1,0)   normal (left->right)
       180 -> (-1,0)  upside-down (front cards on the fold sheet)
       90  -> (0,-1)  rotated CCW (vertical, reads bottom->top)  [tactical/faction sheets]
       270 -> (0,1)   rotated CW  (vertical, reads top->bottom)
    """
    dx, dy = line.get("dir", (1, 0))
    if abs(dx) >= abs(dy):
        return 0 if dx >= 0 else 180
    return 90 if dy < 0 else 270


# page dimensions, set per page before assembly (for the logical-frame transform)
PAGE_W = 595.3
PAGE_H = 841.9


def to_logical(x, y, d):
    """Page point -> the span's reading frame, so every orientation reads left->right,
    top->bottom and one row-major ordering handles them all. d is a rotation code from
    span_dir(): 0 identity, 180 = rotate 180°, 90 = card rotated CCW, 270 = rotated CW."""
    if d == 0:
        return x, y
    if d == 180:
        return PAGE_W - x, PAGE_H - y
    if d == 90:            # page (0,-1) reading: logical right = page up, logical down = page right
        return PAGE_H - y, x
    # d == 270: page (0,1): logical right = page down, logical down = page left
    return y, PAGE_W - x


def reading_key(s):
    """Sort key reproducing reading order in the span's own frame (logical row-major)."""
    lx, ly = to_logical(s["org"][0], s["org"][1], s["dir"])
    return (round(ly / 2.2) * 2.2, lx)


# --- grey ability panels -----------------------------------------------------
def grey_panels(page):
    """The #dadad9/#dadada filled bars that back an ability body."""
    out = []
    for d in page.get_drawings():
        f = d.get("fill")
        if f and all(abs(c - 0.855) < 0.025 for c in f):
            r = fitz.Rect(d["rect"])
            if r.width > 30 and 8 < r.height < 60:
                out.append(r)
    return out


def in_rect(bb, r, pad=1.0):
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    return r.x0 - pad <= cx <= r.x1 + pad and r.y0 - pad <= cy <= r.y1 + pad


# --- span collection ---------------------------------------------------------
def collect_spans(page):
    spans = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            d = span_dir(l)
            for s in l.get("spans", []):
                t = s["text"].strip()
                if not t:
                    continue
                spans.append({
                    "t": t, "bb": list(s["bbox"]), "org": list(s["origin"]),
                    "font": s["font"], "sz": round(s["size"], 1),
                    "color": s["color"], "dir": d,
                })
    return spans


# --- classification ----------------------------------------------------------
# single-faction banner words that appear ALONE as a strip banner (CondensedBlack sz~8)
FACTION_WORD = {"PROTOSS", "TERRAN", "ZERG", "KHALAI", "TARSONIS", "DAELAAM"}


def classify(s, weapon_baselines=None):
    """First-pass per-span kind, BEFORE body-grouping. Returns one of
    label/header/pill/cell/None(=prose-candidate)/skip.

    weapon_baselines: set of (dir, round(baseline_y)) for weapon-title headers. A
    prose-candidate sharing one of those baselines is a strike-table VALUE cell, not body.
    """
    t, font, sz = s["t"], s["font"], s["sz"]
    if SKIP_RE.match(t) or is_symbol(t):
        return "skip"
    if t in PILL_WORDS or PILL_COST_RE.match(t):
        return "pill"
    if t in PHASE_WORDS:
        return "header"
    if header_text_endswith_colon(font, t):
        return "header"
    if t in COLUMN_HEADERS:
        return "cell"
    # weapon-table TITLE (left-most ExtraB cell of a strike row, no colon) e.g. STRIKE,
    # GLAIVE CANNON, SWEEP, TWILIGHT BLADES — bold all-caps in a strike table.
    if font == "NotoSans-CondensedExtraB" and t.isupper() and not t.endswith(":"):
        return "header"
    if t in STAT_LABELS or t in UI_LABELS:
        return "label"
    if FACTION_BANNER_RE.match(t) or t in CARD_TYPE_BANNER:
        return "label"
    # lone faction-name strip banner (CondensedBlack ~8pt) -> frame label, not prose.
    if font == "NotoSans-CondensedBlack" and t in FACTION_WORD:
        return "label"
    # army-slot / model-class / combat-role frame tags: ALL-CAPS CondensedBlack at >=7.5pt
    # (TANK, HERO, 40MM, ELITE, CORE, DAMAGE DEALER, SUPPORT) — frame chrome, never prose.
    # (Body prose never sets a whole run in CondensedBlack at this size; bold body keywords
    # are ExtraB/Bold, and ACTIVE/PASSIVE pills are caught earlier.)
    if (font == "NotoSans-CondensedBlack" and sz >= 7.5 and t.isupper()
            and t not in PHASE_WORDS):
        return "label"
    # the 'UNIQUE' limit-1 marker (CondensedBold, ~8pt, isolated) -> frame label.
    if t == "UNIQUE" and font == "NotoSans-CondensedBold":
        return "label"
    # Geogrotesque = the card title / stat-frame typography -> frame label, never prose.
    if font.startswith("Geogrotesque") or font.startswith("KozGo") or font.startswith("Lato"):
        # the big unit/card NAME and bordered stat labels: treat as label.
        return "label"
    # strike-table cell: anything on a weapon strike-row baseline (the value row) or the
    # 'FOR <weapon>' label one line below it — value cells, the Bold weapon title, the FOR
    # label — is table chrome, never prose.
    if weapon_baselines is not None and font.startswith("NotoSans-Condensed") and sz <= 9.5:
        ly = to_logical(s["org"][0], s["org"][1], s["dir"])[1]
        if ((s["dir"], round(ly)) in weapon_baselines
                or (s["dir"], round(ly - LINE_H)) in weapon_baselines):
            return "cell"
    # remaining NotoSans-Condensed runs at body size -> prose-candidate (body)
    if font in PROSE_FONTS and 5.5 <= sz <= 9.5:
        return None
    # everything else (rare): a standalone short label / value cell
    return "cell"


# --- body block assembly -----------------------------------------------------
ROW_H = 8.4   # logical line height (~one body line); rows within this band are "same row"


def logical_xy(s):
    return to_logical(s["org"][0], s["org"][1], s["dir"])


def _assign_landscape(plist, alist):
    """Greedy nearest-header body assignment for DENSE landscape cards (dir 90/270), in the logical
    reading frame. Each anchor (top-to-bottom reading order) consumes the contiguous run of prose
    lines in its half-width column, stopping at the next anchor down in that column or a line-sized
    vertical gap. Robust where the column-gutter heuristic mis-splits tightly-packed abilities whose
    bodies wrap wider than their header. Returns [(reading_key(anchor), group, anchor), ...]."""
    out = []
    info = [{"a": a, "x": logical_xy(a)[0], "y": logical_xy(a)[1]} for a in alist]
    order = sorted(info, key=lambda it: (it["y"], it["x"]))
    consumed = set()
    for it in order:
        a = it["a"]; ax, ay = it["x"], it["y"]
        # half-width column centred on the header, narrowed to the midpoint of any anchor sharing
        # this header's row (side-by-side abilities)
        col_l, col_r = ax - 150, ax + 150
        for o in info:
            if o is it:
                continue
            if abs(o["y"] - ay) < ROW_H:
                if o["x"] > ax:
                    col_r = min(col_r, (ax + o["x"]) / 2)
                else:
                    col_l = max(col_l, (ax + o["x"]) / 2)
        # the next anchor DOWN in this column ends the body
        next_y = None
        for o in info:
            if o is it:
                continue
            if o["y"] > ay + 2 and col_l - 2 <= o["x"] <= col_r + 2:
                next_y = o["y"] if next_y is None else min(next_y, o["y"])
        cand = []
        for ps in plist:
            if id(ps) in consumed:
                continue
            px, py = logical_xy(ps)
            xc = (to_logical(ps["bb"][0], ps["bb"][1], ps["dir"])[0]
                  + to_logical(ps["bb"][2], ps["bb"][3], ps["dir"])[0]) / 2
            if py < ay - 6 or not (col_l <= xc <= col_r):
                continue
            if next_y is not None and py >= next_y - 2:
                continue
            cand.append((py, ps))
        cand.sort(key=lambda t: t[0])
        if not cand:
            continue
        sizes = sorted(ps["sz"] for _, ps in cand)
        line_adv = sizes[len(sizes) // 2] * 1.7
        prev = ay
        grp = []
        for py, ps in cand:
            if py - prev > line_adv + 4:
                break
            grp.append(ps); consumed.add(id(ps)); prev = max(prev, py)
        if grp:
            out.append((reading_key(a), grp, a))
    return out


def assemble_bodies(prose, headers, panels, doc, page_no):
    """Group prose spans into ability bodies.

    Every ability body sits under an ExtraB ':'-header. Working in the logical reading
    frame (per dir), we cluster headers into COLUMNS (cards stack abilities in a grid, and
    two abilities frequently share a row in two columns). Each prose span is assigned to
    the header in its own column that most-recently precedes it in row-major reading order.
    Blocks are emitted top-to-bottom in reading order; block_index drives the id the layout
    engine matches on.
    """
    bodies = []
    anchors = [h for h in headers if h["t"].rstrip().endswith(":")]

    def bucket(items):
        b = {}
        for it in items:
            b.setdefault(it["dir"], []).append(it)
        return b

    assigned = []  # (sort_key, group, anchor)

    # --- panel-confined pass: grey panels give exact ability boundaries -----------------
    # A grey panel with exactly ONE ':'-header confines that ability; its prose belongs to
    # that header. A grey panel with NO ':'-header is a strike-stat panel (e.g. "FOR STRIKE")
    # -> its prose-candidates are table chrome, dropped from the body stream. Prose handled
    # here is removed from the geometric pass below.
    panel_handled = set()
    for r in panels:
        ph = [h for h in anchors if in_rect(h["bb"], r, 2)]
        pp = [s for s in prose if in_rect(s["bb"], r, 2)]
        if not pp:
            continue
        if len(ph) == 1:
            for s in pp:
                s["_anchor"] = id(ph[0])
                panel_handled.add(id(s))
            assigned.append((reading_key(ph[0]), [s for s in pp], ph[0]))
        elif len(ph) == 0:
            for s in pp:                       # strike-stat panel: not body
                panel_handled.add(id(s))
        # (>=2 headers in one panel is rare; leave those to the geometric pass)

    prose = [s for s in prose if id(s) not in panel_handled]

    prose_by_dir = bucket(prose)
    anchors_by_dir = bucket(anchors)

    for d, plist in prose_by_dir.items():
        alist = anchors_by_dir.get(d, [])
        if not alist:
            groups = group_by_panel(plist, panels) if panels else [plist]
            for g in groups:
                if g:
                    assigned.append((min(reading_key(x) for x in g), g, None))
            continue
        # DENSE LANDSCAPE cards (dir 90/270): the gutter heuristic below mis-columns abilities whose
        # body wraps WIDER than its header — bodies leak between neighbours and one ability is dropped
        # (Protoss p8 MASS RECALL, Terran p8 SCANNER SWEEP / STRAP IN, Zerg p12 EXTENDED CLAWS). For
        # these we use the robust greedy nearest-header consumption (mirrors the layout engine's
        # card_inplace._assign_bodies): each anchor, in reading order, consumes the contiguous run of
        # prose lines in its half-width column, bounded below by the next anchor DOWN in that column.
        # The portrait unit cards (dir 0/180) keep the proven gutter logic untouched.
        if d in (90, 270):
            assigned.extend(_assign_landscape(plist, alist))
            continue
        # Assign each prose span to its owning header in the LOGICAL frame. Two stages:
        #   (1) ROW: pick the header-row nearest at/above the prose (an ability's body wraps
        #       full-column-width below its header, never above it).
        #   (2) COLUMN: if that row holds several headers side-by-side, assign by which
        #       column the prose's x-centre falls in, using gutters midway between the
        #       columns' x-spans (computed from BOTH headers and their wrapped prose, so the
        #       full-width wrap of each column is captured). Header-x alone is unreliable
        #       because bodies wrap to a different left margin than the header.
        ainfo = [{"a": a, "x": logical_xy(a)[0], "y": logical_xy(a)[1]} for a in alist]
        # bucket headers into rows (logical y within ROW_H)
        rows = []
        for ai in sorted(ainfo, key=lambda a: a["y"]):
            if rows and abs(ai["y"] - rows[-1][0]["y"]) < ROW_H:
                rows[-1].append(ai)
            else:
                rows.append([ai])
        row_y = [min(a["y"] for a in r) for r in rows]

        def owning_row(py):
            cand = [i for i, ry in enumerate(row_y) if ry <= py + ROW_H * 0.6]
            return max(cand) if cand else 0

        # first pass: row assignment, gather prose x-centres per (row, header) for gutters
        for ps in plist:
            px, py = logical_xy(ps)
            ps["_row"] = owning_row(py)
        # second pass: within each multi-header row, derive column gutters from prose x-mids
        for ri, row in enumerate(rows):
            members = sorted(row, key=lambda a: a["x"])
            row_prose = [ps for ps in plist if ps["_row"] == ri]
            if len(members) == 1:
                for ps in row_prose:
                    ps["_anchor"] = id(members[0]["a"])
                continue
            # Gutters: a column boundary is the empty vertical strip BETWEEN columns. The
            # header x marks each column's left edge but bodies wrap wider, so we locate the
            # gutter as the centre of the widest x-gap in the row's occupied x-intervals
            # (prose + header spans), searching only between adjacent header x's.
            def lxc(s_bb, d):
                return ((to_logical(s_bb[0], s_bb[1], d)[0]
                         + to_logical(s_bb[2], s_bb[3], d)[0]) / 2)

            def lx_interval(s_bb, d):
                a = to_logical(s_bb[0], s_bb[1], d)[0]
                b = to_logical(s_bb[2], s_bb[3], d)[0]
                return (min(a, b), max(a, b))

            intervals = sorted(lx_interval(ps["bb"], ps["dir"]) for ps in row_prose)
            gutters = []
            for i in range(len(members) - 1):
                lo, hi = members[i]["x"], members[i + 1]["x"]
                # widest empty x-gap among prose intervals located between this header pair
                edge_r = lo
                best_gap, best_mid = -1.0, (lo + hi) / 2
                for a, b in intervals:
                    if a > edge_r and a <= hi + 60:    # gap before this interval
                        gap = a - edge_r
                        if gap > best_gap and edge_r >= lo - 1:
                            best_gap, best_mid = gap, (edge_r + a) / 2
                    edge_r = max(edge_r, b)
                gutters.append(best_mid)

            def col_index(xc):
                i = 0
                while i < len(gutters) and xc >= gutters[i]:
                    i += 1
                return i
            for ps in row_prose:
                ps["_anchor"] = id(members[col_index(lxc(ps["bb"], ps["dir"]))]["a"])
        for a in alist:
            g = [ps for ps in plist if ps.get("_anchor") == id(a)]
            if g:
                assigned.append((reading_key(a), g, a))

    assigned.sort(key=lambda x: x[0])
    for _key, group, _anchor in assigned:
        group = sorted(group, key=reading_key)
        text, bold = join_with_bold(group)
        if not is_real_body(text):
            continue
        # header_source = the EN ability-header text this body flows from. This is the STABLE,
        # language-independent key the layout engine matches on (its own ability detector orders
        # blocks differently than this extractor, so the positional block_index alone is NOT a
        # reliable cross-engine key — the header text is). Anchor-less bodies (no ':'-header, e.g.
        # a faction-card panel) get "".
        header_source = _anchor["t"].rstrip() if _anchor is not None else ""
        bodies.append({"source_text": text, "bold": bold, "header_source": header_source})
    # block_index is assigned AFTER dropping non-prose stragglers, so it stays a contiguous
    # top-to-bottom ability order (kept as a positional fallback for the layout engine).
    for idx, b in enumerate(bodies):
        b["block_index"] = idx
    return bodies


def is_real_body(text):
    """A real ability body is flowing prose: it must carry at least one multi-letter
    lowercase word. Drops stray non-prose blocks (a lone stat number like '40', or leaked
    pill text like 'CP: 1 CP: 1') that no real ability consists of."""
    t = text.strip()
    if len(t) < 6:
        return False
    return re.search(r"[a-ząćęłńóśźż]{3,}", t) is not None


def group_by_panel(prose, panels):
    groups = []
    used = set()
    for r in panels:
        g = [p for p in prose if in_rect(p["bb"], r)]
        for p in g:
            used.add(id(p))
        if g:
            groups.append(g)
    leftover = [p for p in prose if id(p) not in used]
    if leftover:
        groups.append(leftover)
    return groups


def join_with_bold(group):
    """Join span texts in reading order by single spaces; record bold char ranges.
    Punctuation spans (a lone ',' '.' etc.) are glued to the previous token without a
    leading space, matching natural prose."""
    parts = []   # (text, is_bold)
    for s in group:
        parts.append((s["t"], is_bold_font(s["font"])))
    out = []
    bold = []
    pos = 0
    for i, (txt, b) in enumerate(parts):
        glue = (i > 0 and re.match(r"^[\.,;:!?\)\]”'\"]", txt) is not None)
        if i > 0 and not glue:
            out.append(" ")
            pos += 1
        start = pos
        out.append(txt)
        pos += len(txt)
        if b:
            bold.append([start, pos])
    text = "".join(out)
    bold = merge_ranges(bold)
    return text, bold


def merge_ranges(ranges):
    if not ranges:
        return []
    ranges = sorted(ranges)
    out = [ranges[0][:]]
    for s, e in ranges[1:]:
        if s <= out[-1][1] + 1:        # merge adjacent/overlapping (the +1 absorbs the join space)
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


# --- merge multi-span headers (e.g. "BOUND BY THE" + "KHALA:") ---------------
def merge_split_headers(headers):
    """Two ExtraB ':'-less + ':'-final runs on the same line that together form one
    header (e.g. 'BOUND BY THE' 'KHALA:') -> one header span. Conservative: only merges
    an ExtraB non-colon run immediately followed (same line, adjacent) by an ExtraB run."""
    headers = sorted(headers, key=reading_key)
    out = []
    i = 0
    while i < len(headers):
        h = headers[i]
        # a header that does NOT end with ':' but is an ExtraB title preceding a ':'-run
        if (i + 1 < len(headers) and not h["t"].rstrip().endswith(":")
                and h["font"] == "NotoSans-CondensedExtraB"
                and headers[i + 1]["font"] == "NotoSans-CondensedExtraB"
                and headers[i + 1]["t"].rstrip().endswith(":")
                and h["dir"] == headers[i + 1]["dir"]
                and abs(to_logical(*h["org"], h["dir"])[1]
                        - to_logical(*headers[i + 1]["org"], headers[i + 1]["dir"])[1]) < 4):
            nxt = headers[i + 1]
            joined = h["t"] + " " + nxt["t"]
            # union bbox
            bb = [min(h["bb"][0], nxt["bb"][0]), min(h["bb"][1], nxt["bb"][1]),
                  max(h["bb"][2], nxt["bb"][2]), max(h["bb"][3], nxt["bb"][3])]
            merged = dict(h)
            merged["t"] = joined
            merged["bb"] = bb
            out.append(merged)
            i += 2
            continue
        out.append(h)
        i += 1
    return out


# --- per-page extraction -----------------------------------------------------
LINE_H = 11.0   # weapon-table row pitch (value row -> FOR row), in logical pt


def weapon_title_baselines(spans):
    """Logical baselines (dir, round(ly)) of weapon strike-table VALUE rows, which we keep
    out of the prose/body stream.

    A strike row = a weapon title + value cells on one baseline, with a 'FOR <weapon>'
    label one line below. The title is set in either CondensedExtraB (e.g. STRIKE, GLAIVE
    CANNON) OR CondensedBold (e.g. GLAIVE STRIKE, SHREDDING CLAWS). We anchor on:
      (a) ExtraB all-caps titles (the value cells share their baseline), and
      (b) the value baseline implied by every 'FOR' italic marker (one line above it) —
          this catches the CondensedBold-titled strike rows, which always carry a FOR row.
    Both signals are specific to weapon stat-tables, so prose lines (which never carry a
    'FOR' italic nor an ExtraB-non-':' title on the same baseline) are left alone.
    """
    out = set()
    for s in spans:
        t, font = s["t"], s["font"]
        ly = to_logical(s["org"][0], s["org"][1], s["dir"])[1]
        if font == "NotoSans-CondensedExtraB" and t.isupper() and not t.rstrip().endswith(":"):
            out.add((s["dir"], round(ly)))
        if t == "FOR" and font == "NotoSans-CondensedItalic":
            out.add((s["dir"], round(ly - LINE_H)))   # value row is one line above the FOR
    return out


def _logical_box(s):
    a = to_logical(s["bb"][0], s["bb"][1], s["dir"]); b = to_logical(s["bb"][2], s["bb"][3], s["dir"])
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]


def merge_split_colon_headers(spans):
    """Mirror of card_inplace.merge_split_colon_headers: some ability names are CondensedBOLD with a
    SEPARATE tiny ExtraBold ':' span (Zerg 'FERAL RAGE' + ':'). Merge them into one ExtraBold
    'FERAL RAGE:' header span so the extractor classifies it as a header (matching the layout engine)
    instead of leaving the lone ':' as a spurious empty-named header and folding the name into prose."""
    out = list(spans)
    for c in [s for s in out if s["t"] == ":" and s["font"] == "NotoSans-CondensedExtraB"]:
        clb = _logical_box(c); ccy = (clb[1] + clb[3]) / 2
        best = None
        for s in out:
            if s is c or s["dir"] != c["dir"]:
                continue
            if "Bold" not in s["font"] and "ExtraB" not in s["font"]:
                continue
            if s["t"] != s["t"].upper() or not any(ch.isalpha() for ch in s["t"]):
                continue
            slb = _logical_box(s)
            if abs((slb[1] + slb[3]) / 2 - ccy) > 3 or not (0 <= clb[0] - slb[2] < 6):
                continue
            if best is None or slb[2] > _logical_box(best)[2]:
                best = s
        if best is None:
            continue
        merged = dict(best)
        merged["t"] = best["t"].rstrip() + ":"
        merged["font"] = "NotoSans-CondensedExtraB"
        merged["bb"] = [min(best["bb"][0], c["bb"][0]), min(best["bb"][1], c["bb"][1]),
                        max(best["bb"][2], c["bb"][2]), max(best["bb"][3], c["bb"][3])]
        out.remove(best); out.remove(c); out.append(merged)
    return out


# --- scenario / mission card prose ------------------------------------------
# The scenario sheets (Protoss p10-13, Terran p10-13, Zerg p16-19) are NOT ability cards: each
# mission card carries multi-paragraph prose under CondensedBLACK ':' sub-headers (MISSION
# PARAMETERS:, SCORING CONDITIONS:, ADDITIONAL CONDITIONS:) — no ExtraBold ability header anchors
# them, so the ability-body pipeline leaves them EN. We detect those sub-headers as anchors and
# group the prose below each in its card column. The body header_source is "<CARD TITLE> / <SUB>:"
# (the Geogrotesque card title above disambiguates the sub-header, which repeats per card).
SCEN_SUBHEADER_RE = re.compile(r":$")


def is_scenario_subheader(s):
    return (s["font"] == "NotoSans-CondensedBlack" and s["dir"] == 0 and 7 <= s["sz"] <= 9
            and s["t"].rstrip().endswith(":") and s["t"] == s["t"].upper()
            and len(s["t"]) > 4 and s["t"] not in PHASE_WORDS)


def scenario_card_title(s, titles):
    """The Geogrotesque card title (e.g. SUPPLY DROP) whose column+above-position best owns this
    sub-header — disambiguates the repeated sub-header text across the 6-8 cards on the page."""
    sx = (s["bb"][0] + s["bb"][2]) / 2
    cand = [t for t in titles if t["bb"][1] <= s["bb"][1] + 2
            and abs((t["bb"][0] + t["bb"][2]) / 2 - sx) < 150]
    if not cand:
        cand = [t for t in titles if abs((t["bb"][0] + t["bb"][2]) / 2 - sx) < 150] or titles
    return max(cand, key=lambda t: t["bb"][1])["t"] if cand else ""


def scenario_bodies(spans):
    """Group scenario/mission-card prose under its CondensedBlack ':' sub-header (per card column).
    Returns [{source_text, bold, header_source}] with header_source '<CARD TITLE> / <SUB>:' so the
    layout engine can re-find each body. Returns [] when the page has no such sub-headers (i.e. it
    is a normal unit/tactical page) — so this is inert except on the scenario sheets."""
    subs = [s for s in spans if is_scenario_subheader(s)]
    if not subs:
        return []
    titles = [s for s in spans if s["font"].startswith("Geogrotesque") and s["dir"] == 0
              and s["sz"] >= 11 and s["t"].strip()]
    prose = [s for s in spans
             if s["dir"] == 0 and s["font"] in PROSE_FONTS and 5 < s["sz"] < 9
             and not is_symbol(s["t"]) and not is_scenario_subheader(s)]
    subs_sorted = sorted(subs, key=lambda s: (round(s["bb"][1]), s["bb"][0]))
    out = []
    used = set()
    for h in subs_sorted:
        hx = (h["bb"][0] + h["bb"][2]) / 2
        col_l, col_r = hx - 48, hx + 150     # sub-header is indented; body wraps a touch further left
        # next sub-header DOWN in this column bounds the prose
        next_y = min([o["bb"][1] for o in subs_sorted
                      if o is not h and col_l <= (o["bb"][0] + o["bb"][2]) / 2 <= col_r
                      and o["bb"][1] > h["bb"][3] + 1], default=h["bb"][3] + 260)
        mem = [s for s in prose if id(s) not in used
               and col_l <= (s["bb"][0] + s["bb"][2]) / 2 <= col_r
               and h["bb"][1] - 1 <= s["bb"][1] < next_y - 1]
        if not mem:
            continue
        mem.sort(key=reading_key)
        for s in mem:
            used.add(id(s))
        text, bold = join_with_bold(mem)
        if not is_real_body(text):
            continue
        title = scenario_card_title(h, titles)
        header_source = (title + " / " + h["t"].rstrip()) if title else h["t"].rstrip()
        out.append({"source_text": text, "bold": bold, "header_source": header_source})
    return out


def extract_page(page, doc, page_no):
    global PAGE_W, PAGE_H
    PAGE_W, PAGE_H = page.rect.width, page.rect.height
    spans = merge_split_colon_headers(collect_spans(page))
    panels = grey_panels(page)
    wbl = weapon_title_baselines(spans)
    labels, headers_raw, pills, cells, prose = [], [], [], [], []
    for s in spans:
        k = classify(s, wbl)
        if k == "skip":
            continue
        if k == "label":
            labels.append(s)
        elif k == "header":
            headers_raw.append(s)
        elif k == "pill":
            pills.append(s)
        elif k == "cell":
            cells.append(s)
        else:
            prose.append(s)

    headers = merge_split_headers(headers_raw)

    # Scenario / mission cards: prose under CondensedBlack ':' sub-headers (no ExtraBold anchor). When
    # present, those prose spans are consumed here and kept OUT of the ability-body assembler (which
    # has no anchor for them and would dump them as one garbled leftover block).
    scen = scenario_bodies(spans)
    scen_used = set()
    if scen:
        # re-derive which prose spans the scenario pass consumed, by re-grouping deterministically
        prose_dir0 = [s for s in prose if s["dir"] == 0]
        for s in prose_dir0:
            scen_used.add(id(s))
        prose = [s for s in prose if id(s) not in scen_used]

    bodies = assemble_bodies(prose, headers, panels, doc, page_no)

    segs = []

    def emit(kind, text, bold=None, block_index=None, header_source=None, scen_index=None):
        if block_index is not None:
            sid = f"{doc}:p{page_no}:ability:{block_index}"
        elif scen_index is not None:
            sid = f"{doc}:p{page_no}:scenario:{scen_index}"
        else:
            sid = f"{doc}:p{page_no}:{kind}:{emit.counters.setdefault(kind, 0)}"
            emit.counters[kind] += 1
        rec = {
            "id": sid, "doc": doc, "page": page_no, "kind": kind,
            "source_text": text, "target_text": "",
            "bold": bold if bold is not None else [],
            "status": "new", "notes": "",
        }
        if kind == "body":
            # the EN ability-header this body belongs to — the engine's robust lookup key.
            rec["header_source"] = header_source or ""
        segs.append(rec)
    emit.counters = {}

    # deterministic emission order: labels, headers, pills, cells (each in reading order),
    # then bodies (already block-indexed).
    for s in sorted(labels, key=reading_key):
        emit("label", s["t"])
    for s in sorted(headers, key=reading_key):
        emit("header", s["t"])
    for s in sorted(pills, key=reading_key):
        emit("pill", s["t"])
    for s in sorted(cells, key=reading_key):
        emit("cell", s["t"])
    for b in bodies:
        emit("body", b["source_text"], bold=b["bold"], block_index=b["block_index"],
             header_source=b.get("header_source", ""))
    for i, b in enumerate(scen):
        emit("body", b["source_text"], bold=b["bold"], scen_index=i,
             header_source=b.get("header_source", ""))
    return segs


def extract_doc(pdf_path: Path):
    doc = pdf_path.stem
    d = fitz.open(pdf_path)
    all_segs = []
    for pno in range(d.page_count):
        all_segs.extend(extract_page(d[pno], doc, pno))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{doc}.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for seg in all_segs:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
    kinds = {}
    for s in all_segs:
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    print(f"{doc}: {len(all_segs)} segments {kinds} -> {out}")
    return out, all_segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", nargs="?", help="path to a P2P card-sheet PDF")
    ap.add_argument("--all", action="store_true", help="extract all 3 P2P sheets")
    a = ap.parse_args()
    if a.all:
        for name in P2P_SHEETS:
            p = PDF_DIR / name
            if p.exists():
                extract_doc(p)
            else:
                print(f"  MISSING {p}", file=sys.stderr)
    elif a.pdf:
        extract_doc(Path(a.pdf))
    else:
        ap.error("give a PDF path or --all")


if __name__ == "__main__":
    main()
