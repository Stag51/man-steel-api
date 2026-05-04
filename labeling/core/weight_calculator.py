import os
import csv
import re
from pathlib import Path
from typing import Dict, Optional, List

class WeightCalculator:
    def __init__(self, csv_dir: str):
        self.csv_dir = Path(csv_dir)
        self.lookup: Dict[str, float] = {}  # Normalized Name -> kg/m
        self._load_all_csvs()

    def _get_signature(self, name: str) -> str:
        """
        Creates a robust 'signature' for a steel section.
        Example: '305 x 165 UB 40' -> ('ub', '165', '305', '40')
                 '305x165x40 UB'   -> ('ub', '165', '305', '40')
        """
        if not name: return ""
        name = name.lower().replace('x', ' ') # Treat 'x' as a separator for cleaner number extraction
        # Find the section type
        types = re.findall(r'[a-z]+', name)
        # Filter out common separators like 'x' if they were missed
        section_type = next((t for t in types if t not in ['x']), "")
        
        numbers = re.findall(r'\d+\.?\d*', name)
        # Remove duplicates (e.g. 152x152 -> 152) and sort
        unique_numbers = sorted(list(set(numbers)))
        
        sig = f"{section_type}:" + ",".join(unique_numbers)
        return sig

    def _parse_float(self, val: str) -> float:
        """Handles both 12.5 and 12,5 formats."""
        if not val: return 0.0
        val = val.replace('"', '').replace(',', '.').strip()
        try:
            return float(val)
        except ValueError:
            return 0.0

    def _load_all_csvs(self):
        if not self.csv_dir.exists():
            print(f"Warning: Weightage directory {self.csv_dir} not found.")
            return

        for csv_file in self.csv_dir.glob("*.csv"):
            try:
                with open(csv_file, mode='r', encoding='utf-8') as f:
                    # Skip potentially messy headers or handle them
                    reader = csv.reader(f)
                    header = next(reader)
                    count = 0
                    
                    # Try to find the TYPE and WEIGHT columns
                    type_idx = -1
                    weight_idx = -1
                    
                    for i, col in enumerate(header):
                        col_upper = col.upper()
                        if "TYPE" in col_upper:
                            type_idx = i
                        elif "WEIGHT" in col_upper:
                            weight_idx = i
                    
                    if type_idx == -1 or weight_idx == -1:
                        # Fallback for files with multi-line headers (like the ones viewed)
                        # The viewed files had WEIGHT in the second row sometimes, 
                        # but often it's the first data column after TYPE.
                        type_idx = 0
                        weight_idx = 1
                    
                    for row in reader:
                        if len(row) <= max(type_idx, weight_idx): continue
                        name = row[type_idx].strip()
                        weight = self._parse_float(row[weight_idx])
                        
                        if name and weight > 0:
                            sig = self._get_signature(name)
                            self.lookup[sig] = weight
                            count += 1
                    
                    # print(f"Loaded {count} items from {csv_file.name}")
            except Exception as e:
                print(f"Error loading {csv_file.name}: {e}")
        
        print(f"Weight Calculator: Total of {len(self.lookup)} structural sections loaded.")

    def get_unit_weight(self, label: str) -> float:
        """Returns kg/m for a given label string."""
        sig = self._get_signature(label)
        # Direct match
        if sig in self.lookup:
            return self.lookup[sig]
        
        # Partial match attempts
        for k, v in self.lookup.items():
            if sig and k and (sig in k or k in sig):
                return v
        
        # Fallback: Match by numbers only if section type is missing or unknown
        # Extract just the numeric part of the signature
        nums_only = sig.split(':')[-1] if ':' in sig else sig
        if nums_only:
            for k, v in self.lookup.items():
                k_nums = k.split(':')[-1]
                if k_nums == nums_only:
                    return v
        
        return 0.0

    def calculate(self, labels: List[dict]) -> dict:
        """
        Calculates weights for a list of labels.
        Each label dict should have: 'label' (text), 'length_mm' (optional)
        """
        results = []
        total_weight = 0.0
        
        for item in labels:
            text = item.get("label", "")
            length_m = item.get("length_mm", 0) / 1000.0
            if length_m <= 0: length_m = 1.0 # Fallback to unit weight if no length
            
            unit_weight = self.get_unit_weight(text)
            item_weight = unit_weight * length_m
            
            results.append({
                "id": item.get("id"),
                "label": text,
                "unit_weight_kg_m": unit_weight,
                "length_m": round(length_m, 3),
                "total_kg": round(item_weight, 2)
            })
            total_weight += item_weight
            
        return {
            "items": results,
            "total_weight_kg": round(total_weight, 2),
            "count": len(results)
        }

# Global instance
_calc = None
def get_calculator():
    global _calc
    if _calc is None:
        csv_path = Path(__file__).resolve().parent.parent.parent / "labels_weightage"
        _calc = WeightCalculator(str(csv_path))
    return _calc
