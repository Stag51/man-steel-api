"""
grammar_parser.py
─────────────────
Structural grammar parser: regex validation + steel section database
cross-reference for all extracted labels.

Public API
----------
parse(text) -> list[ParsedSection]
    Find and validate every structural section label in ``text``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from steel_section_db import lookup, correct, _normalise_key

# ══════════════════════════════════════════════════════════════════════════════
# Section-type registry (same family as extraction.py; extend here centrally)
# ══════════════════════════════════════════════════════════════════════════════

SECTION_TYPES: tuple[str, ...] = (
    "UC", "UB", "PFC", "CHS", "SHS", "RHS", "FLT", "RSA_E", "RSA_U",
    # Aliases for detection (will be normalised to the above)
    "FL", "FLAT", "PLATE", "PL", "RSA", "EA", "UA",
)

# The strictly provided list from Manchester Steels
PROVIDED_SECTIONS = {"UC", "UB", "PFC", "CHS", "SHS", "RHS", "FLT", "RSA_E", "RSA_U"}

# Longest-first so the alternation engine is greedy
_ST = "|".join(re.escape(s) for s in sorted(SECTION_TYPES, key=len, reverse=True))

# ── Primary pattern: mark + dash + section + dims + optional suffix ──────────
#   B1 - SHS100X4   M1002-CHS88.9x3   F500 - FL90x10x200 Lg
STRUCTURAL_PATTERN = re.compile(
    r'\b'
    r'(?P<mark>[A-Z]{1,4}\d[\d/]*[A-Z]?\d*)'   # B1, C4, RL1, M1002, F500
    r'\s*[-–—]\s*'
    r'(?P<section>' + _ST + r')'
    r'\s*'                                    # optional space
    r'(?P<dims>[\d.]+(?:\s*[xX×]\s*[\d.]+)*)' # optional spaces around x
    r'(?:\s*(?P<suffix>[Ll][Gg]|mm|m))?'
    r'\b',
    re.IGNORECASE,
)

# ── Bare section (no mark):  UB457x191x82   CHS88.9x3 ────────────────────────
BARE_SECTION_PATTERN = re.compile(
    r'\b(?P<section>' + _ST + r')\s*(?P<dims>[\d.]+(?:\s*[xX×]\s*[\d.]+)+)\b',
    re.IGNORECASE,
)

# ── Dimension First (mostly for flats/plates): 100x10 FLAT ───────────────────
DIM_SECTION_PATTERN = re.compile(
    r'\b(?P<dims>[\d.]+(?:\s*[xX×]\s*[\d.]+)+)\s*(?P<section>' + _ST + r')\b',
    re.IGNORECASE,
)

# ── Normalisation helpers ─────────────────────────────────────────────────────
_DIM_SEP = re.compile(r'[xX×]', re.IGNORECASE)

# ══════════════════════════════════════════════════════════════════════════════
# Result type
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParsedSection:
    """
    Fully validated structural section extracted from a text string.

    Attributes
    ----------
    raw             : exact text as matched from input
    normalised      : uppercase, X separators, stripped
    section_type    : e.g. "UB", "UC", "SHS", "RHS"
    mark            : member mark prefix e.g. "B1" (None for bare sections)
    dims_raw        : dimension string as written, e.g. "203x133x30"
    depth           : first dimension value (depth / outer-diameter) in mm
    width           : second dimension value (width / breadth) in mm; None if absent
    mass_or_t       : third dimension value (mass kg/m or wall thickness); None if absent
    suffix          : trailing suffix token if present, e.g. "Lg"
    db_match        : raw DB record dict or None
    db_corrected    : corrected canonical key if label was not found verbatim
    db_score        : 0–1 confidence from DB lookup / fuzzy correction
    regex_valid     : True if either structural pattern matched
    """
    raw:          str
    normalised:   str
    section_type: str
    mark:         str | None
    dims_raw:     str
    depth:        float | None
    width:        float | None
    mass_or_t:    float | None
    suffix:       str | None
    db_match:     dict[str, Any] | None
    db_corrected: str | None
    db_score:     float
    regex_valid:  bool
    is_provided:  bool = True  # Whether Manchester Steels provides this type


def _parse_dims(dims_str: str) -> tuple[float | None, float | None, float | None]:
    """Split 'dim1xdim2xdim3' into up to three floats."""
    parts = [d for d in _DIM_SEP.split(dims_str) if d]
    vals: list[float | None] = []
    for p in parts[:3]:
        try:
            vals.append(float(p))
        except ValueError:
            vals.append(None)
    while len(vals) < 3:
        vals.append(None)
    return vals[0], vals[1], vals[2]


def _make_parsed(
    raw: str,
    section_type: str,
    dims_raw: str,
    mark: str | None,
    suffix: str | None,
) -> ParsedSection:
    """
    Build a ``ParsedSection`` by cross-referencing the steel section DB.
    """
    # Normalise to canonical form
    norm = _normalise_key(f"{dims_raw}{section_type}".strip())

    depth, width, mass_or_t = _parse_dims(dims_raw)

    # DB lookup
    db_match    = lookup(norm)
    db_corrected: str | None = None
    db_score    = 0.0

    if db_match is not None:
        db_score = 1.0
    else:
        best_key, score = correct(norm)
        db_score = max(0.0, score)  # already 0–1
        if best_key and db_score >= 0.70:
            db_corrected = best_key
            db_match     = lookup(best_key)   # may still be None if score just-below

    return ParsedSection(
        raw          = raw,
        normalised   = norm,
        section_type = section_type.upper(),
        mark         = mark.upper() if mark else None,
        dims_raw     = dims_raw,
        depth        = depth,
        width        = width,
        mass_or_t    = mass_or_t,
        suffix       = suffix,
        db_match     = db_match,
        db_corrected = db_corrected,
        db_score     = db_score,
        regex_valid  = True,
        is_provided  = section_type.upper() in PROVIDED_SECTIONS,
    )


def _classify_and_normalise(section_type: str, dims_raw: str) -> str:
    """
    Map detected aliases to the provided Manchester Steels naming convention.
    """
    st = section_type.upper()
    
    # Map Flats/Plates to FLT
    if st in {"FL", "FLAT", "PLATE", "PL"}:
        return "FLT"
    
    # Map Angles to RSA_E or RSA_U
    if st in {"RSA", "EA", "UA"}:
        # Logic: If first two dimensions are equal, it's RSA_E
        parts = [p for p in re.split(r'[xX×]', dims_raw) if p]
        try:
            if len(parts) >= 2 and float(parts[0]) == float(parts[1]):
                return "RSA_E"
            return "RSA_U"
        except (ValueError, IndexError):
            return "RSA_E" # Default to equal if unclear

    return st


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def parse(text: str) -> list[ParsedSection]:
    """
    Find and validate every structural section label in ``text``.

    Both the full mark+section pattern and the bare section pattern are applied.
    Duplicate spans (same start position) are deduplicated, preferring the
    full mark+section match.

    Parameters
    ----------
    text : input string (a span of OCR text, a PDF text block, or a Revit
           type parameter value)

    Returns
    -------
    list of ``ParsedSection`` objects, in order of appearance.
    """
    results: list[ParsedSection] = []
    matched_ranges: list[tuple[int, int]] = []

    # ── Full mark+section matches ─────────────────────────────────────────────
    for m in STRUCTURAL_PATTERN.finditer(text):
        matched_ranges.append((m.start(), m.end()))
        st_normalised = _classify_and_normalise(m.group("section"), m.group("dims"))
        ps = _make_parsed(
            raw          = m.group(0),
            section_type = st_normalised,
            dims_raw     = m.group("dims"),
            mark         = m.group("mark"),
            suffix       = m.group("suffix"),
        )
        results.append(ps)

    # ── Bare section matches (skip if overlapping) ───────────────────────────
    for m in BARE_SECTION_PATTERN.finditer(text):
        start, end = m.start(), m.end()
        if any(rs <= start < re or rs < end <= re for rs, re in matched_ranges):
            continue
            
        matched_ranges.append((start, end))
        st_normalised = _classify_and_normalise(m.group("section"), m.group("dims"))
        ps = _make_parsed(
            raw          = m.group(0),
            section_type = st_normalised,
            dims_raw     = m.group("dims"),
            mark         = None,
            suffix       = None,
        )
        results.append(ps)

    # ── Dimension First matches (100x10 FLAT) ────────────────────────────────
    for m in DIM_SECTION_PATTERN.finditer(text):
        start, end = m.start(), m.end()
        if any(rs <= start < re or rs < end <= re for rs, re in matched_ranges):
            continue

        matched_ranges.append((start, end))
        st_normalised = _classify_and_normalise(m.group("section"), m.group("dims"))
        ps = _make_parsed(
            raw          = m.group(0),
            section_type = st_normalised,
            dims_raw     = m.group("dims"),
            mark         = None,
            suffix       = None,
        )
        results.append(ps)

    # Sort by order of appearance
    results.sort(key=lambda r: text.find(r.raw))
    return results


def normalise_label(code: str) -> str:
    """
    Return a canonical representation:
      - Uppercase
      - ' - ' dash separator
      - 'X' dimension separators
    """
    code = code.strip().upper()
    code = re.sub(r'\s*[-–—]\s*', ' - ', code)
    code = re.sub(r'[×x]', 'X', code, flags=re.IGNORECASE)
    return code
