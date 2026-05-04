# Structural Steel Engineering API (v3.0.0)
## Full Integration Manual for Frontend Developers

This document details the architecture, data structures, and implementation logic required to build a frontend for the Structural Steel Extraction Pipeline.

---

## 1. System Architecture Overview

The backend is built on **FastAPI** and uses **Asynchronous Background Workers**. The process follows a "Submit and Listen" pattern:
1. **Frontend** uploads a PDF.
2. **Backend** returns a Job ID and metadata.
3. **Frontend** opens a persistent connection (SSE) to receive real-time detection events.
4. **Backend** processes the PDF in the background, emitting labels as they are found.

---

## 2. API Pillars & Endpoint Details

### Pillar 1: The Job Management Pillar

#### `POST /upload`
Starts the extraction process.
- **Request (Multipart/Form-Data)**:
  - `file`: (Binary) The PDF drawing.
  - `pipeline_type`: (String) `auto_label` for geometric scan or `detect` for OCR scan.
  - `scale_ratio`: (Int) The drawing scale denominator (e.g., 50 for 1:50).
  - `paper_size`: (String) Target paper size (e.g., "A3").
- **Response (200 OK)**:
```json
{
  "job_id": "8a3d...",
  "total_pages": 1,
  "pages": [
    {
      "page": 0,
      "width": 1190.55, 
      "height": 841.89
    }
  ]
}
```
> [!IMPORTANT]
> **Coordinate Units**: All `width`, `height`, `x`, and `y` values are in **PDF Points (pt)**. 
> Formula: `1 inch = 72 points`. 

---

### Pillar 2: The Streaming Pillar (Server-Sent Events)

#### `GET /stream/{job_id}`
Connect to this via `new EventSource('/stream/job_id')`.

| Event Type | Purpose | Key Fields |
| :--- | :--- | :--- |
| `start` | Initialization | `total_pages` |
| `boundary` | Draw Frames | `frames: [{x0, y0, x1, y1}]` |
| `label` | Member Detection | `label`, `weight_kg`, `length_mm`, `x`, `y` |
| `progress` | Progress Bar | `page`, `percent` |
| `complete` | Finalization | `total_labels` |
| `error` | Failure | `message` |

**The `label` Event Schema:**
```json
{
  "type": "label",
  "id": "uuid-string",
  "label": "254x146x31 UB",      // Normalized label string
  "raw_text": "UB 254x146x31",   // OCR-raw or Vector-raw text
  "x": 450.5, "y": 300.2,        // Centroid of the member
  "unit_weight": 31.0,           // kg/m from CSV catalog
  "length_mm": 3420.5,           // Real-world length at 1:50 scale
  "weight_kg": 106.04,           // Final calculation: (unit_weight * length)
  "source": "ocr",               // ocr, pdf_vector, or feedback
  "color": "blue"                // UI hint: blue=auto, orange=review, green=corrected
}
```

---

### Pillar 3: The Human-in-the-Loop Pillar (Feedback)

#### `POST /feedback`
Updates the backend's "Learned Knowledge Base".

**Scenario A: Correcting a Label**
```json
{
  "type": "correct",
  "original_label": "Mistyped Section",
  "corrected_label": "152x152x37 UC",
  "page": 0, "x": 450, "y": 300
}
```

**Scenario B: Excluding an Irrelevant Area**
If a label is detected in the legend or title block, mark it as an exclusion zone.
```json
{
  "type": "exclude",
  "page": 0, "x": 10, "y": 10
}
```

---

## 3. Frontend Implementation Guide (Step-by-Step)

### Step 1: Scaling the Drawing Viewer
The PDF image (`/page-image`) might be 1500px wide, but the PDF coordinates (`x`, `y`) might only go up to 1190. 
**Math for the developer:**
```javascript
const scaleX = canvasElement.width / page_width_pt;
const scaleY = canvasElement.height / page_height_pt;

function drawDot(event) {
  const pixelX = event.x * scaleX;
  const pixelY = event.y * scaleY;
  // Draw dot at (pixelX, pixelY)
}
```

### Step 2: Managing State (The Store)
- Use a `Map` or `Object` keyed by `job_id` and `page_num`.
- When a `label` event arrives, **check for duplicates** by `id`. 
- Always `prepend` new labels to the list so the user sees them arriving in real-time.

### Step 3: Tonnage Calculation
Do not wait for the backend to finish to show the total weight.
1. Create a `liveTotalWeight` variable.
2. Every time a `label` event arrives, add `event.weight_kg` to the total.
3. Update the UI ticker instantly.

---

## 4. Troubleshooting & Error Codes

- **404 Not Found**: The `job_id` has expired or the server restarted (Jobs are kept in memory).
- **SSE Connection Failure**: Usually happens if the client-side timeout is too low. Ensure `EventSource` is robust.
- **Weight = 0**: Means the label exists but was not found in the `labels_weightage/*.csv` files. Show a warning icon next to these labels.

---

## 5. Engineering Logic Reference (The Formula)

For transparency, the backend calculates tonnage as follows:
1. **Drawing Length**: `L_pts = sqrt(dx^2 + dy^2)`
2. **Real World MM**: `L_mm = L_pts * (25.4 / 72) * Scale_Ratio`
3. **Weight KG**: `Weight = (L_mm / 1000) * (kg_m from CSV)`
