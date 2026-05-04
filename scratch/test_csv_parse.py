import csv
import os

files = ['FLT.csv', 'RAS_E.csv', 'UB.csv']
dir_path = r'c:\Users\AISpr\Documents\man_steel_combined\labels_weightage'

for fname in files:
    path = os.path.join(dir_path, fname)
    print(f"\n--- Testing {fname} ---")
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        print(f"Header: {header}")
        # Try to find columns
        type_idx = -1
        weight_idx = -1
        for i, col in enumerate(header):
            c = col.upper().replace("\n", " ")
            if "TYPE" in c: type_idx = i
            if "WEIGHT" in c or "KG/M" in c: weight_idx = i
        
        print(f"Indices: type={type_idx}, weight={weight_idx}")
        
        # Show first data row
        try:
            first_row = next(reader)
            print(f"First Data Row: {first_row}")
        except:
            print("No data rows found!")
