"""
Structural matching logic. Maps real-world dimensions (mm) to standard steel sections.
"""
from config import Config

# Common British/European section sizes
SECTION_TABLE = {
    # ── UC (Universal Columns) ─────────────────────────────────────────────────
    (152, 152, 'rect'): "UC152x152x37",
    (152.4, 152.4, 'rect'): "UC152x152x37",
    (203, 203, 'rect'): "UC203x203x46",
    (203.2, 203.2, 'rect'): "UC203x203x46",
    (254, 254, 'rect'): "UC254x254x73",
    (305, 305, 'rect'): "UC305x305x118",
    (356, 368, 'rect'): "UC356x368x202",

    # ── UB (Universal Beams) ───────────────────────────────────────────────────
    # 178 family
    (178, 102, 'rect'): "UB178x102x19",
    # 203 family
    (203, 102, 'rect'): "UB203x102x23",
    (203, 133, 'rect'): "UB203x133x25",
    # 254 family
    (254, 102, 'rect'): "UB254x102x22",
    (254, 146, 'rect'): "UB254x146x31",
    # 305 family
    (305, 102, 'rect'): "UB305x102x25",
    (305, 127, 'rect'): "UB305x127x37",
    (305, 165, 'rect'): "UB305x165x40",
    # 356 family
    (356, 127, 'rect'): "UB356x127x33",
    (356, 171, 'rect'): "UB356x171x45",
    # 406 family
    (406, 140, 'rect'): "UB406x140x39",
    (406, 178, 'rect'): "UB406x178x54",
    # 457 family
    (457, 152, 'rect'): "UB457x152x52",
    (457, 191, 'rect'): "UB457x191x67",
    # 533 family
    (533, 210, 'rect'): "UB533x210x82",
    # 610 family
    (610, 229, 'rect'): "UB610x229x101",

    # ── PFC (Parallel Flange Channels) ────────────────────────────────────────
    (100, 50, 'rect'): "PFC100x50x10",
    (125, 65, 'rect'): "PFC125x65x15",
    (150, 75, 'rect'): "PFC150x75x18",
    (150, 90, 'rect'): "PFC150x90x24",
    (180, 75, 'rect'): "PFC180x75x20",
    (200, 75, 'rect'): "PFC200x75x23",
    (200, 90, 'rect'): "PFC200x90x30",
    (230, 90, 'rect'): "PFC230x90x32",
    (260, 90, 'rect'): "PFC260x90x35",
    (300, 100, 'rect'): "PFC300x100x46",

    # ── SHS (Square Hollow Sections) ──────────────────────────────────────────
    (80, 80, 'rect'): "SHS80x80x5",
    (100, 100, 'rect'): "SHS100x100x6.3",
    (120, 120, 'rect'): "SHS120x120x8",
    (140, 140, 'rect'): "SHS140x140x10",
    (150, 150, 'rect'): "SHS150x150x10",
    (160, 160, 'rect'): "SHS160x160x10",
    (180, 180, 'rect'): "SHS180x180x10",
    (200, 200, 'rect'): "SHS200x200x10",
    (250, 250, 'rect'): "SHS250x250x12.5",

    # ── RHS (Rectangular Hollow Sections) ─────────────────────────────────────
    (200, 100, 'rect'): "RHS200x100x5",
    (250, 150, 'rect'): "RHS250x150x12.5",
    (300, 200, 'rect'): "RHS300x200x10",
    (400, 200, 'rect'): "RHS400x200x12.5",

    # ── CHS (Circular Hollow Sections) ────────────────────────────────────────
    (60.3, 60.3, 'circle'): "CHS60.3x5",
    (76.1, 76.1, 'circle'): "CHS76.1x5",
    (88.9, 88.9, 'circle'): "CHS88.9x5",
    (101.6, 101.6, 'circle'): "CHS101.6x6.3",
    (114.3, 114.3, 'circle'): "CHS114.3x6.3",
    (139.7, 139.7, 'circle'): "CHS139.7x8",
    (168.3, 168.3, 'circle'): "CHS168.3x10",
    (193.7, 193.7, 'circle'): "CHS193.7x10",
    (219.1, 219.1, 'circle'): "CHS219.1x10",
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
