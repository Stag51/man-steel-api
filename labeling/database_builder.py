import pdfplumber
import os
import re
import json

DATA_DIR = r"c:\Users\AISpr\Documents\man-steel\data"
OUTPUT_DB = r"c:\Users\AISpr\Documents\man-steel\project_db.json"

section_pattern = re.compile(r'\b(UC|UB|CHS|SHS|PFC|RSA|RHS|EA|UA)\s?\d+\.?\d*x\d+\.?\d*(x\d+\.?\d*)?\b')
id_pattern = re.compile(r'\b(SE\d+|SG\d+|S\d+|B\d+|C\d+|F\d+|FF\d+)\b')

def build_database():
    mappings = {}
    files_to_scan = [f for f in os.listdir(DATA_DIR) if ("Section" in f or "Schedule" in f) and f.endswith(".pdf")]
    
    print(f"Scanning {len(files_to_scan)} files for sophisticated member mappings...")
    
    for filename in files_to_scan:
        path = os.path.join(DATA_DIR, filename)
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    # Get all words with their coordinates
                    words = page.extract_words()
                    if not words: continue
                    
                    # Sort words by top then left
                    # This helps in reading sections sequentially
                    words.sort(key=lambda w: (w['top'], w['x0']))
                    
                    # Look for "Section-ID" headers or IDs in large text
                    # And find the nearest Section Label
                    current_id = None
                    for word in words:
                        text = word['text']
                        
                        # Check if it looks like an ID
                        match_id = id_pattern.search(text)
                        if match_id and text not in ["S355", "S275", "SCALE"]:
                            current_id = match_id.group(0)
                        
                        # Check if it looks like a Section Label
                        match_sec = section_pattern.search(text)
                        if match_sec and current_id:
                            # We found a section label after an ID
                            # Let's check distance to be sure? 
                            # For now, let's assume the order is Header -> Content
                            mappings[current_id] = match_sec.group(0)
                        
                        # Special Case: "Section-SE1"
                        header_match = re.search(r'Section-([A-Z0-9]+)', text)
                        if header_match:
                            current_id = header_match.group(1)

        except Exception as e:
            print(f"Error scanning {filename}: {e}")

    # Remove duplicates and clean
    if "S355" in mappings: del mappings["S355"]
    if "S275" in mappings: del mappings["S275"]

    print(f"Found {len(mappings)} unique mappings.")
    with open(OUTPUT_DB, 'w') as f:
        json.dump(mappings, f, indent=4)
    
    return mappings

if __name__ == "__main__":
    db = build_database()
    print("Sophisticated Database built.")
    # Print sample
    for k in sorted(list(db.keys()))[:20]:
        print(f"{k} -> {db[k]}")
