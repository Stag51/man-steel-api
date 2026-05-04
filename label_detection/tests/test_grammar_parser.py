"""
tests/test_grammar_parser.py
───────────────────────────
Unit tests for grammar_parser.parse() and normalise_label().
Verifies regex matching, DB cross-reference, UB/UC disambiguation,
and rejection of malformed strings.
"""

import sys
import os

# Allow running from the repo root or from this directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from grammar_parser import parse, normalise_label, ParsedSection


# ── Full mark+section hits ──────────────────────────────────────────────────

FULL_MARK_CASES = [
    # (input_string,           expected_section_type, expected_mark)
    ("B1 - SHS100X4",          "SHS",  "B1"),
    ("C4 - CHS88.9x3",         "CHS",  "C4"),
    ("F500 - FL90x10x200 Lg",  "FL",   "F500"),
    ("HR1-CHS48.3x3",          "CHS",  "HR1"),
    ("SG1 - PFC200x90x30",     "PFC",  "SG1"),
    ("M1002 - RHS150x50x5",    "RHS",  "M1002"),
    ("RL1 - UC203x203x46",     "UC",   "RL1"),
    ("B12 - UB457x191x82",     "UB",   "B12"),
]

@pytest.mark.parametrize("text,section_type,mark", FULL_MARK_CASES)
def test_full_mark_matching(text, section_type, mark):
    results = parse(text)
    assert results, f"Expected a parse hit for: {text!r}"
    assert results[0].section_type == section_type
    assert results[0].mark == mark
    assert results[0].regex_valid is True


# ── Bare section hits ───────────────────────────────────────────────────────

BARE_CASES = [
    ("UB457x191x82",   "UB"),
    ("CHS88.9x3",      "CHS"),
    ("RHS150x50x5",    "RHS"),
    ("SHS100x100x4",   "SHS"),
    ("UC203x203x46",   "UC"),
    ("WB700x300x115",  "WB"),
    ("EA100x100x10",   "EA"),
    ("PFC200x90x30",   "PFC"),
]

@pytest.mark.parametrize("text,section_type", BARE_CASES)
def test_bare_section_matching(text, section_type):
    results = parse(text)
    assert results, f"Expected a parse hit for: {text!r}"
    assert results[0].section_type == section_type
    assert results[0].mark is None
    assert results[0].regex_valid is True


# ── Multi-label text ────────────────────────────────────────────────────────

def test_multiple_hits_in_one_string():
    text = "B1 - UB203x133x30   and   C2 - UC254x254x89"
    results = parse(text)
    assert len(results) == 2
    types = {r.section_type for r in results}
    assert "UB" in types
    assert "UC" in types


# ── DB score ────────────────────────────────────────────────────────────────

def test_known_ub_gets_full_db_score():
    results = parse("UB457x191x82")
    assert results
    # 457×191×82 UB is in the BS4-1 DB
    assert results[0].db_score == 1.0
    assert results[0].db_match is not None


def test_known_uc_gets_full_db_score():
    results = parse("UC203x203x46")
    assert results
    assert results[0].db_score == 1.0


def test_unknown_section_gets_low_db_score():
    # Completely fabricated dimensions unlikely to be in the DB
    results = parse("UB999x999x999")
    assert results
    # Should not be found verbatim
    assert results[0].db_score < 1.0


def test_typo_corrected_by_db():
    # 203x133x30 UB exists; a minor typo (31 vs 30) should trigger fuzzy correction
    results = parse("UB203x133x31")
    assert results
    ps = results[0]
    # db_score should be > 0 (fuzzy found a close match) but < 1.0 (not exact)
    assert 0.0 < ps.db_score < 1.0


# ── Rejection of noise ──────────────────────────────────────────────────────

REJECT_CASES = [
    "T10",        # tread prefix without dims
    "6fw",        # weld callout
    "100",        # bare number
    "HELLO",      # random text
    "B1",         # mark without section
]

@pytest.mark.parametrize("text", REJECT_CASES)
def test_rejects_non_sections(text):
    results = parse(text)
    assert results == [], f"Should not match: {text!r}"


# ── normalise_label ──────────────────────────────────────────────────────────

def test_normalise_lowercase_x():
    assert normalise_label("203x133x30ub") == "203X133X30UB"

def test_normalise_em_dash():
    assert normalise_label("B1—SHS100X4") == "B1 - SHS100X4"

def test_normalise_strip_spaces():
    assert normalise_label("  UB 457 x 191 x 82  ") == "UB 457 X 191 X 82"
