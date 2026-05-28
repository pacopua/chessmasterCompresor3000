import heapq
import bitarray as bitLib


class _Node:
    __slots__ = ('freq', 'symbol', 'left', 'right')

    def __init__(self, freq, symbol=None, left=None, right=None):
        self.freq = freq
        self.symbol = symbol
        self.left = left
        self.right = right


def build_huffman_codes(
    symbols_freqs: list[tuple[str, int]],
) -> tuple[dict[str, bitLib.bitarray], dict[str, str]]:
    """
    Build Huffman codes from (symbol, frequency) pairs.

    Returns (encode_table, decode_table):
        encode_table: symbol    -> bitarray
        decode_table: bitstring -> symbol
    """
    if not symbols_freqs:
        return {}, {}

    counter = 0

    def _push(heap, node):
        nonlocal counter
        heapq.heappush(heap, (node.freq, counter, node))
        counter += 1

    heap: list = []
    for symbol, freq in symbols_freqs:
        _push(heap, _Node(freq, symbol=symbol))

    if len(heap) == 1:
        sym = heap[0][2].symbol
        return {sym: bitLib.bitarray("0")}, {"0": sym}

    while len(heap) > 1:
        _, _, left = heapq.heappop(heap)
        _, _, right = heapq.heappop(heap)
        _push(heap, _Node(left.freq + right.freq, left=left, right=right))

    encode: dict[str, bitLib.bitarray] = {}
    decode: dict[str, str] = {}

    def _assign(node: _Node, prefix: str) -> None:
        if node.symbol is not None:
            encode[node.symbol] = bitLib.bitarray(prefix)
            decode[prefix] = node.symbol
        else:
            _assign(node.left, prefix + "0")
            _assign(node.right, prefix + "1")

    _assign(heap[0][2], "")
    return encode, decode


def huffman_decode(
    bits: bitLib.bitarray, pos: int, decode_table: dict[str, str]
) -> tuple[str, int]:
    """Decode one Huffman symbol from bits starting at pos."""
    code = ""
    while code not in decode_table:
        code += "1" if bits[pos] else "0"
        pos += 1
    return decode_table[code], pos
