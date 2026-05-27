"""
Player-name encoding helpers.

First occurrence  →  flag 0  +  5-bit length  +  Huffman(char) × length
                      (length=0 is an escape: raw UTF-8 string follows)
Repeat occurrence →  flag 1  +  adaptive-width dict index

The Huffman alphabet is the 64-character Lichess username set
[0-9 A-Z a-z _ -] plus an UNKNOWN_CHAR sentinel for anything outside it.
"""

from .huffman import build_huffman_codes
from .frequencies import NAME_CHAR_FREQS

# Lichess username alphabet (sorted for determinism).
NAME_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-"
NAME_CHAR_SET = set(NAME_CHARS)

# 5 bits covers lengths 1-31 (max Lichess username = 20); 0 is reserved as
# the raw-string escape for names containing characters outside NAME_CHAR_SET.
NAME_LENGTH_BITS = 5

_char_freqs = [(c, NAME_CHAR_FREQS.get(c, 1)) for c in NAME_CHARS]
_char_freqs.append(("UNKNOWN_CHAR", NAME_CHAR_FREQS.get("UNKNOWN_CHAR", 1)))

char_to_bits, bits_to_char = build_huffman_codes(_char_freqs)


def index_width(dict_size: int) -> int:
    """Bits needed to represent any index in [0, dict_size-1]."""
    return max(1, (dict_size - 1).bit_length())
