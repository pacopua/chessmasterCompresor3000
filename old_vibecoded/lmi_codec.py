"""
Legal Move Indexing (LMI) chess codec.

Instead of storing moves as text (e.g. "Nf3"), each move is encoded as its
index into the sorted list of legal moves at that position.  With ~30 legal
moves on average, this requires only ~5 bits per move vs ~10-20 bytes of text.

Pipeline (encode):  PGN → parse headers + SAN tokens
                        → for each position: gen legal moves, find SAN index
                        → bit-pack indices
                        → write  [headers][n_moves][n_bytes][bits]

Pipeline (decode):  read headers
                        → for each move: gen legal moves, read bits → index
                        → convert index to SAN
                        → write PGN
"""

import sys, glob, os, struct, re, heapq
from collections import namedtuple, Counter

# ── Constants ─────────────────────────────────────────────────────────────────

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 1, 2, 3, 4, 5, 6
WHITE, BLACK = 0, 1

FILES = 'abcdefgh'
PIECES = {KNIGHT: 'N', BISHOP: 'B', ROOK: 'R', QUEEN: 'Q', KING: 'K'}
# Promotion pieces in canonical sort order (2, 3, 4, 5)
PROMO_PIECES = (KNIGHT, BISHOP, ROOK, QUEEN)
PROMO_CHAR = {KNIGHT: 'N', BISHOP: 'B', ROOK: 'R', QUEEN: 'Q'}

def _sq(r, f):  return r * 8 + f
def _r(s):      return s >> 3
def _f(s):      return s & 7
def _name(s):   return FILES[_f(s)] + str(_r(s) + 1)

def bits_needed(n):
    """Bits required to represent an index in [0, n-1]."""
    return 0 if n <= 1 else (n - 1).bit_length()


# ── Board ─────────────────────────────────────────────────────────────────────

_BACK = (ROOK, KNIGHT, BISHOP, QUEEN, KING, BISHOP, KNIGHT, ROOK)

class Board:
    __slots__ = ('sq', 'turn', 'castle', 'ep')

    def __init__(self):
        # sq[i] = None  or  (piece_type, color)
        self.sq = [None] * 64
        self.turn = WHITE
        # castling rights: 'K' 'Q' for white, 'k' 'q' for black
        self.castle = {'K': True, 'Q': True, 'k': True, 'q': True}
        self.ep = -1  # en-passant target square, -1 if none
        for f, p in enumerate(_BACK):
            self.sq[_sq(0, f)] = (p, WHITE)
            self.sq[_sq(7, f)] = (p, BLACK)
        for f in range(8):
            self.sq[_sq(1, f)] = (PAWN, WHITE)
            self.sq[_sq(6, f)] = (PAWN, BLACK)

    def copy(self):
        b = object.__new__(Board)
        b.sq = self.sq[:]
        b.turn = self.turn
        b.castle = dict(self.castle)
        b.ep = self.ep
        return b

    def find_king(self, color):
        for s in range(64):
            if self.sq[s] == (KING, color):
                return s
        return -1

    # ── Attack detection ─────────────────────────────────────────────────────

    def is_attacked(self, target, by_color):
        """True if `target` square is attacked by any piece of `by_color`."""
        tr, tf = _r(target), _f(target)
        sq = self.sq

        # Pawns
        if by_color == WHITE:
            for df in (-1, 1):
                r, f = tr - 1, tf + df
                if 0 <= r < 8 and 0 <= f < 8 and sq[_sq(r, f)] == (PAWN, WHITE):
                    return True
        else:
            for df in (-1, 1):
                r, f = tr + 1, tf + df
                if 0 <= r < 8 and 0 <= f < 8 and sq[_sq(r, f)] == (PAWN, BLACK):
                    return True

        # Knights
        for dr, df in ((-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)):
            r, f = tr + dr, tf + df
            if 0 <= r < 8 and 0 <= f < 8 and sq[_sq(r, f)] == (KNIGHT, by_color):
                return True

        # King
        for dr in (-1, 0, 1):
            for df in (-1, 0, 1):
                if dr == df == 0: continue
                r, f = tr + dr, tf + df
                if 0 <= r < 8 and 0 <= f < 8 and sq[_sq(r, f)] == (KING, by_color):
                    return True

        # Rooks / Queens (straight)
        for dr, df in ((1,0),(-1,0),(0,1),(0,-1)):
            r, f = tr + dr, tf + df
            while 0 <= r < 8 and 0 <= f < 8:
                s = _sq(r, f)
                if sq[s] is not None:
                    p, c = sq[s]
                    if c == by_color and p in (ROOK, QUEEN): return True
                    break
                r, f = r + dr, f + df

        # Bishops / Queens (diagonal)
        for dr, df in ((1,1),(1,-1),(-1,1),(-1,-1)):
            r, f = tr + dr, tf + df
            while 0 <= r < 8 and 0 <= f < 8:
                s = _sq(r, f)
                if sq[s] is not None:
                    p, c = sq[s]
                    if c == by_color and p in (BISHOP, QUEEN): return True
                    break
                r, f = r + dr, f + df

        return False

    # ── Move generation ───────────────────────────────────────────────────────

    def _pseudo(self):
        """Generate pseudo-legal moves as (from_sq, to_sq, promo) tuples."""
        moves = []
        color, opp = self.turn, 1 - self.turn

        for from_s in range(64):
            pc = self.sq[from_s]
            if pc is None or pc[1] != color:
                continue
            piece = pc[0]
            r, f = _r(from_s), _f(from_s)

            if piece == PAWN:
                dr      = 1 if color == WHITE else -1
                start_r = 1 if color == WHITE else 6
                promo_r = 7 if color == WHITE else 0

                # Single push
                nr = r + dr
                if 0 <= nr < 8:
                    to_s = _sq(nr, f)
                    if self.sq[to_s] is None:
                        if nr == promo_r:
                            for promo in PROMO_PIECES:
                                moves.append((from_s, to_s, promo))
                        else:
                            moves.append((from_s, to_s, None))
                            # Double push
                            if r == start_r:
                                to2 = _sq(nr + dr, f)
                                if self.sq[to2] is None:
                                    moves.append((from_s, to2, None))

                # Diagonal captures (and en passant)
                for df2 in (-1, 1):
                    nf = f + df2
                    if 0 <= nf < 8 and 0 <= nr < 8:
                        to_s = _sq(nr, nf)
                        if (self.sq[to_s] is not None and self.sq[to_s][1] == opp):
                            if nr == promo_r:
                                for promo in PROMO_PIECES:
                                    moves.append((from_s, to_s, promo))
                            else:
                                moves.append((from_s, to_s, None))
                        elif to_s == self.ep:
                            moves.append((from_s, to_s, None))

            elif piece == KNIGHT:
                for dr2, df2 in ((-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)):
                    nr, nf = r + dr2, f + df2
                    if 0 <= nr < 8 and 0 <= nf < 8:
                        to_s = _sq(nr, nf)
                        if self.sq[to_s] is None or self.sq[to_s][1] == opp:
                            moves.append((from_s, to_s, None))

            elif piece in (BISHOP, ROOK, QUEEN):
                dirs = []
                if piece != ROOK:   dirs += [(1,1),(1,-1),(-1,1),(-1,-1)]
                if piece != BISHOP: dirs += [(1,0),(-1,0),(0,1),(0,-1)]
                for dr2, df2 in dirs:
                    nr, nf = r + dr2, f + df2
                    while 0 <= nr < 8 and 0 <= nf < 8:
                        to_s = _sq(nr, nf)
                        if self.sq[to_s] is None:
                            moves.append((from_s, to_s, None))
                        elif self.sq[to_s][1] == opp:
                            moves.append((from_s, to_s, None))
                            break
                        else:
                            break
                        nr, nf = nr + dr2, nf + df2

            elif piece == KING:
                for dr2 in (-1, 0, 1):
                    for df2 in (-1, 0, 1):
                        if dr2 == df2 == 0: continue
                        nr, nf = r + dr2, f + df2
                        if 0 <= nr < 8 and 0 <= nf < 8:
                            to_s = _sq(nr, nf)
                            if self.sq[to_s] is None or self.sq[to_s][1] == opp:
                                moves.append((from_s, to_s, None))

        return moves

    def _castling_moves(self):
        """Generate castling moves (already verified safe: path not attacked)."""
        moves = []
        color, opp = self.turn, 1 - self.turn

        if color == WHITE:
            if (self.castle['K']
                    and self.sq[4] == (KING, WHITE)
                    and self.sq[5] is None and self.sq[6] is None
                    and self.sq[7] == (ROOK, WHITE)
                    and not self.is_attacked(4, opp)
                    and not self.is_attacked(5, opp)
                    and not self.is_attacked(6, opp)):
                moves.append((4, 6, None))
            if (self.castle['Q']
                    and self.sq[4] == (KING, WHITE)
                    and self.sq[3] is None and self.sq[2] is None and self.sq[1] is None
                    and self.sq[0] == (ROOK, WHITE)
                    and not self.is_attacked(4, opp)
                    and not self.is_attacked(3, opp)
                    and not self.is_attacked(2, opp)):
                moves.append((4, 2, None))
        else:
            if (self.castle['k']
                    and self.sq[60] == (KING, BLACK)
                    and self.sq[61] is None and self.sq[62] is None
                    and self.sq[63] == (ROOK, BLACK)
                    and not self.is_attacked(60, opp)
                    and not self.is_attacked(61, opp)
                    and not self.is_attacked(62, opp)):
                moves.append((60, 62, None))
            if (self.castle['q']
                    and self.sq[60] == (KING, BLACK)
                    and self.sq[59] is None and self.sq[58] is None and self.sq[57] is None
                    and self.sq[56] == (ROOK, BLACK)
                    and not self.is_attacked(60, opp)
                    and not self.is_attacked(59, opp)
                    and not self.is_attacked(58, opp)):
                moves.append((60, 58, None))

        return moves

    def legal_moves(self):
        """Return sorted list of legal (from_sq, to_sq, promo) moves."""
        color, opp = self.turn, 1 - self.turn
        result = []
        for move in self._pseudo():
            b2 = self.copy()
            b2._apply(*move)
            king_sq = b2.find_king(color)
            if not b2.is_attacked(king_sq, opp):
                result.append(move)
        result.extend(self._castling_moves())
        result.sort(key=lambda m: (m[0], m[1], m[2] if m[2] is not None else -1))
        return result

    def _apply(self, from_s, to_s, promo):
        """Apply a move in-place. Does NOT check legality."""
        piece, color = self.sq[from_s]
        prev_ep = self.ep
        self.ep = -1

        # En passant capture: remove the pawn behind the target square
        if piece == PAWN and to_s == prev_ep and prev_ep != -1:
            self.sq[to_s + (-8 if color == WHITE else 8)] = None

        # Castling: also move the rook
        if piece == KING:
            if   from_s == 4  and to_s == 6:  self.sq[7]  = None; self.sq[5]  = (ROOK, WHITE)
            elif from_s == 4  and to_s == 2:  self.sq[0]  = None; self.sq[3]  = (ROOK, WHITE)
            elif from_s == 60 and to_s == 62: self.sq[63] = None; self.sq[61] = (ROOK, BLACK)
            elif from_s == 60 and to_s == 58: self.sq[56] = None; self.sq[59] = (ROOK, BLACK)

        # Move piece
        self.sq[from_s] = None
        self.sq[to_s] = (promo, color) if promo else (piece, color)

        # Update castling rights (king or rook moved, or rook captured)
        if piece == KING:
            if color == WHITE: self.castle['K'] = self.castle['Q'] = False
            else:              self.castle['k'] = self.castle['q'] = False
        _ROOK_RIGHTS = {0: 'Q', 7: 'K', 56: 'q', 63: 'k'}
        if from_s in _ROOK_RIGHTS: self.castle[_ROOK_RIGHTS[from_s]] = False
        if to_s   in _ROOK_RIGHTS: self.castle[_ROOK_RIGHTS[to_s]]   = False

        # Set en-passant square after double pawn push
        if piece == PAWN and abs(to_s - from_s) == 16:
            self.ep = (from_s + to_s) // 2

        self.turn = 1 - color

    # ── SAN generation ───────────────────────────────────────────────────────

    def san_base(self, move, legal):
        """SAN string without check / checkmate suffix."""
        from_s, to_s, promo = move
        piece, color = self.sq[from_s]

        # Castling
        if piece == KING and abs(to_s - from_s) == 2:
            return "O-O" if to_s > from_s else "O-O-O"

        is_cap = (self.sq[to_s] is not None) or (piece == PAWN and to_s == self.ep)
        promo_str = ("=" + PROMO_CHAR[promo]) if promo else ""
        dest = _name(to_s)

        if piece == PAWN:
            if is_cap:
                return FILES[_f(from_s)] + "x" + dest + promo_str
            return dest + promo_str

        # Non-pawn: find disambiguation
        p_char = PIECES[piece]
        cap_str = "x" if is_cap else ""

        # Collect other pieces of same type/color that can also reach to_s
        same = [m for m in legal
                if m[1] == to_s and m[0] != from_s
                and self.sq[m[0]] is not None
                and self.sq[m[0]][0] == piece
                and self.sq[m[0]][1] == color]

        if not same:
            dis = ""
        else:
            from_files = {_f(m[0]) for m in same}
            from_ranks = {_r(m[0]) for m in same}
            if _f(from_s) not in from_files:
                dis = FILES[_f(from_s)]
            elif _r(from_s) not in from_ranks:
                dis = str(_r(from_s) + 1)
            else:
                dis = _name(from_s)

        return p_char + dis + cap_str + dest + promo_str

    def san_full(self, move, legal):
        """SAN string including + or # suffix."""
        base = self.san_base(move, legal)
        b2 = self.copy()
        b2._apply(*move)
        opp_king = b2.find_king(b2.turn)
        if b2.is_attacked(opp_king, self.turn):
            opp_moves = b2.legal_moves()
            return base + ("#" if not opp_moves else "+")
        return base


# ── Bit stream ────────────────────────────────────────────────────────────────

class BitWriter:
    def __init__(self):
        self._buf = bytearray()
        self._cur = 0
        self._n = 0

    def write(self, value, n_bits):
        for i in range(n_bits - 1, -1, -1):
            self._cur = (self._cur << 1) | ((value >> i) & 1)
            self._n += 1
            if self._n == 8:
                self._buf.append(self._cur)
                self._cur = self._n = 0

    def finish(self):
        if self._n:
            self._buf.append(self._cur << (8 - self._n))
        return bytes(self._buf)


class BitReader:
    def __init__(self, data):
        self._data = data
        self._pos = 0
        self._bit = 7

    def read(self, n_bits):
        v = 0
        for _ in range(n_bits):
            if self._pos >= len(self._data):
                raise ValueError("BitReader: ran out of data")
            v = (v << 1) | ((self._data[self._pos] >> self._bit) & 1)
            if self._bit == 0:
                self._bit = 7; self._pos += 1
            else:
                self._bit -= 1
        return v


# ── PGN parsing ───────────────────────────────────────────────────────────────

# Matches annotation quality markers that Lichess appends to SAN tokens
_STRIP_RE = re.compile(r'[?!+#]+$')

# Matches a SAN move token
_SAN_RE = re.compile(
    r'O-O-O|O-O|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[?!+#]*'
)

_RESULT_TOKENS = {'1-0', '0-1', '1/2-1/2', '*'}
_MOVE_NUM_RE   = re.compile(r'^\d+\.+$')


def _extract_sans(move_text):
    """Strip comments/annotations, return list of clean SAN tokens."""
    # Remove { ... } blocks
    buf, depth = [], 0
    for ch in move_text:
        if ch == '{':   depth += 1
        elif ch == '}': depth -= 1
        elif depth == 0: buf.append(ch)
    clean = ''.join(buf)

    # Remove ( ... ) variation lines (simple, non-nested)
    while '(' in clean:
        clean = re.sub(r'\([^()]*\)', ' ', clean)

    tokens = []
    for tok in clean.split():
        if tok in _RESULT_TOKENS: continue
        if _MOVE_NUM_RE.match(tok): continue
        tok = _STRIP_RE.sub('', tok)  # strip ?! !! + # from end
        if tok:
            tokens.append(tok)
    return tokens


def parse_games(data: bytes):
    """
    Yield (header_lines: list[str], result: str, san_tokens: list[str])
    for each game in the PGN byte string.
    """
    text = data.decode('utf-8', errors='ignore')
    lines = text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        # Skip blank lines between games
        while i < n and not lines[i].strip():
            i += 1
        if i >= n:
            break

        # Collect header lines
        headers = []
        while i < n and lines[i].startswith('['):
            headers.append(lines[i])
            i += 1

        if not headers:
            i += 1
            continue

        # Skip blank lines between headers and moves
        while i < n and not lines[i].strip():
            i += 1

        # Collect move text
        move_lines = []
        while i < n and lines[i].strip() and not lines[i].startswith('['):
            move_lines.append(lines[i])
            i += 1
        move_text = ' '.join(move_lines)

        # Extract result from headers
        result = '*'
        for h in headers:
            m = re.match(r'\[Result\s+"([^"]+)"\]', h)
            if m:
                result = m.group(1)
                break

        yield headers, result, _extract_sans(move_text)


# ── Header Huffman ───────────────────────────────────────────────────────────

class _HNode:
    __slots__ = ('sym', 'freq', 'left', 'right')
    def __init__(self, sym, freq, left=None, right=None):
        self.sym = sym; self.freq = freq
        self.left = left; self.right = right
    def __lt__(self, o): return self.freq < o.freq

def _build_htree(freqs):
    items = list(freqs.items())
    if not items: return None
    if len(items) == 1:
        items = items * 2  # single-symbol edge case
    heap = [_HNode(s, f) for s, f in items]
    heapq.heapify(heap)
    while len(heap) > 1:
        l, r = heapq.heappop(heap), heapq.heappop(heap)
        heapq.heappush(heap, _HNode(None, l.freq + r.freq, l, r))
    return heap[0]

def _get_hcodes(node, prefix='', codes=None):
    if codes is None: codes = {}
    if node is None: return codes
    if node.sym is not None:
        codes[node.sym] = prefix or '0'
    else:
        _get_hcodes(node.left, prefix + '0', codes)
        _get_hcodes(node.right, prefix + '1', codes)
    return codes

def _huff_encode(data: bytes, codes: dict):
    """Encode bytes to bits. Returns (packed_bytes, n_bits)."""
    writer = BitWriter()
    for b in data:
        code = codes[b]
        writer.write(int(code, 2), len(code))
    n_bits = sum(len(codes[b]) for b in data)
    return writer.finish(), n_bits

def _huff_decode(packed: bytes, n_bits: int, tree) -> bytes:
    result = bytearray()
    node = tree
    seen = 0
    for byte in packed:
        for shift in range(7, -1, -1):
            if seen >= n_bits:
                break
            bit = (byte >> shift) & 1
            node = node.right if bit else node.left
            seen += 1
            if node.sym is not None:
                result.append(node.sym)
                node = tree
    return bytes(result)


_MAGIC = b'LMI2'

# ── Codec ─────────────────────────────────────────────────────────────────────

def encode_game(headers, result, sans):
    """
    Encode one game's moves.  Returns (n_moves: int, bit_bytes: bytes).
    Header serialisation is handled by encode_pgn (global Huffman pass).
    """
    board = Board()
    writer = BitWriter()
    n_moves = 0

    for san in sans:
        legal = board.legal_moves()
        if not legal:
            break  # game over (shouldn't happen mid-list in a valid PGN)

        bits = bits_needed(len(legal))

        # Primary match: compare against minimal SAN we generate.
        idx = None
        for i, move in enumerate(legal):
            if board.san_base(move, legal) == san:
                idx = i
                break

        # Fallback: handle "long SAN" like Ne7c6 / Re2e5 / Nd2f3 where some
        # PGN generators write the full from-square instead of minimal disambig.
        # Pattern: [KQRBN][a-h][1-8]x?[a-h][1-8](=[QRBN])?
        if idx is None:
            _long = re.fullmatch(
                r'([KQRBN])([a-h][1-8])x?([a-h][1-8])(=[QRBN])?', san)
            if _long:
                from_name, to_name = _long.group(2), _long.group(3)
                from_s = FILES.index(from_name[0]) + (int(from_name[1]) - 1) * 8
                to_s   = FILES.index(to_name[0])   + (int(to_name[1])   - 1) * 8
                promo_str = _long.group(4)
                promo_p = ({'N':KNIGHT,'B':BISHOP,'R':ROOK,'Q':QUEEN}
                           [promo_str[1]] if promo_str else None)
                for i, move in enumerate(legal):
                    if move[0] == from_s and move[1] == to_s and move[2] == promo_p:
                        idx = i
                        break

        if idx is None:
            raise ValueError(
                f"No legal move matches '{san}'.\n"
                f"Position: turn={'W' if board.turn==WHITE else 'B'}, "
                f"ep={board.ep}\n"
                f"Legal: {[board.san_base(m, legal) for m in legal]}"
            )

        if bits > 0:
            writer.write(idx, bits)
        board._apply(*legal[idx])
        n_moves += 1

    return n_moves, writer.finish()


def decode_game(headers: list, n_moves: int, bit_bytes: bytes) -> str:
    """Replay n_moves from bit_bytes, return formatted PGN text."""
    result = '*'
    for h in headers:
        m = re.match(r'\[Result\s+"([^"]+)"\]', h)
        if m:
            result = m.group(1)
            break

    reader = BitReader(bit_bytes)
    board = Board()
    san_list = []

    for _ in range(n_moves):
        legal = board.legal_moves()
        bits = bits_needed(len(legal))
        idx = reader.read(bits) if bits > 0 else 0
        move = legal[idx]
        san_list.append(board.san_full(move, legal))
        board._apply(*move)

    parts = []
    for i, s in enumerate(san_list):
        if i % 2 == 0:
            parts.append(f"{i // 2 + 1}. {s}")
        else:
            parts.append(s)
    parts.append(result)

    return '\n'.join(headers) + '\n\n' + ' '.join(parts) + '\n\n'


def encode_pgn(infile, outfile):
    print(f"Encoding {infile}...", end=" ", flush=True)
    with open(infile, 'rb') as f:
        data = f.read()

    # Pass 1: encode all moves, collect raw header bytes per game.
    records = []  # (hdr_bytes, n_moves, bit_bytes)
    errors = 0
    for headers, result, sans in parse_games(data):
        try:
            n_moves, bit_bytes = encode_game(headers, result, sans)
            hdr_bytes = b''.join((h + '\n').encode('utf-8') for h in headers)
            records.append((hdr_bytes, n_moves, bit_bytes))
        except ValueError as e:
            errors += 1
            if errors <= 3:
                print(f"\n  [skip: {e}]", end=" ", flush=True)

    # Pass 2: build global Huffman table over all header bytes.
    all_hdrs = b''.join(r[0] for r in records)
    freqs = Counter(all_hdrs)
    tree = _build_htree(freqs)
    codes = _get_hcodes(tree)

    with open(outfile, 'wb') as f:
        f.write(_MAGIC)
        f.write(struct.pack('>I', len(records)))
        f.write(struct.pack('>I', len(freqs)))
        for sym, freq in freqs.items():
            f.write(struct.pack('>BI', sym, freq))
        for hdr_bytes, n_moves, bit_bytes in records:
            hbits, n_hbits = _huff_encode(hdr_bytes, codes)
            f.write(struct.pack('>I', n_hbits))
            f.write(hbits)
            f.write(struct.pack('>HH', n_moves, len(bit_bytes)))
            f.write(bit_bytes)

    orig = os.path.getsize(infile)
    comp = os.path.getsize(outfile)
    print(f"{len(records)} games, {orig//1024} KB → {comp//1024} KB  "
          f"({(1 - comp/orig)*100:.1f}% smaller)"
          + (f"  [{errors} skipped]" if errors else ""))


def decode_pgn(infile, outfile):
    print(f"Decoding {infile}...", end=" ", flush=True)
    with open(infile, 'rb') as f:
        raw = f.read()

    offset = 0
    if raw[offset:offset + 4] != _MAGIC:
        raise ValueError(f"{infile}: not a valid LMI2 file")
    offset += 4

    n_games = struct.unpack('>I', raw[offset:offset + 4])[0]; offset += 4
    n_syms  = struct.unpack('>I', raw[offset:offset + 4])[0]; offset += 4
    freqs = {}
    for _ in range(n_syms):
        sym, freq = struct.unpack('>BI', raw[offset:offset + 5])
        freqs[sym] = freq; offset += 5

    tree = _build_htree(freqs)

    parts = []
    for _ in range(n_games):
        n_hbits = struct.unpack('>I', raw[offset:offset + 4])[0]; offset += 4
        n_hbytes = (n_hbits + 7) // 8
        hdr_packed = raw[offset:offset + n_hbytes]; offset += n_hbytes

        hdr_text = _huff_decode(hdr_packed, n_hbits, tree).decode('utf-8')
        headers = [h for h in hdr_text.split('\n') if h]

        n_moves, n_mbytes = struct.unpack('>HH', raw[offset:offset + 4]); offset += 4
        bit_bytes = raw[offset:offset + n_mbytes]; offset += n_mbytes

        parts.append(decode_game(headers, n_moves, bit_bytes))

    with open(outfile, 'w', encoding='utf-8') as f:
        f.write(''.join(parts))
    print(f"{n_games} games decoded")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python lmi_codec.py [encode|decode] <file_pattern>")
        sys.exit(1)

    action, pattern = sys.argv[1], sys.argv[2]

    if action == 'encode':
        for f in sorted(glob.glob(pattern)):
            if 'restored' not in f and not f.endswith('.lpgn'):
                encode_pgn(f, f + '.lpgn')

    elif action == 'decode':
        for f in sorted(glob.glob(pattern)):
            decode_pgn(f, f.replace('.lpgn', '_lmi_restored.pgn'))
