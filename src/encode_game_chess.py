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
    board = chess.Board()
    raw   = moves_text.encode('latin-1')

    # Extract {annotation} blocks; replace each with DEL (0x7F) placeholder
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
    bits   = bitLib.bitarray()
    for move, annot in plies:
        legal = list(board2.legal_moves)
        n     = len(legal)
        idx   = next(i for i, m in enumerate(legal) if m == move)
        width = math.ceil(math.log2(n)) if n > 1 else 0
        if width:
            bits.extend(format(idx, f'0{width}b'))
        bits.append(1 if annot else 0)
        board2.push(move)

    pad = (8 - len(bits) % 8) % 8
    bits.extend('0' * pad)

    annot_blob = b''.join(a for _, a in plies if a)

    return (
        struct.pack('>H', ply_count) +
        struct.pack('>B', result_code) +
        bits.tobytes() +
        annot_blob
    )


def encode_pgn_file_chess(input_path: str, output_path: str) -> None:
    with open(input_path, 'r', encoding='utf-8') as f:
        text = f.read()

    games = _split_pgn_games(text)
    print(f"  {len(games)} games")

    header_bits = bitLib.bitarray()
    for hdr, _ in games:
        header_bits.extend(encode_headers(hdr))

    move_blocks: list[bytes] = []
    for i, (_, mv) in enumerate(games):
        try:
            move_blocks.append(_encode_game(mv))
        except Exception as e:
            print(f"  WARNING game {i+1}: {e}")
            move_blocks.append(struct.pack('>HB', 0, 3))

    with open(output_path, 'wb') as f:
        f.write(MAGIC)
        f.write(struct.pack('>I', len(header_bits)))
        f.write(header_bits.tobytes())
        f.write(struct.pack('>I', len(games)))
        for block in move_blocks:
            f.write(struct.pack('>I', len(block)))
            f.write(block)

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
    bits  = bitLib.bitarray()
    bits.frombytes(block[pos:])
    bit_pos = 0

    ply_info: list[tuple[chess.Move, bool]] = []

    for _ in range(ply_count):
        legal = list(board.legal_moves)
        n     = len(legal)
        width = math.ceil(math.log2(n)) if n > 1 else 0
        if width:
            idx = int(bits[bit_pos:bit_pos+width].to01(), 2)
            bit_pos += width
        else:
            idx = 0
        has_annot = bool(bits[bit_pos])
        bit_pos  += 1
        move = legal[idx]
        board.push(move)
        ply_info.append((move, has_annot))

    # Advance pos past the bit-packed bytes (rounded up to byte boundary)
    pos += (bit_pos + 7) // 8

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

    game_headers: list[str] = []
    hpos = 0
    while hpos < n_bits:
        hdr, hpos = decode_headers(hdr_ba, hpos)
        game_headers.append(hdr)

    n_games = struct.unpack_from('>I', raw, pos)[0]; pos += 4

    game_moves: list[str] = []
    for _ in range(n_games):
        block_len = struct.unpack_from('>I', raw, pos)[0]; pos += 4
        game_moves.append(_decode_game(raw[pos:pos+block_len]))
        pos += block_len

    out = [f"{h}\n\n{m}" for h, m in zip(game_headers, game_moves)]
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(out))
        f.write('\n')
