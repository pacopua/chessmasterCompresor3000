"""
Round-trip test for all PGN files in data/input/.

For each file:
  1. Encode to data/output/encoded/<name>.cpg3
  2. Decode to data/output/decoded/<name>.pgn
  3. Byte-compare original vs decoded

Prints per-file compression ratio and a pass/fail result.
Exits with code 1 if any file fails.
"""

import os
import sys
import glob

from src.encode_game import encode_pgn_file, decode_pgn_file

ENC_DIR = "data/output/encoded"
DEC_DIR = "data/output/decoded"
os.makedirs(ENC_DIR, exist_ok=True)
os.makedirs(DEC_DIR, exist_ok=True)

pgn_files = sorted(glob.glob("data/input/*.pgn"))
if not pgn_files:
    print("No PGN files found in data/input/")
    sys.exit(1)

total_orig = 0
total_comp = 0
all_pass   = True

print(f"{'File':<25} {'Orig':>10} {'Comp':>10} {'Ratio':>7}  Result")
print("-" * 65)

for pgn_path in pgn_files:
    name     = os.path.basename(pgn_path)
    stem     = name.replace(".pgn", "")
    enc_path = os.path.join(ENC_DIR, stem + ".cpg3")
    dec_path = os.path.join(DEC_DIR, stem + ".pgn")

    # Encode
    try:
        encode_pgn_file(pgn_path, enc_path)
    except Exception as e:
        print(f"{name:<25}  ENCODE ERROR: {e}")
        all_pass = False
        continue

    # Decode
    try:
        decode_pgn_file(enc_path, dec_path)
    except Exception as e:
        print(f"{name:<25}  DECODE ERROR: {e}")
        all_pass = False
        continue

    # Integrity check
    with open(pgn_path, "rb") as f:
        orig_bytes = f.read()
    with open(dec_path, "rb") as f:
        dec_bytes = f.read()

    orig_size = len(orig_bytes)
    comp_size = os.path.getsize(enc_path)
    ratio     = orig_size / comp_size
    total_orig += orig_size
    total_comp += comp_size

    if orig_bytes == dec_bytes:
        status = "PASS"
    else:
        status = "FAIL"
        all_pass = False
        # Show first difference
        for i, (a, b) in enumerate(zip(orig_bytes, dec_bytes)):
            if a != b:
                ctx_o = orig_bytes[max(0, i-40):i+40]
                ctx_d = dec_bytes[max(0, i-40):i+40]
                print(f"  first diff at byte {i}")
                print(f"    orig    : {ctx_o!r}")
                print(f"    decoded : {ctx_d!r}")
                break
        if orig_bytes == dec_bytes[:len(orig_bytes)] and len(dec_bytes) != len(orig_bytes):
            print(f"  size mismatch: orig={len(orig_bytes)} decoded={len(dec_bytes)}")

    print(f"{name:<25} {orig_size:>10,} {comp_size:>10,} {ratio:>6.2f}×  {status}")

print("-" * 65)
overall_ratio = total_orig / total_comp if total_comp else 0
print(f"{'TOTAL':<25} {total_orig:>10,} {total_comp:>10,} {overall_ratio:>6.2f}×")
print()
if all_pass:
    print("ALL FILES PASSED")
else:
    print("SOME FILES FAILED")
    sys.exit(1)
