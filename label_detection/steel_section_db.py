"""
steel_section_db.py
───────────────────
Authoritative lookup table for structural steel sections used in UK (BS 4-1)
and Australian (AS/NZS 3679.1, AS 1163) practice, plus hollow sections.

Key public API
--------------
lookup(label)   -> dict | None
    Return the section record for `label`, or None if not in the database.

correct(label)  -> tuple[str, float]
    Return the (best_match_key, edit_distance_score 0–1) using rapidfuzz.
    Falls back to difflib if rapidfuzz is not installed.

SECTION_DB      : dict[str, dict]
    Keyed by canonical label, e.g. "203X133X30UB".
    Values: {"d": depth_mm, "b": width_mm, "m": mass_kg_m,
              "type": "UB"|"UC"|..., "standard": "BS4-1"|...}
"""

from __future__ import annotations

import re
from typing import Any

# ── Optional fast fuzzy matching ──────────────────────────────────────────────
try:
    from rapidfuzz import process as _rf_process, fuzz as _rf_fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False
    import difflib

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _k(d: float, b: float, m: float, stype: str, std: str) -> tuple[str, dict]:
    """Build a canonical key + record tuple for the DB."""
    dims = f"{int(d)}X{int(b)}X{int(m)}{stype}"
    return dims, {"d": d, "b": b, "m": m, "type": stype, "standard": std}


def _normalise_key(raw: str) -> str:
    """
    Normalise a raw label to the canonical DB key format:
      - uppercase
      - replace 'x' / '×' dimension separators with 'X'
      - strip whitespace and all separators except 'X'
    """
    s = raw.strip().upper()
    s = re.sub(r"[×x]", "X", s, flags=re.IGNORECASE)
    # Remove any spaces / dashes that are not part of the label
    s = re.sub(r"[\s\-–—]+", "", s)
    return s


# ══════════════════════════════════════════════════════════════════════════════
# UK Universal Beams — BS 4-1 (d×b×m UB)
# ══════════════════════════════════════════════════════════════════════════════

_UB_BS4: list[tuple[float, float, float]] = [
    # d_mm, b_mm, m_kg/m  (nominal serial size × mass)
    (127,  76,  13), (127,  76,  15),
    (152,  89,  16), (152,  89,  17), (152,  89,  19), (152,  89,  23), (152,  89,  28),
    (178, 102,  19), (178, 102,  25), (178, 102,  28),
    (203, 102,  23), (203, 102,  25), (203, 102,  28),
    (203, 133,  25), (203, 133,  30), (203, 133,  35), (203, 133,  40),
    (254, 102,  22), (254, 102,  25), (254, 102,  28),
    (254, 146,  31), (254, 146,  37), (254, 146,  43),
    (305, 102,  25), (305, 102,  28), (305, 102,  33),
    (305, 127,  37), (305, 127,  42), (305, 127,  48),
    (305, 165,  40), (305, 165,  46), (305, 165,  54),
    (356, 127,  33), (356, 127,  39), (356, 127,  45),
    (356, 171,  45), (356, 171,  51), (356, 171,  57), (356, 171,  67),
    (406, 140,  39), (406, 140,  46),
    (406, 178,  54), (406, 178,  60), (406, 178,  67), (406, 178,  74),
    (457, 152,  52), (457, 152,  60), (457, 152,  67), (457, 152,  74), (457, 152,  82),
    (457, 191,  67), (457, 191,  74), (457, 191,  82), (457, 191,  89), (457, 191,  98),
    (533, 210,  82), (533, 210,  92), (533, 210, 101), (533, 210, 109), (533, 210, 122),
    (610, 229,  94), (610, 229, 101), (610, 229, 113), (610, 229, 125), (610, 229, 140),
    (610, 305, 149), (610, 305, 179), (610, 305, 238),
    (686, 254, 125), (686, 254, 140), (686, 254, 152), (686, 254, 170),
    (762, 267, 134), (762, 267, 147), (762, 267, 173), (762, 267, 197),
    (838, 292, 176), (838, 292, 194), (838, 292, 226),
    (914, 305, 201), (914, 305, 224), (914, 305, 253), (914, 305, 289),
    (914, 419, 343), (914, 419, 388),
]

# ══════════════════════════════════════════════════════════════════════════════
# UK Universal Columns — BS 4-1 (d×b×m UC)
# ══════════════════════════════════════════════════════════════════════════════

_UC_BS4: list[tuple[float, float, float]] = [
    (152, 152,  23), (152, 152,  30), (152, 152,  37),
    (203, 203,  46), (203, 203,  52), (203, 203,  60), (203, 203,  71), (203, 203,  86),
    (254, 254,  73), (254, 254,  89), (254, 254, 107), (254, 254, 132), (254, 254, 167),
    (305, 305,  97), (305, 305, 118), (305, 305, 137), (305, 305, 158), (305, 305, 198),
    (305, 305, 240), (305, 305, 283),
    (356, 368, 129), (356, 368, 153), (356, 368, 177), (356, 368, 202),
    (356, 406, 235), (356, 406, 287), (356, 406, 340), (356, 406, 393),
    (356, 406, 467), (356, 406, 551), (356, 406, 634),
]

# ══════════════════════════════════════════════════════════════════════════════
# UK Universal Bearing Piles — BS 4-1 (d×b×m UBP)
# ══════════════════════════════════════════════════════════════════════════════

_UBP_BS4: list[tuple[float, float, float]] = [
    (203, 203,  45), (203, 203,  54),
    (254, 254,  63), (254, 254,  71), (254, 254,  85),
    (305, 305,  79), (305, 305,  88), (305, 305, 110), (305, 305, 126),
    (356, 368, 109), (356, 368, 133), (356, 368, 152), (356, 368, 174),
]

# ══════════════════════════════════════════════════════════════════════════════
# UK Parallel Flange Channel — BS 4-1 (d×b×m PFC)
# ══════════════════════════════════════════════════════════════════════════════

_PFC_BS4: list[tuple[float, float, float]] = [
    (100,  50,  10),
    (125,  65,  15),
    (150,  75,  18),
    (180,  90,  26),
    (200,  90,  30),
    (230,  90,  32),
    (260,  90,  35),
    (300, 100,  46),
    (380, 100,  54),
    (430, 100,  64),
]

# ══════════════════════════════════════════════════════════════════════════════
# Australian WB / WC — AS/NZS 3679.1
# ══════════════════════════════════════════════════════════════════════════════

_WB_ASNZS: list[tuple[float, float, float]] = [
    (700, 300, 115), (700, 300, 130), (700, 300, 150), (700, 300, 173),
    (700, 300, 196), (700, 300, 220),
    (800, 300, 122), (800, 300, 146), (800, 300, 168), (800, 300, 192),
    (800, 300, 218),
    (900, 300, 143), (900, 300, 175), (900, 300, 218), (900, 300, 257),
    (1000, 300, 215), (1000, 300, 249), (1000, 300, 296),
]

_WC_ASNZS: list[tuple[float, float, float]] = [
    (400, 400, 144), (400, 400, 181), (400, 400, 212),
    (500, 500, 267), (500, 500, 325), (500, 500, 383), (500, 500, 440),
]

# ══════════════════════════════════════════════════════════════════════════════
# Hollow Sections — SHS / RHS (AS 1163, EN 10219)
# Selected common sizes; extend as needed.
# ══════════════════════════════════════════════════════════════════════════════

_SHS_COMMON: list[tuple[float, float, float, float]] = [
    # (d, b, t, mass_approx)  square hollow section d==b
    (25,  25, 2.0,  1.36), (25,  25, 2.5,  1.66),
    (32,  32, 2.5,  2.19),
    (40,  40, 2.5,  2.77), (40,  40, 3.0,  3.28), (40,  40, 4.0,  4.20),
    (50,  50, 2.5,  3.53), (50,  50, 3.0,  4.17), (50,  50, 4.0,  5.40), (50,  50, 5.0,  6.56),
    (65,  65, 3.0,  5.52), (65,  65, 4.0,  7.18), (65,  65, 5.0,  8.77),
    (75,  75, 3.0,  6.44), (75,  75, 4.0,  8.42), (75,  75, 5.0, 10.32), (75,  75, 6.0, 12.12),
    (89,  89, 3.5,  9.14), (89,  89, 5.0, 12.79), (89,  89, 6.0, 15.10),
    (100,100, 4.0, 11.90), (100,100, 5.0, 14.74), (100,100, 6.0, 17.50), (100,100, 8.0, 22.60),
    (125,125, 5.0, 18.67), (125,125, 6.0, 22.20), (125,125, 8.0, 28.80),
    (150,150, 5.0, 22.60), (150,150, 6.0, 26.90), (150,150, 8.0, 35.10),
    (200,200, 6.0, 36.20), (200,200, 8.0, 47.40), (200,200,10.0, 58.20),
    (250,250, 8.0, 59.80), (250,250,10.0, 73.80), (250,250,12.5, 91.00),
    (300,300, 8.0, 72.40), (300,300,10.0, 89.60), (300,300,12.5,110.50),
    (350,350,10.0,105.30), (350,350,12.5,130.00),
    (400,400,10.0,121.00), (400,400,12.5,149.50), (400,400,16.0,188.00),
]

_RHS_COMMON: list[tuple[float, float, float, float]] = [
    # (d, b, t, mass_approx)
    (50,  25, 2.5,  2.17), (50,  25, 3.0,  2.57),
    (50,  50, 2.5,  3.53), (50,  50, 3.0,  4.17),
    (75,  25, 2.5,  2.92), (75,  25, 3.0,  3.47),
    (75,  50, 2.5,  3.53), (75,  50, 3.0,  4.17), (75,  50, 5.0,  6.71),
    (76,  38, 3.2,  4.69),
    (100, 50, 3.0,  5.54), (100, 50, 4.0,  7.24), (100, 50, 5.0,  8.86),
    (100, 75, 4.0,  8.42), (100, 75, 5.0, 10.32),
    (125, 50, 3.0,  6.44), (125, 50, 5.0, 10.40),
    (125, 75, 4.0,  9.87), (125, 75, 5.0, 12.10),
    (150, 50, 4.0,  9.54), (150, 50, 5.0, 11.70),
    (150,100, 4.0, 11.40), (150,100, 5.0, 14.07), (150,100, 6.0, 16.60),
    (200,100, 5.0, 18.00), (200,100, 6.0, 21.30), (200,100, 8.0, 27.70),
    (200,150, 5.0, 21.70), (200,150, 6.0, 25.80), (200,150, 8.0, 33.80),
    (250,150, 6.0, 30.30), (250,150, 8.0, 39.80), (250,150,10.0, 48.90),
    (300,200, 8.0, 54.80), (300,200,10.0, 67.70), (300,200,12.5, 83.10),
    (350,250,10.0, 86.60), (350,250,12.5,107.00),
    (400,200,10.0, 89.60), (400,200,12.5,110.50),
]

# ══════════════════════════════════════════════════════════════════════════════
# CHS — Circular Hollow Section
# ══════════════════════════════════════════════════════════════════════════════

_CHS_COMMON: list[tuple[float, float, float]] = [
    # (od_mm, t_mm, mass_kg/m)
    (21.3,  2.3,  1.02), (26.9,  2.3,  1.33), (33.7,  2.6,  1.99),
    (42.4,  2.6,  2.55), (42.4,  3.2,  3.09),
    (48.3,  2.5,  2.84), (48.3,  3.2,  3.56), (48.3,  4.0,  4.37),
    (60.3,  2.9,  4.11), (60.3,  3.2,  4.51), (60.3,  4.0,  5.55), (60.3,  5.0,  6.82),
    (76.1,  3.2,  5.75), (76.1,  4.0,  7.11), (76.1,  5.0,  8.77),
    (88.9,  3.2,  6.76), (88.9,  4.0,  8.38), (88.9,  5.0, 10.30), (88.9,  6.3, 12.80),
    (101.6, 3.6,  8.72), (101.6, 5.0, 11.90), (101.6, 6.3, 14.80),
    (114.3, 5.0, 13.50), (114.3, 6.3, 16.80), (114.3, 8.0, 21.00),
    (127,   5.0, 15.00), (127,   6.3, 18.70), (127,   8.0, 23.60),
    (139.7, 5.0, 16.60), (139.7, 6.3, 20.70), (139.7, 8.0, 26.00),
    (168.3, 5.0, 20.10), (168.3, 6.3, 25.20), (168.3, 8.0, 31.60), (168.3,10.0, 39.00),
    (193.7, 5.0, 23.30), (193.7, 6.3, 29.10), (193.7, 8.0, 36.60),
    (219.1, 6.3, 33.10), (219.1, 8.0, 41.60), (219.1,10.0, 51.60), (219.1,12.5, 63.70),
    (273.1, 8.0, 52.30), (273.1,10.0, 65.00), (273.1,12.5, 80.30),
    (323.9,10.0, 77.40), (323.9,12.5, 96.00), (323.9,16.0,121.00),
    (355.6,10.0, 85.20), (355.6,12.5,106.00), (355.6,16.0,133.00),
    (406.4,10.0, 97.80), (406.4,12.5,121.50), (406.4,16.0,153.00),
    (457.0,12.5,136.00), (457.0,16.0,172.00),
    (508.0,12.5,152.00), (508.0,16.0,192.00),
]

# ══════════════════════════════════════════════════════════════════════════════
# Equal Angles / Unequal Angles (EA / UA) — AS/NZS 3679.1
# ══════════════════════════════════════════════════════════════════════════════

_EA_ASNZS: list[tuple[float, float, float]] = [
    # (leg_mm, t_mm, mass_kg/m)  equal angle legs
    (25,  3,  1.12), (25,  5,  1.77),
    (30,  3,  1.36),
    (40,  4,  2.42), (40,  5,  2.97),
    (50,  5,  3.77), (50,  6,  4.47),
    (65,  6,  5.84), (65,  8,  7.64), (65, 10,  9.37),
    (75,  6,  6.81), (75,  8,  8.96), (75, 10, 11.00),
    (90,  6,  8.23), (90,  8, 10.90), (90, 10, 13.40),
    (100, 8, 12.20), (100,10, 15.10), (100,12, 17.90),
    (125,10, 19.00), (125,12, 22.60),
    (150,10, 23.00), (150,12, 27.30), (150,16, 35.80),
    (200,16, 48.10), (200,20, 59.30),
]

_UA_ASNZS: list[tuple[float, float, float, float]] = [
    # (long_leg, short_leg, t, mass_kg/m)
    (65,  50, 5,  4.39), (65,  50, 8,  6.84),
    (75,  50, 6,  5.55), (75,  50, 8,  7.24),
    (100, 65, 7,  8.77), (100, 65,10, 12.20),
    (125, 75, 8, 11.90), (125, 75,10, 14.70),
    (150,100,10, 18.70), (150,100,12, 22.20),
    (200,100,12, 27.30), (200,100,15, 33.70),
]

# ══════════════════════════════════════════════════════════════════════════════
# Flat Bar / Plate (FL / PL / FB)
# These are parametric so we store a sentinel to signify "any" known type.
# ══════════════════════════════════════════════════════════════════════════════

_FL_WIDTHS = [25, 30, 32, 40, 50, 60, 65, 75, 90, 100, 125, 150, 200, 250, 300]
_FL_THICKNESSES = [3, 4, 5, 6, 8, 10, 12, 16, 20, 25, 32]

# ══════════════════════════════════════════════════════════════════════════════
# Build the master lookup dict
# ══════════════════════════════════════════════════════════════════════════════

SECTION_DB: dict[str, dict[str, Any]] = {}

# UB
for _d, _b, _m in _UB_BS4:
    _key, _rec = _k(_d, _b, _m, "UB", "BS4-1")
    SECTION_DB[_key] = _rec

# UC
for _d, _b, _m in _UC_BS4:
    _key, _rec = _k(_d, _b, _m, "UC", "BS4-1")
    SECTION_DB[_key] = _rec

# UBP
for _d, _b, _m in _UBP_BS4:
    _key, _rec = _k(_d, _b, _m, "UBP", "BS4-1")
    SECTION_DB[_key] = _rec

# PFC
for _d, _b, _m in _PFC_BS4:
    _key, _rec = _k(_d, _b, _m, "PFC", "BS4-1")
    SECTION_DB[_key] = _rec

# WB
for _d, _b, _m in _WB_ASNZS:
    _key, _rec = _k(_d, _b, _m, "WB", "AS/NZS3679.1")
    SECTION_DB[_key] = _rec

# WC
for _d, _b, _m in _WC_ASNZS:
    _key, _rec = _k(_d, _b, _m, "WC", "AS/NZS3679.1")
    SECTION_DB[_key] = _rec

# SHS
for _d, _b, _t, _m in _SHS_COMMON:
    _key = f"{int(_d)}X{int(_b)}X{_t}SHS".replace(".0", "")
    SECTION_DB[_key] = {"d": _d, "b": _b, "t": _t, "m": _m, "type": "SHS", "standard": "AS1163/EN10219"}

# RHS
for _d, _b, _t, _m in _RHS_COMMON:
    _key = f"{int(_d)}X{int(_b)}X{_t}RHS".replace(".0", "")
    SECTION_DB[_key] = {"d": _d, "b": _b, "t": _t, "m": _m, "type": "RHS", "standard": "AS1163/EN10219"}

# CHS
for _od, _t, _m in _CHS_COMMON:
    _t_str = str(_t).rstrip("0").rstrip(".")
    _key = f"{_od}X{_t_str}CHS"
    SECTION_DB[_key] = {"d": _od, "b": _od, "t": _t, "m": _m, "type": "CHS", "standard": "AS1163/EN10219"}

# EA
for _leg, _t, _m in _EA_ASNZS:
    _key = f"{int(_leg)}X{int(_leg)}X{int(_t)}EA"
    SECTION_DB[_key] = {"d": _leg, "b": _leg, "t": _t, "m": _m, "type": "EA", "standard": "AS/NZS3679.1"}

# UA
for _ll, _sl, _t, _m in _UA_ASNZS:
    _key = f"{int(_ll)}X{int(_sl)}X{int(_t)}UA"
    SECTION_DB[_key] = {"d": _ll, "b": _sl, "t": _t, "m": _m, "type": "UA", "standard": "AS/NZS3679.1"}

# FL / FB — store common widths × thicknesses as sentinel records
for _w in _FL_WIDTHS:
    for _th in _FL_THICKNESSES:
        for _st, _stype in [("FL", "FL"), ("FB", "FB"), ("PL", "PL")]:
            _key = f"{int(_w)}X{int(_th)}{_st}"
            SECTION_DB[_key] = {
                "d": _th, "b": _w, "t": _th, "m": None,
                "type": _stype, "standard": "AS/NZS3679.2"
            }

_ALL_KEYS: list[str] = list(SECTION_DB.keys())


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def lookup(label: str) -> dict[str, Any] | None:
    """
    Return the section record for ``label``, or ``None`` if not found.

    The label is first normalised (uppercase, 'X' separators) before lookup.
    """
    return SECTION_DB.get(_normalise_key(label))


def correct(label: str) -> tuple[str, float]:
    """
    Find the closest section in the database to ``label`` using fuzzy matching.

    Returns
    -------
    (best_key, score)
        ``best_key`` is the canonical DB key of the closest match;
        ``score`` is a float in [0, 1] where 1.0 is a perfect match.

    If rapidfuzz is available, uses token_sort_ratio (fast C extension).
    Falls back to difflib.SequenceMatcher otherwise.
    """
    query = _normalise_key(label)

    if _HAS_RAPIDFUZZ:
        result = _rf_process.extractOne(
            query, _ALL_KEYS,
            scorer=_rf_fuzz.token_sort_ratio,
            score_cutoff=0,
        )
        if result is None:
            return ("", 0.0)
        best_key, score, _ = result
        return (best_key, score / 100.0)
    else:
        # difflib fallback
        matches = difflib.get_close_matches(query, _ALL_KEYS, n=1, cutoff=0.0)
        if not matches:
            return ("", 0.0)
        best_key = matches[0]
        ratio = difflib.SequenceMatcher(None, query, best_key).ratio()
        return (best_key, ratio)


def ub_uc_heuristic(label: str, orientation: str | None = None) -> dict[str, Any]:
    """
    Apply a UB/UC disambiguation heuristic.

    If ``label`` is a UB section but ``orientation`` is 'vertical', or it is
    a UC section but ``orientation`` is 'horizontal', check whether the
    complementary type exists in the DB with identical dimensions.

    Returns
    -------
    dict with keys:
        original   : normalised input label
        suggested  : recommended label (may be same as original)
        swapped    : bool — True if a type swap was proposed
        confidence : float how confident the swap recommendation is
    """
    norm = _normalise_key(label)
    rec  = SECTION_DB.get(norm)

    if rec is None:
        return {"original": norm, "suggested": norm, "swapped": False, "confidence": 0.0}

    stype = rec["type"]
    swap_map = {"UB": "UC", "UC": "UB"}

    if stype not in swap_map or orientation is None:
        return {"original": norm, "suggested": norm, "swapped": False, "confidence": 1.0}

    expected  = {"UB": "horizontal", "UC": "vertical"}
    if orientation.lower() == expected[stype]:
        # Orientation aligns — no swap needed
        return {"original": norm, "suggested": norm, "swapped": False, "confidence": 1.0}

    # Try the complementary type
    alt_type = swap_map[stype]
    alt_key  = f"{int(rec['d'])}X{int(rec['b'])}X{int(rec['m'])}{alt_type}"
    if alt_key in SECTION_DB:
        return {
            "original": norm, "suggested": alt_key,
            "swapped": True, "confidence": 0.75,
        }

    # Complementary type not in DB — keep original but flag low confidence
    return {"original": norm, "suggested": norm, "swapped": False, "confidence": 0.55}
