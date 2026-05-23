import os
import glob
import sys

originals = glob.glob("Matches/*.pgn")

print("=== FOUND ORIGINAL FILES ===")
for o in originals:
    print("  ", o)
print()

total_orig = 0
total_comp = 0

print("=== SMART CHESS COMPRESSION RATIO ===")

for orig in originals:

    base = os.path.basename(orig)

    comp = os.path.join(
        "Encoded",
        base + ".scpgn"
    )

    print(f"[CHECK] {base}")
    print(f"        looking for compressed: {comp}")

    if not os.path.exists(comp):
        print("        -> MISSING COMPRESSED FILE ❌\n")
        continue

    print("        -> compressed file found ✔")

    o_size = os.path.getsize(orig)
    c_size = os.path.getsize(comp)

    total_orig += o_size
    total_comp += c_size

    ratio = o_size / c_size

    print(f"        original size   : {o_size}")
    print(f"        compressed size  : {c_size}")
    print(f"        ratio            : {ratio:.4f}\n")

if total_comp == 0:
    print("ERROR: No compressed files found.")
    sys.exit(1)

ratio = total_orig / total_comp

print("=== TOTAL ===")
print(f"Total Original Size:   {total_orig} bytes")
print(f"Total Compressed Size: {total_comp} bytes")
print(f"Compression Ratio:     {ratio:.4f}")
print(f"-> Originals are {ratio:.2f}x larger\n")

print("=== DATA INTEGRITY CHECK ===")

all_match = True

for orig in originals:

    base = os.path.basename(orig)

    restored = os.path.join(
        "Decoded",
        base.replace(".pgn", "_smart_restored.pgn")
    )

    print(f"[COMPARE] {base}")
    print(f"          original : {orig}")
    print(f"          restored : {restored}")

    if not os.path.exists(restored):
        print("          -> MISSING RESTORED FILE ❌\n")
        all_match = False
        continue

    print("          -> restored file found ✔")
    print("          comparing bytes...")

    with open(orig, 'rb') as f1, open(restored, 'rb') as f2:

        orig_data = f1.read()
        restored_data = f2.read()

        if orig_data == restored_data:
            print("          RESULT: MATCH ✔\n")
        else:
            print("          RESULT: DIFFER ❌")
            print(f"          original size : {len(orig_data)}")
            print(f"          restored size : {len(restored_data)}\n")
            all_match = False

if all_match:
    print("\nSUCCESS: All files restored byte-for-byte!")
else:
    print("\nSome files failed verification.")