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

# ── CPG5 (chess-aware) ───────────────────────────────────────────────────────
import time, io, contextlib

print()
print("── CPG5 (chess-aware) ─────────────────────────────────────────────────")
from src.encode_game_chess import encode_pgn_file_chess, decode_pgn_file_chess

ENC5_DIR  = "data/output/encoded5"
DEC5_DIR  = "data/output/decoded5"
ENC5B_DIR = "data/output/encoded5b"
for d in (ENC5_DIR, DEC5_DIR, ENC5B_DIR):
    os.makedirs(d, exist_ok=True)

SPEED_MIN_KB = 250  # KB/s threshold

print(f"{'File':<25} {'Orig':>10} {'Comp':>10} {'Ratio':>7} {'Enc KB/s':>10} {'Dec KB/s':>10}  Result")
print("-" * 85)

total_orig5 = total_comp5 = 0
total_enc_t = total_dec_t = 0.0
all_pass5 = True

for pgn_path in pgn_files:
    name  = os.path.basename(pgn_path)
    stem  = name.replace(".pgn", "")
    enc1  = os.path.join(ENC5_DIR,  stem + ".cpg5")
    dec1  = os.path.join(DEC5_DIR,  stem + ".pgn")
    enc2  = os.path.join(ENC5B_DIR, stem + ".cpg5")

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            t0 = time.perf_counter()
            encode_pgn_file_chess(pgn_path, enc1)
            enc_time = time.perf_counter() - t0

            t0 = time.perf_counter()
            decode_pgn_file_chess(enc1, dec1)
            dec_time = time.perf_counter() - t0

            encode_pgn_file_chess(dec1, enc2)
    except Exception as e:
        print(f"{name:<25}  ERROR: {e}")
        all_pass5 = False
        continue

    orig_size = os.path.getsize(pgn_path)
    comp_size = os.path.getsize(enc1)
    ratio     = orig_size / comp_size
    orig_kb   = orig_size / 1024
    enc_kbs   = orig_kb / enc_time
    dec_kbs   = orig_kb / dec_time

    total_orig5 += orig_size
    total_comp5 += comp_size
    total_enc_t += enc_time
    total_dec_t += dec_time

    with open(enc1, 'rb') as f: b1 = f.read()
    with open(enc2, 'rb') as f: b2 = f.read()
    status = "PASS" if b1 == b2 else "FAIL"
    if status == "FAIL":
        all_pass5 = False
        for i, (a, b) in enumerate(zip(b1, b2)):
            if a != b:
                print(f"  first diff at byte {i}: {a:#04x} vs {b:#04x}")
                break

    slow = " ENC_SLOW" if enc_kbs < SPEED_MIN_KB else ""
    slow += " DEC_SLOW" if dec_kbs < SPEED_MIN_KB else ""
    if slow:
        all_pass5 = False
    print(f"{name:<25} {orig_size:>10,} {comp_size:>10,} {ratio:>6.2f}× {enc_kbs:>10.1f} {dec_kbs:>10.1f}  {status}{slow}")

print("-" * 85)
ov5      = total_orig5 / total_comp5 if total_comp5 else 0
total_kb = total_orig5 / 1024
avg_enc  = total_kb / total_enc_t if total_enc_t else 0
avg_dec  = total_kb / total_dec_t if total_dec_t else 0
print(f"{'TOTAL':<25} {total_orig5:>10,} {total_comp5:>10,} {ov5:>6.2f}× {avg_enc:>10.1f} {avg_dec:>10.1f}")
if all_pass5:
    print("ALL CPG5 FILES PASSED")
else:
    print("SOME CPG5 FILES FAILED")
    sys.exit(1)
