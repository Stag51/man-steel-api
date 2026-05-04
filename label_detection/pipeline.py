"""
pipeline.py
───────────
Main orchestrator for the dual-path structural extraction pipeline.
Fully open-source — no API keys or cloud services required.

Uses:
  • PyMuPDF    — native text extraction from vector PDFs
  • PaddleOCR  — rotation-aware OCR for raster/scanned PDFs
  • Revit API / CSV/JSON import — for .rvt files
  • grammar_parser + steel_section_db — validation and DB lookup
  • confidence_scorer — composite 0-1 scoring

Usage (CLI)
-----------
  python pipeline.py drawing.pdf --output results.json --dpi 350
  python pipeline.py model.rvt   --output results.json
  python pipeline.py schedule.csv --output results.json   # Revit CSV export

Public API
----------
run(input_path, dpi, output_json) -> dict
    Execute the full pipeline and return the output dict.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from file_detector import FileType, detect as detect_type, describe as describe_type
from grammar_parser import ParsedSection
from confidence_scorer import (
    ConfidenceBreakdown,
    from_pdf_label,
    from_revit_element,
    REVIEW_THRESHOLD,
)

# ══════════════════════════════════════════════════════════════════════════════
# Output schema builder
# ══════════════════════════════════════════════════════════════════════════════

def _pdf_label_to_record(label: Any, file_type_str: str, page_or_view: int) -> dict[str, Any]:
    """
    Convert an ExtractedLabel (from pdf_vector_extractor or pdf_raster_extractor)
    into the canonical output JSON record.
    """
    ps: ParsedSection | None = label.parsed

    section_type = ps.section_type if ps else "UNKNOWN"
    depth        = ps.depth        if ps else None
    width        = ps.width        if ps else None
    mass_or_t    = ps.mass_or_t    if ps else None
    db_score     = ps.db_score     if ps else 0.0
    db_corrected = ps.db_corrected if ps else None

    cx, cy = label.centre

    conf = from_pdf_label(
        ocr_prob     = label.ocr_prob,
        db_score     = db_score,
        clarity      = label.clarity,
        section_type = section_type,
        angle_deg    = label.angle_deg,
        centre       = (cx, cy),
        lines        = None,   # structural line geometry not passed at this stage
        max_pt       = 50.0,
    )

    return {
        "source_file":    None,   # filled by caller
        "file_type":      file_type_str,
        "page_or_view":   page_or_view,
        "raw_text":       label.text,
        "normalised":     ps.normalised if ps else label.text.upper(),
        "section_type":   section_type,
        "depth_mm":       depth,
        "width_mm":       width,
        "mass_kg_m":      mass_or_t,
        "db_corrected":   db_corrected,
        "coordinates": {
            "x":    round(cx, 3),
            "y":    round(cy, 3),
            "unit": "pt",
        },
        "angle_deg":      round(label.angle_deg, 2),
        "source":         label.source,
        "is_provided":    ps.is_provided if ps else True,
        "confidence":     conf.as_dict(),
    }


def _revit_element_to_record(elem: Any, file_type_str: str) -> dict[str, Any]:
    """
    Convert a RevitElement into the canonical output JSON record.
    """
    parsed_list = elem.parsed or []

    if parsed_list:
        ps: ParsedSection = parsed_list[0]
        section_type = ps.section_type
        depth        = ps.depth
        width        = ps.width
        mass_or_t    = ps.mass_or_t
        db_score     = ps.db_score
        db_corrected = ps.db_corrected
    else:
        section_type = "UNKNOWN"
        depth = width = mass_or_t = db_score = None
        db_corrected = None

    conf = from_revit_element(
        db_score     = db_score or 0.0,
        orientation  = elem.orientation,
        section_type = section_type,
    )

    return {
        "source_file":    None,
        "file_type":      file_type_str,
        "page_or_view":   f"element_{elem.element_id}",
        "raw_text":       elem.type_name,
        "normalised":     parsed_list[0].normalised if parsed_list else elem.type_name.upper(),
        "section_type":   section_type,
        "depth_mm":       depth,
        "width_mm":       width,
        "mass_kg_m":      mass_or_t,
        "db_corrected":   db_corrected,
        "coordinates": {
            "x":    round(elem.location.get("x", 0.0), 3),
            "y":    round(elem.location.get("y", 0.0), 3),
            "z":    round(elem.location.get("z", 0.0), 3),
            "unit": "mm",
        },
        "angle_deg":      None,   # not applicable for RVT (orientation captured separately)
        "orientation":    elem.orientation,
        "element_id":     elem.element_id,
        "family":         elem.family_name,
        "source":         elem.source,
        "confidence":     conf.as_dict(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Main pipeline runner
# ══════════════════════════════════════════════════════════════════════════════

def run(
    input_path: Path | str,
    dpi: int = 400,
    output_json: Path | str | None = None,
) -> dict[str, Any]:
    """
    Execute the dual-path extraction pipeline on a single file.
    Fully open-source — no API keys required.

    Parameters
    ----------
    input_path  : path to .pdf or .rvt (or .csv/.json Revit export)
    dpi         : raster DPI for rasterised PDF pages (default 350)
    output_json : optional path to write the JSON report; if None, no file
                  is written

    Returns
    -------
    dict with keys:
        source_file, file_type, total_labels, needs_review_count, records
    """
    input_path = Path(input_path)
    t0         = time.perf_counter()

    # ── Step 1: Detect file type ────────────────────────────────────────────
    file_type = detect_type(input_path)
    print(f"[pipeline] Input : {input_path.name}")
    print(f"[pipeline] Type  : {describe_type(file_type)}")

    if file_type == FileType.UNKNOWN:
        print(
            f"[pipeline] ERROR: unsupported file type '{input_path.suffix}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    file_type_str = file_type.name.lower()   # "pdf_vector" | "pdf_raster" | "rvt"
    records: list[dict] = []

    # ── Step 2: Route to extractor ──────────────────────────────────────────
    if file_type in (FileType.PDF_VECTOR, FileType.PDF_RASTER):
        if file_type == FileType.PDF_VECTOR:
            from pdf_vector_extractor import extract as pdf_extract, ExtractedLabel
            labels = pdf_extract(input_path, raster_dpi=dpi, raster_fallback=True)
        else:
            from pdf_raster_extractor import extract as pdf_extract, ExtractedLabel  # type: ignore[assignment]
            labels = pdf_extract(input_path, dpi=dpi)

        for label in labels:
            rec = _pdf_label_to_record(label, file_type_str, label.page)
            rec["source_file"] = str(input_path)
            records.append(rec)

    elif file_type == FileType.RVT:
        from rvt_extractor import extract as rvt_extract

        # For .rvt passing direct path — native mode only if inside Revit
        elements = rvt_extract(input_path)

        for elem in elements:
            rec = _revit_element_to_record(elem, file_type_str)
            rec["source_file"] = str(input_path)
            records.append(rec)

    # ── Step 3: Assemble output ───────────────────────────────────────────────
    needs_review = [r for r in records if r["confidence"]["needs_review"]]

    elapsed = time.perf_counter() - t0
    output: dict[str, Any] = {
        "source_file":         str(input_path),
        "file_type":           file_type_str,
        "total_labels":        len(records),
        "needs_review_count":  len(needs_review),
        "review_threshold":    REVIEW_THRESHOLD,
        "processing_time_s":   round(elapsed, 3),
        "records":             records,
    }

    # ── Step 4: Persist JSON ─────────────────────────────────────────────────
    if output_json is not None:
        out_path = Path(output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(output, fh, indent=2, ensure_ascii=False)
        print(f"\n[pipeline] Results saved -> {out_path}")

    print(
        f"[pipeline] Done in {elapsed:.2f}s — "
        f"{len(records)} label(s), {len(needs_review)} flagged for review."
    )
    return output


# Backwards-compatible alias (no gemini_pass kwarg silently accepted)
def run_compat(input_path, dpi=400, output_json=None, **_ignored):
    return run(input_path, dpi=dpi, output_json=output_json)


# ══════════════════════════════════════════════════════════════════════════════
# Console report
# ══════════════════════════════════════════════════════════════════════════════

def print_report(output: dict[str, Any]) -> None:
    sep = "=" * 72
    print(f"\n{'STRUCTURAL EXTRACTION REPORT':^72}")
    print(sep)
    print(f"  Source      : {output['source_file']}")
    print(f"  File type   : {output['file_type']}")
    print(f"  Total labels: {output['total_labels']}")
    print(f"  Needs review: {output['needs_review_count']}")
    print(f"  Threshold   : {output['review_threshold']}")
    print(sep)

    for rec in output["records"]:
        star = " ⚠" if rec["confidence"]["needs_review"] else ""
        print(
            f"  [{rec.get('page_or_view', '?'):>6}]  "
            f"{rec['normalised']:<30}  "
            f"type={rec['section_type']:<5}  "
            f"conf={rec['confidence']['composite']:.2f}{star}"
        )

    print(sep)

    flagged = [r for r in output["records"] if r["confidence"]["needs_review"]]
    unsupported = [r for r in output["records"] if not r.get("is_provided", True)]

    if flagged:
        print(f"\n  ⚠  {len(flagged)} label(s) flagged for human review:")
        for r in flagged:
            print(
                f"     [{r.get('page_or_view', '?'):>6}]  "
                f"{r['raw_text']}  →  composite={r['confidence']['composite']:.2f}"
            )

    if unsupported:
        print(f"\n  ✖  {len(unsupported)} label(s) use section types WE DO NOT PROVIDE:")
        for r in unsupported:
            print(
                f"     [{r.get('page_or_view', '?'):>6}]  "
                f"{r['raw_text']}  →  {r['section_type']} (NOT PROVIDED)"
            )
    print(sep)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dual-path structural extraction pipeline. "
            "Supports vector PDFs, raster PDFs, and Revit (.rvt / .csv / .json) files."
        )
    )
    parser.add_argument(
        "input",
        help="Path to the input file (.pdf, .rvt, .csv, .json).",
    )
    parser.add_argument(
        "--output", "-o",
        default="extraction_results.json",
        help="Path for the JSON output report (default: extraction_results.json).",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=400,
        help="DPI for rasterised PDF pages (default: 400).",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        default=False,
        help="Suppress the console summary.",
    )
    return parser.parse_args()


def main() -> None:
    args   = _parse_args()
    output = run(
        input_path  = Path(args.input),
        dpi         = args.dpi,
        output_json = Path(args.output),
    )
    if not args.no_report:
        print_report(output)


if __name__ == "__main__":
    main()
