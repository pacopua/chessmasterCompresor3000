import bitarray as bitLib
from .openings import bits_to_opening, OPENING_BITS, OPENING_UNKNOWN
from .constant_types import (
    headers_bit_decoding,
    bits_to_result, bits_to_termination, bits_to_title, bits_to_eco_letter,
    bits_to_event, EVENT_BITS, EVENT_UNKNOWN,
    ELO_BITS, ELO_UNKNOWN,
    RATING_DIFF_MAG_BITS, RATING_DIFF_UNKNOWN_MAG,
    UTC_DATE_BASE_YEAR, UTC_DATE_YEAR_BITS, UTC_DATE_MONTH_BITS, UTC_DATE_DAY_BITS,
    UTC_DATE_UNKNOWN_YEAR,
    UTC_TIME_BITS, UTC_TIME_UNKNOWN,
    TIME_CONTROL_BASE_BITS, TIME_CONTROL_INC_BITS, TIME_CONTROL_UNKNOWN_BASE,
    SITE_PREFIX, SITE_ID_LEN, SITE_CHAR_BITS, SITE_IDX_TO_CHAR, SITE_UNKNOWN,
    RAW_STRING_LEN_BITS,
)


def _read_int(bits: bitLib.bitarray, pos: int, width: int) -> tuple[int, int]:
    return int(bits[pos:pos + width].to01(), 2), pos + width


def _read_raw_string(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    """Read 8-bit byte-length then UTF-8 bytes."""
    length, pos = _read_int(bits, pos, RAW_STRING_LEN_BITS)
    raw = bits[pos:pos + length * 8].tobytes()
    return raw.decode("utf-8"), pos + length * 8


# --- Individual value decoders ---

def decode_result(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    key = bits[pos:pos + 3].to01()
    pos += 3
    if bits_to_result[key] == "UNKNOWN_TEXT":
        return _read_raw_string(bits, pos)
    return bits_to_result[key], pos


def decode_termination(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    key = bits[pos:pos + 3].to01()
    pos += 3
    if bits_to_termination[key] == "UNKNOWN_TEXT":
        return _read_raw_string(bits, pos)
    return bits_to_termination[key], pos


def decode_title(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    key = bits[pos:pos + 3].to01()
    pos += 3
    if bits_to_title[key] == "UNKNOWN_TEXT":
        return _read_raw_string(bits, pos)
    return bits_to_title[key], pos


def decode_eco(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    letter_key = bits[pos:pos + 3].to01()
    pos += 3
    if bits_to_eco_letter[letter_key] == "UNKNOWN_TEXT":
        return _read_raw_string(bits, pos)
    letter = bits_to_eco_letter[letter_key]
    number, pos = _read_int(bits, pos, 7)
    return f"{letter}{number:02d}", pos


def decode_elo(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    value, pos = _read_int(bits, pos, ELO_BITS)
    if value == ELO_UNKNOWN:
        return _read_raw_string(bits, pos)
    return str(value), pos


def decode_rating_diff(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    negative = bool(bits[pos])
    pos += 1
    magnitude, pos = _read_int(bits, pos, RATING_DIFF_MAG_BITS)
    if magnitude == RATING_DIFF_UNKNOWN_MAG:
        return _read_raw_string(bits, pos)
    sign = "-" if negative else "+"
    return f"{sign}{magnitude}", pos


def decode_utc_date(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    year_offset, pos = _read_int(bits, pos, UTC_DATE_YEAR_BITS)
    if year_offset == UTC_DATE_UNKNOWN_YEAR:
        return _read_raw_string(bits, pos)
    month, pos = _read_int(bits, pos, UTC_DATE_MONTH_BITS)
    day, pos   = _read_int(bits, pos, UTC_DATE_DAY_BITS)
    year = year_offset + UTC_DATE_BASE_YEAR
    return f"{year:04d}.{month:02d}.{day:02d}", pos


def decode_utc_time(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    total, pos = _read_int(bits, pos, UTC_TIME_BITS)
    if total == UTC_TIME_UNKNOWN:
        return _read_raw_string(bits, pos)
    h, rem = divmod(total, 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}", pos


def decode_opening(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    value, pos = _read_int(bits, pos, OPENING_BITS)
    if value == OPENING_UNKNOWN:
        return _read_raw_string(bits, pos)
    return bits_to_opening[format(value, f"0{OPENING_BITS}b")], pos


def decode_event(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    value, pos = _read_int(bits, pos, EVENT_BITS)
    if value == EVENT_UNKNOWN:
        return _read_raw_string(bits, pos)
    return bits_to_event[format(value, f"0{EVENT_BITS}b")], pos


def decode_site(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    first, _ = _read_int(bits, pos, SITE_CHAR_BITS)
    if first == SITE_UNKNOWN:
        return _read_raw_string(bits, pos + SITE_CHAR_BITS)
    game_id = ""
    for _ in range(SITE_ID_LEN):
        idx, pos = _read_int(bits, pos, SITE_CHAR_BITS)
        game_id += SITE_IDX_TO_CHAR[idx]
    return SITE_PREFIX + game_id, pos


def decode_time_control(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    base, pos = _read_int(bits, pos, TIME_CONTROL_BASE_BITS)
    if base == TIME_CONTROL_UNKNOWN_BASE:
        return _read_raw_string(bits, pos)
    inc, pos = _read_int(bits, pos, TIME_CONTROL_INC_BITS)
    return f"{base}+{inc}", pos


VALUE_DECODERS = {
    "Result":          decode_result,
    "Termination":     decode_termination,
    "WhiteTitle":      decode_title,
    "BlackTitle":      decode_title,
    "ECO":             decode_eco,
    "WhiteElo":        decode_elo,
    "BlackElo":        decode_elo,
    "WhiteRatingDiff": decode_rating_diff,
    "BlackRatingDiff": decode_rating_diff,
    "UTCDate":         decode_utc_date,
    "UTCTime":         decode_utc_time,
    "TimeControl":     decode_time_control,
    "Site":            decode_site,
    "Event":           decode_event,
    "Opening":         decode_opening,
}


def decode_value(tag: str, bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    """Decode a single tag value from the bitstream."""
    decoder = VALUE_DECODERS.get(tag)
    if decoder:
        return decoder(bits, pos)
    return _read_raw_string(bits, pos)


def decode_headers(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    """
    Decode a PGN header block from bits.

    Reads tag/value pairs until the SEACABO marker, then returns the
    reconstructed  [TagName "TagValue"]  lines and the new bit position.
    """
    lines = []
    while True:
        tag_key = bits[pos:pos + 5].to01()
        pos += 5
        tag = headers_bit_decoding[tag_key]
        if tag == "SEACABO":
            break
        if tag == "UNKNOWN_TAG":
            tag, pos   = _read_raw_string(bits, pos)
            value, pos = _read_raw_string(bits, pos)
        else:
            value, pos = decode_value(tag, bits, pos)
        lines.append(f'[{tag} "{value}"]')
    return "\n".join(lines), pos
