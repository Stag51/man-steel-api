"""
pdf_raster_extractor.py
───────────────────────
Extract structural section labels from rasterised (image-only) PDF pages
using PaddleOCR with rotation-aware detection and blur scoring.

Requires: paddlepaddle, paddleocr, opencv-python, pdf2image, Pillow.

Public API
----------
extract(pdf_path, dpi) -> list[ExtractedLabel]
    Full-document raster pipeline.

_process_pil_image(pil_img, page_no, dpi, source) -> list[ExtractedLabel]
    Single-image entry point (used by pdf_vector_extractor's raster fallback).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from pdf2image import convert_from_path
from PIL import Image

from grammar_parser import parse as grammar_parse, ParsedSection
from spatial_mapper import pixel_to_pt, bbox_centre, is_in_drawing_zone

# ── Optional imports with graceful degradation ────────────────────────────────
try:
    import cv2 as _cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False
    print("[raster] WARNING: opencv-python not installed. Blur scoring disabled.", file=sys.stderr)

try:
    from paddleocr import PaddleOCR as _PaddleOCR
    _HAS_PADDLE = True
except ImportError:
    _HAS_PADDLE = False
    print("[raster] WARNING: paddleocr not installed. Raster OCR unavailable.", file=sys.stderr)

# ══════════════════════════════════════════════════════════════════════════════
# Result type (re-exported shape identical to pdf_vector_extractor)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExtractedLabel:
    """
    A single structural label found via OCR on a rasterised PDF page.

    Attributes
    ----------
    text        : raw matched text
    parsed      : ParsedSection (or None if grammar found no hit)
    bbox        : (x0, y0, x1, y1) in PDF points
    centre      : bbox centre in PDF points
    page        : 1-based page number
    angle_deg   : detected text rotation angle (0 / 90 / 180 / 270)
    source      : "pdf_raster" | "pdf_raster_fallback"
    ocr_prob    : PaddleOCR detection confidence 0–1
    clarity     : Laplacian variance score normalised to 0–1
    """
    text:       str
    parsed:     ParsedSection | None
    bbox:       tuple[float, float, float, float]
    centre:     tuple[float, float]
    page:       int
    angle_deg:  float
    source:     str
    ocr_prob:   float
    clarity:    float


# ══════════════════════════════════════════════════════════════════════════════
# Lazy PaddleOCR initialisation (avoid loading model at import time)
# ══════════════════════════════════════════════════════════════════════════════

_ocr_instance: Any = None


def _get_ocr() -> Any:
    """Return a cached PaddleOCR instance, initialising it on first call."""
    global _ocr_instance
    if _ocr_instance is None:
        if not _HAS_PADDLE:
            raise ImportError(
                "paddleocr is not installed. "
                "Run: pip install paddlepaddle paddleocr"
            )
        _ocr_instance = _PaddleOCR(
            use_angle_cls=True,   # enable 0 / 90 / 180 / 270 classification
            lang="en",
            show_log=False,
            # Sensitivity adjustments
            det_db_thresh=0.2,    # lower threshold for text detection (default 0.3)
            det_db_box_thresh=0.3, # lower box threshold (default 0.5)
            drop_score=0.3,       # keep lower confidence hits for grammar to filter
        )
    return _ocr_instance


# ══════════════════════════════════════════════════════════════════════════════
# Blur / clarity scoring
# ══════════════════════════════════════════════════════════════════════════════

_CLARITY_SATURATION_VAR = 200.0   # Laplacian variance above which score = 1.0


def _laplacian_clarity(pil_img: Image.Image, bbox_px: tuple) -> float:
    """
    Compute a clarity (sharpness) score for the text ROI using the
    Laplacian variance method.

    Returns a float in [0, 1] where 1.0 = perfectly sharp and 0.0 = very blurry.
    Returns 1.0 if cv2 is not available.
    """
    if not _HAS_CV2:
        return 1.0

    x0, y0, x1, y1 = [int(v) for v in bbox_px]
    arr  = np.array(pil_img.convert("L"))
    roi  = arr[y0:y1, x0:x1]

    if roi.size == 0:
        return 0.0

    variance = float(_cv2.Laplacian(roi, _cv2.CV_64F).var())
    score    = min(1.0, variance / _CLARITY_SATURATION_VAR)
    return score


# ══════════════════════════════════════════════════════════════════════════════
# Angle classification mapping
# ══════════════════════════════════════════════════════════════════════════════

# PaddleOCR angle classifier returns an integer index (0 or 1) meaning
# 0° and 180°. The label angle is extracted from OCR output directly
# where available as a float. For robustness we maintain a mapping.
_PADDLE_ANGLE_MAP: dict[int, float] = {0: 0.0, 1: 180.0}


def _parse_paddle_angle(angle_result: Any) -> float:
    """
    Extract a float angle in degrees from PaddleOCR angle classifier output.

    PaddleOCR returns angle_result as (label_idx, confidence).
    """
    try:
        if isinstance(angle_result, (list, tuple)):
            idx = int(angle_result[0])
            return _PADDLE_ANGLE_MAP.get(idx, 0.0)
        return float(angle_result)
    except Exception:
        return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Core single-image processing
# ══════════════════════════════════════════════════════════════════════════════

def _process_pil_image(
    pil_img: Image.Image,
    page_no: int,
    dpi: float,
    source: str = "pdf_raster",
) -> list[ExtractedLabel]:
    """
    Run OCR on a PIL image and return validated structural labels.

    Parameters
    ----------
    pil_img  : PIL.Image (RGB or L)
    page_no  : 1-based page number for traceability
    dpi      : the render DPI (used to convert pixel coords → PDF points)
    source   : label tag ("pdf_raster" | "pdf_raster_fallback")
    """
    if not _HAS_PADDLE:
        raise ImportError("paddleocr required for raster extraction.")

    ocr    = _get_ocr()
    # det_db_thresh: lower = more sensitive to small/faint text
    # det_limit_side_len: larger = better for large high-res drawings
    result = ocr.ocr(np.array(pil_img), cls=True)

    labels: list[ExtractedLabel] = []

    if not result or result[0] is None:
        return labels

    for line in result[0]:
        # line format: [[[x0,y0],[x1,y1],[x2,y2],[x3,y3]], (text, conf)]
        try:
            quad, (text, conf) = line
        except (ValueError, TypeError):
            continue

        if not text or not text.strip():
            continue

        # Grammar validation
        parsed_hits = grammar_parse(text)
        if not parsed_hits:
            continue

        # Derive axis-aligned bounding box from the quad vertices
        xs = [pt[0] for pt in quad]
        ys = [pt[1] for pt in quad]
        px_bbox = (min(xs), min(ys), max(xs), max(ys))

        # Convert pixel bbox → PDF points
        pt_bbox = pixel_to_pt(px_bbox, dpi)
        centre  = bbox_centre(pt_bbox)

        # Spatial Filtering: Skip if label is in the 'legend/title block' zone
        # (Assuming standard margin-based filtering for now)
        if not is_in_drawing_zone(centre, pil_img.size, dpi):
            continue

        # Detect angle from quad: angle of the base edge (bottom of text)
        dx = quad[1][0] - quad[0][0]
        dy = quad[1][1] - quad[0][1]
        import math
        angle_deg = math.degrees(math.atan2(dy, dx))

        # Clarity score on the ROI
        clarity = _laplacian_clarity(pil_img, px_bbox)

        for ps in parsed_hits:
            labels.append(ExtractedLabel(
                text      = ps.raw,
                parsed    = ps,
                bbox      = pt_bbox,
                centre    = centre,
                page      = page_no,
                angle_deg = angle_deg,
                source    = source,
                ocr_prob  = float(conf),
                clarity   = clarity,
            ))

    return labels


# ══════════════════════════════════════════════════════════════════════════════
# Public API — full document
# ══════════════════════════════════════════════════════════════════════════════

def extract(
    pdf_path: Path | str,
    dpi: int = 400,
) -> list[ExtractedLabel]:
    """
    Extract structural labels from every page of a raster PDF.

    Parameters
    ----------
    pdf_path : path to the PDF file
    dpi      : render resolution (300–400 recommended; default 350)

    Returns
    -------
    Flat list of ``ExtractedLabel`` objects across all pages.
    """
    pdf_path = Path(pdf_path)
    labels:  list[ExtractedLabel] = []

    print(f"[raster] Rasterising '{pdf_path.name}' at {dpi} DPI …")
    
    # Discovery logic for poppler on Windows/Anaconda
    poppler_path = None
    if sys.platform == "win32":
        # Check standard Anaconda/Library/bin or common install locations
        possible_paths = [
            Path(sys.prefix) / "Library" / "bin",
            Path(r"C:\Program Files\poppler\bin"),
            Path(r"C:\poppler\bin"),
        ]
        for p in possible_paths:
            if (p / "pdftoppm.exe").exists():
                poppler_path = str(p)
                break

    pages = convert_from_path(str(pdf_path), dpi=dpi, poppler_path=poppler_path)
    total = len(pages)

    for page_no, pil_img in enumerate(pages, start=1):
        print(f"[raster] OCR page {page_no}/{total} …", end=" ", flush=True)
        try:
            page_labels = _process_pil_image(pil_img, page_no, float(dpi))
            labels.extend(page_labels)
            print(f"{len(page_labels)} hit(s).")
        except Exception as exc:
            print(f"ERROR — {exc}", file=sys.stderr)

    print(f"[raster] Total labels: {len(labels)}")
    return labels
