"""
confidence_scorer.py
────────────────────
Compute a composite confidence score for each extracted structural label,
combining OCR probability, database validation, spatial association,
text clarity, and rule-based orientation logic.

Public API
----------
score(...)   -> ConfidenceBreakdown
    Build a ConfidenceBreakdown from individual component scores.

from_label(label, lines, section_type, orientation_deg)
    Convenience wrapper that derives all component scores from an
    ExtractedLabel (PDF) or RevitElement and optional geometry context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, TYPE_CHECKING

from spatial_mapper import (
    Line2D,
    nearest_line_distance,
    spatial_association_score,
    orientation_heuristic,
)

# ══════════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════════

# Composite score below which a label is flagged for human review
REVIEW_THRESHOLD: float = 0.70

# Component weights (must sum to 1.0)
WEIGHTS: dict[str, float] = {
    "ocr_prob":    0.25,
    "db_score":    0.35,
    "spatial":     0.20,
    "clarity":     0.10,
    "orientation": 0.10,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"


# ══════════════════════════════════════════════════════════════════════════════
# Result type
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ConfidenceBreakdown:
    """
    Composite confidence for a single extracted structural label.

    Attributes
    ----------
    ocr_prob          : OCR detection confidence (1.0 for vector/RVT sources)
    db_score          : steel section database match confidence (0–1)
    spatial_score     : proximity-to-geometry score (0–1); 0.5 if no geometry
    clarity_score     : image sharpness score (1.0 for vector/RVT sources)
    orientation_score : rule-based orientation plausibility (0–1)
    composite         : weighted average of all components, clamped [0, 1]
    needs_review      : True if composite < REVIEW_THRESHOLD
    """
    ocr_prob:          float
    db_score:          float
    spatial_score:     float
    clarity_score:     float
    orientation_score: float
    composite:         float
    needs_review:      bool

    def as_dict(self) -> dict:
        return {
            "ocr_prob":          round(self.ocr_prob, 4),
            "db_score":          round(self.db_score, 4),
            "spatial_score":     round(self.spatial_score, 4),
            "clarity_score":     round(self.clarity_score, 4),
            "orientation_score": round(self.orientation_score, 4),
            "composite":         round(self.composite, 4),
            "needs_review":      self.needs_review,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Core scorer
# ══════════════════════════════════════════════════════════════════════════════

def score(
    ocr_prob:          float,
    db_score:          float,
    spatial_score:     float,
    clarity_score:     float,
    orientation_score: float,
) -> ConfidenceBreakdown:
    """
    Compute a ConfidenceBreakdown from pre-computed component scores.

    All inputs should be floats in [0, 1].  The composite is the weighted
    average defined by ``WEIGHTS``, clamped to [0, 1].
    """
    w = WEIGHTS
    composite = (
        w["ocr_prob"]    * float(ocr_prob)
        + w["db_score"]    * float(db_score)
        + w["spatial"]     * float(spatial_score)
        + w["clarity"]     * float(clarity_score)
        + w["orientation"] * float(orientation_score)
    )
    composite = float(min(1.0, max(0.0, composite)))

    return ConfidenceBreakdown(
        ocr_prob          = float(ocr_prob),
        db_score          = float(db_score),
        spatial_score     = float(spatial_score),
        clarity_score     = float(clarity_score),
        orientation_score = float(orientation_score),
        composite         = composite,
        needs_review      = composite < REVIEW_THRESHOLD,
    )


def from_pdf_label(
    ocr_prob:     float,
    db_score:     float,
    clarity:      float,
    section_type: str,
    angle_deg:    float,
    centre:       tuple[float, float],
    lines:        Sequence[Line2D] | None = None,
    max_pt:       float = 50.0,
) -> ConfidenceBreakdown:
    """
    Build a ConfidenceBreakdown for a PDF-sourced label.

    Parameters
    ----------
    ocr_prob     : PaddleOCR confidence (1.0 for vector text)
    db_score     : from grammar_parser.ParsedSection.db_score
    clarity      : Laplacian blur score (1.0 for vector text)
    section_type : e.g. "UB", "UC"
    angle_deg    : text rotation angle
    centre       : (cx, cy) in PDF points
    lines        : structural line geometry for spatial association
    max_pt       : distance normalisation factor (PDF points)
    """
    dist      = nearest_line_distance(centre, lines or [])
    sp_score  = spatial_association_score(dist, max_expected_pt=max_pt)
    ori_score = orientation_heuristic(section_type, angle_deg)

    return score(
        ocr_prob          = ocr_prob,
        db_score          = db_score,
        spatial_score     = sp_score,
        clarity_score     = clarity,
        orientation_score = ori_score,
    )


def from_revit_element(
    db_score:    float,
    orientation: str,
    section_type: str,
) -> ConfidenceBreakdown:
    """
    Build a ConfidenceBreakdown for a Revit API–sourced element.

    RVT elements require no OCR (prob = 1.0) and no clarity check (1.0).
    Spatial score defaults to 1.0 (native coordinates are exact).
    Orientation is derived from the element's LocationCurve direction.
    """
    # Map Revit orientation string → expected angle
    revit_angle_map = {
        "horizontal": 0.0,
        "vertical":   90.0,
        "diagonal":   45.0,
        "unknown":    0.0,
    }
    angle_deg = revit_angle_map.get(orientation.lower(), 0.0)
    ori_score = orientation_heuristic(section_type, angle_deg)

    return score(
        ocr_prob          = 1.0,   # no OCR
        db_score          = db_score,
        spatial_score     = 1.0,   # native coordinates
        clarity_score     = 1.0,   # no image quality concern
        orientation_score = ori_score,
    )
