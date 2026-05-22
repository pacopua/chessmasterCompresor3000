"""
Full-game PGN encoder (CPG4 format) — LZW + arithmetic coding variant.

Pipeline:
  headers    : compact bit-level encoding  (src/encode_headers.py)
  moves      : chess-aware tokenization    (src/encode_game.py helpers)
  combined   : LZW dictionary compression  (same as CPG3)
  entropy    : arithmetic coding on the raw LZW integer symbols
               (uses encode_ints / decode_ints for arbitrary alphabets)

Replacing Huffman with arithmetic coding eliminates the ≤1-bit-per-symbol
rounding overhead and gives asymptotically optimal entropy coding.

File layout:
  [4]  magic b'CPG4'
  [4]  uint32 BE  — total bits in the header section
  [4]  uint32 BE  — total LZW symbols
  [4]  uint32 BE  — number of distinct LZW symbol values
  [N]  frequency table: [4] uint32 BE symbol + [4] uint32 BE frequency
  [4]  uint32 BE  — number of valid bits in the arithmetic-coded output
  [M]  arithmetic-coded bytes (zero-padded to byte boundary)
"""

import os
import struct
import bitarray as bitLib
from collections import Counter

from .encode_headers import encode_headers
from .decode_headers import decode_headers
from .encode_game import (
    _split_pgn_games,
    _tokenize_moves,
    _detokenize_moves,
    _lzw_compress,
    _lzw_decompress,
    GAME_SEP,
)
from .arithmetic import encode_ints, decode_ints
from .encode_game import _write_vlq, _read_vlq

MAGIC = b'CPG4'


def encode_pgn_file(input_path: str, output_path: str) -> None:
    with open(input_path, 'r', encoding='utf-8') as f:
        text = f.read()

    games = _split_pgn_games(text)
    print(f"  {len(games)} games")

    # --- Headers (compact bit encoding) ---
    header_bits = bitLib.bitarray()
    for headers, _ in games:
        header_bits.extend(encode_headers(headers))

    # --- Moves (tokenize all games, separated by GAME_SEP) ---
    all_tok = bytearray()
    for i, (_, moves) in enumerate(games):
        all_tok.extend(_tokenize_moves(moves))
        if i < len(games) - 1:
            all_tok.append(GAME_SEP)

    # --- LZW over combined stream ---
    combined = header_bits.tobytes() + bytes(all_tok)
    lzw_syms = _lzw_compress(combined)

    # --- Frequency model on the integer LZW symbols ---
    freqs: dict[int, int] = dict(Counter(lzw_syms))

    # --- Arithmetic encode the LZW integer stream ---
    comp_bytes, n_out_bits = encode_ints(lzw_syms, freqs)

    # --- Write CPG4 file (VLQ-delta frequency table, same as CPG3) ---
    sorted_syms = sorted(freqs)
    with open(output_path, 'wb') as f:
        f.write(MAGIC)
        f.write(struct.pack('>I', len(header_bits)))   # bits in header section
        f.write(struct.pack('>I', len(sorted_syms)))   # distinct symbol count
        f.write(struct.pack('>I', len(lzw_syms)))      # total LZW symbols
        prev = 0
        for sym in sorted_syms:
            f.write(_write_vlq(sym - prev))
            f.write(_write_vlq(freqs[sym]))
            prev = sym
        f.write(struct.pack('>I', n_out_bits))
        f.write(comp_bytes)

    orig  = os.path.getsize(input_path)
    compr = os.path.getsize(output_path)
    print(f"  {orig:,} B → {compr:,} B  (ratio {orig/compr:.2f}×)")


def decode_pgn_file(input_path: str, output_path: str) -> None:
    with open(input_path, 'rb') as f:
        raw = f.read()

    pos = 0
    assert raw[pos:pos+4] == MAGIC, "Not a CPG4 file"
    pos += 4

    n_hdr_bits  = struct.unpack_from('>I', raw, pos)[0]; pos += 4
    n_entries   = struct.unpack_from('>I', raw, pos)[0]; pos += 4
    n_lzw_syms  = struct.unpack_from('>I', raw, pos)[0]; pos += 4

    freqs: dict[int, int] = {}
    prev = 0
    for _ in range(n_entries):
        delta, pos = _read_vlq(raw, pos)
        freq,  pos = _read_vlq(raw, pos)
        sym = prev + delta
        freqs[sym] = freq
        prev = sym

    n_out_bits = struct.unpack_from('>I', raw, pos)[0]; pos += 4
    comp_bytes = raw[pos:]

    # --- Arithmetic decode → LZW integer list ---
    lzw_syms = decode_ints(comp_bytes, n_out_bits, freqs, n_lzw_syms)

    # --- LZW decompress → combined stream ---
    combined = _lzw_decompress(lzw_syms)

    # --- Split: first n_hdr_bytes → headers, rest → tokenized moves ---
    n_hdr_bytes = (n_hdr_bits + 7) // 8
    hdr_ba = bitLib.bitarray()
    hdr_ba.frombytes(combined[:n_hdr_bytes])
    del hdr_ba[n_hdr_bits:]   # trim byte-alignment padding

    game_headers: list[str] = []
    hpos = 0
    while hpos < n_hdr_bits:
        hdr, hpos = decode_headers(hdr_ba, hpos)
        game_headers.append(hdr)

    all_tok    = combined[n_hdr_bytes:]
    chunks     = bytes(all_tok).split(bytes([GAME_SEP]))
    game_moves = [_detokenize_moves(chunk) for chunk in chunks]

    # --- Reconstruct PGN ---
    out_games = [f"{hdr}\n\n{mv}" for hdr, mv in zip(game_headers, game_moves)]
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(out_games))
        f.write('\n')   # preserve trailing newline of the original file
