"""
Structural matching logic. Maps real-world dimensions (mm) to standard steel sections.
"""
from config import Config

# Common British/European section sizes
SECTION_TABLE = {
    # UC (Universal Columns)
    (152, 152, 'rect'): "UC 152x152x37",
    (152.4, 152.4, 'rect'): "UC 152x152x37",
    (203, 203, 'rect'): "UC 203x203x46",
    (203.2, 203.2, 'rect'): "UC 203x203x46",
    (254, 254, 'rect'): "UC 254x254x73",
    (305, 305, 'rect'): "UC 305x305x118",
    
    # UB (Universal Beams)
    (178, 102, 'rect'): "178x102x19 UB",
    (203, 102, 'rect'): "203x102x23 UB",
    (203, 133, 'rect'): "203x133x30 UB",
    (254, 102, 'rect'): "254x102x22 UB",
    (254, 146, 'rect'): "254x146x31 UB",
    (305, 102, 'rect'): "305x102x25 UB",
    (305, 127, 'rect'): "305x127x37 UB",
    (305, 165, 'rect'): "305x165x40 UB",
    (356, 127, 'rect'): "356x127x33 UB",
    (356, 171, 'rect'): "356x171x51 UB",
    (406, 140, 'rect'): "406x140x39 UB",
    (406, 178, 'rect'): "406x178x67 UB",
    (457, 152, 'rect'): "457x152x52 UB",
    (457, 191, 'rect'): "457x191x74 UB",

    # PFC (Parallel Flange Channels)
    (150, 75, 'rect'): "PFC 150x75x18",
    (150, 90, 'rect'): "PFC 150x90x24",
    (180, 75, 'rect'): "PFC 180x75x20",
    (200, 75, 'rect'): "PFC 200x75x23",
    (200, 90, 'rect'): "PFC 200x90x30",

    # SHS/RHS (Hollow Sections)
    (100, 100, 'rect'): "SHS 100x100x6.3",
    (120, 120, 'rect'): "SHS 120x120x8",
    (140, 140, 'rect'): "SHS 140x140x10",
    (150, 150, 'rect'): "SHS 150x150x10",
    (200, 100, 'rect'): "RHS 200x100x8",
    (200, 200, 'rect'): "SHS 200x200x10",
    
    # CHS (Circular Hollow Sections)
    (193.7, 193.7, 'circle'): "CHS 193.7x10",
    (168.3, 168.3, 'circle'): "CHS 168.3x10",
    (139.7, 139.7, 'circle'): "CHS 139.7x10",
    (114.3, 114.3, 'circle'): "CHS 114.3x6",
    (88.9, 88.9, 'circle'): "CHS 88.9x5",
}

def match_section(w, h, shape_type='rect'):
    """
    Finds the closest matching structural section from the table.
    Uses an adaptive tolerance to handle PDF rounding errors.
    """
    # Ensure dimensions are agnostic of orientation
    d_max, d_min = max(w, h), min(w, h)
    
    best_label = None
    min_diff = 15.0 # mm tolerance (increased to handle rounding errors)
    
    for (sw, sh, stype), label in SECTION_TABLE.items():
        if stype != shape_type:
            continue
            
        target_max, target_min = max(sw, sh), min(sw, sh)
        diff = abs(d_max - target_max) + abs(d_min - target_min)
        
        if diff < min_diff:
            min_diff = diff
            best_label = label
            
    return best_label
