import glob
import re

header_regex = re.compile(r'^\[([A-Za-z0-9_]+)\s+"')
unique_headers = set()
files = glob.glob('*.pgn')

for file in files:
    with open(file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            match = header_regex.match(line.strip())
            if match:
                unique_headers.add(match.group(1))

print("Found the following unique headers across all PGN files:\n")
for header in sorted(list(unique_headers)):
    print(f"- {header}")
