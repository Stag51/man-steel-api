"""
boundary_detector.py
────────────────────
Detects structural drawing frame rectangles on a PDF page.
Prevents auto-labeling of elements in title blocks, legends, and notes areas.
"""
import fitz
from typing import List


class DrawingFrame:
    """A detected drawing frame boundary on a PDF page."""

    def __init__(self, rect: fitz.Rect):
        self.rect = rect

    @property
    def x0(self): return self.rect.x0

    @property
    def y0(self): return self.rect.y0

    @property
    def x1(self): return self.rect.x1

    @property
    def y1(self): return self.rect.y1

    def contains(self, x: float, y: float, margin: float = 10.0) -> bool:
        """Return True if point (x, y) falls inside this frame (+/- margin)."""
        return (
            self.x0 - margin <= x <= self.x1 + margin
            and self.y0 - margin <= y <= self.y1 + margin
        )

    def as_dict(self) -> dict:
        return {
            "x0": round(self.x0, 2),
            "y0": round(self.y0, 2),
            "x1": round(self.x1, 2),
            "y1": round(self.y1, 2),
        }


def detect_drawing_frames(page: fitz.Page) -> List[DrawingFrame]:
    """
    Find all structural drawing frame rectangles on a page by scanning
    for large, stroked, rectangular vector paths that act as drawing borders.

    A drawing frame must:
    - Cover between 5% and 97% of page area
    - Be at least 20pt wide and tall on both sides
    - Be un-filled (or white-filled) — frames are outlines
    - Contain at least one 're' item or ≥4 'l' line segments
    """
    pw, ph = page.rect.width, page.rect.height
    page_area = pw * ph
    candidates = []

    for path in page.get_drawings():
        rect = path.get("rect")
        if not rect:
            continue

        w, h = rect.width, rect.height
        area = w * h

        # Area range: must be a MAJOR frame (>=25% of page), not a small detail box.
        # The 25% threshold stops schedule tables and tiny detail frames from
        # being treated as drawing boundaries and blocking the main floor plan.
        if area < page_area * 0.25 or area > page_area * 0.97:
            continue

        # Minimum thickness (reject dimension lines / thin borders)
        if min(w, h) < 20:
            continue

        # Reject filled shapes (hatch patterns etc.) — allow white fill
        fill = path.get("fill")
        if fill is not None and fill not in ((1, 1, 1), [1, 1, 1]):
            continue

        # Must have a stroke
        if path.get("color") is None and not path.get("width"):
            continue

        # Confirm rectangular topology
        items = path.get("items", [])
        has_re = any(item[0] == "re" for item in items)
        line_count = sum(1 for item in items if item[0] == "l")
        if has_re or line_count >= 4:
            candidates.append(DrawingFrame(rect))

    frames = _deduplicate(candidates)
    # Largest frames first
    frames.sort(
        key=lambda f: (f.x1 - f.x0) * (f.y1 - f.y0),
        reverse=True,
    )
    return frames


def _intersection_area(a: fitz.Rect, b: fitz.Rect) -> float:
    ix0, iy0 = max(a.x0, b.x0), max(a.y0, b.y0)
    ix1, iy1 = min(a.x1, b.x1), min(a.y1, b.y1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return (ix1 - ix0) * (iy1 - iy0)


def _deduplicate(frames: List[DrawingFrame]) -> List[DrawingFrame]:
    """Remove frames that are >90% covered by another (near-duplicates)."""
    result: List[DrawingFrame] = []
    for f in frames:
        area = f.rect.width * f.rect.height
        if any(
            _intersection_area(f.rect, e.rect) > 0.90 * area
            for e in result
        ):
            continue
        result.append(f)
    return result


def get_effective_frames(page: fitz.Page) -> List[DrawingFrame]:
    """
    Return detected drawing frames, or a permissive page-margin fallback.
    Prioritizes the single largest frame as the 'Main Drawing'.
    """
    pw, ph = page.rect.width, page.rect.height
    page_area = pw * ph

    frames = detect_drawing_frames(page)

    if frames:
        # Sort by area descending
        frames.sort(key=lambda f: (f.x1 - f.x0) * (f.y1 - f.y0), reverse=True)
        largest = frames[0]
        l_area = (largest.x1 - largest.x0) * (largest.y1 - largest.y0)
        
        # If the largest frame is a significant portion of the page, it's our Main Drawing
        if l_area >= page_area * 0.30:
            return [largest]
        
        # Otherwise, if we have multiple frames that collectively cover the page
        covered = sum((f.x1 - f.x0) * (f.y1 - f.y0) for f in frames)
        if covered >= page_area * 0.40:
            return frames

    # Fallback to generous margins
    return [DrawingFrame(fitz.Rect(pw * 0.01, ph * 0.05, pw * 0.92, ph * 0.90))]


def point_in_drawing(x: float, y: float, frames: List[DrawingFrame],
                     margin: float = 10.0) -> bool:
    """Return True if (x, y) is inside at least one detected drawing frame."""
    if not frames:
        return True
    return any(f.contains(x, y, margin) for f in frames)
