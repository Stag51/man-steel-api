import re

SECTION_TYPES = ("UC", "UB", "SHS", "RHS", "PFC", "FL", "PL")
_ST = "|".join(re.escape(s) for s in sorted(SECTION_TYPES, key=len, reverse=True))

BARE = re.compile(r'\b(?P<section>' + _ST + r')(?P<dims>[\d.]+(?:[xX×][\d.]+)+)\b', re.I)

test_strings = [
    "UC203x203x46",
    "UB356x171x45",
    "SHS140x140x6.3",
    "PFC150x75x18",
    "CHS219.1x10"
]

for s in test_strings:
    match = BARE.search(s)
    print(f"'{s}': {match.group(0) if match else 'NO MATCH'}")
