import sys
import glob
import os
import struct
import heapq
from collections import Counter
import re

def write_vlq(val: int) -> bytearray:
    """Encodes an integer into a Variable-Length Quantity (LEB128)."""
    res = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            res.append(b | 0x80)
        else:
            res.append(b)
            break
    return res

def read_vlq(f) -> int:
    """Decodes a Variable-Length Quantity from a file stream."""
    res = 0
    shift = 0
    while True:
        b = f.read(1)
        if not b:
            raise EOFError("Unexpected end of file while reading VLQ")
        b = b[0]
        res |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return res

# --- Smart Chess Pre-Processor ---
# We analyze the move sequence and replace predictable patterns with single byte tokens.
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
            
            # Safely apply smart tokenization only if the line is purely ASCII
            # This prevents any risk of corrupting UTF-8 characters (like player names)
            if all(b < 128 for b in line):
                # 1. Outcomes -> mapped to \xFB, \xFC, \xFA
                line = line.replace(b'1-0', b'\xFB')
                line = line.replace(b'0-1', b'\xFC')
                line = line.replace(b'1/2-1/2', b'\xFA')
                
                # 2. Board Squares [a-h][1-8] -> mapped to \x80..\xBF (64 combinations)
                def sq_repl(m):
                    f = m.group(1)[0] - 97  # 'a' -> 0
                    r = m.group(1)[1] - 49  # '1' -> 0
                    return bytes([128 + f * 8 + r])
                line = re.sub(rb'([a-h][1-8])', sq_repl, line)
                
                # 3. Move Numbers (1., 2., 3...) -> \xFD (for 1.), \xFE (for >1.)
                def move_repl(m):
                    nonlocal expected_move
                    num = int(m.group(1))
                    if num == expected_move:
                        expected_move += 1
                        return b'\xFD' if num == 1 else b'\xFE'
                    return m.group(0) # Fallback to preserve exact original if sequence breaks
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
            # Restore Squares
            def sq_restore(m):
                val = m.group(1)[0]
                if 128 <= val <= 191:
                    f = (val - 128) // 8
                    r = (val - 128) % 8
                    return bytes([f + 97, r + 49])
                return m.group(1)
            line = re.sub(rb'([\x80-\xBF])', sq_restore, line)
            
            # Restore Move Numbers
            if b'\xFD' in line or b'\xFE' in line:
                res = bytearray()
                for b in line:
                    if b == 253: # \xFD
                        res.extend(b'1.')
                        expected_move = 2
                    elif b == 254: # \xFE
                        res.extend(str(expected_move).encode() + b'.')
                        expected_move += 1
                    else:
                        res.append(b)
                line = bytes(res)
                
            # Restore Outcomes
            line = line.replace(b'\xFB', b'1-0')
            line = line.replace(b'\xFC', b'0-1')
            line = line.replace(b'\xFA', b'1/2-1/2')
            
            out_lines.append(line)
            
    return b'\n'.join(out_lines)

# --- Huffman and LZW Algorithms ---
class Node:
    def __init__(self, char, freq):
        self.char = char
        self.freq = freq
        self.left = None
        self.right = None
    def __lt__(self, other):
        return self.freq < other.freq

def build_tree(freqs):
    # CRITICAL FIX: Sort by symbol code to guarantee identical heap ordering
    heap = [Node(c, f) for c, f in sorted(freqs.items())]
    heapq.heapify(heap)
    if not heap: return None
    while len(heap) > 1:
        l = heapq.heappop(heap)
        r = heapq.heappop(heap)
        merged = Node(None, l.freq + r.freq)
        merged.left, merged.right = l, r
        heapq.heappush(heap, merged)
    return heap[0]

def get_codes(node, prefix="", codes=None):
    if codes is None:
        codes = {}

    if node is None:
        return codes

    if node.char is not None:
        codes[node.char] = prefix or "0"
    else:
        get_codes(node.left, prefix + "0", codes)
        get_codes(node.right, prefix + "1", codes)

    return codes

def lzw_compress(data: bytes) -> list:
    dict_size = 256
    dictionary = {bytes([i]): i for i in range(256)}
    w = b""
    res = []
    for byte in data:
        c = bytes([byte])
        wc = w + c
        if wc in dictionary: w = wc
        else:
            res.append(dictionary[w])
            if dict_size < 65535:
                dictionary[wc] = dict_size
                dict_size += 1
            w = c
    if w: res.append(dictionary[w])
    return res

def lzw_decompress(compressed: list) -> bytes:
    dict_size = 256
    dictionary = {i: bytes([i]) for i in range(256)}
    if not compressed: return b""
    w = dictionary[compressed[0]]
    res = bytearray(w)
    for k in compressed[1:]:
        if k in dictionary: entry = dictionary[k]
        elif k == dict_size: entry = w + bytes([w[0]])
        else: raise ValueError(f"Bad LZW sequence: {k}")
        res.extend(entry)
        if dict_size < 65535:
            dictionary[dict_size] = w + bytes([entry[0]])
            dict_size += 1
        w = entry
    return bytes(res)

# --- Codec Execution ---
def encode_pgn(infile, outfile):
    print(f"Encoding {infile}...")
    with open(infile, 'rb') as f:
        data = f.read()
        
    # Apply Smart Move Pre-Processor
    tokenized_data = tokenize_moves(data)
    
    # LZW + Huffman
    lzw_data = lzw_compress(tokenized_data)
    freqs = Counter(lzw_data)
    tree = build_tree(freqs)
    codes = get_codes(tree)
    
    with open(outfile, 'wb') as f:
        # Write total number of unique symbols
        f.write(struct.pack('>I', len(freqs)))
        
        # DELTA + VLQ ENCODING FOR HEADER
        sorted_syms = sorted(freqs.keys())
        prev_sym = 0
        for sym in sorted_syms:
            delta = sym - prev_sym
            f.write(write_vlq(delta))          # Variable-length delta
            f.write(write_vlq(freqs[sym]))     # Variable-length frequency
            prev_sym = sym
            
        bit_data = bytearray()
        cur_byte, bit_cnt = 0, 0
        for sym in lzw_data:
            code = codes[sym]
            for bit in code:
                cur_byte = (cur_byte << 1) | int(bit)
                bit_cnt += 1
                if bit_cnt == 8:
                    bit_data.append(cur_byte)
                    cur_byte, bit_cnt = 0, 0
        
        padding = 0
        if bit_cnt > 0:
            padding = 8 - bit_cnt
            cur_byte = cur_byte << padding
            bit_data.append(cur_byte)
            
        f.write(struct.pack('>B', padding))
        f.write(bit_data)

def decode_pgn(infile, outfile):
    print(f"Decoding {infile}...")
    with open(infile, 'rb') as f:
        num_freqs_data = f.read(4)
        if not num_freqs_data: return
        num_freqs = struct.unpack('>I', num_freqs_data)[0]
        
        freqs = {}
        prev_sym = 0
        
        # DELTA + VLQ DECODING FOR HEADER
        for _ in range(num_freqs):
            delta = read_vlq(f)
            freq = read_vlq(f)
            sym = prev_sym + delta
            freqs[sym] = freq
            prev_sym = sym
            
        padding_data = f.read(1)
        if not padding_data: return
        padding = struct.unpack('>B', padding_data)[0]
        bit_data = f.read()
        
    tree = build_tree(freqs)

    # Special case: only one symbol in Huffman tree
    if tree.left is None and tree.right is None:
        lzw_data = [tree.char] * tree.freq
    else:
        lzw_data = []
        node = tree

        full_bits = "".join(bin(byte)[2:].zfill(8) for byte in bit_data)

        if padding > 0:
            full_bits = full_bits[:-padding]

        for bit in full_bits:
            node = node.left if bit == '0' else node.right

            if node.char is not None:
                lzw_data.append(node.char)
                node = tree
            
    decompressed_data = lzw_decompress(lzw_data)
    
    # Detokenize the Smart Moves
    restored_data = detokenize_moves(decompressed_data)
    
    with open(outfile, 'wb') as f:
        f.write(restored_data)

if __name__ == "__main__":

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python smart_chess_codec.py encode")
        print("  python smart_chess_codec.py decode")
        sys.exit(1)

    action = sys.argv[1]

    os.makedirs("Encoded", exist_ok=True)
    os.makedirs("Decoded", exist_ok=True)

    if action == "encode":

        files = glob.glob("Matches/**/*.pgn", recursive=True)

        print(f"Found {len(files)} PGN files")

        for file in files:

            base = os.path.basename(file)

            out_file = os.path.join(
                "Encoded",
                base + ".scpgn"
            )

            print(f"Encoding:")
            print(f"  Input : {file}")
            print(f"  Output: {out_file}")

            try:
                encode_pgn(file, out_file)

            except Exception as e:
                print(f"ERROR encoding {file}: {e}")

    elif action == "decode":

        files = glob.glob("Encoded/*.scpgn")

        print(f"Found {len(files)} compressed files")

        for file in files:

            base = os.path.basename(file)

            base = base.replace(
                ".pgn.scpgn",
                "_smart_restored.pgn"
            )

            out_file = os.path.join(
                "Decoded",
                base
            )

            print(f"Decoding:")
            print(f"  Input : {file}")
            print(f"  Output: {out_file}")

            try:
                decode_pgn(file, out_file)

            except Exception as e:
                print(f"ERROR decoding {file}: {e}")

    else:
        print("Unknown action:", action)