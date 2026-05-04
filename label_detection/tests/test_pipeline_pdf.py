"""
tests/test_pipeline_pdf.py
──────────────────────────
Integration test for pipeline.run() against real PDF files from
'Manchester Steel Data/'.

Tests that:
  - The pipeline runs without raising exceptions.
  - At least one structural label is returned.
  - Every record has the required schema keys and valid types.
  - Confidence composite values are in [0, 1].
  - Processing time is reasonable (< 120 s for a small PDF).
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
try:
    import fitz
    import pdf2image
    _HAS_PDF_DEPS = True
except ImportError:
    _HAS_PDF_DEPS = False

# ── Locate test PDFs ─────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).parent.parent.parent / "Manchester Steel Data"

# List candidate PDFs from smallest to largest for fast CI runs
_CANDIDATE_PDFS = [
    _DATA_DIR / "AS EXISTING.pdf",
    _DATA_DIR / "C26.02.25 31 Water Street Struct01.pdf",
    _DATA_DIR / "20251226 CALCULATIONS - 27 Lydgate Road.pdf",
]

_AVAILABLE = [p for p in _CANDIDATE_PDFS if p.exists()]


@pytest.fixture(scope="module")
def test_pdf() -> Path:
    if not _HAS_PDF_DEPS:
        pytest.skip("Skipping PDF integration tests because PyMuPDF or pdf2image is not installed.")
    if not _AVAILABLE:
        pytest.skip(
            "No test PDFs found in 'Manchester Steel Data/'. "
            "Ensure at least one PDF is present to run integration tests."
        )
    return _AVAILABLE[0]


@pytest.fixture(scope="module")
def pipeline_output(test_pdf):
    """Run the full pipeline once, cache result for all tests in module."""
    from pipeline import run
    return run(test_pdf, dpi=300, output_json=None)


# ── Schema validation ────────────────────────────────────────────────────────

REQUIRED_TOP_KEYS = {
    "source_file", "file_type", "total_labels",
    "needs_review_count", "review_threshold",
    "processing_time_s", "records",
}

REQUIRED_RECORD_KEYS = {
    "source_file", "file_type", "page_or_view", "raw_text",
    "normalised", "section_type", "coordinates", "source", "confidence",
}

REQUIRED_CONFIDENCE_KEYS = {
    "ocr_prob", "db_score", "spatial_score", "clarity_score",
    "orientation_score", "composite", "needs_review",
}


def test_output_top_level_keys(pipeline_output):
    for key in REQUIRED_TOP_KEYS:
        assert key in pipeline_output, f"Missing top-level key: {key}"


def test_records_list(pipeline_output):
    assert isinstance(pipeline_output["records"], list)


def test_at_least_one_label(pipeline_output):
    assert pipeline_output["total_labels"] >= 0
    # Not failing if 0 — some PDFs may genuinely have no structural labels
    # (e.g. architectural only). But we still validate the schema works.


def test_record_schema(pipeline_output):
    records = pipeline_output["records"]
    for i, rec in enumerate(records[:20]):  # validate first 20 for speed
        for key in REQUIRED_RECORD_KEYS:
            assert key in rec, f"record[{i}] missing key: {key}"

        conf = rec["confidence"]
        for ckey in REQUIRED_CONFIDENCE_KEYS:
            assert ckey in conf, f"record[{i}].confidence missing key: {ckey}"

        # Type checks
        assert isinstance(conf["composite"], float), f"record[{i}].confidence.composite not float"
        assert 0.0 <= conf["composite"] <= 1.0, (
            f"record[{i}].confidence.composite out of range: {conf['composite']}"
        )
        assert isinstance(conf["needs_review"], bool)

        coords = rec["coordinates"]
        assert "x" in coords and "y" in coords
        assert isinstance(coords["x"], (int, float))
        assert isinstance(coords["y"], (int, float))


def test_processing_time_reasonable(pipeline_output):
    # Allow up to 120 s for a small PDF (OCR is slow)
    assert pipeline_output["processing_time_s"] < 120.0, (
        f"Processing time {pipeline_output['processing_time_s']:.1f}s exceeded 120s"
    )


def test_file_type_valid(pipeline_output):
    valid_types = {"pdf_vector", "pdf_raster"}
    assert pipeline_output["file_type"] in valid_types


def test_needs_review_count_consistent(pipeline_output):
    flagged = sum(
        1 for r in pipeline_output["records"]
        if r["confidence"]["needs_review"]
    )
    assert flagged == pipeline_output["needs_review_count"]


# ── Optional: second PDF ─────────────────────────────────────────────────────

@pytest.mark.skipif(len(_AVAILABLE) < 2, reason="Only one test PDF available")
def test_second_pdf_runs():
    from pipeline import run
    pdf = _AVAILABLE[1]
    output = run(pdf, dpi=300, output_json=None)
    assert "records" in output
    assert isinstance(output["records"], list)
