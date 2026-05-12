import sys
import glob
import os

# Custom static dictionaries for PGN structure
# We use bytes in the range 0x80 to 0xFF to represent these common strings
HEADER_KEYS = {
    b"Event": b"\x80", b"Site": b"\x81", b"White": b"\x82", b"Black": b"\x83",
    b"Result": b"\x84", b"UTCDate": b"\x85", b"UTCTime": b"\x86", b"WhiteElo": b"\x87",
    b"BlackElo": b"\x88", b"WhiteRatingDiff": b"\x89", b"BlackRatingDiff": b"\x8A",
    b"ECO": b"\x8B", b"Opening": b"\x8C", b"TimeControl": b"\x8D", b"Termination": b"\x8E",
    b"WhiteTitle": b"\x8F", b"BlackTitle": b"\x90"
}
INV_HEADER_KEYS = {v: k for k, v in HEADER_KEYS.items()}

COMMON_VALUES = {
    b"https://lichess.org/": b"\xA0",
    b"Rated Bullet game": b"\xA1",
    b"Rated Blitz game": b"\xA2",
    b"Rated Rapid game": b"\xA3",
    b"Rated Classical game": b"\xA4",
    b"Normal": b"\xA5",
    b"Time forfeit": b"\xA6",
    b"1-0": b"\xA7",
    b"0-1": b"\xA8",
    b"1/2-1/2": b"\xA9",
    b"120+0": b"\xAA",
    b"60+0": b"\xAB",
    b"180+0": b"\xAC",
    b"300+0": b"\xAD",
    b"600+0": b"\xAE"
}
INV_COMMON_VALUES = {v: k for k, v in COMMON_VALUES.items()}

COMMON_MOVES = {
    b" O-O ": b"\xC0", b" O-O-O ": b"\xC1",
    b" e4 ": b"\xC2", b" e5 ": b"\xC3",
    b" d4 ": b"\xC4", b" d5 ": b"\xC5",
    b" Nf3 ": b"\xC6", b" Nc6 ": b"\xC7",
    b" c4 ": b"\xC8", b" c5 ": b"\xC9",
    b"1-0": b"\xCA", b"0-1": b"\xCB", b"1/2-1/2": b"\xCC"
}
INV_COMMON_MOVES = {v: k for k, v in COMMON_MOVES.items()}

def encode_pgn(input_file, output_file):
    print(f"Encoding {input_file} -> {output_file}")
    with open(input_file, 'rb') as f:
        lines = f.readlines()

    out_bytes = bytearray()
    in_moves = False
    move_buffer = bytearray()

    for line in lines:
        line = line.strip()
        if not line:
            if in_moves and move_buffer:
                # Flush moves
                moves = move_buffer
                # Structural compression: remove spaces after move numbers
                import re
                moves = re.sub(b'(\\d+)\\.\\s+', b'\\1.', moves)
                
                # Replace common move patterns
                for k, v in COMMON_MOVES.items():
                    moves = moves.replace(k, v)
                
                out_bytes.extend(moves + b"\n\n")
                move_buffer = bytearray()
                in_moves = False
            else:
                # Still in headers or between games
                pass 
            continue
            
        if line.startswith(b"[") and line.endswith(b"]"):
            # It's a header
            in_moves = False
            content = line[1:-1]
            try:
                space_idx = content.index(b' ')
                key = content[:space_idx]
                val = content[space_idx+1:].strip(b'"')
                
                enc_key = HEADER_KEYS.get(key, key)
                
                # Replace common values in the value string
                for k, v in COMMON_VALUES.items():
                    val = val.replace(k, v)
                
                if enc_key in HEADER_KEYS.values():
                    # We mapped the key to a single byte. Format: <ByteKey><EncodedVal>\n
                    out_bytes.extend(enc_key + val + b"\n")
                else:
                    # Unmapped key. Format: [<Key> "<Val>"]\n
                    out_bytes.extend(b"[" + key + b' "' + val + b'"]\n')
            except ValueError:
                out_bytes.extend(line + b"\n")
        else:
            # It's a move line
            in_moves = True
            if move_buffer:
                move_buffer.extend(b" ")
            move_buffer.extend(line)

    # Flush remaining
    if move_buffer:
        moves = move_buffer
        import re
        moves = re.sub(b'(\\d+)\\.\\s+', b'\\1.', moves)
        for k, v in COMMON_MOVES.items():
            moves = moves.replace(k, v)
        out_bytes.extend(moves + b"\n\n")

    with open(output_file, 'wb') as f:
        f.write(out_bytes)
        
    orig_size = os.path.getsize(input_file)
    new_size = os.path.getsize(output_file)
    print(f"  Reduced from {orig_size/1024:.2f} KB to {new_size/1024:.2f} KB ({(1 - new_size/orig_size)*100:.1f}%)")


def decode_pgn(input_file, output_file):
    print(f"Decoding {input_file} -> {output_file}")
    with open(input_file, 'rb') as f:
        lines = f.readlines()

    out_bytes = bytearray()
    
    for line in lines:
        line = line.strip(b"\n") # Only strip newline, keep spaces if any
        if not line:
            out_bytes.extend(b"\n")
            continue
            
        if line[0:1] in INV_HEADER_KEYS:
            # It's an encoded header
            key = INV_HEADER_KEYS[line[0:1]]
            val = line[1:]
            
            # Restore values
            for k, v in INV_COMMON_VALUES.items():
                val = val.replace(k, v)
                
            out_bytes.extend(b"[" + key + b' "' + val + b'"]\n')
            
        elif line.startswith(b"["):
            # Unmapped header
            val = line
            for k, v in INV_COMMON_VALUES.items():
                val = val.replace(k, v)
            out_bytes.extend(val + b"\n")
            
        else:
            # It's a move line
            moves = line
            # Restore common moves
            for k, v in INV_COMMON_MOVES.items():
                moves = moves.replace(k, v)
                
            # Restore space after move number
            import re
            moves = re.sub(b'(\\d+)\\.', b'\\1. ', moves)
            
            # PGN lines shouldn't be infinitely long. Standard is 80 chars. Let's wrap it.
            # Wrapping it precisely isn't strictly necessary for PGN validity but helps readability.
            words = moves.split(b" ")
            current_line = bytearray()
            for word in words:
                if len(current_line) + len(word) > 75:
                    out_bytes.extend(current_line.strip() + b"\n")
                    current_line = bytearray()
                current_line.extend(word + b" ")
            if current_line:
                out_bytes.extend(current_line.strip() + b"\n")

    with open(output_file, 'wb') as f:
        f.write(out_bytes)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python custom_codec.py [encode|decode] [file_pattern]")
        sys.exit(1)
        
    action = sys.argv[1]
    
    if action == "encode":
        pattern = sys.argv[2] if len(sys.argv) > 2 else "*.pgn"
        for file in glob.glob(pattern):
            if not file.endswith("_restored.pgn"):
                encode_pgn(file, file + ".custom_cpgn")
            
    elif action == "decode":
        pattern = sys.argv[2] if len(sys.argv) > 2 else "*.custom_cpgn"
        for file in glob.glob(pattern):
            out_file = file.replace(".custom_cpgn", "_custom_restored.pgn")
            decode_pgn(file, out_file)
