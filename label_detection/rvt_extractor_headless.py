# -*- coding: utf-8 -*-
"""
rvt_extractor_headless.py
─────────────────────────
IronPython script for pyRevit CLI (pyrevit run).
Extracts structural elements from a Revit model and writes to JSON.

This script runs inside a headless Revit instance.
"""

import os
import sys
import json
import math

# Attempt to import Revit API
try:
    import clr
    clr.AddReference('RevitAPI')
    from Autodesk.Revit.DB import (
        FilteredElementCollector,
        BuiltInCategory,
        LocationCurve,
        LocationPoint,
        Document
    )
except ImportError:
    print("Error: This script must be run within a Revit/pyRevit environment.")
    sys.exit(1)

def feet_to_mm(feet):
    return feet * 304.8

def get_midpoint(location):
    if isinstance(location, LocationCurve):
        c = location.Curve
        p = c.Evaluate(0.5, True)
        return {"x": feet_to_mm(p.X), "y": feet_to_mm(p.Y), "z": feet_to_mm(p.Z)}
    elif isinstance(location, LocationPoint):
        p = location.Point
        return {"x": feet_to_mm(p.X), "y": feet_to_mm(p.Y), "z": feet_to_mm(p.Z)}
    return {"x": 0.0, "y": 0.0, "z": 0.0}

def get_orientation(location):
    if not isinstance(location, LocationCurve):
        return "unknown"
    c = location.Curve
    try:
        p0 = c.GetEndPoint(0)
        p1 = c.GetEndPoint(1)
        dx = abs(p1.X - p0.X)
        dy = abs(p1.Y - p0.Y)
        dz = abs(p1.Z - p0.Z)
        dominant = max(dx, dy, dz)
        if dominant == 0.0: return "point"
        if dominant == dz: return "vertical"
        if dx >= dy: return "horizontal"
        return "diagonal"
    except:
        return "unknown"

def extract_from_doc(doc):
    elements = []
    categories = [
        (BuiltInCategory.OST_StructuralFraming, "Structural Framing"),
        (BuiltInCategory.OST_StructuralColumns,  "Structural Columns"),
    ]

    for bic, cat_name in categories:
        collector = FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType()
        for elem in collector:
            try:
                sym = elem.Symbol
                type_name = sym.Name or ""
                family_name = sym.Family.Name or ""
                location = elem.Location
                midpoint = get_midpoint(location)
                orientation = get_orientation(location)

                elements.append({
                    "element_id": elem.Id.IntegerValue,
                    "category": cat_name,
                    "type_name": type_name,
                    "family_name": family_name,
                    "location": midpoint,
                    "orientation": orientation,
                    "source": "revit_api_headless"
                })
            except Exception as e:
                print("Error extracting element: {}".format(e))
    return elements

if __name__ == "__main__":
    # pyrevit run transmits the model path via __revit__ or args
    # For simplicity in this bridge, we expect the caller to pass:
    # rvt_extractor_headless.py <rvt_path> <output_json_path>
    
    if len(sys.argv) < 3:
        print("Usage: pyrevit run rvt_extractor_headless.py <rvt_path> <output_json_path>")
        sys.exit(1)

    rvt_path = sys.argv[1]
    output_path = sys.argv[2]

    # In pyrevit runner, the doc might already be open or we might need to open it
    # If __revit__ is available, it's the UIApplication
    try:
        # This is a placeholder for the pyrevit entry point logic
        # Usually pyrevit run handles opening the model if passed as an argument
        from Autodesk.Revit.ApplicationServices import Application
        
        # Accessing the current document from pyrevit context if possible
        # Otherwise open explicitly
        app = __revit__.Application
        model_path = rvt_path
        
        # Check if model is already open
        doc = None
        for d in app.Documents:
            if d.PathName == model_path:
                doc = d
                break
        
        if not doc:
            doc = app.OpenDocumentFile(model_path)

        data = extract_from_doc(doc)
        
        with open(output_path, 'w') as f:
            json.dump(data, f)
            
        print("Successfully extracted {} elements to {}".format(len(data), output_path))
        
    except Exception as e:
        print("Headless extraction failed: {}".format(e))
        sys.exit(1)
