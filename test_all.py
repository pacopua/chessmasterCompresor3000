"""
Round-trip test for all PGN files in data/input/.

For each file:
  1. Encode to data/output/encoded5/<name>.cpg5
  2. Decode to data/output/decoded5/<name>.pgn
  3. Text-diff original vs decoded (trailing whitespace ignored, leading preserved)

Prints per-file compression ratio and a pass/fail result.
Exits with code 1 if any file fails.
"""

import difflib
import glob
import os
import sys
import time

from src.encode_game_chess import encode_pgn_file_chess, decode_pgn_file_chess


def main():
    pgn_files = sorted(glob.glob("data/input/*.pgn"))

    print()
    print("── CPG5 (chess-aware) ─────────────────────────────────────────────────")

    ENC5_DIR  = "data/output/encoded5"
    DEC5_DIR  = "data/output/decoded5"
    for d in (ENC5_DIR, DEC5_DIR):
        os.makedirs(d, exist_ok=True)

    SPEED_MIN_KB = 250  # KB/s threshold

    print(f"{'File':<25} {'Orig':>10} {'Comp':>10} {'Ratio':>7} {'Enc KB/s':>10} {'Dec KB/s':>10}  Result")
    print("-" * 93)

    total_orig5 = total_comp5 = 0
    total_enc_t = total_dec_t = 0.0
    all_pass5 = True

    for pgn_path in pgn_files:
        name  = os.path.basename(pgn_path)
        stem  = name.replace(".pgn", "")
        enc1  = os.path.join(ENC5_DIR, stem + ".cpg5")
        dec1  = os.path.join(DEC5_DIR, stem + ".pgn")

        enc_time = 0.0
        dec_time = 0.0

        try:
            t0 = time.perf_counter()
            encode_pgn_file_chess(pgn_path, enc1)
            enc_time = time.perf_counter() - t0

            t0 = time.perf_counter()
            decode_pgn_file_chess(enc1, dec1)
            dec_time = time.perf_counter() - t0
        except Exception as e:
            print(f"{name:<25}  ERROR: {e}")

            orig_size = os.path.getsize(pgn_path)
            orig_kb   = orig_size / 1024
            
            if enc_time > 0:
                print(f"  TIME TO ENCODE: {enc_time:.4f} sec | KB/s: {orig_kb/enc_time:.2f}")
            else:
                print("  Encoding failed before completion.")

            all_pass5 = False
            continue

        orig_size = os.path.getsize(pgn_path)
        comp_size = os.path.getsize(enc1)
        ratio     = orig_size / comp_size if comp_size else 0
        orig_kb   = orig_size / 1024
        enc_kbs   = orig_kb / enc_time if enc_time else 0
        dec_kbs   = orig_kb / dec_time if dec_time else 0

        total_orig5 += orig_size
        total_comp5 += comp_size
        total_enc_t += enc_time
        total_dec_t += dec_time

        # Fidelity: decoded text must match original (trailing whitespace stripped, leading preserved)
        def _norm(lines):
            return [l.rstrip() + '\n' for l in lines]
        with open(pgn_path, encoding='utf-8') as f: orig_lines = _norm(f.readlines())
        with open(dec1,     encoding='utf-8') as f: dec_lines  = _norm(f.readlines())
        diff = list(difflib.unified_diff(orig_lines, dec_lines, fromfile="original", tofile="decoded", n=0))
        fidelity = len(diff) == 0

        slow_enc = enc_kbs < SPEED_MIN_KB
        slow_dec = dec_kbs < SPEED_MIN_KB
        passed = fidelity and not slow_enc and not slow_dec

        if not fidelity:
            all_pass5 = False
            print(f"  FIDELITY FAIL: {len(diff)} lines differ:")
            for line in diff[:6]:
                print(f"    {line}", end="")
        if slow_enc or slow_dec:
            all_pass5 = False
            flags = ("ENC_SLOW " if slow_enc else "") + ("DEC_SLOW" if slow_dec else "")
            print(f"  SPEED FAIL: {flags.strip()}")

        status = "PASS" if passed else "FAIL"
        print(f"{name:<25} {orig_size:>10,} {comp_size:>10,} {ratio:>6.2f}× {enc_kbs:>10.1f} {dec_kbs:>10.1f}  {status}")

    print("-" * 93)
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


# Needed for python multiprocessing
if __name__ == '__main__':
    main()