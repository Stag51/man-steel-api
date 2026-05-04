"""
Scaling and coordinate transformation utilities for steel structure drawings.
Default scale: 1:50 on A3 paper.
A3 Dimensions: 297mm x 420mm.
PDF Point: 1/72 inch.
"""

MM_TO_PT = 72 / 25.4  # ~2.8346

class Scaler:
    def __init__(self, paper_size="A3", scale_ratio=50):
        """
        :param paper_size: "A3" or "A1"
        :param scale_ratio: e.g., 50 for 1:50
        """
        self.scale_ratio = scale_ratio
        if paper_size == "A3":
            self.paper_width_mm = 420
            self.paper_height_mm = 297
        elif paper_size == "A1":
            self.paper_width_mm = 841
            self.paper_height_mm = 594
        else:
            raise ValueError(f"Unsupported paper size: {paper_size}")
            
        self.paper_width_pt = self.paper_width_mm * MM_TO_PT
        self.paper_height_pt = self.paper_height_mm * MM_TO_PT

    def mm_to_pt(self, mm):
        return mm * MM_TO_PT

    def real_to_paper_mm(self, real_mm):
        return real_mm / self.scale_ratio

    def real_to_pt(self, real_mm):
        return self.mm_to_pt(self.real_to_paper_mm(real_mm))

    def get_text_height_pt(self, target_mm_on_paper=2.5):
        """Standard drawing text height is often 2.5mm or 3.5mm."""
        return self.mm_to_pt(target_mm_on_paper)

# Example conversion:
# A member at (5000mm, 5000mm) in reality.
# At 1:50, it is 100mm, 100mm on paper.
# On A3 (420x297), it is valid.
