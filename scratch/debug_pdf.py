import pdfplumber
from pypdf import PdfReader
import sys
from pathlib import Path

def debug_pdf(pdf_path):
    print(f"Analyzing: {pdf_path}")
    reader = PdfReader(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        for i, (pypdf_page, plumber_page) in enumerate(zip(reader.pages, pdf.pages)):
            print(f"\nPage {i+1}:")
            print(f"  PyPDF MediaBox: {pypdf_page.mediabox}")
            print(f"  PyPDF CropBox:  {pypdf_page.get('/CropBox', 'Not set')}")
            print(f"  PyPDF Rotation: {pypdf_page.get('/Rotate', 0)}")
            print(f"  pdfplumber Size: {plumber_page.width} x {plumber_page.height}")
            print(f"  pdfplumber BBox: {plumber_page.bbox}")

if __name__ == "__main__":
    pdf_file = r"c:\Users\AISpr\Documents\man_steel_combined\labeling\uploads\360e6118-17d0-4533-b9e7-146b4318e058_Structural Drawings - D28387_ST_201_P2_Existing Office_GF Plan Showing Floor Structure Over.pdf"
    if Path(pdf_file).exists():
        debug_pdf(pdf_file)
    else:
        print("File not found.")
