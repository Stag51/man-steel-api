"""
file_detector.py
────────────────
Detect whether an input file is a vector PDF, raster PDF, or Revit (RVT) file.

Public API
----------
detect(path: Path) -> FileType
    Returns one of: FileType.PDF_VECTOR, FileType.PDF_RASTER, FileType.RVT,
    FileType.UNKNOWN.

FileType (Enum)
    PDF_VECTOR  — PDF with native text objects (direct text extraction possible)
    PDF_RASTER  — PDF whose sampled pages carry no native text (image-only)
    RVT         — Autodesk Revit file
    UNKNOWN     — Unrecognised extension or unreadable file
"""

from __future__ import annotations

import sys
from enum import Enum, auto
from pathlib import Path

# Optional PyMuPDF import — graceful degradation
try:
    import fitz  # PyMuPDF
    _HAS_FITZ = True
except ImportError:
    _HAS_FITZ = False


class FileType(Enum):
    PDF_VECTOR = auto()   # native text objects present
    PDF_RASTER = auto()   # image-only pages / no native text
    RVT        = auto()   # Autodesk Revit model
    UNKNOWN    = auto()   # unrecognised


# Number of pages (from the start) to sample when classifying a PDF
_PDF_SAMPLE_PAGES = 3

# Minimum number of *non-whitespace* characters on a page for it to be
# considered to contain native text.
_MIN_VECTOR_CHARS = 20


def _pdf_has_native_text(path: Path) -> bool:
    """
    Return True if the PDF appears to contain native (vector) text objects.

    Samples up to ``_PDF_SAMPLE_PAGES`` pages; if ANY of them carries
    ``_MIN_VECTOR_CHARS`` or more non-whitespace characters, the file is
    classified as vector.

    Falls back to False (raster) if PyMuPDF is not available.
    """
    if not _HAS_FITZ:
        # Cannot determine without PyMuPDF — assume raster so OCR is used.
        print(
            "[file_detector] WARNING: PyMuPDF (fitz) not installed. "
            "Cannot detect vector text; defaulting to PDF_RASTER.",
            file=sys.stderr,
        )
        return False

    try:
        doc = fitz.open(str(path))
        sample = min(len(doc), _PDF_SAMPLE_PAGES)
        for i in range(sample):
            page = doc[i]
            text = page.get_text("text")  # fastest full-text extraction
            non_ws = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
            if non_ws >= _MIN_VECTOR_CHARS:
                doc.close()
                return True
        doc.close()
        return False
    except Exception as exc:
        print(
            f"[file_detector] WARNING: Could not open PDF '{path.name}': {exc}. "
            "Defaulting to PDF_RASTER.",
            file=sys.stderr,
        )
        return False


def detect(path: Path | str) -> FileType:
    """
    Identify the file type of ``path``.

    Parameters
    ----------
    path : pathlib.Path or str — path to the input file.

    Returns
    -------
    FileType enum value.

    Notes
    -----
    - Extension check is case-insensitive.
    - For PDFs, pages are opened (not rendered) to detect native text.
    - Mixed PDFs (some vector, some raster) are classified as PDF_VECTOR;
      per-page raster fallback is handled by the vector extractor.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Input file not found: '{path}'")

    suffix = path.suffix.lower()

    if suffix == ".rvt":
        return FileType.RVT

    if suffix == ".pdf":
        if _pdf_has_native_text(path):
            return FileType.PDF_VECTOR
        return FileType.PDF_RASTER

    # Future: .ifc, .dwg, etc.
    return FileType.UNKNOWN


def describe(file_type: FileType) -> str:
    """Return a human-readable description of a FileType value."""
    return {
        FileType.PDF_VECTOR: "PDF (vector — native text objects detected)",
        FileType.PDF_RASTER: "PDF (raster — image-only, OCR required)",
        FileType.RVT:        "Revit model (.rvt)",
        FileType.UNKNOWN:    "Unknown / unsupported file type",
    }[file_type]
