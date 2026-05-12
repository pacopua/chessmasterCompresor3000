import os
import lzma
import glob
import sys
import re

def optimize_pgn_text(text):
    """
    Performs PGN-specific text optimizations before compression:
    1. Removes redundant Lichess URL base in Site.
    2. Condenses multiple spaces and newlines in move lists.
    """
    # Replace Lichess URL with just the ID
    text = text.replace('https://lichess.org/', 'LICHESS:')
    
    # Remove extra spaces in move numbers (e.g., "1. e4" -> "1.e4")
    text = re.sub(r'(\d+)\.\s+', r'\1.', text)
    
    return text

def restore_pgn_text(text):
    """
    Restores the optimized text back to standard PGN format.
    """
    # Restore Lichess URL
    text = text.replace('LICHESS:', 'https://lichess.org/')
    
    # Restore spaces after move numbers
    text = re.sub(r'(\d+)\.', r'\1. ', text)
    
    return text

def encode_pgn(input_file, output_file):
    print(f"Encoding {input_file} -> {output_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    optimized_content = optimize_pgn_text(content)
    
    # Compress using LZMA (extremely efficient for repetitive text like PGNs)
    with lzma.open(output_file, 'wt', encoding='utf-8') as f:
        f.write(optimized_content)
        
    orig_size = os.path.getsize(input_file)
    new_size = os.path.getsize(output_file)
    print(f"  Size reduced from {orig_size/1024:.2f} KB to {new_size/1024:.2f} KB ({(1 - new_size/orig_size)*100:.1f}%)")

def decode_pgn(input_file, output_file):
    print(f"Decoding {input_file} -> {output_file}")
    with lzma.open(input_file, 'rt', encoding='utf-8') as f:
        optimized_content = f.read()
        
    restored_content = restore_pgn_text(optimized_content)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(restored_content)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pgn_codec.py [encode|decode] [file_pattern]")
        sys.exit(1)
        
    action = sys.argv[1]
    
    if action == "encode":
        pattern = sys.argv[2] if len(sys.argv) > 2 else "*.pgn"
        for file in glob.glob(pattern):
            encode_pgn(file, file + ".cpgn")
            
    elif action == "decode":
        pattern = sys.argv[2] if len(sys.argv) > 2 else "*.cpgn"
        for file in glob.glob(pattern):
            out_file = file.replace(".cpgn", "_restored.pgn")
            decode_pgn(file, out_file)
    else:
        print("Invalid action. Use 'encode' or 'decode'.")
