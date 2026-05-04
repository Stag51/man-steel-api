"""
PDF Service: Handles overlays, merges, and coordinate transformations.
"""
import io
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter
from config import Config

class PDFService:
    @staticmethod
    def get_overlay_canvas(width: float, height: float, rotation: int = 0):
        packet = io.BytesIO()
        # Always use the visible dimensions provided (already handled by pdfplumber)
        can = canvas.Canvas(packet, pagesize=(width, height))
        return can, packet

    @staticmethod
    def finalize_overlay(can, packet):
        can.save()
        packet.seek(0)
        return PdfReader(packet)

    @staticmethod
    def merge_pages(original_page, overlay_pdf):
        if len(overlay_pdf.pages) > 0:
            original_page.merge_page(overlay_pdf.pages[0])
        return original_page
