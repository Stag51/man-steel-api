import os
import io
import json
import re
from typing import Generator, Optional
import fitz  # PyMuPDF

from config import Config
from core.matching import match_section
from core.clustering import ClusteringService
from core.boundary_detector import get_effective_frames, point_in_drawing
from core.feedback_store import lookup_correction
from core.weight_calculator import get_calculator


class LabelEngine:
    def __init__(
        self,
        paper_size=Config.DEFAULT_PAPER_SIZE,
        scale_ratio=Config.DEFAULT_SCALE_RATIO,
        label_size=Config.DEFAULT_LABEL_SIZE,
    ):
        self.paper_size = paper_size
        self.scale_ratio = scale_ratio
        self.label_size = label_size
        self.PT_TO_MM = 25.4 / 72

        self.db = {}
        if os.path.exists(Config.DB_PATH):
            with open(Config.DB_PATH, "r") as f:
                self.db = json.load(f)

        self.id_pattern = re.compile(
            r"\b(SE\d+|SG\d+|S\d+|B\d+|C\d+|F\d+|FF\d+|GFR\d+|PST\d+|L\d+)\b"
        )

    def pt_to_real_mm(self, pt: float) -> float:
        return pt * self.PT_TO_MM * self.scale_ratio

    # ──────────────────────────────────────────────────────────────────────────
    # Streaming core — yields events consumed by SSE endpoint or auto_label
    # ──────────────────────────────────────────────────────────────────────────

    def stream_labels(self, input_pdf_path: str, mode: str = "geometric") -> Generator[dict, None, None]:
        """
        Generator that yields structured events as labels are discovered.

        Event types:
          {"type": "start",    "total_pages": N}
          {"type": "boundary", "page": N, "frames": [...]}
          {"type": "label",    "page": N, "id": str, "label": str,
                               "x": float, "y": float, "color": str,
                               "source": "text"|"geometric"|"feedback",
                               "confidence": float}
          {"type": "progress", "page": N, "percent": float}
          {"type": "complete", "total_labels": N}
          {"type": "error",    "message": str}
        """
        try:
            doc = fitz.open(input_pdf_path)
            total_pages = len(doc)
            yield {"type": "start", "total_pages": total_pages}

            total_labels = 0

            for page_num in range(total_pages):
                page = doc[page_num]
                rect = page.rect
                vw, vh = rect.width, rect.height

                # ── Detect drawing frames for this page ───────────────────────
                frames = get_effective_frames(page)
                yield {
                    "type": "boundary",
                    "page": page_num,
                    "frames": [f.as_dict() for f in frames],
                }

                cluster_service = ClusteringService(radius=25)
                label_counter = 0

                # ── Phase 1: ID tag detection (text) ──────────────────────────
                words = page.get_text("words")
                for w in words:
                    text = w[4]
                    match = self.id_pattern.search(text)
                    if not match:
                        continue
                    mid = match.group(0)
                    if mid not in self.db:
                        continue
                    cx, cy = float((w[0] + w[2]) / 2), float((w[1] + w[3]) / 2)
                    # ── Boundary gate ─────────────────────────────────────────
                    if not point_in_drawing(cx, cy, frames):
                        continue
                    hub = cluster_service.find_or_create_hub(cx, cy)
                    hub.id = mid
                    hub.id_label = self.db[mid]

                # ── Phase 2: Geometry detection (vector paths) ────────────────
                if mode == "geometric":
                    paths = page.get_drawings()
                    for p in paths:
                        b = p["rect"]
                        w_pt = b[2] - b[0]
                        h_pt = b[3] - b[1]
                        if w_pt <= 1.5 or h_pt <= 1.5:
                            continue

                        w_mm = self.pt_to_real_mm(w_pt)
                        h_mm = self.pt_to_real_mm(h_pt)

                        is_filled = p.get("fill") is not None
                        shape_type = (
                            "circle" if len(p.get("items", [])) > 4 else "rect"
                        )

                        cx, cy = float((b[0] + b[2]) / 2), float((b[1] + b[3]) / 2)

                        # ── Boundary gate ──────────────────────────────────────
                        if not point_in_drawing(cx, cy, frames):
                            continue

                        # Density guard: skip if >5 shapes in 40 pt radius
                        if len(cluster_service.get_nearby(cx, cy, 40)) > 5:
                            continue

                        max_segments = 500 if is_filled else 50
                        if len(p.get("items", [])) >= max_segments:
                            continue

                        # ── Feedback & Spatial Exclusion ──────────────────────────
                        label = lookup_correction(shape_type, w_mm, h_mm, page=page_num, x=cx, y=cy)
                        if label == "__IGNORE__":
                            continue
                            
                        source = "feedback"
                        if label is None:
                            label = match_section(w_mm, h_mm, shape_type)
                            source = "geometric"

                        if label:
                            hub = cluster_service.find_or_create_hub(cx, cy)
                            if label not in hub.candidates:
                                hub.candidates.append(label)
                                if not hasattr(hub, "candidate_sources"):
                                    hub.candidate_sources = []
                                hub.candidate_sources.append(source)
                                # Store dimensions for weightage
                                hub.w_mm = w_mm
                                hub.h_mm = h_mm
                                hub.length_mm = max(w_mm, h_mm)
                                hub.shape_type = shape_type

                # ── Phase 3: Emit label events ────────────────────────────────
                for hub in cluster_service.hubs:
                    hcx, hcy = hub.centroid

                    if hub.id and hub.id_label:
                        color = "red"
                        display_text = f"{hub.id}: {hub.id_label}"
                        source = "text"
                        confidence = 0.95
                    elif hub.candidates:
                        src_list = getattr(hub, "candidate_sources", ["geometric"])
                        source = src_list[0] if src_list else "geometric"
                        color = "green" if source == "feedback" else "blue"
                        display_text = hub.candidates[0]
                        confidence = 0.90 if source == "feedback" else 0.70
                    else:
                        continue

                    label_id = f"p{page_num}_l{label_counter}"
                    event = {
                        "type": "label",
                        "page": page_num,
                        "id": label_id,
                        "label": display_text,
                        "x": round(hcx, 2),
                        "y": round(hcy, 2),
                        "color": color,
                        "source": source,
                        "confidence": confidence,
                        "w_mm": round(getattr(hub, "w_mm", 0) or 0, 1),
                        "h_mm": round(getattr(hub, "h_mm", 0) or 0, 1),
                        "length_mm": round(getattr(hub, "length_mm", 0) or 0, 1),
                        "shape_type": getattr(hub, "shape_type", "rect"),
                    }
                    
                    # Add Weightage
                    calc = get_calculator()
                    u_weight = calc.get_unit_weight(display_text)
                    event["unit_weight"] = u_weight
                    event["weight_kg"] = round(u_weight * (event["length_mm"] / 1000.0), 2)
                    
                    yield event
                    
                    label_counter += 1
                    total_labels += 1
                    import time
                    time.sleep(0.6) # Very deliberate delay for one-by-one review UX

                yield {
                    "type": "progress",
                    "page": page_num,
                    "percent": round((page_num + 1) / total_pages * 100, 1),
                }

            doc.close()
            yield {"type": "complete", "total_labels": total_labels}

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield {"type": "error", "message": str(e)}

    # ──────────────────────────────────────────────────────────────────────────
    # auto_label — single-pass annotator (boundary-filtered + feedback-aware)
    # ──────────────────────────────────────────────────────────────────────────

    def auto_label(self, input_pdf_path: str, output_pdf_path: str, mode: str = "geometric") -> str:
        """
        Single-pass annotator: generates and draws labels in one pass over the doc.
        Boundary detection and feedback overrides are both active.
        Also aliased as auto_label_fast for backward compatibility.
        """
        try:
            doc = fitz.open(input_pdf_path)

            for page_num in range(len(doc)):
                page = doc[page_num]
                frames = get_effective_frames(page)
                cluster_service = ClusteringService(radius=25)

                # Phase 1: ID tags
                for w in page.get_text("words"):
                    text = w[4]
                    match = self.id_pattern.search(text)
                    if not match:
                        continue
                    mid = match.group(0)
                    if mid not in self.db:
                        continue
                    cx, cy = float((w[0] + w[2]) / 2), float((w[1] + w[3]) / 2)
                    if not point_in_drawing(cx, cy, frames):
                        continue
                    hub = cluster_service.find_or_create_hub(cx, cy)
                    hub.id = mid
                    hub.id_label = self.db[mid]

                # Phase 2: Geometry
                if mode == "geometric":
                    for p in page.get_drawings():
                        b = p["rect"]
                        w_pt, h_pt = b[2] - b[0], b[3] - b[1]
                        if w_pt <= 1.5 or h_pt <= 1.5:
                            continue
                        w_mm = self.pt_to_real_mm(w_pt)
                        h_mm = self.pt_to_real_mm(h_pt)
                        is_filled = p.get("fill") is not None
                        shape_type = "circle" if len(p.get("items", [])) > 4 else "rect"
                        cx, cy = float((b[0] + b[2]) / 2), float((b[1] + b[3]) / 2)

                        if not point_in_drawing(cx, cy, frames):
                            continue
                        if len(cluster_service.get_nearby(cx, cy, 40)) > 5:
                            continue
                        max_seg = 500 if is_filled else 50
                        if len(p.get("items", [])) >= max_seg:
                            continue

                        label = lookup_correction(shape_type, w_mm, h_mm, page=page_num, x=cx, y=cy)
                        if label == "__IGNORE__":
                            continue
                            
                        source = "feedback" if label else "geometric"
                        if label is None:
                            label = match_section(w_mm, h_mm, shape_type)
                        if label:
                            hub = cluster_service.find_or_create_hub(cx, cy)
                            if label not in hub.candidates:
                                hub.candidates.append(label)
                                if not hasattr(hub, "candidate_sources"):
                                    hub.candidate_sources = []
                                hub.candidate_sources.append(source)

                # Phase 3: Draw labels
                labels_added = 0
                for hub in cluster_service.hubs:
                    hcx, hcy = hub.centroid
                    if hub.id and hub.id_label:
                        color = (0.8, 0, 0)
                        display_text = f"{hub.id}: {hub.id_label}"
                    elif hub.candidates:
                        src = (getattr(hub, "candidate_sources", ["geometric"]) or ["geometric"])[0]
                        color = (0, 0.5, 0) if src == "feedback" else (0, 0, 0.6)
                        display_text = hub.candidates[0]
                    else:
                        continue

                    page.draw_circle((float(hcx), float(hcy)), 1.2, color=(0, 0.4, 0.8), fill=(0, 0.4, 0.8))
                    page.insert_text(
                        (float(hcx - 20), float(hcy + 12)),
                        display_text,
                        fontsize=self.label_size,
                        color=color,
                        fontname="helv",
                    )
                    labels_added += 1

                print(f"Page {page_num + 1}: labeled {labels_added} structural hubs (boundary-filtered).")

            doc.save(output_pdf_path)
            doc.close()
            return output_pdf_path

        except Exception as e:
            import traceback
            traceback.print_exc()
            raise e

    # Backward-compatibility alias
    def auto_label_fast(self, input_pdf_path, output_pdf_path, mode="geometric"):
        return self.auto_label(input_pdf_path, output_pdf_path, mode=mode)

    def apply_labels_manual(self, input_pdf_path, output_pdf_path, members):
        return self.auto_label(input_pdf_path, output_pdf_path)


if __name__ == "__main__":
    print("LabelEngine with boundary detection + feedback ready.")
