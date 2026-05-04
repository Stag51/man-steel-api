from paddlex.utils import logging
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
import uvicorn

# Setup Robust Logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Add subdirectories to sys.path for modular imports

BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR / "labeling"))
sys.path.append(str(BASE_DIR / "label_detection"))

# Imports from submodules
from config import Config as LabelingConfig
from label_engine import LabelEngine
import pipeline as detection_pipeline

app = FastAPI(
    title="Structural Engineering Unified API",
    version="1.0.0",
    description="Unified API for Label Detection and Auto-Labeling."
)