import shutil
import os
import uuid
import json
import base64
import logging
import pdfplumber
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List

from config import Config
from label_engine import LabelEngine

# Setup Robust Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Structural Steel Labeling API", 
    version="2.0.0",
    description="Refactored Modular API for structural engineering PDF labeling."
)

class Member(BaseModel):
    x_real: float
    y_real: float
    label: str
    angle: float = 0

@app.post("/label")
async def label_drawing(
    file: UploadFile = File(...),
    members_json: str = Form(...),
    paper_size: str = Form(Config.DEFAULT_PAPER_SIZE),
    scale_ratio: int = Form(Config.DEFAULT_SCALE_RATIO),
    label_size: int = Form(Config.DEFAULT_LABEL_SIZE)
):
    """
    Manually labels a drawing based on provided real-world coordinates.
    """
    try:
        data = json.loads(members_json)
        members = [Member(**m) for m in data]
    except Exception as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail="Invalid data format.")

    file_id = str(uuid.uuid4())
    input_path = os.path.join(Config.UPLOAD_DIR, f"{file_id}_{file.filename}")
    output_path = os.path.join(Config.OUTPUT_DIR, f"labeled_{file_id}_{file.filename}")

    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        engine = LabelEngine(paper_size=paper_size, scale_ratio=scale_ratio, label_size=label_size)
        member_dicts = [m.model_dump() for m in members]
        engine.apply_labels_manual(input_path, output_path, member_dicts)
    except Exception as e:
        logger.error(f"Labeling error: {e}")
        raise HTTPException(status_code=500, detail="Internal processing error.")

    with open(output_path, "rb") as f:
        encoded_pdf = base64.b64encode(f.read()).decode('utf-8')

    return {
        "status": "success", 
        "filename": os.path.basename(output_path),
        "download_url": f"/download/{os.path.basename(output_path)}",
        "base64_data": encoded_pdf
    }

@app.post("/auto-label")
async def auto_label_drawing(
    file: UploadFile = File(...),
    paper_size: str = Form(Config.DEFAULT_PAPER_SIZE),
    scale_ratio: int = Form(Config.DEFAULT_SCALE_RATIO),
    label_size: int = Form(Config.DEFAULT_LABEL_SIZE),
    mode: str = Form("geometric")
):
    """
    Automatically detects shapes and labels structural members.
    """
    file_id = str(uuid.uuid4())
    input_path = os.path.join(Config.UPLOAD_DIR, f"{file_id}_{file.filename}")
    output_path = os.path.join(Config.OUTPUT_DIR, f"auto_labeled_{file_id}_{file.filename}")

    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    warning = None
    try:
        with pdfplumber.open(input_path) as pdf:
            text = pdf.pages[0].extract_text() or ""
            if "1 : 100" in text and scale_ratio == 50:
                warning = "Scale mismatch detected (1:100 indicated, 1:50 provided)."
            elif "1 : 50" in text and scale_ratio == 100:
                warning = "Scale mismatch detected (1:50 indicated, 1:100 provided)."

        engine = LabelEngine(paper_size=paper_size, scale_ratio=scale_ratio, label_size=label_size)
        engine.auto_label(input_path, output_path, mode=mode)
    except Exception as e:
        logger.error(f"Auto-Labeling error: {e}")
        raise HTTPException(status_code=500, detail="Auto-Labeling processing error.")

    with open(output_path, "rb") as f:
        encoded_pdf = base64.b64encode(f.read()).decode('utf-8')

    return {
        "status": "success", 
        "warning": warning,
        "filename": os.path.basename(output_path),
        "download_url": f"/download/{os.path.basename(output_path)}",
        "base64_data": encoded_pdf
    }

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(Config.OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(file_path, media_type='application/pdf')

@app.get("/")
async def root():
    return {"status": "online", "api_version": "2.0.0", "description": "Modular Steel API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
