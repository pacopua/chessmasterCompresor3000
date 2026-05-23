"""
Arithmetic coder — integer implementation (CACM87 / Witten-Neal-Cleary).

Uses 32-bit scaled integers with E1/E2/E3 (underflow) rescaling.
Zero-frequency symbols are allowed in the model and are simply never emitted.

Public API
----------
encode(data, freqs) -> (compressed_bytes, n_bits)
decode(data, n_bits, freqs, n_symbols) -> bytes
"""

PREC          = 32
FULL          = 1 << PREC          # 2^32
HALF          = FULL  >> 1         # 2^31
QUARTER       = FULL  >> 2         # 2^30
THREE_QUARTER = HALF + QUARTER     # 3 * 2^30


def _cum_table(freqs: dict[int, int]) -> tuple[list[int], int]:
    """Return cumulative frequency table cum[0..256] and total."""
    cum = [0] * 257
    for i in range(256):
        cum[i + 1] = cum[i] + freqs.get(i, 0)
    return cum, cum[256]


def encode(data: bytes, freqs: dict[int, int]) -> tuple[bytes, int]:
    """
    Encode *data* using the static frequency model *freqs*.
    Returns (compressed_bytes, n_bits).
    """
    cum, total = _cum_table(freqs)

    low, high = 0, FULL - 1
    pending   = 0
    buf       = bytearray()
    cur, cnt  = 0, 0     # current output byte being built, bit count in it
    n_bits    = 0

    def emit(bit: int) -> None:
        nonlocal pending, cur, cnt, n_bits
        for b in (bit,) + (1 - bit,) * pending:
            cur = (cur << 1) | b
            cnt += 1
            n_bits += 1
            if cnt == 8:
                buf.append(cur)
                cur = cnt = 0
        pending = 0

    for sym in data:
        f_lo = cum[sym]
        f_hi = cum[sym + 1]
        r    = high - low + 1
        high = low + r * f_hi // total - 1
        low  = low + r * f_lo  // total

        while True:
            if high < HALF:                                   # E1: both in lower half
                emit(0)
                low  = low  * 2
                high = high * 2 + 1
            elif low >= HALF:                                 # E2: both in upper half
                emit(1)
                low  = (low  - HALF) * 2
                high = (high - HALF) * 2 + 1
            elif low >= QUARTER and high < THREE_QUARTER:    # E3: straddle midpoint
                pending += 1
                low  = (low  - QUARTER) * 2
                high = (high - QUARTER) * 2 + 1
            else:
                break

    # Flush: output enough bits to identify a value in [low, high]
    pending += 1
    emit(0 if low < QUARTER else 1)

    if cnt:   # partial final byte
        buf.append(cur << (8 - cnt))

    return bytes(buf), n_bits


def encode_ints(symbols: list[int], freqs: dict[int, int]) -> tuple[bytes, int]:
    """
    Arithmetic-encode a list of arbitrary non-negative integers.
    *freqs* maps each integer symbol to its frequency.
    Returns (compressed_bytes, n_bits).
    """
    max_sym  = max(freqs)
    cum      = [0] * (max_sym + 2)
    for i in range(max_sym + 1):
        cum[i + 1] = cum[i] + freqs.get(i, 0)
    total = cum[max_sym + 1]

    low, high = 0, FULL - 1
    pending   = 0
    buf       = bytearray()
    cur, cnt  = 0, 0
    n_bits    = 0

    def emit(bit: int) -> None:
        nonlocal pending, cur, cnt, n_bits
        for b in (bit,) + (1 - bit,) * pending:
            cur = (cur << 1) | b
            cnt += 1
            n_bits += 1
            if cnt == 8:
                buf.append(cur)
                cur = cnt = 0
        pending = 0

    for sym in symbols:
        f_lo = cum[sym]
        f_hi = cum[sym + 1]
        r    = high - low + 1
        high = low + r * f_hi // total - 1
        low  = low + r * f_lo  // total

        while True:
            if high < HALF:
                emit(0)
                low  = low  * 2
                high = high * 2 + 1
            elif low >= HALF:
                emit(1)
                low  = (low  - HALF) * 2
                high = (high - HALF) * 2 + 1
            elif low >= QUARTER and high < THREE_QUARTER:
                pending += 1
                low  = (low  - QUARTER) * 2
                high = (high - QUARTER) * 2 + 1
            else:
                break

    pending += 1
    emit(0 if low < QUARTER else 1)

    if cnt:
        buf.append(cur << (8 - cnt))

    return bytes(buf), n_bits


def decode_ints(data: bytes, n_bits: int, freqs: dict[int, int], n_symbols: int) -> list[int]:
    """
    Decode *n_symbols* integers from *data* using the static model *freqs*.
    *n_bits* is the number of valid bits in *data* (rest is padding).
    """
    max_sym = max(freqs)
    cum     = [0] * (max_sym + 2)
    for i in range(max_sym + 1):
        cum[i + 1] = cum[i] + freqs.get(i, 0)
    total = cum[max_sym + 1]

    def bit_at(pos: int) -> int:
        byte_i, bit_i = divmod(pos, 8)
        if byte_i >= len(data):
            return 0
        return (data[byte_i] >> (7 - bit_i)) & 1

    value   = 0
    bit_pos = 0
    for _ in range(PREC):
        value = (value << 1) | bit_at(bit_pos)
        bit_pos += 1

    low, high = 0, FULL - 1
    result    = []

    for _ in range(n_symbols):
        r      = high - low + 1
        scaled = ((value - low + 1) * total - 1) // r

        lo, hi = 0, max_sym
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if cum[mid] <= scaled:
                lo = mid
            else:
                hi = mid - 1
        sym = lo

        result.append(sym)

        f_lo = cum[sym]
        f_hi = cum[sym + 1]
        high = low + r * f_hi // total - 1
        low  = low + r * f_lo  // total

        while True:
            if high < HALF:
                low   = low  * 2
                high  = high * 2 + 1
                value = value * 2 + bit_at(bit_pos); bit_pos += 1
            elif low >= HALF:
                low   = (low  - HALF) * 2
                high  = (high - HALF) * 2 + 1
                value = (value - HALF) * 2 + bit_at(bit_pos); bit_pos += 1
            elif low >= QUARTER and high < THREE_QUARTER:
                low   = (low  - QUARTER) * 2
                high  = (high - QUARTER) * 2 + 1
                value = (value - QUARTER) * 2 + bit_at(bit_pos); bit_pos += 1
            else:
                break

    return result


def decode(data: bytes, n_bits: int, freqs: dict[int, int], n_symbols: int) -> bytes:
    """
    Decode *n_symbols* bytes from *data* using the static model *freqs*.
    *n_bits* is the number of valid bits in *data* (rest is padding).
    """
    cum, total = _cum_table(freqs)

    def bit_at(pos: int) -> int:
        byte_i, bit_i = divmod(pos, 8)
        if byte_i >= len(data):
            return 0
        return (data[byte_i] >> (7 - bit_i)) & 1

    # Prime the decoder value with the first PREC bits
    value   = 0
    bit_pos = 0
    for _ in range(PREC):
        value = (value << 1) | bit_at(bit_pos)
        bit_pos += 1

    low, high = 0, FULL - 1
    result    = bytearray()

    for _ in range(n_symbols):
        r      = high - low + 1
        scaled = ((value - low + 1) * total - 1) // r

        # Binary search: find sym such that cum[sym] <= scaled < cum[sym+1]
        lo, hi = 0, 255
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if cum[mid] <= scaled:
                lo = mid
            else:
                hi = mid - 1
        sym = lo

        result.append(sym)

        f_lo = cum[sym]
        f_hi = cum[sym + 1]
        high = low + r * f_hi // total - 1
        low  = low + r * f_lo  // total

        while True:
            if high < HALF:
                low   = low  * 2
                high  = high * 2 + 1
                value = value * 2 + bit_at(bit_pos); bit_pos += 1
            elif low >= HALF:
                low   = (low  - HALF) * 2
                high  = (high - HALF) * 2 + 1
                value = (value - HALF) * 2 + bit_at(bit_pos); bit_pos += 1
            elif low >= QUARTER and high < THREE_QUARTER:
                low   = (low  - QUARTER) * 2
                high  = (high - QUARTER) * 2 + 1
                value = (value - QUARTER) * 2 + bit_at(bit_pos); bit_pos += 1
            else:
                break

    return bytes(result)
