"""
pdf_vector_extractor.py
───────────────────────
Extract structural section labels with exact bounding-box coordinates from
vector (native-text) PDFs using PyMuPDF.

For pages that yield no native text, a per-page fallback to the raster
extractor is performed automatically.

Public API
----------
extract(pdf_path, raster_dpi) -> list[ExtractedLabel]
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import fitz  # PyMuPDF

from grammar_parser import parse as grammar_parse, ParsedSection
from spatial_mapper import is_in_drawing_zone

if TYPE_CHECKING:
    pass


# ══════════════════════════════════════════════════════════════════════════════
# Result type
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExtractedLabel:
    """
    A single structural section label extracted from a PDF.

    Attributes
    ----------
    text        : raw text as matched
    parsed      : validated ParsedSection (None if regex found no hit)
    bbox        : (x0, y0, x1, y1) in PDF points (1 pt = 1/72 in)
                  origin is bottom-left in PDF coordinates
    centre      : bounding-box centre (cx, cy) in pt
    page        : 1-based page number
    angle_deg   : text rotation angle in degrees (0 = left→right)
    source      : "pdf_vector" | "pdf_raster_fallback"
    ocr_prob    : always 1.0 for native vector text
    clarity     : always 1.0 for native vector text (no blur)
    """
    text:       str
    parsed:     ParsedSection | None
    bbox:       tuple[float, float, float, float]
    centre:     tuple[float, float]
    page:       int
    angle_deg:  float
    source:     str
    ocr_prob:   float = 1.0
    clarity:    float = 1.0


# ══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _direction_to_angle(dir_vec: tuple[float, float]) -> float:
    """
    Convert a PyMuPDF direction cosine vector to a rotation angle in degrees.
    dir_vec = (cos θ, sin θ) in PDF coordinate space.
    """
    dx, dy = dir_vec
    return math.degrees(math.atan2(dy, dx))


def _span_angle(span: dict) -> float:
    """Return the rotation angle of a text span dict from rawdict output."""
    try:
        return _direction_to_angle(span.get("dir", (1.0, 0.0)))
    except Exception:
        return 0.0


def _span_bbox(span: dict) -> tuple[float, float, float, float]:
    """Return (x0, y0, x1, y1) from a rawdict span."""
    bb = span.get("bbox", (0, 0, 0, 0))
    return float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])


def _bbox_centre(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _extract_page_vector(page: fitz.Page, page_no: int) -> list[ExtractedLabel]:
    """
    Extract all structural labels from a single vector PDF page.
    Uses 'words' for robust text extraction and grouping.
    """
    labels: list[ExtractedLabel] = []

    # get_text("words") returns: (x0, y0, x1, y1, "word", block_no, line_no, word_no)
    words = page.get_text("words")
    
    # Group by (block_no, line_no)
    lines: dict[tuple[int, int], list[tuple]] = {}
    for w in words:
        key = (w[5], w[6])
        if key not in lines:
            lines[key] = []
        lines[key].append(w)

    for key in sorted(lines.keys()):
        line_words = sorted(lines[key], key=lambda w: w[7]) # sort by word_no
        line_text = " ".join(w[4] for w in line_words).strip()
        
        if not line_text:
            pass

        parsed_hits = grammar_parse(line_text)
        if not parsed_hits:
            continue

        # Line geometry
        x0 = min(w[0] for w in line_words)
        y0 = min(w[1] for w in line_words)
        x1 = max(w[2] for w in line_words)
        y1 = max(w[3] for w in line_words)
        bbox = (x0, y0, x1, y1)
        centre = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)

        # rotation fallback: page.get_text("words") doesn't give angle.
        # Most structural labels are horizontal or vertical.
        # We'll assume horizontal (0.0) unless the bbox is tall.
        width = x1 - x0
        height = y1 - y0
        angle = 90.0 if height > width * 2 else 0.0

        # Spatial Filtering: Skip if label is in the 'legend/title block' zone
        # We simulate the img_size_px/dpi logic by passing actual pt dimensions
        page_rect = page.rect
        # is_in_drawing_zone expects img_size_px and dpi to calculate pt. 
        # We can pass them such that factor = 1.0 (dpi=72).
        if not is_in_drawing_zone(centre, (int(page_rect.width), int(page_rect.height)), 72.0):
            continue

        for ps in parsed_hits:
            labels.append(ExtractedLabel(
                text      = ps.raw,
                parsed    = ps,
                bbox      = bbox,
                centre    = centre,
                page      = page_no,
                angle_deg = angle,
                source    = "pdf_vector",
                ocr_prob  = 1.0,
                clarity   = 1.0,
            ))

    return labels


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

MIN_VECTOR_CHARS = 20   # below this, treat page as effectively raster


def extract(
    pdf_path: Path | str,
    raster_dpi: int = 400,
    raster_fallback: bool = True,
) -> list[ExtractedLabel]:
    """
    Extract structural labels from a (primarily) vector PDF.

    For pages that carry fewer than ``MIN_VECTOR_CHARS`` non-whitespace
    characters the per-page raster fallback is invoked automatically
    (requires ``pdf_raster_extractor`` to be importable).

    Parameters
    ----------
    pdf_path        : path to the PDF file
    raster_dpi      : DPI to use for the raster fallback (default 350)
    raster_fallback : whether to attempt raster OCR on text-empty pages

    Returns
    -------
    Flat list of ``ExtractedLabel`` objects across all pages.
    """
    pdf_path = Path(pdf_path)
    labels: list[ExtractedLabel] = []

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)

    for idx, page in enumerate(doc):
        page_no = idx + 1
        page_text = page.get_text("text")
        non_ws    = len(page_text.replace(" ", "").replace("\n", "").replace("\t", ""))

        if non_ws >= MIN_VECTOR_CHARS:
            page_labels = _extract_page_vector(page, page_no)
            labels.extend(page_labels)
            print(
                f"[vector] Page {page_no}/{total_pages}: "
                f"{len(page_labels)} label(s) extracted."
            )
        elif raster_fallback:
            print(
                f"[vector] Page {page_no}/{total_pages}: "
                f"no native text — falling back to raster OCR."
            )
            try:
                from pdf_raster_extractor import extract_page_pil
                pil_image = page.get_pixmap(dpi=raster_dpi).pil_image()
                from pdf_raster_extractor import _process_pil_image
                raster_labels = _process_pil_image(pil_image, page_no, raster_dpi, source="pdf_raster_fallback")
                labels.extend(raster_labels)
                print(
                    f"         (raster) {len(raster_labels)} label(s) from OCR."
                )
            except Exception as exc:
                print(
                    f"[vector] Page {page_no}: raster fallback failed: {exc}",
                    file=sys.stderr,
                )
        else:
            print(f"[vector] Page {page_no}/{total_pages}: skipped (no text, no fallback).")

    doc.close()
    print(f"[vector] Total labels extracted: {len(labels)}")
    return labels
