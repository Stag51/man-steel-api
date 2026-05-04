"""
Structural matching logic. Maps real-world dimensions (mm) to standard steel sections.
"""

# Common British/European section sizes
SECTION_TABLE = {
    # UC (Universal Columns)
    (152, 152, 'rect'): "UC 152x152x37",
    (152.4, 152.4, 'rect'): "UC 152x152x37",
    (203, 203, 'rect'): "UC 203x203x46", # This is the "flood" suspect
    (203.2, 203.2, 'rect'): "UC 203x203x46",
    (254, 254, 'rect'): "UC 254x254x73",
    (305, 305, 'rect'): "UC 305x305x118",
    
    # SHS (Square Hollow Sections)
    (100, 100, 'rect'): "SHS 100x100x6.3",
    (140, 140, 'rect'): "SHS 140x140x10",
    (160, 160, 'rect'): "SHS 160x160x10",
    (200, 200, 'rect'): "SHS 200x200x10",
    
    # CHS (Circular Hollow Sections)
    (193.7, 193.7, 'circle'): "CHS 193.7x10",
    (139.7, 139.7, 'circle'): "CHS 139.7x10",
    (114.3, 114.3, 'circle'): "CHS 114.3x6",
}

def match_section(w, h, shape_type='rect', tolerance=3.0):
    """
    Finds the best matching section. Tolerance reduced to 3.0mm to prevent false positives.
    """
    best_match = None
    min_diff = float('inf')
    
    # If the shape is too aspect-ratio heavy, it's a wall or line, not a column/beam section
    if shape_type == 'rect':
        aspect = max(w, h) / min(w, h) if min(w, h) > 0 else 100
        if aspect > 2.5: # Columns/Beams are usually near-square or only 2x tall
            return None

    for (sw, sh, stype), label in SECTION_TABLE.items():
        if stype != shape_type:
            continue
            
        diff = min(abs(w - sw) + abs(h - sh), abs(w - sh) + abs(h - sw))
        
        if diff < tolerance and diff < min_diff:
            min_diff = diff
            best_match = label
            
    return best_match
