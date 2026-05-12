import sys
import glob
import os
import struct
import heapq
from collections import Counter
import re

BLOCK_SIZE = 8192

# ── Smart Chess Pre-Processor (from smart_chess_codec.py) ────────────────────

def tokenize_moves(data: bytes) -> bytes:
    lines = data.split(b'\n')
    out_lines = []
    in_moves = False
    expected_move = 1

    for line in lines:
        if line.startswith(b'['):
            in_moves = False
            out_lines.append(line)
        elif line.strip() == b'':
            out_lines.append(line)
        else:
            if not in_moves:
                in_moves = True
                expected_move = 1
            if all(b < 128 for b in line):
                line = line.replace(b'1-0', b'\xFB')
                line = line.replace(b'0-1', b'\xFC')
                line = line.replace(b'1/2-1/2', b'\xFA')

                def sq_repl(m):
                    f = m.group(1)[0] - 97
                    r = m.group(1)[1] - 49
                    return bytes([128 + f * 8 + r])
                line = re.sub(rb'([a-h][1-8])', sq_repl, line)

                def move_repl(m):
                    nonlocal expected_move
                    num = int(m.group(1))
                    if num == expected_move:
                        expected_move += 1
                        return b'\xFD' if num == 1 else b'\xFE'
                    return m.group(0)
                line = re.sub(rb'\b(\d+)\.', move_repl, line)
            out_lines.append(line)

    return b'\n'.join(out_lines)


def detokenize_moves(data: bytes) -> bytes:
    lines = data.split(b'\n')
    out_lines = []
    expected_move = 1

    for line in lines:
        if line.startswith(b'['):
            out_lines.append(line)
        elif line.strip() == b'':
            out_lines.append(line)
        else:
            def sq_restore(m):
                val = m.group(1)[0]
                if 128 <= val <= 191:
                    f = (val - 128) // 8
                    r = (val - 128) % 8
                    return bytes([f + 97, r + 49])
                return m.group(1)
            line = re.sub(rb'([\x80-\xBF])', sq_restore, line)

            if b'\xFD' in line or b'\xFE' in line:
                res = bytearray()
                for b in line:
                    if b == 253:
                        res.extend(b'1.')
                        expected_move = 2
                    elif b == 254:
                        res.extend(str(expected_move).encode() + b'.')
                        expected_move += 1
                    else:
                        res.append(b)
                line = bytes(res)

            line = line.replace(b'\xFB', b'1-0')
            line = line.replace(b'\xFC', b'0-1')
            line = line.replace(b'\xFA', b'1/2-1/2')
            out_lines.append(line)

    return b'\n'.join(out_lines)


# ── Burrows-Wheeler Transform ─────────────────────────────────────────────────

def bwt_encode_block(block: bytes):
    n = len(block)
    if n <= 1:
        return block, 0
    # Sort indices of all cyclic rotations
    indices = sorted(range(n), key=lambda i: block[i:] + block[:i])
    # Last column of the sorted rotation matrix
    bwt = bytes(block[(i - 1) % n] for i in indices)
    # Row index of the original string
    orig_idx = indices.index(0)
    return bwt, orig_idx


def bwt_decode_block(bwt: bytes, orig_idx: int) -> bytes:
    n = len(bwt)
    if n <= 1:
        return bwt

    # Build LF mapping: for each position i in L (=bwt),
    # lf[i] = position in the sorted first column F where bwt[i] would be placed,
    # counting occurrences in order.
    counts = [0] * 256
    for b in bwt:
        counts[b] += 1

    starts = [0] * 256
    t = 0
    for i in range(256):
        starts[i] = t
        t += counts[i]

    occ = [0] * 256
    lf = [0] * n
    for i in range(n):
        c = bwt[i]
        lf[i] = starts[c] + occ[c]
        occ[c] += 1

    # Reconstruct: walk backwards through the LF mapping from orig_idx
    result = bytearray(n)
    pos = orig_idx
    for i in range(n - 1, -1, -1):
        result[i] = bwt[pos]
        pos = lf[pos]

    return bytes(result)


# ── Move-To-Front Transform ───────────────────────────────────────────────────
# BWT clusters identical bytes into runs. MTF converts those runs into
# sequences of 0s and small numbers, which LZW/Huffman compress extremely well.

def mtf_encode(data: bytes) -> bytes:
    alpha = bytearray(range(256))
    out = bytearray(len(data))
    for i, b in enumerate(data):
        idx = alpha.index(b)
        out[i] = idx
        del alpha[idx]
        alpha.insert(0, b)
    return bytes(out)


def mtf_decode(data: bytes) -> bytes:
    alpha = bytearray(range(256))
    out = bytearray(len(data))
    for i, idx in enumerate(data):
        b = alpha[idx]
        out[i] = b
        del alpha[idx]
        alpha.insert(0, b)
    return bytes(out)


# ── LZW ──────────────────────────────────────────────────────────────────────

def lzw_compress(data: bytes) -> list:
    dict_size = 256
    dictionary = {bytes([i]): i for i in range(256)}
    w = b""
    res = []
    for byte in data:
        c = bytes([byte])
        wc = w + c
        if wc in dictionary:
            w = wc
        else:
            res.append(dictionary[w])
            if dict_size < 65535:
                dictionary[wc] = dict_size
                dict_size += 1
            w = c
    if w:
        res.append(dictionary[w])
    return res


def lzw_decompress(compressed: list) -> bytes:
    dict_size = 256
    dictionary = {i: bytes([i]) for i in range(256)}
    if not compressed:
        return b""
    w = dictionary[compressed[0]]
    res = bytearray(w)
    for k in compressed[1:]:
        if k in dictionary:
            entry = dictionary[k]
        elif k == dict_size:
            entry = w + bytes([w[0]])
        else:
            raise ValueError(f"Bad LZW code: {k}")
        res.extend(entry)
        if dict_size < 65535:
            dictionary[dict_size] = w + bytes([entry[0]])
            dict_size += 1
        w = entry
    return bytes(res)


# ── Huffman ───────────────────────────────────────────────────────────────────

class Node:
    def __init__(self, char, freq):
        self.char, self.freq, self.left, self.right = char, freq, None, None
    def __lt__(self, other):
        return self.freq < other.freq


def build_tree(freqs):
    heap = [Node(c, f) for c, f in freqs.items()]
    heapq.heapify(heap)
    if not heap:
        return None
    while len(heap) > 1:
        l, r = heapq.heappop(heap), heapq.heappop(heap)
        m = Node(None, l.freq + r.freq)
        m.left, m.right = l, r
        heapq.heappush(heap, m)
    return heap[0]


def get_codes(node, prefix="", codes=None):
    if codes is None:
        codes = {}
    if node is None:
        return codes
    if node.char is not None:
        codes[node.char] = prefix
    else:
        get_codes(node.left, prefix + "0", codes)
        get_codes(node.right, prefix + "1", codes)
    return codes


# ── Codec ─────────────────────────────────────────────────────────────────────

def encode_pgn(infile, outfile):
    print(f"Encoding {infile}...", end=" ", flush=True)
    with open(infile, 'rb') as f:
        data = f.read()

    # 1. Smart chess tokenization
    tokenized = tokenize_moves(data)
    total_len = len(tokenized)
    n_blocks = (total_len + BLOCK_SIZE - 1) // BLOCK_SIZE

    # 2. BWT per block
    bwt_data = bytearray()
    orig_indices = []
    for i in range(n_blocks):
        block = tokenized[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE]
        bwt_block, idx = bwt_encode_block(block)
        bwt_data.extend(bwt_block)
        orig_indices.append(idx)

    # 3. Move-To-Front
    mtf_data = mtf_encode(bytes(bwt_data))

    # 4. Huffman directly on MTF byte values (0-255).
    # MTF output is dominated by 0s and small values — Huffman is the right tool
    # here, not LZW, because the structure is frequency-skew, not repeated substrings.
    freqs = Counter(mtf_data)
    tree = build_tree(freqs)
    codes = get_codes(tree)

    with open(outfile, 'wb') as f:
        # Header: total tokenized length + block indices
        f.write(struct.pack('>I', total_len))
        f.write(struct.pack('>I', n_blocks))
        for idx in orig_indices:
            # Max idx = BLOCK_SIZE - 1 = 4095, fits in uint16
            f.write(struct.pack('>H', idx))

        # Huffman frequency table (symbols are bytes 0-255, so 1B per symbol)
        f.write(struct.pack('>I', len(freqs)))
        for sym, freq in freqs.items():
            f.write(struct.pack('>BI', sym, freq))

        # Bitstream
        bit_data = bytearray()
        cur_byte, bit_cnt = 0, 0
        for sym in mtf_data:
            for bit in codes[sym]:
                cur_byte = (cur_byte << 1) | int(bit)
                bit_cnt += 1
                if bit_cnt == 8:
                    bit_data.append(cur_byte)
                    cur_byte, bit_cnt = 0, 0
        padding = 0
        if bit_cnt > 0:
            padding = 8 - bit_cnt
            cur_byte <<= padding
            bit_data.append(cur_byte)

        f.write(struct.pack('>B', padding))
        f.write(bit_data)

    orig_sz = os.path.getsize(infile)
    new_sz = os.path.getsize(outfile)
    print(f"{orig_sz // 1024} KB → {new_sz // 1024} KB  ({(1 - new_sz / orig_sz) * 100:.1f}% smaller)")


def decode_pgn(infile, outfile):
    print(f"Decoding {infile}...", end=" ", flush=True)
    with open(infile, 'rb') as f:
        total_len = struct.unpack('>I', f.read(4))[0]
        n_blocks = struct.unpack('>I', f.read(4))[0]
        orig_indices = [struct.unpack('>H', f.read(2))[0] for _ in range(n_blocks)]

        n_freqs = struct.unpack('>I', f.read(4))[0]
        freqs = {}
        for _ in range(n_freqs):
            sym, freq = struct.unpack('>BI', f.read(5))
            freqs[sym] = freq

        padding = struct.unpack('>B', f.read(1))[0]
        bit_data = f.read()

    # Huffman decode → raw MTF bytes
    tree = build_tree(freqs)
    mtf_data = bytearray()
    node = tree
    full_bits = "".join(bin(b)[2:].zfill(8) for b in bit_data)
    if padding > 0:
        full_bits = full_bits[:-padding]
    for bit in full_bits:
        node = node.left if bit == '0' else node.right
        if node.char is not None:
            mtf_data.append(node.char)
            node = tree
    mtf_data = bytes(mtf_data)

    # MTF decode
    bwt_data = mtf_decode(mtf_data)

    # BWT decode per block
    tokenized = bytearray()
    offset = 0
    for i, idx in enumerate(orig_indices):
        if i < n_blocks - 1:
            block_size = BLOCK_SIZE
        else:
            last_size = total_len % BLOCK_SIZE
            block_size = last_size if last_size > 0 else BLOCK_SIZE
        block = bwt_data[offset:offset + block_size]
        tokenized.extend(bwt_decode_block(block, idx))
        offset += block_size

    # Detokenize
    result = detokenize_moves(bytes(tokenized))

    with open(outfile, 'wb') as f:
        f.write(result)
    print("done")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python bwt_codec.py [encode|decode] [file_pattern]")
        sys.exit(1)

    action, pattern = sys.argv[1], sys.argv[2]

    if action == "encode":
        for file in sorted(glob.glob(pattern)):
            if 'restored' not in file and not file.endswith('.bpgn'):
                encode_pgn(file, file + ".bpgn")
    elif action == "decode":
        for file in sorted(glob.glob(pattern)):
            out_file = file.replace(".bpgn", "_bwt_restored.pgn")
            decode_pgn(file, out_file)
