"""
CPG5 encoder/decoder — chess-aware move index encoding.

File layout:
  [4]   b'CPG5'
  [4]   uint32 BE — header bit count
  [N]   header bytes (raw, zero-padded)
  [4]   uint32 BE — game count
  For each game:
    [4]   uint32 BE — move block byte length (L)
    [L]   move block:
            [2] uint16 BE — ply count
            [1] uint8     — result (0=1-0, 1=0-1, 2=1/2-1/2, 3=*)
            [B] bit-packed plies: ceil(log2(N_legal)) index bits + 1 has_annot bit, zero-padded
            [A] annotation bytes for annotated plies in order (TOK_ANNOT_* + 0x00 per ply)
"""

import os, re, struct, math
import chess
import bitarray as bitLib
import numpy as np
import concurrent.futures
import multiprocessing

from .encode_headers import encode_headers
from .decode_headers import decode_headers

MAGIC = b'CPG5'

TOK_ANNOT_EVAL = 0x01
TOK_ANNOT_MATE = 0x02
TOK_ANNOT_CLK  = 0x03
TOK_ANNOT_RAW  = 0x04

_ANNOT_RE = re.compile(rb'\{([^}]*)\}')
_EVAL_RE  = re.compile(rb'\[%eval\s+(#-?\d+|-?\d+(?:\.\d+)?)\]')
_CLK_RE   = re.compile(rb'\[%clk\s+(\d+):(\d{2}):(\d{2})\]')

_RESULT_ENC = {'1-0': 0, '0-1': 1, '1/2-1/2': 2, '*': 3}
_RESULT_DEC = {0: '1-0', 1: '0-1', 2: '1/2-1/2', 3: '*'}


def _split_pgn_games(text: str) -> list[tuple[str, str]]:
    games, headers, moves, in_moves = [], [], [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('['):
            if in_moves:
                games.append(('\n'.join(headers), '\n'.join(moves)))
                headers, moves, in_moves = [], [], False
            headers.append(line)
        elif not s:
            if headers and not in_moves:
                in_moves = True
        elif in_moves:
            moves.append(line)
    if headers:
        games.append(('\n'.join(headers), '\n'.join(moves)))
    return games


def _encode_annot_bytes(content: bytes) -> bytes:
    """Encode one {…} block's inner content → TOK_ANNOT_* bytes + 0x00 terminator."""
    eval_m = _EVAL_RE.search(content)
    clk_m  = _CLK_RE.search(content)
    leftover = _EVAL_RE.sub(b'', _CLK_RE.sub(b'', content)).strip()

    out = bytearray()
    if leftover or (not eval_m and not clk_m):
        raw = b'{' + content + b'}'
        n = min(len(raw), 255)
        out += bytes([TOK_ANNOT_RAW, n]) + raw[:n]
    else:
        if eval_m:
            val = eval_m.group(1)
            if val.startswith(b'#'):
                n = max(-128, min(127, int(val[1:])))
                out += bytes([TOK_ANNOT_MATE]) + struct.pack('>b', n)
            else:
                cp = max(-32767, min(32767, round(float(val) * 100)))
                out += bytes([TOK_ANNOT_EVAL]) + struct.pack('>h', cp)
        if clk_m:
            h  = int(clk_m.group(1))
            mm = int(clk_m.group(2))
            ss = int(clk_m.group(3))
            h_capped = min(h, 15)
            packed = (h_capped << 12) | (mm << 6) | ss
            out += bytes([TOK_ANNOT_CLK]) + struct.pack('>H', packed)
    out += b'\x00'
    return bytes(out)



def _encode_game(moves_text: str) -> bytes:
    """Encode one game's move text → move block bytes."""
    # initialize the board to emulate
    board = chess.Board()
    raw   = moves_text.encode('latin-1')

    # the games may include annotiation blocks like
    #{annotation}; replace each with DEL (0x7F) as a placeholder
    annot_queue: list[bytes] = []
    def _pull(m: re.Match) -> bytes:
        annot_queue.append(m.group(1))
        return b' \x7f '
    raw = _ANNOT_RE.sub(_pull, raw)

    result_code = 3  # default: *
    # plies: list of [chess.Move, annot_bytes_or_None]
    plies: list[list] = []
    annot_idx = 0

    for tok in raw.split():
        tok_s = tok.decode('latin-1', errors='replace')

        # Any text in the following categories is ignored for move parsing and not included in the bit-packed data, since it doesn't affect the board state:
        if tok == b'\x7f':                           # annotation placeholder
            if plies:
                plies[-1][1] = _encode_annot_bytes(annot_queue[annot_idx])
            annot_idx += 1
            continue

        if tok_s in _RESULT_ENC:                     # result token
            result_code = _RESULT_ENC[tok_s]
            continue

        if tok_s.replace('.', '').isdigit():         # move number (1. or 1...)
            continue

        if tok_s.startswith('$'):                    # NAG token ($1, $2, ...)
            continue

        if tok_s in ('(', ')'):                      # variation delimiters
            continue

        if set(tok_s) <= set('!?') and tok_s:        # standalone NAG symbol
            continue

        # SAN move — strip NAG suffixes before parsing
        clean = tok_s.rstrip('!?')
        move = board.parse_san(clean)
        board.push(move)
        plies.append([move, None])

    ply_count = len(plies)

    # Build bit stream
    board2 = chess.Board()
    m_bytes = bytearray()
    for move, annot in plies:
        # given the current state of the board, what moves are legal?
        legal = list(board2.legal_moves)
        n     = len(legal)
        idx   = next(i for i, m in enumerate(legal) if m == move)
        # Tots els moves els allarguem a simbols de 8 bits
        
        m_bytes.append(idx)
        if annot:
            m_bytes.append(254)
        board2.push(move)

    #pad = (8 - len(bits) % 8) % 8 Ya no es necessari ja que ja ho fem que tanqui en un multiple de 8
    #bits.extend('0' * pad)


    annot_blob = b''.join(a for _, a in plies if a)

    
    return (
        struct.pack('>H', ply_count)+
        struct.pack('>B', result_code)+
        m_bytes+
        annot_blob
    )

def _safe_encode_game_worker(args: tuple[int, str]) -> tuple[int, bytes, str]:
    """Top-level worker function required for multiprocessing serialization."""
    idx, moves_text = args
    try:
        return idx, _encode_game(moves_text), None
    except Exception as e:
        return idx, struct.pack('>HB', 0, 3), str(e)




import heapq
from collections import Counter
from bitarray import bitarray


class Node:
    def __init__(self, sym=None, freq=0, left=None, right=None):
        self.sym = sym
        self.freq = freq
        self.left = left
        self.right = right

    def __lt__(self, other):
        return self.freq < other.freq

def build_tree(data: bytearray):
    freq = Counter(data)
    heap = [Node(sym=s, freq=f) for s, f in freq.items()]
    heapq.heapify(heap)

    if len(heap) == 1:
        return heap[0]

    while len(heap) > 1:
        a = heapq.heappop(heap)
        b = heapq.heappop(heap)
        merged = Node(freq=a.freq + b.freq, left=a, right=b)
        heapq.heappush(heap, merged)

    return heap[0]


def build_codes(node, prefix="", table=None):
    if table is None:
        table = {}

    if node.sym is not None:
        table[node.sym] = prefix or "0"
        return table

    build_codes(node.left, prefix + "0", table)
    build_codes(node.right, prefix + "1", table)

    return table



def huffman_compress(data: bytearray):
    tree = build_tree(data)
    codes = build_codes(tree)

    b = bitarray()
    b.extend(''.join(codes[x] for x in data))

    return b, tree

def serialize_tree(root):
    out = bytearray()

    i = 0
    def dfs(node):
        nonlocal i
        if node.left is None and node.right is None:
            out.append(1)
            out.append(node.sym) 
            i += 2
        else:
            out.append(0)
            i += 1
            dfs(node.left)
            dfs(node.right)

    dfs(root)
    return bytes(out), i




def encode_pgn_file_chess(input_path: str, output_path: str) -> None:
    with open(input_path, 'r', encoding='utf-8') as f:
        text = f.read()

    games = _split_pgn_games(text)

    # Sequentially encode headers
    header_bits = bitLib.bitarray()
    name_dict:  dict[str, int] = {}
    prev_days:  int | None = None
    prev_secs:  int | None = None
    for hdr, _ in games:
        game_bits, prev_days, prev_secs = encode_headers(hdr, name_dict, prev_days, prev_secs)
        header_bits.extend(game_bits)

    # Parallelize Move Encoding
    # Map the text blocks to our worker across all available CPU cores.
    game_args = [(i, mv) for i, (_, mv) in enumerate(games)]
    move_blocks = [b''] * len(games)
    
    cores = max(1, multiprocessing.cpu_count() - 1) # Leave 1 core for OS stability
    with concurrent.futures.ProcessPoolExecutor(max_workers=cores) as executor:
        results = executor.map(_safe_encode_game_worker, game_args, chunksize=100)
        
        for idx, block, error in results:
            if error:
                print(f"  WARNING encoding game {idx+1}: {error}")
            move_blocks[idx] = block

    # Pre-allocate bytearray for faster batched writing
    out_buffer = bytearray()
    out_buffer.extend(MAGIC)
    out_buffer.extend(struct.pack('>I', len(header_bits)))
    out_buffer.extend(header_bits.tobytes())
    out_buffer.extend(struct.pack('>I', len(games)))

    
    all_blocks = bytearray()
    for g in move_blocks:
        all_blocks.extend(struct.pack('>I', len(g)))
        all_blocks.extend(g)

    games_huffman, tree = huffman_compress(all_blocks)
    tree_serialized, i = serialize_tree(tree)

    out_buffer.extend(struct.pack('>I', i))
    out_buffer.extend(tree_serialized)
    out_buffer.extend(games_huffman.tobytes())

    with open(output_path, 'wb') as f:
        f.write(out_buffer)

    orig  = os.path.getsize(input_path)
    compr = os.path.getsize(output_path)
    print(f"  {orig:,} B → {compr:,} B  (ratio {orig/compr:.2f}×)")


def _decode_annot_bytes(data: bytes, pos: int) -> tuple[str, int]:
    """Read TOK_ANNOT_* tokens until 0x00; return annotation string and new pos."""
    parts = []
    while pos < len(data):
        b = data[pos]
        if b == 0x00:
            pos += 1
            break
        elif b == TOK_ANNOT_EVAL:
            cp  = struct.unpack('>h', data[pos+1:pos+3])[0]
            val = f'{cp/100:.1f}' if cp % 10 == 0 else f'{cp/100:.2f}'
            parts.append(f'[%eval {val}]')
            pos += 3
        elif b == TOK_ANNOT_MATE:
            n = struct.unpack('>b', data[pos+1:pos+2])[0]
            parts.append(f'[%eval #{n}]')
            pos += 2
        elif b == TOK_ANNOT_CLK:
            v  = struct.unpack('>H', data[pos+1:pos+3])[0]
            h, mm, ss = (v >> 12) & 0xF, (v >> 6) & 0x3F, v & 0x3F
            parts.append(f'[%clk {h}:{mm:02d}:{ss:02d}]')
            pos += 3
        elif b == TOK_ANNOT_RAW:
            n = data[pos+1]
            parts.append(data[pos+2:pos+2+n].decode('latin-1'))
            pos += 2 + n
        else:
            break
    if len(parts) == 1 and parts[0].startswith('{'):
        return parts[0], pos   # already a fully-formed {…} string
    return '{ ' + ' '.join(parts) + ' }', pos


def _decode_game(block: bytes) -> str:
    """Decode one move block → moves text string."""
    pos         = 0
    ply_count   = struct.unpack_from('>H', block, pos)[0]; pos += 2
    result_code = struct.unpack_from('>B', block, pos)[0]; pos += 1

    board = chess.Board()
    ply_info: list[tuple[chess.Move, bool]] = []

    for _ in range(ply_count):
        legal = list(board.legal_moves)
        idx = block[pos]; pos += 1
        has_annot = pos < len(block) and block[pos] == 254
        if has_annot:
            pos += 1
        move = legal[idx]
        board.push(move)
        ply_info.append((move, has_annot))

    # Read annotation bytes in ply order
    annots: list[str] = []
    for _, has_annot in ply_info:
        if has_annot:
            s, pos = _decode_annot_bytes(block, pos)
            annots.append(s)

    # Reconstruct move text
    board2   = chess.Board()
    annot_it = iter(annots)
    parts: list[str] = []
    prev_had_annot = False
    for ply_num, (move, has_annot) in enumerate(ply_info):
        full_move = ply_num // 2 + 1
        if ply_num % 2 == 0:
            parts.append(f'{full_move}.')
        elif prev_had_annot:
            parts.append(f'{full_move}...')
        san = board2.san(move)
        board2.push(move)
        parts.append(san)
        if has_annot:
            parts.append(next(annot_it))
        prev_had_annot = has_annot

    parts.append(_RESULT_DEC[result_code])
    return ' '.join(parts)

def _safe_decode_game_worker(args: tuple[int, bytes]) -> tuple[int, str, str]:
    """Top-level worker for safe multiprocessing of game decoding."""
    idx, block = args
    try:
        return idx, _decode_game(block), None
    except Exception as e:
        return idx, "", str(e)

def deserialize_tree(data):
    i = 0

    def dfs():
        nonlocal i
        flag = data[i]
        i += 1
        if flag == 1:
            byte = data[i]
            i += 1
            
            return Node(sym=byte)
        else:
            left = dfs()
            right = dfs()
            return Node(left=left, right=right)

    return dfs(), i

def huffman_decompress(bits: bitarray, tree):
    out = bytearray()
    node = tree

    for bit in bits:
        node = node.left if bit == 0 else node.right

        if node.sym is not None:
            out.append(node.sym)
            node = tree

    return out

def decode_pgn_file_chess(input_path: str, output_path: str) -> None:
    with open(input_path, 'rb') as f:
        raw = f.read()

    pos = 0
    assert raw[pos:pos+4] == MAGIC, "Not a CPG5 file"
    pos += 4

    n_bits      = struct.unpack_from('>I', raw, pos)[0]; pos += 4
    n_hdr_bytes = (n_bits + 7) // 8
    hdr_ba = bitLib.bitarray()
    hdr_ba.frombytes(raw[pos:pos+n_hdr_bytes]); pos += n_hdr_bytes
    del hdr_ba[n_bits:]

    # 1. Decode Headers Sequentially
    game_headers: list[str] = []
    hpos = 0
    name_list:  list[str] = []
    prev_days:  int | None = None
    prev_secs:  int | None = None
    while hpos < n_bits:
        hdr, hpos, prev_days, prev_secs = decode_headers(hdr_ba, hpos, name_list, prev_days, prev_secs)
        game_headers.append(hdr)

    n_games = struct.unpack_from('>I', raw, pos)[0]; pos += 4

    #2. Decompressing of game data before block extraction
    length_tree = struct.unpack_from('>I', raw, pos)[0]
    pos += 4
    
    
    tree,_ = deserialize_tree(raw[pos:pos+length_tree])
    
    pos += length_tree

    huffman_comp = bitarray()
    huffman_comp.frombytes(raw[pos:])
    huffman_decomp = huffman_decompress(huffman_comp, tree)

    # 3. Fast Sequential Block Extraction from decompressed data
    game_blocks: list[bytes] = []
    dpos = 0
    for _ in range(n_games):
        block_len = struct.unpack_from('>I', huffman_decomp, dpos)[0]; dpos += 4
        game_blocks.append(bytes(huffman_decomp[dpos:dpos+block_len]))
        dpos += block_len

    # 4. Parallel Decoding of Chess Logic
    game_moves: list[str] = [""] * n_games
    decode_args = [(i, block) for i, block in enumerate(game_blocks)]

    cores = max(1, multiprocessing.cpu_count() - 1)
    with concurrent.futures.ProcessPoolExecutor(max_workers=cores) as executor:
        # Use chunking to reduce IPC overhead
        results = executor.map(_safe_decode_game_worker, decode_args, chunksize=100)

        for idx, moves_text, error in results:
            if error:
                print(f"  WARNING decoding game {idx+1}: {error}")
            game_moves[idx] = moves_text

    # 4. Batched Reassembly and Writing
    out = [f"{h}\n\n{m}" for h, m in zip(game_headers, game_moves)]
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(out))
        f.write('\n')
