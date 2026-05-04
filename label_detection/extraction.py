"""
extraction.py
─────────────
Structural section extractor — **fully open-source, zero API calls**.

Replaced the previous Gemini/Vertex AI pipeline with:
  • PyMuPDF (fitz)   — native text extraction from vector PDFs
  • PaddleOCR        — rotation-aware OCR for raster/scanned PDFs
  • grammar_parser   — regex + steel-section DB validation
  • confidence_scorer— composite 0-1 score per label

Workflow:
  1. Detect whether the PDF page has native text (vector) or is image-only (raster).
  2. For vector pages  → extract text objects directly via PyMuPDF, preserving
     exact bounding-box coordinates and character-level rotation angles.
  3. For raster pages  → convert at high DPI (300–400), run PaddleOCR with
     angle classification, compute Laplacian blur score per region.
  4. Validate every extracted string through grammar_parser (regex +
     steel-section database cross-reference).
  5. Score each label with a composite confidence value.
  6. Save a structured JSON report.

Usage:
  python extraction.py drawing.pdf
  python extraction.py drawing.pdf --output results.json --dpi 350
  python extraction.py drawing.pdf --keep-images --image-dir ./pages
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# ── Open-source pipeline modules ─────────────────────────────────────────────
from file_detector    import detect as detect_type, FileType
from grammar_parser   import ParsedSection
from confidence_scorer import from_pdf_label, REVIEW_THRESHOLD

# ── Optional heavy dependencies (graceful error messages) ────────────────────
try:
    import fitz   # PyMuPDF
    _HAS_FITZ = True
except ImportError:
    _HAS_FITZ = False

try:
    from paddleocr import PaddleOCR
    _HAS_PADDLE = True
except ImportError:
    _HAS_PADDLE = False

# ══════════════════════════════════════════════════════════════════════════════
# Default settings (override via CLI flags)
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_DPI         = 350          # 300–400 is optimal for structural drawings
DEFAULT_OUTPUT_JSON = "extraction_results.json"
REVIEW_FLAG_THRESHOLD = REVIEW_THRESHOLD   # 0.70


# ══════════════════════════════════════════════════════════════════════════════
# Core single-file runner
# ══════════════════════════════════════════════════════════════════════════════

def run_pdf(pdf_path: Path, dpi: int = DEFAULT_DPI) -> list[dict[str, Any]]:
    """
    Run the open-source extraction pipeline on a single PDF.

    Automatically chooses the vector or raster path per page.

    Returns
    -------
    List of label dicts (one per structural hit across all pages).
    """
    file_type = detect_type(pdf_path)

    if file_type == FileType.PDF_VECTOR:
        from pdf_vector_extractor import extract
        labels = extract(pdf_path, raster_dpi=dpi, raster_fallback=True)
    elif file_type == FileType.PDF_RASTER:
        from pdf_raster_extractor import extract
        labels = extract(pdf_path, dpi=dpi)
    else:
        raise ValueError(f"Unsupported file type for PDF path: {file_type}")

    records: list[dict[str, Any]] = []
    for lbl in labels:
        ps: ParsedSection | None = lbl.parsed
        conf = from_pdf_label(
            ocr_prob     = lbl.ocr_prob,
            db_score     = ps.db_score     if ps else 0.0,
            clarity      = lbl.clarity,
            section_type = ps.section_type if ps else "UNKNOWN",
            angle_deg    = lbl.angle_deg,
            centre       = lbl.centre,
            lines        = None,
        )
        records.append({
            "page":          lbl.page,
            "raw_text":      lbl.text,
            "normalised":    ps.normalised   if ps else lbl.text.upper(),
            "section_type":  ps.section_type if ps else "UNKNOWN",
            "depth_mm":      ps.depth        if ps else None,
            "width_mm":      ps.width        if ps else None,
            "mass_kg_m":     ps.mass_or_t    if ps else None,
            "db_corrected":  ps.db_corrected if ps else None,
            "coordinates": {
                "x": round(lbl.centre[0], 3),
                "y": round(lbl.centre[1], 3),
                "unit": "pt",
            },
            "angle_deg":    round(lbl.angle_deg, 2),
            "source":       lbl.source,
            "ocr_prob":     round(lbl.ocr_prob, 4),
            "clarity":      round(lbl.clarity, 4),
            "confidence":   conf.as_dict(),
        })

    return records


# ══════════════════════════════════════════════════════════════════════════════
# Report + output
# ══════════════════════════════════════════════════════════════════════════════

def print_report(pdf_path: Path, records: list[dict[str, Any]]) -> None:
    sep  = "=" * 72
    sep2 = "-" * 72

    needs_review = [r for r in records if r["confidence"]["needs_review"]]

    print(f"\n{'STRUCTURAL EXTRACTION REPORT':^72}")
    print(sep)
    print(f"  Source         : {pdf_path}")
    print(f"  Total labels   : {len(records)}")
    print(f"  Needs review   : {len(needs_review)}  (confidence < {REVIEW_FLAG_THRESHOLD})")
    print(sep)

    # Group by page
    pages: dict[int, list[dict]] = {}
    for r in records:
        pages.setdefault(r["page"], []).append(r)

    for page_no, page_records in sorted(pages.items()):
        print(f"\n  Page {page_no}")
        print(f"  {sep2}")
        for r in page_records:
            flag = " ⚠" if r["confidence"]["needs_review"] else ""
            print(
                f"    {r['normalised']:<35}  "
                f"conf={r['confidence']['composite']:.2f}  "
                f"({r['source']}){flag}"
            )

    if needs_review:
        print(f"\n{sep}")
        print(f"  ⚠  Labels requiring human review:")
        for r in needs_review:
            print(
                f"    [p{r['page']}]  {r['raw_text']!r}  "
                f"->  composite={r['confidence']['composite']:.2f}"
            )

    print(f"\n{sep}")

    # Global unique section list
    unique = sorted({r["normalised"] for r in records})
    if unique:
        print(f"  All unique sections ({len(unique)}):")
        for u in unique:
            print(f"    {u}")
    print(sep)


def save_results(
    pdf_path: Path,
    records: list[dict[str, Any]],
    output_json: Path,
    elapsed: float,
) -> None:
    unique_sections = sorted({r["normalised"] for r in records})
    summary = {
        "source_pdf":         str(pdf_path),
        "total_labels":       len(records),
        "total_unique":       len(unique_sections),
        "needs_review_count": sum(1 for r in records if r["confidence"]["needs_review"]),
        "review_threshold":   REVIEW_FLAG_THRESHOLD,
        "processing_time_s":  round(elapsed, 3),
        "all_unique_sections": unique_sections,
        "records":            records,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    print(f"\n[done] Results saved -> {output_json}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Open-source structural section extractor for PDF drawings. "
            "Uses PyMuPDF (vector) and PaddleOCR (raster) — no API keys required."
        )
    )
    parser.add_argument(
        "pdf",
        help="Path to the input PDF drawing.",
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT_JSON,
        help=f"Path for the JSON output report (default: {DEFAULT_OUTPUT_JSON}).",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"DPI for raster-page rendering (default: {DEFAULT_DPI}).",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Suppress the console summary report.",
    )
    return parser.parse_args()


def main() -> None:
    args     = parse_args()
    pdf_path = Path(args.pdf)

    if not pdf_path.exists():
        print(f"[error] File not found: '{pdf_path}'", file=sys.stderr)
        sys.exit(1)

    if not _HAS_FITZ:
        print("[error] PyMuPDF (fitz) is required: pip install pymupdf", file=sys.stderr)
        sys.exit(1)

    t0      = time.perf_counter()
    records = run_pdf(pdf_path, dpi=args.dpi)
    elapsed = time.perf_counter() - t0

    output_json = Path(args.output)
    save_results(pdf_path, records, output_json, elapsed)

    if not args.no_report:
        print_report(pdf_path, records)

    print(f"[done] {len(records)} label(s) extracted in {elapsed:.2f}s.")


if __name__ == "__main__":
    main()
