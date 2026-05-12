import sys
import glob
import os
import struct
import heapq
from collections import Counter
import re

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
    heap = [Node(c, f) for c, f in freqs.items()]
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
    if codes is None: codes = {}
    if node is None: return codes
    if node.char is not None: codes[node.char] = prefix
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
        f.write(struct.pack('>I', len(freqs)))
        for sym, freq in freqs.items():
            f.write(struct.pack('>HI', sym, freq))
            
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
        for _ in range(num_freqs):
            sym, freq = struct.unpack('>HI', f.read(6))
            freqs[sym] = freq
            
        padding = struct.unpack('>B', f.read(1))[0]
        bit_data = f.read()
        
    tree = build_tree(freqs)
    lzw_data = []
    node = tree
    
    full_bits = "".join(bin(byte)[2:].zfill(8) for byte in bit_data)
    if padding > 0: full_bits = full_bits[:-padding]
        
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
    if len(sys.argv) < 3:
        sys.exit(1)
        
    action, pattern = sys.argv[1], sys.argv[2]
    
    if action == "encode":
        for file in glob.glob(pattern):
            if 'restored' not in file and not file.endswith('.scpgn'):
                encode_pgn(file, file + ".scpgn")
    elif action == "decode":
        for file in glob.glob(pattern):
            out_file = file.replace(".scpgn", "_smart_restored.pgn")
            decode_pgn(file, out_file)
