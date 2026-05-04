# Antigravity Steel Labeling Engine

An advanced, automated FastAPI service for labeling structural steel members in engineering PDF drawings.

## Features
- **Geometric Detection**: Automatically identifies UC, UB, CHS, and SHS sections by their physical shapes.
- **Cluster-Based Labeling**: Groups complex structural hubs (columns, plates, bolts) to prevent overlapping labels.
- **Rotation-Aware**: Automatically handles 90°/270° rotated PDF sheets.
- **Scale-Independent**: Supports 1:50, 1:100, and custom structural scales.
- **Base64 Responses**: Returns labeled PDFs directly as Base64 strings for easy integration.

## Installation

1. **Clone the repository**:
   ```bash
   git clone <your-repo-url>
   cd man-steel
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the Service**:
   ```bash
   python main.py
   ```

## API Endpoints

- **`POST /auto-label`**: Automatically detects and labels a structural drawing.
  - Parameters: `file`, `paper_size` (A3/A1), `scale_ratio` (50/100), `mode` (geometric/id).
- **`GET /download/{filename}`**: Direct download link for processed PDFs.

## Architecture
For a detailed explanation of the labeling logic (hubs, centroids, and rotation), see `artifacts/system_architecture.md`.

## License
Proprietary - Prepared for SWF Consulting.
