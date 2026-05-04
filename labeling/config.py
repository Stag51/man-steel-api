import os

class Config:
    # Directories
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
    OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
    DB_PATH = os.path.join(BASE_DIR, "project_db.json")

    # Labeling Defaults
    DEFAULT_PAPER_SIZE = "A3"
    DEFAULT_SCALE_RATIO = 50
    DEFAULT_LABEL_SIZE = 8
    
    # Hub Clustering Settings (pts)
    HUB_RADIUS = 15
    DEDUPLICATION_THRESHOLD = 10
    STRICT_MATCH_TOLERANCE = 3.0 # mm

    # Colors (RGB normalized 0-1)
    COLOR_ID_LABEL = (0.8, 0, 0)
    COLOR_GEO_LABEL = (0, 0, 0.6)
    COLOR_DOT = (0, 0.4, 0.8)

    # Ensure dirs exist
    for d in [UPLOAD_DIR, OUTPUT_DIR]:
        os.makedirs(d, exist_ok=True)
