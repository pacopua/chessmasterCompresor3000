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

pgn_files = sorted(glob.glob("data/input/*.pgn"))

# To try other encoder and decoder versions, just change the imports and function calls below.

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

        orig_size = os.path.getsize(pgn_path)
        comp_size = os.path.getsize(enc1)
        ratio     = orig_size / comp_size
        orig_kb   = orig_size / 1024
        print(f"TIME TO ENCODE: {enc_time} KB/s: {orig_kb/enc_time}")

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
