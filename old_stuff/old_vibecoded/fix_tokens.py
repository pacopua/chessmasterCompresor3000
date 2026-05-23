import sys
import struct
import re

def fix_binary_headers(data: bytes) -> bytes:
    # Use totally clean high-ascii bytes for binary headers: 0x80 to 0x83.
    # 0x80 = WhiteElo (2 bytes follow)
    # 0x81 = BlackElo (2 bytes follow)
    # 0x82 = UTCDate (4 bytes follow)
    # 0x83 = UTCTime (3 bytes follow)
    
    def we_repl(m): return b'\x80' + struct.pack('>H', int(m.group(1))) + b'\n'
    data = re.sub(rb'\[WhiteElo "(\d+)"\]\r?\n', we_repl, data)
    
    def be_repl(m): return b'\x81' + struct.pack('>H', int(m.group(1))) + b'\n'
    data = re.sub(rb'\[BlackElo "(\d+)"\]\r?\n', be_repl, data)
    
    def d_repl(m):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return b'\x82' + struct.pack('>HBB', y, mo, d) + b'\n'
    data = re.sub(rb'\[UTCDate "(\d{4})\.(\d{2})\.(\d{2})"\]\r?\n', d_repl, data)
    
    def t_repl(m):
        h, m_min, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return b'\x83' + struct.pack('>BBB', h, m_min, s) + b'\n'
    data = re.sub(rb'\[UTCTime "(\d{2}):(\d{2}):(\d{2})"\]\r?\n', t_repl, data)
    
    return data

def unfix_binary_headers(data: bytes) -> bytes:
    def we_repl(m): return b'[WhiteElo "' + str(struct.unpack('>H', m.group(1))[0]).encode() + b'"]\n'
    data = re.sub(rb'\x80(.{2})\n', we_repl, data)
    
    def be_repl(m): return b'[BlackElo "' + str(struct.unpack('>H', m.group(1))[0]).encode() + b'"]\n'
    data = re.sub(rb'\x81(.{2})\n', be_repl, data)
    
    def d_repl(m):
        y, mo, d = struct.unpack('>HBB', m.group(1))
        return b'[UTCDate "%04d.%02d.%02d"]\n' % (y, mo, d)
    data = re.sub(rb'\x82(.{4})\n', d_repl, data)
    
    def t_repl(m):
        h, m_min, s = struct.unpack('>BBB', m.group(1))
        return b'[UTCTime "%02d:%02d:%02d"]\n' % (h, m_min, s)
    data = re.sub(rb'\x83(.{3})\n', t_repl, data)
    
    return data

# Modify ultimate_codec.py
with open("ultimate_codec.py", "r", encoding="utf-8") as f:
    code = f.read()

# Swap the hex codes in pack_binary_headers
code = code.replace("b'\\xD8'", "b'\\x80'")
code = code.replace("b'\\xD9'", "b'\\x81'")
code = code.replace("b'\\xDA'", "b'\\x82'")
code = code.replace("b'\\xDB'", "b'\\x83'")

# Shift the squares up to \x85..\xC4
code = code.replace("bytes([128 + f * 8 + r])", "bytes([133 + f * 8 + r])")
code = code.replace("val - 128", "val - 133")
code = code.replace("128 <= val <= 191", "133 <= val <= 196")
code = code.replace("b'[\\x80-\\xBF]'", "b'[\\x85-\\xC4]'")

with open("ultimate_codec.py", "w", encoding="utf-8") as f:
    f.write(code)
