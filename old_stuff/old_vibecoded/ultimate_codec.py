import sys
import glob
import os
import struct
import heapq
from collections import Counter
import re

# --- The Safest Possible Tokenization ---
# We will NOT use regex replacements for tokens that might create conflicts
# We will use exactly defined byte replacements, completely distinct from everything else

REPLACEMENTS = [
    # Headers
    (b'[Event "', b'\xD0'), (b'[Site "', b'\xD1'),
    (b'[White "', b'\xD2'), (b'[Black "', b'\xD3'),
    (b'[Result "', b'\xD4'), (b'[ECO "', b'\xD5'),
    (b'[Opening "', b'\xD6'), (b'[TimeControl "', b'\xD7'),
    (b'[Termination "', b'\xD8'), (b'[WhiteRatingDiff "', b'\xD9'),
    (b'[BlackRatingDiff "', b'\xDA'),
    (b'"]\r\n', b'\xDB'), (b'"]\n', b'\xDC'),
    
    # Common text
    (b'https://lichess.org/', b'\xDD'),
    (b'Rated Bullet game', b'\xDE'), (b'Rated Blitz game', b'\xDF'),
    (b'Rated Rapid game', b'\xE0'), (b'Rated Classical game', b'\xE1'),
    (b'Normal', b'\xE2'), (b'Time forfeit', b'\xE3'),
    
    # Castling & Promotions
    (b'O-O-O', b'\xE4'), (b'O-O', b'\xE5'),
    (b'=Q', b'\xE6'), (b'=R', b'\xE7'),
    (b'=B', b'\xE8'), (b'=N', b'\xE9'),
    
    # Results
    (b'1/2-1/2', b'\xEA'), (b'1-0', b'\xEB'), (b'0-1', b'\xEC'),
]

def pack_binary_headers(data: bytes) -> bytes:
    # Safely pack headers by replacing EXACT prefixes that have not been tokenized yet
    # Or actually, let's tokenize the prefixes directly in pack_binary_headers!
    # So we don't conflict with anything
    
    def we_repl(m): return b'\x80' + struct.pack('>H', int(m.group(1))) + m.group(2)
    data = re.sub(rb'\[WhiteElo "(\d+)"\](\r?\n)', we_repl, data)
    
    def be_repl(m): return b'\x81' + struct.pack('>H', int(m.group(1))) + m.group(2)
    data = re.sub(rb'\[BlackElo "(\d+)"\](\r?\n)', be_repl, data)
    
    def d_repl(m):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return b'\x82' + struct.pack('>HBB', y, mo, d) + m.group(4)
    data = re.sub(rb'\[UTCDate "(\d{4})\.(\d{2})\.(\d{2})"\](\r?\n)', d_repl, data)
    
    def t_repl(m):
        h, m_min, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return b'\x83' + struct.pack('>BBB', h, m_min, s) + m.group(4)
    data = re.sub(rb'\[UTCTime "(\d{2}):(\d{2}):(\d{2})"\](\r?\n)', t_repl, data)
    
    return data

def unpack_binary_headers(data: bytes) -> bytes:
    def we_repl(m): return b'[WhiteElo "' + str(struct.unpack('>H', m.group(1))[0]).encode() + b'"]' + m.group(2)
    data = re.sub(rb'\x80(.{2})(\r?\n)', we_repl, data)
    
    def be_repl(m): return b'[BlackElo "' + str(struct.unpack('>H', m.group(1))[0]).encode() + b'"]' + m.group(2)
    data = re.sub(rb'\x81(.{2})(\r?\n)', be_repl, data)
    
    def d_repl(m):
        y, mo, d = struct.unpack('>HBB', m.group(1))
        return b'[UTCDate "%04d.%02d.%02d"]' % (y, mo, d) + m.group(2)
    data = re.sub(rb'\x82(.{4})(\r?\n)', d_repl, data)
    
    def t_repl(m):
        h, m_min, s = struct.unpack('>BBB', m.group(1))
        return b'[UTCTime "%02d:%02d:%02d"]' % (h, m_min, s) + m.group(2)
    data = re.sub(rb'\x83(.{3})(\r?\n)', t_repl, data)
    
    return data

def tokenize_data(data: bytes) -> bytes:
    # 1. Binary Headers FIRST, while the data is fully ASCII
    data = pack_binary_headers(data)
    
    # 2. String Replacements
    for orig, tok in REPLACEMENTS:
        data = data.replace(orig, tok)
        
    lines = data.split(b'\n')
    out_lines = []
    expected_move = 1
    in_moves = False
    
    for line in lines:
        if not line:
            out_lines.append(line)
            continue
            
        first_byte = line[0]
        # Exclude everything except standard text
        if first_byte == ord('[') or first_byte >= 0x80:
            in_moves = False
            out_lines.append(line)
        else:
            if not in_moves:
                in_moves = True
                expected_move = 1
            
            # Since first_byte < 0x80, this is definitely a move line
            # We map a1..h8 to \x90..\xCF
            def sq_repl(m):
                f = m.group(1)[0] - 97
                r = m.group(1)[1] - 49
                return bytes([144 + f * 8 + r])
            line = re.sub(rb'\b([a-h][1-8])\b', sq_repl, line)
            
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

def detokenize_data(data: bytes) -> bytes:
    lines = data.split(b'\n')
    out_lines = []
    expected_move = 1
    
    for line in lines:
        if not line:
            out_lines.append(line)
            continue
            
        first_byte = line[0]
        if first_byte == ord('[') or first_byte >= 0x80:
            out_lines.append(line)
        else:
            def sq_restore(m):
                val = m.group(1)[0]
                if 144 <= val <= 207:
                    f = (val - 144) // 8
                    r = (val - 144) % 8
                    return bytes([f + 97, r + 49])
                return m.group(1)
            line = re.sub(rb'([\x90-\xCF])', sq_restore, line)
            
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
            out_lines.append(line)
            
    res_data = b'\n'.join(out_lines)
    
    # Detokenize String Replacements
    for orig, tok in reversed(REPLACEMENTS):
        res_data = res_data.replace(tok, orig)
        
    # Detokenize Binary Headers
    res_data = unpack_binary_headers(res_data)
    return res_data

# --- LZW + Huffman ---
class Node:
    def __init__(self, char, freq):
        self.char, self.freq, self.left, self.right = char, freq, None, None
    def __lt__(self, other): return self.freq < other.freq

def build_tree(freqs):
    heap = [Node(c, f) for c, f in freqs.items()]
    heapq.heapify(heap)
    if not heap: return None
    while len(heap) > 1:
        l, r = heapq.heappop(heap), heapq.heappop(heap)
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

def encode_pgn(infile, outfile):
    with open(infile, 'rb') as f: data = f.read()
    
    tokenized_data = tokenize_data(data)
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
    restored_data = detokenize_data(decompressed_data)
    
    with open(outfile, 'wb') as f:
        f.write(restored_data)

if __name__ == "__main__":
    if len(sys.argv) < 3: sys.exit(1)
    action, pattern = sys.argv[1], sys.argv[2]
    
    if action == "encode":
        for file in glob.glob(pattern):
            if 'restored' not in file and not file.endswith('.ucpgn'):
                encode_pgn(file, file + ".ucpgn")
    elif action == "decode":
        for file in glob.glob(pattern):
            out_file = file.replace(".ucpgn", "_ultimate_restored.pgn")
            decode_pgn(file, out_file)
