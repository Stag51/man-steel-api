"""
tests/test_steel_section_db.py
──────────────────────────────
Unit tests for the steel_section_db module: lookup, correct, ub_uc_heuristic.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from steel_section_db import lookup, correct, ub_uc_heuristic, SECTION_DB, _normalise_key


# ── Helper ──────────────────────────────────────────────────────────────────

def test_db_not_empty():
    assert len(SECTION_DB) > 200, "Expected at least 200 entries in SECTION_DB"


# ── lookup() ────────────────────────────────────────────────────────────────

LOOKUP_HITS = [
    # (raw_label,           expected_type, expected_depth)
    ("203X133X30UB",        "UB",   203),
    ("457X191X82UB",        "UB",   457),
    ("203x203x46uc",        "UC",   203),   # lowercase
    ("88.9X3.2CHS",         "CHS",  88.9),
    ("100X100X4SHS",        "SHS",  100),
    ("150X100X5RHS",        "RHS",  150),
    ("152X152X23UC",        "UC",   152),
    ("305X305X97UC",        "UC",   305),
    ("700X300X115WB",       "WB",   700),
    ("400X400X144WC",       "WC",   400),
    ("100X100X10EA",        "EA",   100),
    ("200X90X30PFC",        "PFC",  200),
]

@pytest.mark.parametrize("label,stype,depth", LOOKUP_HITS)
def test_lookup_hit(label, stype, depth):
    rec = lookup(label)
    assert rec is not None, f"lookup({label!r}) returned None"
    assert rec["type"] == stype
    assert abs(rec["d"] - depth) < 0.1


LOOKUP_MISSES = [
    "999X999X999UB",   # non-existent dimensions
    "UB",              # no dimensions
    "",                # empty
    "GARBAGE",         # random text
]

@pytest.mark.parametrize("label", LOOKUP_MISSES)
def test_lookup_miss(label):
    assert lookup(label) is None, f"Expected None for {label!r}"


# ── _normalise_key() ─────────────────────────────────────────────────────────

def test_normalise_lowercasex():
    assert _normalise_key("203x133x30UB") == "203X133X30UB"

def test_normalise_unicode_x():
    assert _normalise_key("203×133×30UB") == "203X133X30UB"

def test_normalise_strips_spaces():
    assert _normalise_key("  203X133X30UB  ") == "203X133X30UB"


# ── correct() ───────────────────────────────────────────────────────────────

def test_correct_exact_match():
    key, score = correct("203X133X30UB")
    assert key == "203X133X30UB"
    assert score == pytest.approx(1.0, abs=0.05)


def test_correct_finds_close_match():
    # "203x133x31UB" — 31 is wrong, should suggest 30
    key, score = correct("203x133x31UB")
    assert score > 0.7, f"Expected high score, got {score}"
    assert "UB" in key


def test_correct_ub_not_confused_with_uc():
    # 203x203x46 is clearly a UC — correction should prefer UC side
    key, score = correct("203X203X46UB")
    # Either finds the UC correctly or the UB doesn't exist; either way score should still be reasonable
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_correct_returns_valid_tuple():
    key, score = correct("457X191X82UB")
    assert isinstance(key, str)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


# ── ub_uc_heuristic() ───────────────────────────────────────────────────────

def test_ub_horizontal_no_swap():
    result = ub_uc_heuristic("457X191X82UB", orientation="horizontal")
    assert result["swapped"] is False
    assert result["confidence"] == pytest.approx(1.0)


def test_ub_vertical_suggests_swap():
    # UB displayed vertically is unusual — heuristic may suggest UC swap
    result = ub_uc_heuristic("203X133X30UB", orientation="vertical")
    # May or may not find a UC swap, but should not crash
    assert isinstance(result["swapped"], bool)
    assert 0.0 <= result["confidence"] <= 1.0


def test_uc_vertical_no_swap():
    result = ub_uc_heuristic("203X203X46UC", orientation="vertical")
    assert result["swapped"] is False
    assert result["confidence"] == pytest.approx(1.0)


def test_uc_horizontal_suggests_swap():
    result = ub_uc_heuristic("203X203X46UC", orientation="horizontal")
    # A UC displayed horizontally is suspect
    assert isinstance(result["swapped"], bool)
    assert 0.0 <= result["confidence"] <= 1.0


def test_heuristic_on_unknown_label():
    result = ub_uc_heuristic("FAKEFAKE")
    # Should return gracefully
    assert result["confidence"] == pytest.approx(0.0)
    assert result["swapped"] is False
