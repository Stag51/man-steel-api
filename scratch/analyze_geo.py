import pdfplumber
import sys
from pathlib import Path

def analyze_geometry(pdf_path):
    print(f"Analyzing geometry: {pdf_path}")
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        print(f"Page size: {page.width} x {page.height}")
        print(f"Rects count: {len(page.rects)}")
        print(f"Curves count: {len(page.curves)}")
        print(f"Lines count: {len(page.lines)}")
        print(f"Images count: {len(page.images)}")
        print(f"Paths count: {len(page.objects.get('path', []))}")
        
        if page.rects:
            print("\nExample Rects (first 5):")
            for r in page.rects[:5]:
                print(f"  {r['x0'], r['top'], r['x1'], r['bottom']} - width: {r['width']}, height: {r['height']}")
        
        if page.curves:
            print("\nExample Curves (first 5):")
            for c in page.curves[:5]:
                print(f"  {c['x0'], c['top'], c['x1'], c['bottom']} - width: {c['width']}, height: {c['height']}")

if __name__ == "__main__":
    pdf_file = r"c:\Users\AISpr\Documents\man_steel_combined\labeling\uploads\360e6118-17d0-4533-b9e7-146b4318e058_Structural Drawings - D28387_ST_201_P2_Existing Office_GF Plan Showing Floor Structure Over.pdf"
    if Path(pdf_file).exists():
        analyze_geometry(pdf_file)
    else:
        print("File not found.")
