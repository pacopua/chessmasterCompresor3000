#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.encode_game_chess import encode_pgn_file_chess, decode_pgn_file_chess

MAGIC = b'CPG5'

def detect_mode(infile: str) -> str:
    with open(infile, 'rb') as f:
        header = f.read(4)
    return 'decode' if header == MAGIC else 'encode'

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {os.path.basename(sys.argv[0])} <infile> <outfile>", file=sys.stderr)
        sys.exit(1)

    infile, outfile = sys.argv[1], sys.argv[2]

    if not os.path.isfile(infile):
        print(f"Error: '{infile}' not found", file=sys.stderr)
        sys.exit(1)

    mode = detect_mode(infile)
    if mode == 'decode':
        print(f"Decoding '{infile}' → '{outfile}'")
        decode_pgn_file_chess(infile, outfile)
    else:
        print(f"Encoding '{infile}' → '{outfile}'")
        encode_pgn_file_chess(infile, outfile)

if __name__ == '__main__':
    main()
