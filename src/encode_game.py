"""
Full-game PGN encoder (CPG3 format).

Header section : compact bit-level encoding (src/encode_headers.py)
Moves section  : chess-aware tokenization + LZW + Huffman
                 (approach from old_vibecoded/smart_chess_codec.py)

File layout:
  [4]  magic b'CPG3'
  [4]  uint32 BE  — total bits in the header section
  [N]  header bitarray (zero-padded to byte boundary)
  [4]  uint32 BE  — number of Huffman symbol table entries
  [4]  uint32 BE  — total number of LZW symbols (needed for single-symbol edge case)
  [V]  VLQ (delta, freq) pairs  — Huffman symbol table
  [1]  uint8  — padding bits at the end of the move data
  [M]  LZW + Huffman compressed tokenized moves
"""

import os
import re
import struct
import heapq
from collections import Counter
import bitarray as bitLib

from .encode_headers import encode_headers
from .decode_headers import decode_headers

MAGIC    = b'CPG3'
GAME_SEP = 0xFF   # separates games inside the tokenized move stream

# Single-byte move tokens
TOK_RESULT_DRAW  = 0xFA   # 1/2-1/2
TOK_RESULT_WHITE = 0xFB   # 1-0
TOK_RESULT_BLACK = 0xFC   # 0-1
TOK_RESULT_NONE  = 0xF9   # *
TOK_MOVE_FIRST   = 0xFD   # 1.
TOK_MOVE_NEXT    = 0xFE   # 2., 3., 4., …  (decoder increments a counter)
# Board squares: 0x80–0xBF  (file * 8 + rank,  a1=0x80 … h8=0xBF)


# ── VLQ helpers (LEB128) ────────────────────────────────────────────────────

def _write_vlq(val: int) -> bytes:
    res = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            res.append(b | 0x80)
        else:
            res.append(b)
            break
    return bytes(res)


def _read_vlq(data: bytes, pos: int) -> tuple[int, int]:
    res, shift = 0, 0
    while True:
        b = data[pos]; pos += 1
        res |= (b & 0x7F) << shift
        if not (b & 0x80):
            return res, pos
        shift += 7


# ── PGN splitting ────────────────────────────────────────────────────────────

def _split_pgn_games(text: str) -> list[tuple[str, str]]:
    """Return a list of (headers_text, moves_text) for every game."""
    games: list[tuple[str, str]] = []
    headers: list[str] = []
    moves:   list[str] = []
    in_moves = False

    for line in text.splitlines():
        s = line.strip()
        if s.startswith('['):
            if in_moves:
                games.append(('\n'.join(headers), '\n'.join(moves)))
                headers, moves = [], []
                in_moves = False
            headers.append(line)
        elif not s:
            if headers and not in_moves:
                in_moves = True   # blank line after header block → moves follow
        elif in_moves:
            moves.append(line)

    if headers:
        games.append(('\n'.join(headers), '\n'.join(moves)))

    return games


# ── Move tokenization ────────────────────────────────────────────────────────

_SQ_RE = re.compile(rb'([a-h][1-8])')
_MN_RE = re.compile(rb'\b(\d+)\.')


def _tokenize_moves(moves_text: str) -> bytes:
    """
    Replace predictable patterns with single-byte tokens:
      results     → TOK_RESULT_*
      squares     → 0x80–0xBF
      move numbers → TOK_MOVE_FIRST / TOK_MOVE_NEXT  (sequential prediction)
    """
    data = moves_text.encode('latin-1')

    # Results — longest string first to avoid partial matches
    data = data.replace(b'1/2-1/2', bytes([TOK_RESULT_DRAW]))
    data = data.replace(b'1-0',     bytes([TOK_RESULT_WHITE]))
    data = data.replace(b'0-1',     bytes([TOK_RESULT_BLACK]))
    data = data.replace(b'*',       bytes([TOK_RESULT_NONE]))

    # Board squares
    def _sq(m):
        f = m.group(1)[0] - ord('a')
        r = m.group(1)[1] - ord('1')
        return bytes([0x80 + f * 8 + r])
    data = _SQ_RE.sub(_sq, data)

    # Sequential move numbers
    expected = [1]
    def _mn(m):
        num = int(m.group(1))
        if num == expected[0]:
            expected[0] += 1
            return bytes([TOK_MOVE_FIRST if num == 1 else TOK_MOVE_NEXT])
        return m.group(0)   # sequence broken — keep literal
    data = _MN_RE.sub(_mn, data)

    return data


def _detokenize_moves(data: bytes) -> str:
    """Reverse of _tokenize_moves. Resets move counter for each call (one game)."""
    out      = bytearray()
    move_num = 1

    for b in data:
        if 0x80 <= b <= 0xBF:
            f, r = (b - 0x80) // 8, (b - 0x80) % 8
            out.extend(bytes([ord('a') + f, ord('1') + r]))
        elif b == TOK_MOVE_FIRST:
            out.extend(b'1.')
            move_num = 2
        elif b == TOK_MOVE_NEXT:
            out.extend(str(move_num).encode() + b'.')
            move_num += 1
        elif b == TOK_RESULT_WHITE:  out.extend(b'1-0')
        elif b == TOK_RESULT_BLACK:  out.extend(b'0-1')
        elif b == TOK_RESULT_DRAW:   out.extend(b'1/2-1/2')
        elif b == TOK_RESULT_NONE:   out.extend(b'*')
        else:
            out.append(b)

    return out.decode('latin-1')


# ── Huffman ──────────────────────────────────────────────────────────────────

class _Node:
    __slots__ = ('char', 'freq', 'left', 'right')
    def __init__(self, char, freq):
        self.char, self.freq = char, freq
        self.left = self.right = None
    def __lt__(self, other):
        return self.freq < other.freq


def _build_tree(freqs: dict) -> _Node:
    heap = [_Node(c, f) for c, f in sorted(freqs.items())]
    heapq.heapify(heap)
    while len(heap) > 1:
        l, r = heapq.heappop(heap), heapq.heappop(heap)
        node = _Node(None, l.freq + r.freq)
        node.left, node.right = l, r
        heapq.heappush(heap, node)
    return heap[0]


def _get_codes(node: _Node, prefix: str = '', codes: dict | None = None) -> dict:
    if codes is None:
        codes = {}
    if node.char is not None:
        codes[node.char] = prefix or '0'
    else:
        _get_codes(node.left,  prefix + '0', codes)
        _get_codes(node.right, prefix + '1', codes)
    return codes


def _huffman_encode(symbols: list, codes: dict) -> tuple[bytes, int]:
    bits, cur, cnt = bytearray(), 0, 0
    for sym in symbols:
        for bit in codes[sym]:
            cur = (cur << 1) | int(bit)
            cnt += 1
            if cnt == 8:
                bits.append(cur)
                cur, cnt = 0, 0
    padding = 0
    if cnt:
        padding = 8 - cnt
        bits.append(cur << padding)
    return bytes(bits), padding


def _huffman_decode(data: bytes, padding: int, tree: _Node, total: int) -> list:
    # Edge case: only one unique symbol
    if tree.left is None and tree.right is None:
        return [tree.char] * total

    result, node = [], tree
    all_bits = ''.join(bin(b)[2:].zfill(8) for b in data)
    if padding:
        all_bits = all_bits[:-padding]
    for bit in all_bits:
        node = node.left if bit == '0' else node.right
        if node.char is not None:
            result.append(node.char)
            node = tree
    return result


# ── LZW ─────────────────────────────────────────────────────────────────────

def _lzw_compress(data: bytes) -> list:
    d    = {bytes([i]): i for i in range(256)}
    size = 256
    w, out = b'', []
    for byte in data:
        c  = bytes([byte])
        wc = w + c
        if wc in d:
            w = wc
        else:
            out.append(d[w])
            if size < 65535:
                d[wc] = size
                size += 1
            w = c
    if w:
        out.append(d[w])
    return out


def _lzw_decompress(symbols: list) -> bytes:
    d    = {i: bytes([i]) for i in range(256)}
    size = 256
    if not symbols:
        return b''
    w   = d[symbols[0]]
    out = bytearray(w)
    for k in symbols[1:]:
        entry = d[k] if k in d else w + bytes([w[0]])
        out.extend(entry)
        if size < 65535:
            d[size] = w + bytes([entry[0]])
            size += 1
        w = entry
    return bytes(out)


# ── Public API ───────────────────────────────────────────────────────────────

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

    # --- LZW + Huffman on headers + moves combined ---
    # Header bytes come first; n_bits stored in the file lets the decoder split them back.
    combined = header_bits.tobytes() + bytes(all_tok)
    lzw_syms = _lzw_compress(combined)
    freqs    = Counter(lzw_syms)
    tree     = _build_tree(freqs)
    codes    = _get_codes(tree)
    comp_bytes, padding = _huffman_encode(lzw_syms, codes)

    # --- Write ---
    sorted_syms = sorted(freqs)
    with open(output_path, 'wb') as f:
        f.write(MAGIC)

        f.write(struct.pack('>I', len(header_bits)))   # bits, not bytes — lets decoder trim padding

        f.write(struct.pack('>I', len(sorted_syms)))
        f.write(struct.pack('>I', len(lzw_syms)))
        prev = 0
        for sym in sorted_syms:
            f.write(_write_vlq(sym - prev))
            f.write(_write_vlq(freqs[sym]))
            prev = sym

        f.write(struct.pack('>B', padding))
        f.write(comp_bytes)

    orig  = os.path.getsize(input_path)
    compr = os.path.getsize(output_path)
    print(f"  {orig:,} B → {compr:,} B  (ratio {orig/compr:.2f}×)")


def decode_pgn_file(input_path: str, output_path: str) -> None:
    with open(input_path, 'rb') as f:
        raw = f.read()

    pos = 0
    assert raw[pos:pos+4] == MAGIC, "Not a CPG3 file"
    pos += 4

    n_bits    = struct.unpack_from('>I', raw, pos)[0]; pos += 4
    n_hdr_bytes = (n_bits + 7) // 8

    # --- Huffman table ---
    n_entries  = struct.unpack_from('>I', raw, pos)[0]; pos += 4
    total_syms = struct.unpack_from('>I', raw, pos)[0]; pos += 4
    freqs: dict = {}
    prev = 0
    for _ in range(n_entries):
        delta, pos = _read_vlq(raw, pos)
        freq,  pos = _read_vlq(raw, pos)
        sym = prev + delta
        freqs[sym] = freq
        prev = sym

    tree = _build_tree(freqs)

    # --- Decompress combined stream ---
    padding  = raw[pos]; pos += 1
    lzw_syms = _huffman_decode(raw[pos:], padding, tree, total_syms)
    combined = _lzw_decompress(lzw_syms)

    # --- Split: first n_hdr_bytes → headers, rest → tokenized moves ---
    hdr_ba = bitLib.bitarray()
    hdr_ba.frombytes(combined[:n_hdr_bytes])
    del hdr_ba[n_bits:]   # trim byte-alignment padding

    game_headers: list[str] = []
    hpos = 0
    while hpos < n_bits:
        hdr, hpos = decode_headers(hdr_ba, hpos)
        game_headers.append(hdr)

    all_tok    = combined[n_hdr_bytes:]
    chunks     = bytes(all_tok).split(bytes([GAME_SEP]))
    game_moves = [_detokenize_moves(chunk) for chunk in chunks]

    # --- Reconstruct PGN ---
    out_games = [f"{hdr}\n\n{mv}" for hdr, mv in zip(game_headers, game_moves)]
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(out_games))
