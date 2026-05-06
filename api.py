import os
import sys
import uuid
import json
import shutil
import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import fitz

# ── Setup ─────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR / "labeling"))
sys.path.append(str(BASE_DIR / "label_detection"))

from config import Config as LabelingConfig
from label_engine import LabelEngine
from core.feedback_store import record_correction, record_exclusion, get_all_corrections, correction_count
from core.weight_calculator import get_calculator
import pipeline as detection_pipeline

app = FastAPI(title="Structural Unified API", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DETECTION_UPLOAD_DIR = BASE_DIR / "detection_uploads"
STATIC_DIR = BASE_DIR / "static"
for d in [DETECTION_UPLOAD_DIR, STATIC_DIR]: d.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_job_queues: dict[str, asyncio.Queue] = {}
_job_meta:   dict[str, dict]          = {}
_cancelled_jobs: set[str]             = set()

# ── PILLAR 1: JOB MANAGEMENT ──────────────────────────────────────────────────

@app.post("/upload")
async def upload_drawing(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    paper_size: str  = Form(LabelingConfig.DEFAULT_PAPER_SIZE),
    scale_ratio: int = Form(LabelingConfig.DEFAULT_SCALE_RATIO),
    pipeline_type: str = Form("auto_label"), # "auto_label" | "detect"
    dpi:         int = Form(400),
):
    """
    Consolidated Upload: Returns Job ID + File Metadata + Page Info in one call.
    """
    job_id = str(uuid.uuid4())
    input_path = DETECTION_UPLOAD_DIR / f"{job_id}_{file.filename}"
    with open(input_path, "wb") as buf: shutil.copyfileobj(file.file, buf)

    # Pre-calculate page info to save frontend a request
    doc = fitz.open(str(input_path))
    pages_info = []
    for i in range(len(doc)):
        p = doc[i]
        pages_info.append({"page": i, "width": p.rect.width, "height": p.rect.height})
    doc.close()

    _job_queues[job_id] = asyncio.Queue()
    _job_meta[job_id] = {
        "input_path": str(input_path),
        "pipeline_type": pipeline_type,
        "paper_size": paper_size,
        "scale_ratio": scale_ratio,
        "dpi": dpi,
        "pages": pages_info
    }

    background_tasks.add_task(_run_job, job_id)
    return {"job_id": job_id, "total_pages": len(pages_info), "pages": pages_info}

@app.post("/job/{job_id}/stop")
async def stop_job(job_id: str):
    _cancelled_jobs.add(job_id)
    return {"status": "stopping"}

# ── PILLAR 2: STREAMING ───────────────────────────────────────────────────────

@app.get("/stream/{job_id}")
async def stream_labels(job_id: str):
    if job_id not in _job_queues: raise HTTPException(status_code=404)
    queue = _job_queues[job_id]
    async def generator():
        while True:
            ev = await queue.get()
            if ev is None: yield "data: {\"type\": \"done\"}\n\n"; break
            yield f"data: {json.dumps(ev)}\n\n"
    return StreamingResponse(generator(), media_type="text/event-stream")

# ── PILLAR 3: FEEDBACK (Merged) ───────────────────────────────────────────────

@app.post("/feedback")
async def submit_feedback(payload: dict):
    """
    Unified Feedback Endpoint.
    Types: 'correct' | 'exclude'
    """
    fb_type = payload.get("type", "correct")
    
    if fb_type == "exclude":
        regions = record_exclusion(page=payload["page"], x=payload["x"], y=payload["y"])
        return {"status": "excluded", "count": len(regions)}
    
    else: # Correction
        entry = record_correction(
            original_label=payload["original_label"],
            corrected_label=payload["corrected_label"],
            shape_type=payload.get("shape_type", "rect"),
            w_mm=float(payload.get("w_mm", 0)),
            h_mm=float(payload.get("h_mm", 0)),
            source=payload.get("source", "manual"),
            page=payload.get("page", 0)
        )
        return {"status": "saved", "total": correction_count()}

@app.get("/feedback/list")
async def list_corrections():
    return {"corrections": get_all_corrections()}

# ── PILLAR 4: CALCULATIONS ────────────────────────────────────────────────────

@app.post("/calculate-weightage")
async def calculate_weightage(payload: dict):
    """
    Returns unit weights and total weights for a list of labels.
    """
    labels = payload.get("labels", [])
    calc = get_calculator()
    return calc.calculate(labels)

# ── PILLAR 5: RESOURCES ───────────────────────────────────────────────────────

@app.get("/page-image/{job_id}/{page_num}")
async def get_page_image(job_id: str, page_num: int, dpi: int = 150):
    if job_id not in _job_meta: raise HTTPException(status_code=404)
    doc = fitz.open(_job_meta[job_id]["input_path"])
    page = doc[page_num]
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72))
    img_bytes = pix.tobytes("png")
    doc.close()
    import io
    return StreamingResponse(io.BytesIO(img_bytes), media_type="image/png")

@app.post("/download-labeled/{job_id}")
async def download_labeled_pdf(job_id: str, payload: dict):
    """
    Generates a labeled PDF using labels provided by the client.
    """
    try:
        if job_id not in _job_meta:
            logger.error(f"Job {job_id} not found in meta")
            raise HTTPException(status_code=404, detail="Job session expired or not found")
        
        labels = payload.get("labels", [])
        meta = _job_meta[job_id]
        input_path = meta["input_path"]
        
        if not os.path.exists(input_path):
            logger.error(f"Input file not found: {input_path}")
            raise HTTPException(status_code=404, detail="Original drawing file missing on server")

        output_filename = f"labeled_{Path(input_path).name}"
        output_path = DETECTION_UPLOAD_DIR / output_filename
        
        logger.info(f"Generating labeled PDF for job {job_id} with {len(labels)} labels")
        
        engine = LabelEngine(meta["paper_size"], meta["scale_ratio"])
        
        # Apply labels
        engine.apply_labels_manual(input_path, str(output_path), labels)
        
        if not output_path.exists():
            logger.error(f"Output file was not created at {output_path}")
            raise HTTPException(status_code=500, detail="Engine failed to create output file")
            
        return FileResponse(
            path=output_path,
            filename=output_filename,
            media_type="application/pdf"
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception(f"Detailed failure in download_labeled_pdf for job {job_id}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

# ── WORKER LOGIC ─────────────────────────────────────────────────────────────

async def _run_job(job_id: str):
    meta, queue = _job_meta[job_id], _job_queues[job_id]
    loop = asyncio.get_event_loop()
    
    def _work():
        try:
            calc = get_calculator()
            if meta["pipeline_type"] == "auto_label":
                engine = LabelEngine(meta["paper_size"], meta["scale_ratio"])
                for ev in engine.stream_labels(meta["input_path"]):
                    if job_id in _cancelled_jobs: break
                    asyncio.run_coroutine_threadsafe(queue.put(ev), loop)
            else:
                # OCR Detection
                results = detection_pipeline.run(meta["input_path"], dpi=meta["dpi"])
                # Initialize Engine for measurement fallback
                engine = LabelEngine(meta["paper_size"], meta["scale_ratio"])
                doc = fitz.open(meta["input_path"])
                page = doc[0]
                page_geo = page.get_drawings()
                page_rect = page.rect
                
                # Build boundary frames for OCR coordinate filtering
                from core.boundary_detector import get_effective_frames, point_in_drawing
                sys.path.insert(0, str(BASE_DIR / "labeling"))
                frames = get_effective_frames(page)
                doc.close()
                
                asyncio.run_coroutine_threadsafe(queue.put({"type":"start", "total_pages":1}), loop)
                import math
                label_count = 0
                for rec in results.get("records", []):
                    if job_id in _cancelled_jobs: break
                    lbl = rec.get("normalised", rec.get("raw_text", ""))
                    u_weight = calc.get_unit_weight(lbl)
                    # Raw PDF coords from vector extractor
                    x_raw, y_raw = rec["coordinates"]["x"], rec["coordinates"]["y"]
                    # Normalize to CropBox origin (same as geometric pipeline)
                    x = x_raw - page_rect.x0
                    y = y_raw - page_rect.y0
                    
                    # Apply boundary gate — skip labels in blank/notes area
                    if not point_in_drawing(x, y, frames, margin=5.0):
                        logger.debug(f"OCR label '{lbl}' at ({x:.0f},{y:.0f}) outside drawing boundary — skipped")
                        continue
                    
                    # Measure nearest geometry element
                    length_mm = 1000.0
                    best = 50.0
                    for g in page_geo:
                        r = g["rect"]
                        d = math.hypot(x - (r.x0+r.x1)/2 + page_rect.x0, y - (r.y0+r.y1)/2 + page_rect.y0)
                        if d < best: 
                            length_mm = max(engine.pt_to_real_mm(r.x1-r.x0), engine.pt_to_real_mm(r.y1-r.y0))
                            best = d
                    
                    conf_raw = rec.get("confidence", {})
                    confidence = conf_raw.get("composite", 0.8) if isinstance(conf_raw, dict) else 0.8
                    needs_review = conf_raw.get("needs_review", False) if isinstance(conf_raw, dict) else False
                    
                    asyncio.run_coroutine_threadsafe(queue.put({
                        "type":"label", "page":0,
                        "id":str(uuid.uuid4()),
                        "label":lbl,
                        "raw_text": rec.get("raw_text", lbl),
                        "x": round(x, 2), "y": round(y, 2),
                        "color": "orange" if needs_review else "blue",
                        "source":rec.get("source", "ocr"),
                        "confidence": round(confidence, 4),
                        "needs_review": needs_review,
                        "unit_weight":u_weight,
                        "length_mm":round(length_mm,1),
                        "weight_kg":round(u_weight * (length_mm/1000.0),2)
                    }), loop)
                    label_count += 1
                    import time; time.sleep(0.6)
                asyncio.run_coroutine_threadsafe(queue.put({"type":"complete", "total_labels": label_count}), loop)
        except Exception as e:
            logger.exception(f"Job {job_id} failed")
            asyncio.run_coroutine_threadsafe(queue.put({"type":"error", "message":str(e)}), loop)
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    await loop.run_in_executor(None, _work)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
