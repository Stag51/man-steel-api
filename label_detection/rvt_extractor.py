"""
rvt_extractor.py
────────────────
Extract structural framing and column elements from Autodesk Revit models.

Two runtime modes (selected automatically):
  1. NATIVE  — running inside Revit via pyRevit / IronPython.
               Uses the full Revit API (Autodesk.Revit.DB).
  2. IMPORT  — standalone Python (no Revit available).
               Reads an exported CSV or JSON element schedule produced by
               Revit's "Export → Schedule/Quantities" or a custom Dynamo
               script (see docs/revit_export_guide.md).

Public API
----------
detect_mode()  -> str          ("native" | "import")
extract(source) -> list[RevitElement]
    source: Path to .rvt (native mode) or .csv/.json (import mode),
            OR a live Revit Document object (native mode).
"""

from __future__ import annotations

import csv
import json
import math
import sys
import shutil
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grammar_parser import parse as grammar_parse

import subprocess
import tempfile

# ── Attempt Revit API import ──────────────────────────────────────────────────
try:
    from Autodesk.Revit.DB import (           # type: ignore[import]
        FilteredElementCollector,
        BuiltInCategory,
        LocationCurve,
        LocationPoint,
        UnitTypeId,
        UnitUtils,
    )
    _HAS_REVIT_API = True
except ImportError:
    _HAS_REVIT_API = False


# ══════════════════════════════════════════════════════════════════════════════
# Console tool discovery
# ══════════════════════════════════════════════════════════════════════════════

def find_pyrevit() -> Path | None:
    """
    Attempt to locate the pyrevit.exe CLI tool.
    Checks PATH and common installation directories.
    """
    # 1. Check PATH
    pyrevit_path = shutil.which("pyrevit")
    if pyrevit_path:
        return Path(pyrevit_path)

    # 2. Check user-provided custom locations
    custom_paths = [
        Path(r"C:\Program Files\pyRevit-Master\bin\pyrevit.exe"),
        Path(os.environ.get("APPDATA", "")) / "pyRevit-Master" / "bin" / "pyrevit.exe"
    ]
    for p in custom_paths:
        if p.exists():
            return p
            
    return None

# ══════════════════════════════════════════════════════════════════════════════
# Headless Bridge Logic
# ══════════════════════════════════════════════════════════════════════════════

def _run_headless_bridge(rvt_path: Path) -> list[RevitElement]:
    """
    Orchestrate a headless Revit session via pyRevit CLI.
    """
    pyrevit_exe = find_pyrevit()
    if not pyrevit_exe:
        raise RuntimeError(
            "Autodesk Revit is not detected. This system requires a local "
            "Revit installation and pyRevit to process .rvt files directly."
        )

    # Path to the IronPython script (same directory as this file)
    script_path = Path(__file__).parent / "rvt_extractor_headless.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Headless script not found: {script_path}")

    # Use a temp file for data handoff
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        print(f"[rvt] Launching headless Revit bridge for '{rvt_path.name}' ...")
        # Command: pyrevit run <script> <model_path> <output_json>
        # Explicitly targeting Revit 2026 per user configuration
        cmd = [
            str(pyrevit_exe),
            "run",
            "--revit=\"2026\"",
            str(script_path),
            str(rvt_path.absolute()),
            str(tmp_path.absolute())
        ]
        
        # This may take 30-120 seconds to boot Revit
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        
        if result.returncode != 0:
            print(f"[rvt] Bridge error:\n{result.stderr}", file=sys.stderr)
            raise RuntimeError(f"Revit headless bridge failed (return code {result.returncode})")

        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise RuntimeError("Headless bridge finished but produced no data.")

        # Load the extracted data
        extracted_data = _load_json(tmp_path)
        print(f"[rvt] Successfully extracted {len(extracted_data)} elements via Revit API.")
        return extracted_data

    finally:
        if tmp_path.exists():
            os.remove(tmp_path)


# ══════════════════════════════════════════════════════════════════════════════
# Result type
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# Result type
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RevitElement:
    """
    A structural element extracted from a Revit model.

    Attributes
    ----------
    element_id   : Revit ElementId integer
    category     : "Structural Framing" or "Structural Columns"
    type_name    : full type parameter string, e.g. "203x133x30 UB"
    family_name  : Revit family name (steel section family)
    location     : {"x": mm, "y": mm, "z": mm} — element midpoint
    orientation  : "horizontal" | "vertical" | "diagonal"
    source       : "revit_api" | "revit_import_csv" | "revit_import_json"
    parsed       : list of ParsedSection from grammar_parser (may be empty)
    """
    element_id:  int
    category:    str
    type_name:   str
    family_name: str
    location:    dict[str, float]
    orientation: str
    source:      str
    parsed:      list[Any] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# Mode detection
# ══════════════════════════════════════════════════════════════════════════════

def detect_mode() -> str:
    """Return "native" if running inside Revit, otherwise "import"."""
    return "native" if _HAS_REVIT_API else "import"


# ══════════════════════════════════════════════════════════════════════════════
# Native Revit API path
# ══════════════════════════════════════════════════════════════════════════════

def _feet_to_mm(feet: float) -> float:
    """Convert Revit's internal units (decimal feet) to millimetres."""
    return feet * 304.8


def _curve_midpoint_mm(location) -> dict[str, float]:
    """
    Extract the midpoint of a LocationCurve or LocationPoint in mm.
    """
    if isinstance(location, LocationCurve):
        c = location.Curve
        p = c.Evaluate(0.5, True)   # parameter 0.5 = midpoint
        return {"x": _feet_to_mm(p.X), "y": _feet_to_mm(p.Y), "z": _feet_to_mm(p.Z)}
    elif isinstance(location, LocationPoint):
        p = location.Point
        return {"x": _feet_to_mm(p.X), "y": _feet_to_mm(p.Y), "z": _feet_to_mm(p.Z)}
    else:
        return {"x": 0.0, "y": 0.0, "z": 0.0}


def _curve_orientation(location) -> str:
    """
    Classify a LocationCurve as horizontal / vertical / diagonal based on
    the direction vector of the underlying curve.
    """
    if not isinstance(location, LocationCurve):
        return "unknown"
    c = location.Curve
    try:
        # Start → end direction
        p0 = c.GetEndPoint(0)
        p1 = c.GetEndPoint(1)
        dx = abs(p1.X - p0.X)
        dy = abs(p1.Y - p0.Y)
        dz = abs(p1.Z - p0.Z)
        dominant = max(dx, dy, dz)
        if dominant == 0.0:
            return "point"
        if dominant == dz:
            return "vertical"
        if dx >= dy:
            return "horizontal"
        return "diagonal"
    except Exception:
        return "unknown"


def _collect_native(doc) -> list[RevitElement]:
    """Extract structural elements using the live Revit API document."""
    elements: list[RevitElement] = []

    categories = [
        (BuiltInCategory.OST_StructuralFraming, "Structural Framing"),
        (BuiltInCategory.OST_StructuralColumns,  "Structural Columns"),
    ]

    for bic, cat_name in categories:
        collector = (
            FilteredElementCollector(doc)
            .OfCategory(bic)
            .WhereElementIsNotElementType()
        )
        for elem in collector:
            try:
                sym         = elem.Symbol
                type_name   = sym.Name or ""
                family_name = sym.Family.Name or ""
                location    = elem.Location
                midpoint    = _curve_midpoint_mm(location)
                orientation = _curve_orientation(location)
                parsed      = grammar_parse(type_name)

                elements.append(RevitElement(
                    element_id  = elem.Id.IntegerValue,
                    category    = cat_name,
                    type_name   = type_name,
                    family_name = family_name,
                    location    = midpoint,
                    orientation = orientation,
                    source      = "revit_api",
                    parsed      = parsed,
                ))
            except Exception as exc:
                print(
                    f"[rvt] Skipping element {elem.Id}: {exc}",
                    file=sys.stderr,
                )

    return elements


# ══════════════════════════════════════════════════════════════════════════════
# Standalone CSV / JSON import path
# ══════════════════════════════════════════════════════════════════════════════

# Expected CSV column names (case-insensitive)
_CSV_FIELD_MAP = {
    "id":          ("element_id",  int),
    "category":    ("category",    str),
    "family":      ("family_name", str),
    "type":        ("type_name",   str),
    "type name":   ("type_name",   str),
    "x":           ("x",           float),
    "y":           ("y",           float),
    "z":           ("z",           float),
    "orientation": ("orientation", str),
}


def _load_csv(path: Path) -> list[RevitElement]:
    """
    Load elements from an exported Revit schedule CSV.

    Expected columns (flexible, case-insensitive):
        ID, Category, Family, Type, X, Y, Z, Orientation
    """
    elements: list[RevitElement] = []

    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row_no, row in enumerate(reader, start=2):
            # Normalise keys
            norm_row = {k.strip().lower(): v.strip() for k, v in row.items()}

            elem_id     = int(norm_row.get("id", 0) or 0)
            category    = norm_row.get("category", "Structural Framing")
            family_name = norm_row.get("family", "")
            type_name   = norm_row.get("type name") or norm_row.get("type", "")
            orientation = norm_row.get("orientation", "unknown")

            try:
                x = float(norm_row.get("x", 0) or 0)
                y = float(norm_row.get("y", 0) or 0)
                z = float(norm_row.get("z", 0) or 0)
            except ValueError:
                x = y = z = 0.0

            parsed = grammar_parse(type_name)

            elements.append(RevitElement(
                element_id  = elem_id,
                category    = category,
                type_name   = type_name,
                family_name = family_name,
                location    = {"x": x, "y": y, "z": z},
                orientation = orientation,
                source      = "revit_import_csv",
                parsed      = parsed,
            ))

    return elements


def _load_json(path: Path) -> list[RevitElement]:
    """
    Load elements from a JSON schedule export.

    Expected format: list of objects with keys matching CSV columns.
    """
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)

    if isinstance(raw, dict):
        # Wrap single document with "elements" key
        raw = raw.get("elements", [raw])

    elements: list[RevitElement] = []
    for obj in raw:
        norm = {k.strip().lower(): v for k, v in obj.items()}
        type_name   = str(norm.get("type_name") or norm.get("type", ""))
        family_name = str(norm.get("family_name") or norm.get("family", ""))
        location    = norm.get("location", {})
        if isinstance(location, dict):
            x = float(location.get("x", 0))
            y = float(location.get("y", 0))
            z = float(location.get("z", 0))
        else:
            x = float(norm.get("x", 0))
            y = float(norm.get("y", 0))
            z = float(norm.get("z", 0))

        parsed = grammar_parse(type_name)
        elements.append(RevitElement(
            element_id  = int(norm.get("element_id") or norm.get("id", 0)),
            category    = str(norm.get("category", "Structural Framing")),
            type_name   = type_name,
            family_name = family_name,
            location    = {"x": x, "y": y, "z": z},
            orientation = str(norm.get("orientation", "unknown")),
            source      = "revit_import_json",
            parsed      = parsed,
        ))

    return elements


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def extract(source: Any) -> list[RevitElement]:
    """
    Extract structural elements from a Revit model or exported schedule.

    Parameters
    ----------
    source : one of —
        - A live Revit ``Document`` object (native mode inside pyRevit).
        - A ``pathlib.Path`` to a ``.rvt`` file (native mode — opens doc).
        - A ``pathlib.Path`` to a ``.csv`` file (import mode).
        - A ``pathlib.Path`` to a ``.json`` file (import mode).

    Returns
    -------
    List of ``RevitElement`` objects with validated ``parsed`` sections.

    Raises
    ------
    ImportError
        If native mode is requested but Revit API is not available.
    FileNotFoundError
        If the import file path does not exist.
    ValueError
        If the file extension is not recognised.
    """
    # ── Native mode: live Document object ────────────────────────────────────
    if _HAS_REVIT_API and not isinstance(source, (str, Path)):
        print("[rvt] Native Revit API mode — extracting from Document …")
        elements = _collect_native(source)
        print(f"[rvt] Extracted {len(elements)} element(s).")
        return elements

    # ── File-based paths ─────────────────────────────────────────────────────
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"[rvt] File not found: '{path}'")

    suffix = path.suffix.lower()

    if suffix == ".rvt":
        if _HAS_REVIT_API:
            # Native mode: Open the Revit document (only works inside Revit host)
            from Autodesk.Revit.DB import Document  # type: ignore[import]
            doc = Document.Open(str(path))          # type: ignore[attr-defined]
            elements = _collect_native(doc)
            print(f"[rvt] Extracted {len(elements)} element(s) from '{path.name}'.")
            return elements
        else:
            # Standalone mode: Trigger headless bridge
            print(f"[rvt] Suffix .rvt detected in standalone mode — attempting headless bridge …")
            return _run_headless_bridge(path)

    if suffix == ".csv":
        print(f"[rvt] Import CSV mode — reading '{path.name}' …")
        elements = _load_csv(path)
        print(f"[rvt] Loaded {len(elements)} element(s).")
        return elements

    if suffix == ".json":
        print(f"[rvt] Import JSON mode — reading '{path.name}' …")
        elements = _load_json(path)
        print(f"[rvt] Loaded {len(elements)} element(s).")
        return elements

    raise ValueError(
        f"[rvt] Unrecognised file extension '{suffix}'. "
        "Supported: .rvt (native), .csv, .json (import)."
    )
