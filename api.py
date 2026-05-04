import os
import sys
import uuid
import json
import shutil
import asyncio
import logging
import base64
from pathlib import Path
from typing import Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── Path setup ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR / "labeling"))
sys.path.append(str(BASE_DIR / "label_detection"))

from config import Config as LabelingConfig
from label_engine import LabelEngine
from core.feedback_store import (
    record_correction,
    get_all_corrections,
    get_history,
    correction_count,
)
import pipeline as detection_pipeline

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Structural Engineering Unified API",
    version="2.0.0",
    description="Auto-labeling + label detection with real-time streaming & human feedback.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Directories ───────────────────────────────────────────────────────────────
DETECTION_UPLOAD_DIR = BASE_DIR / "detection_uploads"
DETECTION_OUTPUT_DIR = BASE_DIR / "detection_outputs"
STATIC_DIR = BASE_DIR / "static"
for d in [DETECTION_UPLOAD_DIR, DETECTION_OUTPUT_DIR, STATIC_DIR]:
    d.mkdir(exist_ok=True)

# Serve the frontend
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── In-memory job store (job_id → asyncio.Queue) ─────────────────────────────
_job_queues: dict[str, asyncio.Queue] = {}
_job_meta:   dict[str, dict]          = {}


# ══════════════════════════════════════════════════════════════════════════════
# UPLOAD — start a processing job
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/upload")
async def upload_drawing(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    paper_size: str  = Form(LabelingConfig.DEFAULT_PAPER_SIZE),
    scale_ratio: int = Form(LabelingConfig.DEFAULT_SCALE_RATIO),
    label_size:  int = Form(LabelingConfig.DEFAULT_LABEL_SIZE),
    mode:        str = Form("geometric"),
    pipeline_type: str = Form("auto_label"),   # "auto_label" | "detect"
    dpi:         int = Form(400),
):
    """
    Upload a drawing PDF.  Returns a job_id to:
      - GET /stream/{job_id}       → SSE stream of label events
      - GET /page-image/{job_id}/{page_num} → page PNG for the viewer
    """
    job_id = str(uuid.uuid4())
    file_id = str(uuid.uuid4())
    input_path = Path(LabelingConfig.UPLOAD_DIR) / f"{file_id}_{file.filename}"

    with open(input_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)

    queue: asyncio.Queue = asyncio.Queue()
    _job_queues[job_id] = queue
    _job_meta[job_id] = {
        "input_path": str(input_path),
        "filename": file.filename,
        "pipeline_type": pipeline_type,
        "paper_size": paper_size,
        "scale_ratio": scale_ratio,
        "label_size": label_size,
        "mode": mode,
        "dpi": dpi,
    }

    background_tasks.add_task(_run_job, job_id)
    return {"job_id": job_id, "filename": file.filename}


# ── Background worker ─────────────────────────────────────────────────────────

async def _run_job(job_id: str):
    """Run labeling/detection in a thread-pool and push events to the queue."""
    meta  = _job_meta[job_id]
    queue = _job_queues[job_id]
    loop  = asyncio.get_event_loop()

    def _work():
        ptype = meta["pipeline_type"]
        if ptype == "auto_label":
            engine = LabelEngine(
                paper_size=meta["paper_size"],
                scale_ratio=meta["scale_ratio"],
                label_size=meta["label_size"],
            )
            for event in engine.stream_labels(meta["input_path"], mode=meta["mode"]):
                asyncio.run_coroutine_threadsafe(queue.put(event), loop)
        else:
            # Detection pipeline — emit a single batch result
            out_path = str(DETECTION_OUTPUT_DIR / f"detection_{job_id}.json")
            results = detection_pipeline.run(
                input_path=meta["input_path"],
                dpi=meta["dpi"],
                output_json=out_path,
            )
            # Emit individual records as label events
            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "start", "total_pages": 1}), loop
            )
            for rec in results.get("records", []):
                event = {
                    "type": "label",
                    "page": rec.get("page_or_view", 0),
                    "id": str(uuid.uuid4()),
                    "label": rec.get("normalised", rec.get("raw_text", "")),
                    "raw_text": rec.get("raw_text", ""),
                    "x": rec.get("coordinates", {}).get("x", 0),
                    "y": rec.get("coordinates", {}).get("y", 0),
                    "color": "orange" if rec["confidence"].get("needs_review") else "blue",
                    "source": rec.get("source", "ocr"),
                    "confidence": rec["confidence"].get("composite", 0.5),
                    "needs_review": rec["confidence"].get("needs_review", False),
                    "section_type": rec.get("section_type", ""),
                    "depth_mm": rec.get("depth_mm"),
                    "width_mm": rec.get("width_mm"),
                }
                asyncio.run_coroutine_threadsafe(queue.put(event), loop)
            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "complete", "total_labels": len(results.get("records", []))}),
                loop,
            )

    try:
        await loop.run_in_executor(None, _work)
    except Exception as e:
        logger.exception("Job %s failed", job_id)
        await queue.put({"type": "error", "message": str(e)})
    finally:
        await queue.put(None)  # sentinel


# ══════════════════════════════════════════════════════════════════════════════
# SSE STREAM — real-time label events
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/stream/{job_id}")
async def stream_labels(job_id: str):
    """
    Server-Sent Events endpoint.  Connect once upload returns job_id.
    Events are newline-delimited JSON prefixed with 'data: '.
    """
    if job_id not in _job_queues:
        raise HTTPException(status_code=404, detail="Job not found")

    queue = _job_queues[job_id]

    async def generator():
        while True:
            event = await queue.get()
            if event is None:
                yield "data: {\"type\": \"done\"}\n\n"
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE IMAGE — serve PDF page as PNG for the viewer
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/page-image/{job_id}/{page_num}")
async def get_page_image(job_id: str, page_num: int, dpi: int = 150):
    """Rasterize a PDF page and return it as PNG (for the frontend viewer)."""
    if job_id not in _job_meta:
        raise HTTPException(status_code=404, detail="Job not found")
    import fitz
    import io

    pdf_path = _job_meta[job_id]["input_path"]
    doc = fitz.open(pdf_path)
    if page_num >= len(doc):
        raise HTTPException(status_code=404, detail="Page not found")

    page = doc[page_num]
    mat  = fitz.Matrix(dpi / 72, dpi / 72)
    pix  = page.get_pixmap(matrix=mat, alpha=False)
    png_bytes = pix.tobytes("png")
    doc.close()

    return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE DIMENSIONS — so the frontend can scale coordinates correctly
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/page-info/{job_id}/{page_num}")
async def get_page_info(job_id: str, page_num: int):
    if job_id not in _job_meta:
        raise HTTPException(status_code=404, detail="Job not found")
    import fitz
    pdf_path = _job_meta[job_id]["input_path"]
    doc  = fitz.open(pdf_path)
    page = doc[page_num]
    info = {"width_pt": page.rect.width, "height_pt": page.rect.height, "total_pages": len(doc)}
    doc.close()
    return info


# ══════════════════════════════════════════════════════════════════════════════
# FEEDBACK — submit a correction
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/feedback")
async def submit_feedback(payload: dict):
    """
    Submit a label correction.

    Body (JSON):
    {
      "original_label": "SHS 100x100x6.3",
      "corrected_label": "SHS 140x140x10",
      "shape_type": "rect",
      "w_mm": 100.0,
      "h_mm": 100.0,
      "source": "auto_label",
      "page": 0,
      "raw_text": ""
    }
    """
    required = {"original_label", "corrected_label", "shape_type"}
    missing  = required - payload.keys()
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing fields: {missing}")

    entry = record_correction(
        original_label=payload["original_label"],
        corrected_label=payload["corrected_label"],
        shape_type=payload.get("shape_type", "rect"),
        w_mm=float(payload.get("w_mm", 0)),
        h_mm=float(payload.get("h_mm", 0)),
        source=payload.get("source", "auto_label"),
        page=int(payload.get("page", 0)),
        raw_text=payload.get("raw_text", ""),
    )
    return {"status": "saved", "entry": entry, "total_corrections": correction_count()}


@app.get("/feedback/corrections")
async def list_corrections():
    return {"corrections": get_all_corrections(), "total": correction_count()}


@app.get("/feedback/history")
async def list_history(limit: int = 50):
    return {"history": get_history(limit=limit)}


# ══════════════════════════════════════════════════════════════════════════════
# LEGACY ENDPOINTS (backward-compatible)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/auto-label")
async def auto_label_drawing(
    file: UploadFile = File(...),
    paper_size: str = Form(LabelingConfig.DEFAULT_PAPER_SIZE),
    scale_ratio: int = Form(LabelingConfig.DEFAULT_SCALE_RATIO),
    label_size:  int = Form(LabelingConfig.DEFAULT_LABEL_SIZE),
    mode: str = Form("geometric"),
):
    """Legacy endpoint — returns annotated PDF as base64. Use /upload for streaming."""
    file_id    = str(uuid.uuid4())
    input_path  = os.path.join(LabelingConfig.UPLOAD_DIR, f"{file_id}_{file.filename}")
    output_path = os.path.join(LabelingConfig.OUTPUT_DIR, f"auto_labeled_{file_id}_{file.filename}")

    with open(input_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)

    warning = None
    try:
        import pdfplumber
        with pdfplumber.open(input_path) as pdf:
            text = pdf.pages[0].extract_text() or ""
            if "1 : 100" in text and scale_ratio == 50:
                warning = "Scale mismatch detected (1:100 indicated, 1:50 provided)."
            elif "1 : 50" in text and scale_ratio == 100:
                warning = "Scale mismatch detected (1:50 indicated, 1:100 provided)."

        engine = LabelEngine(paper_size=paper_size, scale_ratio=scale_ratio, label_size=label_size)
        engine.auto_label_fast(input_path, output_path, mode=mode)
    except Exception as e:
        logger.error("Auto-Labeling error: %s", e)
        raise HTTPException(status_code=500, detail=f"Auto-Labeling error: {e}")

    with open(output_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    return {
        "status": "success",
        "warning": warning,
        "filename": os.path.basename(output_path),
        "download_url": f"/download/labeling/{os.path.basename(output_path)}",
        "base64_data": encoded,
    }


@app.post("/detect")
async def detect_labels(file: UploadFile = File(...), dpi: int = Form(400)):
    file_id         = str(uuid.uuid4())
    input_path      = DETECTION_UPLOAD_DIR / f"{file_id}_{file.filename}"
    output_json_path = DETECTION_OUTPUT_DIR / f"detection_{file_id}.json"
    with open(input_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)
    try:
        results = detection_pipeline.run(str(input_path), dpi=dpi, output_json=str(output_json_path))
        return {"status": "success", "results": results}
    except Exception as e:
        logger.error("Detection error: %s", e)
        raise HTTPException(status_code=500, detail=f"Detection error: {e}")


@app.get("/download/labeling/{filename}")
async def download_labeled_file(filename: str):
    file_path = os.path.join(LabelingConfig.OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(file_path, media_type="application/pdf")


# ── Frontend entrypoint ───────────────────────────────────────────────────────
@app.get("/")
async def serve_ui():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Place index.html in the /static directory."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
