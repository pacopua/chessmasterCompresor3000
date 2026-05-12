import os
import glob
import re

def main():
    originals = [f for f in glob.glob('SetPartides*.pgn') if 'restored' not in f]
    
    total_orig = 0
    total_comp = 0

    print("=== COMPRESSION RATIO ===")
    for orig in originals:
        comp = orig + ".custom_cpgn"
        if os.path.exists(comp):
            o_size = os.path.getsize(orig)
            c_size = os.path.getsize(comp)
            total_orig += o_size
            total_comp += c_size

    ratio = total_orig / total_comp
    print(f"Total Original Size:   {total_orig} bytes")
    print(f"Total Compressed Size: {total_comp} bytes")
    print(f"Formula: (Sum(Original sizes) / sum(Compressed sizes))")
    print(f"Compression Ratio:     {ratio:.4f}")
    print(f"-> The original files are {ratio:.2f} times larger than the compressed files.\n")

    print("=== FILE COMPARISON ===")
    for orig in originals:
        restored = f"decoded_output/{orig}_custom_restored.pgn"
        if os.path.exists(restored):
            with open(orig, 'r', encoding='utf-8', errors='ignore') as f1, \
                 open(restored, 'r', encoding='utf-8', errors='ignore') as f2:
                
                orig_text = f1.read()
                restored_text = f2.read()
                
                # 1. Strict byte-for-byte check
                if orig_text == restored_text:
                    print(f"[SUCCESS] {orig} is a PERFECT byte-for-byte match.")
                else:
                    # 2. Semantic check (ignore whitespaces, newlines, and carriage returns)
                    # Because our custom encoder/decoder wrapped lines at 75 characters 
                    # and manipulated spaces after move numbers (e.g. "1. e4" vs "1.e4").
                    orig_nospace = re.sub(r'\s+', '', orig_text)
                    rest_nospace = re.sub(r'\s+', '', restored_text)
                    
                    if orig_nospace == rest_nospace:
                        print(f"[WARNING] {orig} data is IDENTICAL, but formatting (whitespaces/newlines) differs.")
                    else:
                        print(f"[ERROR]   {orig} does NOT match! Data was lost or corrupted.")

if __name__ == "__main__":
    main()
