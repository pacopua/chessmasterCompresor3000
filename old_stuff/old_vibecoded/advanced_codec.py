import sys
import glob
import os
import struct
import heapq
from collections import Counter

# --- Huffman Tree Node ---
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
    if not heap:
        return None
    while len(heap) > 1:
        l = heapq.heappop(heap)
        r = heapq.heappop(heap)
        merged = Node(None, l.freq + r.freq)
        merged.left = l
        merged.right = r
        heapq.heappush(heap, merged)
    return heap[0]

def get_codes(node, prefix="", codes=None):
    if codes is None: codes = {}
    if node is None: return codes
    if node.char is not None:
        codes[node.char] = prefix
    else:
        get_codes(node.left, prefix + "0", codes)
        get_codes(node.right, prefix + "1", codes)
    return codes

# --- LZW Dictionary Compression (Caps at 65535 to fit in 2 bytes) ---
def lzw_compress(data: bytes) -> list:
    dict_size = 256
    dictionary = {bytes([i]): i for i in range(256)}
    w = b""
    res = []
    
    # Simple byte iterator
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
            raise ValueError(f"Bad LZW sequence: {k}")
            
        res.extend(entry)
        
        if dict_size < 65535:
            dictionary[dict_size] = w + bytes([entry[0]])
            dict_size += 1
            
        w = entry
    return bytes(res)

# --- Encoding & Decoding Pipeline ---
def encode_pgn(infile, outfile):
    print(f"Encoding {infile}...")
    with open(infile, 'rb') as f:
        data = f.read()
        
    # Step 1: Dictionary Compression (LZW)
    lzw_data = lzw_compress(data)
    
    # Step 2: Huffman Coding
    freqs = Counter(lzw_data)
    tree = build_tree(freqs)
    codes = get_codes(tree)
    
    # Step 3: Serialize to Binary
    with open(outfile, 'wb') as f:
        # Write Frequency Table (for the decoder to rebuild the tree)
        f.write(struct.pack('>I', len(freqs)))
        for sym, freq in freqs.items():
            f.write(struct.pack('>HI', sym, freq)) # H=2 bytes (LZW max 65535), I=4 bytes
            
        # Write Bitstream
        bit_data = bytearray()
        cur_byte = 0
        bit_cnt = 0
        for sym in lzw_data:
            code = codes[sym]
            for bit in code:
                cur_byte = (cur_byte << 1) | int(bit)
                bit_cnt += 1
                if bit_cnt == 8:
                    bit_data.append(cur_byte)
                    cur_byte = 0
                    bit_cnt = 0
        
        padding = 0
        if bit_cnt > 0:
            padding = 8 - bit_cnt
            cur_byte = cur_byte << padding
            bit_data.append(cur_byte)
            
        f.write(struct.pack('>B', padding))
        f.write(bit_data)
        
    orig_sz = os.path.getsize(infile)
    new_sz = os.path.getsize(outfile)
    print(f"  -> Compressed: {orig_sz/1024:.2f} KB -> {new_sz/1024:.2f} KB ({(1-new_sz/orig_sz)*100:.1f}%)")

def decode_pgn(infile, outfile):
    print(f"Decoding {infile}...")
    with open(infile, 'rb') as f:
        num_freqs_data = f.read(4)
        if not num_freqs_data:
            return
        num_freqs = struct.unpack('>I', num_freqs_data)[0]
        
        freqs = {}
        for _ in range(num_freqs):
            sym, freq = struct.unpack('>HI', f.read(6))
            freqs[sym] = freq
            
        padding = struct.unpack('>B', f.read(1))[0]
        bit_data = f.read()
        
    # Rebuild tree
    tree = build_tree(freqs)
    
    # Decode Huffman bits into LZW integers
    lzw_data = []
    node = tree
    
    # Optimize bit iteration by joining bits into a single string
    bit_str_list = [bin(byte)[2:].zfill(8) for byte in bit_data]
    full_bits = "".join(bit_str_list)
    if padding > 0:
        full_bits = full_bits[:-padding]
        
    for bit in full_bits:
        if bit == '0':
            node = node.left
        else:
            node = node.right
            
        if node.char is not None:
            lzw_data.append(node.char)
            node = tree
            
    # Decompress LZW integers back to raw bytes
    decompressed_data = lzw_decompress(lzw_data)
    
    with open(outfile, 'wb') as f:
        f.write(decompressed_data)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python advanced_codec.py [encode|decode] [file_pattern]")
        sys.exit(1)
        
    action = sys.argv[1]
    pattern = sys.argv[2]
    
    if action == "encode":
        for file in glob.glob(pattern):
            if 'restored' not in file and not file.endswith('.hcpgn'):
                encode_pgn(file, file + ".hcpgn")
    elif action == "decode":
        for file in glob.glob(pattern):
            out_file = file.replace(".hcpgn", "_advanced_restored.pgn")
            decode_pgn(file, out_file)
