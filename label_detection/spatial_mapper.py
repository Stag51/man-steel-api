"""
spatial_mapper.py
─────────────────
Map extracted text bounding boxes to structural geometry and derive
orientation quality scores.

Public API
----------
bbox_centre(bbox)                    -> tuple[float, float]
nearest_line_distance(centre, lines) -> float | None
orientation_heuristic(section_type, angle_deg) -> float
pixel_to_pt(px_bbox, dpi)           -> tuple[float, float, float, float]
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


# ══════════════════════════════════════════════════════════════════════════════
# Geometry primitives
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Line2D:
    """
    A line segment in 2-D space (PDF points or mm).

    Attributes
    ----------
    x0, y0 : start point
    x1, y1 : end point
    label   : optional identifier (e.g. grid reference or element ID)
    """
    x0: float
    y0: float
    x1: float
    y1: float
    label: str = ""

    @property
    def midpoint(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    @property
    def length(self) -> float:
        return math.hypot(self.x1 - self.x0, self.y1 - self.y0)

    @property
    def angle_deg(self) -> float:
        """Angle from horizontal in degrees [0, 180)."""
        a = math.degrees(math.atan2(self.y1 - self.y0, self.x1 - self.x0))
        return a % 180.0


# ══════════════════════════════════════════════════════════════════════════════
# Orientation heuristic constants
# ══════════════════════════════════════════════════════════════════════════════

# Section types that are *expected* to be oriented vertically (≈ 90°)
_TYPICALLY_VERTICAL   = {"UC", "WC", "CL", "HP", "RD", "PL"}

# Section types that are *expected* to be oriented horizontally (≈ 0°)
_TYPICALLY_HORIZONTAL = {"UB", "WB", "PFC", "TFC", "BHP", "RSC"}

# Angular tolerance in degrees for orientation match
_ORIENT_TOL_DEG = 20.0


# ══════════════════════════════════════════════════════════════════════════════
# Public helpers
# ══════════════════════════════════════════════════════════════════════════════

def bbox_centre(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """Return the centre point of an (x0, y0, x1, y1) bounding box."""
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def pixel_to_pt(
    px_bbox: tuple[float, float, float, float],
    dpi: float,
) -> tuple[float, float, float, float]:
    """
    Convert a pixel-space bounding box to PDF points.

    PDF points = pixels × 72 / dpi.
    """
    factor = 72.0 / dpi
    x0, y0, x1, y1 = px_bbox
    return (x0 * factor, y0 * factor, x1 * factor, y1 * factor)


def point_to_segment_distance(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
) -> float:
    """
    Euclidean distance from point P to line segment AB.
    """
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        # Degenerate segment (zero length)
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def nearest_line_distance(
    centre: tuple[float, float],
    lines: Sequence[Line2D],
) -> float | None:
    """
    Return the distance (in the source unit — pt or mm) from ``centre`` to
    the nearest structural line segment in ``lines``.

    Returns ``None`` if no lines are supplied.
    """
    if not lines:
        return None

    cx, cy = centre
    return min(
        point_to_segment_distance(cx, cy, ln.x0, ln.y0, ln.x1, ln.y1)
        for ln in lines
    )


def spatial_association_score(
    distance: float | None,
    max_expected_pt: float = 50.0,
) -> float:
    """
    Convert a nearest-line distance to a [0, 1] association score.

    A distance of 0 → 1.0; a distance ≥ ``max_expected_pt`` → ~0.0.
    Uses exponential decay: score = exp(−distance / max_expected_pt × 3).

    Parameters
    ----------
    distance        : pt/mm to nearest structural line (None → 0.5 neutral)
    max_expected_pt : distance above which score saturates at ~0
    """
    if distance is None:
        return 0.5  # neutral when no geometry available
    score = math.exp(-3.0 * distance / max(max_expected_pt, 1.0))
    return float(min(1.0, max(0.0, score)))


def orientation_heuristic(
    section_type: str,
    angle_deg: float,
) -> float:
    """
    Return a [0, 1] score indicating how well the text orientation matches
    the structural expectation for the given section type.

    Rules
    -----
    - UC/WC/Column-type sections are expected to be labelled vertically (≈ 90°).
    - UB/WB/Beam-type sections are expected to be labelled horizontally (≈ 0°/180°).
    - All other section types return a neutral score of 0.5.
    - If the orientation *contradicts* the expectation → 0.0.
    - If the orientation *matches*                   → 1.0.
    - If partially within tolerance on the wrong side → 0.25.

    Parameters
    ----------
    section_type : normalised section type string, e.g. "UB", "UC"
    angle_deg    : text rotation angle in degrees (from horizontal)
    """
    stype = section_type.strip().upper()

    # Normalise angle to [0, 180)
    a = angle_deg % 180.0

    is_vertical   = abs(a - 90.0) <= _ORIENT_TOL_DEG
    is_horizontal = (a <= _ORIENT_TOL_DEG) or (a >= 180.0 - _ORIENT_TOL_DEG)

    if stype in _TYPICALLY_VERTICAL:
        if is_vertical:
            return 1.0
        if is_horizontal:
            return 0.0
        return 0.5  # diagonal / unknown

    if stype in _TYPICALLY_HORIZONTAL:
        if is_horizontal:
            return 1.0
        if is_vertical:
            return 0.0
        return 0.5

    # No expectation for this section type
    return 0.5


def is_in_drawing_zone(
    centre_pt: tuple[float, float],
    img_size_px: tuple[int, int],
    dpi: float,
    right_margin_pct: float = 0.20,
    bottom_margin_pct: float = 0.10,
) -> bool:
    """
    Return True if the centre point is within the 'Main Drawing' area.
    Filters out labels located in common legend/title-block areas.

    Parameters
    ----------
    centre_pt         : (cx, cy) in PDF points
    img_size_px       : (width, height) of the rendered image in pixels
    dpi               : resolution used for rendering
    right_margin_pct  : fraction of width to ignore on the right (0.20 = 20%)
    bottom_margin_pct : fraction of height to ignore at the bottom (0.10 = 10%)
    """
    factor = 72.0 / dpi
    page_w_pt = img_size_px[0] * factor
    page_h_pt = img_size_px[1] * factor

    cx, cy = centre_pt

    # Define boundaries
    # Note: cy=0 is top in PDF points if derived directly from pixel-y
    # We check if cx is too far right or cy is too far down
    if cx > page_w_pt * (1.0 - right_margin_pct):
        return False
    if cy > page_h_pt * (1.0 - bottom_margin_pct):
        return False

    return True
