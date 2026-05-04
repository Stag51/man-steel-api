"""
feedback_store.py
─────────────────
Stores user label corrections and applies them on future labeling runs.

Correction key  = (shape_type, w_bucket_mm, h_bucket_mm)
                  where buckets are rounded to the nearest 5 mm.

On future runs the engine checks this store BEFORE the section table,
so a human correction always wins over the geometric heuristic.
"""
import json
import time
from pathlib import Path
from typing import Optional

_STORE_PATH = Path(__file__).parent.parent / "data" / "feedback.json"


# ── Internal helpers ─────────────────────────────────────────────────────────

def _load() -> dict:
    if _STORE_PATH.exists():
        try:
            return json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"corrections": {}, "history": []}


def _save(data: dict) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _bucket(value_mm: float, step: int = 5) -> int:
    """Round to nearest 5 mm bucket."""
    return round(value_mm / step) * step


def _key(shape_type: str, w_mm: float, h_mm: float) -> str:
    """Canonical string key for a shape dimension pair."""
    lo, hi = sorted([_bucket(w_mm), _bucket(h_mm)])
    return f"{shape_type}|{lo}|{hi}"


# ── Public API ────────────────────────────────────────────────────────────────

def record_correction(
    original_label: str,
    corrected_label: str,
    shape_type: str,
    w_mm: float,
    h_mm: float,
    source: str = "auto_label",
    page: int = 0,
    raw_text: str = "",
) -> dict:
    """
    Persist a user correction.

    Parameters
    ----------
    original_label  : what the system produced
    corrected_label : what the user says it should be
    shape_type      : 'rect' | 'circle' | 'text'
    w_mm / h_mm     : real-world dimensions from the drawing
    source          : 'auto_label' | 'detection'
    """
    data = _load()
    k = _key(shape_type, w_mm, h_mm)

    # Update or create correction entry
    entry = data["corrections"].get(k, {
        "shape_type": shape_type,
        "w_bucket": _bucket(w_mm),
        "h_bucket": _bucket(h_mm),
        "corrected_label": corrected_label,
        "original_label": original_label,
        "count": 0,
    })
    entry["corrected_label"] = corrected_label  # latest wins
    entry["count"] = entry.get("count", 0) + 1
    data["corrections"][k] = entry

    # Append to history log
    data["history"].append({
        "ts": round(time.time()),
        "source": source,
        "page": page,
        "raw_text": raw_text,
        "w_mm": round(w_mm, 1),
        "h_mm": round(h_mm, 1),
        "shape_type": shape_type,
        "original": original_label,
        "corrected": corrected_label,
    })

    _save(data)
    return entry


def lookup_correction(shape_type: str, w_mm: float, h_mm: float) -> Optional[str]:
    """
    Return the human-corrected label for this shape, or None if no correction exists.
    Called by the label engine before falling back to the section table.
    """
    data = _load()
    k = _key(shape_type, w_mm, h_mm)
    entry = data["corrections"].get(k)
    if entry:
        return entry["corrected_label"]
    return None


def get_all_corrections() -> list:
    """Return all stored corrections for the UI stats panel."""
    data = _load()
    return list(data["corrections"].values())


def get_history(limit: int = 50) -> list:
    """Return the most recent correction history entries."""
    data = _load()
    return data["history"][-limit:]


def correction_count() -> int:
    data = _load()
    return len(data["corrections"])
