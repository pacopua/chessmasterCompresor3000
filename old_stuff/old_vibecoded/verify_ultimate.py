import os
import glob

originals = [f for f in glob.glob('SetPartides*.pgn') if 'restored' not in f and not f.endswith('cpgn')]

total_orig = 0
total_comp = 0

print("=== ULTIMATE COMPRESSION RATIO (Binary Headers + Castling/Tokens) ===")
for orig in originals:
    comp = orig + ".ucpgn"
    if os.path.exists(comp):
        o_size = os.path.getsize(orig)
        c_size = os.path.getsize(comp)
        total_orig += o_size
        total_comp += c_size

ratio = total_orig / total_comp
print(f"Total Original Size:   {total_orig} bytes")
print(f"Total Compressed Size: {total_comp} bytes")
print(f"Compression Ratio:     {ratio:.4f}")
print(f"-> The original files are {ratio:.2f} times larger than the compressed files.\n")

print("=== DATA INTEGRITY COMPARISON (BYTE FOR BYTE) ===")
all_match = True
for orig in originals:
    restored = f"{orig}_ultimate_restored.pgn"
    if os.path.exists(restored):
        with open(orig, 'rb') as f1, open(restored, 'rb') as f2:
            if f1.read() == f2.read():
                print(f"[SUCCESS] {orig} matches exactly byte-for-byte!")
            else:
                print(f"[ERROR] {orig} failed match.")
                all_match = False

if all_match:
    print("\nSUCCESS: 100% Lossless recovery with binary header packing!")
