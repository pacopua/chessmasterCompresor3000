from datetime import date as _date, timedelta as _timedelta
import bitarray as bitLib
from .huffman import huffman_decode
from .openings import bits_to_opening
from .player_names import bits_to_char, NAME_LENGTH_BITS, index_width
from .constant_types import (
    headers_bit_decoding,
    bits_to_result, bits_to_termination, bits_to_title, bits_to_eco_letter,
    bits_to_event,
    ELO_BITS, ELO_UNKNOWN,
    RATING_DIFF_MAG_BITS, RATING_DIFF_UNKNOWN_MAG,
    UTC_DATE_BASE_YEAR, UTC_DATE_YEAR_BITS, UTC_DATE_MONTH_BITS, UTC_DATE_DAY_BITS,
    UTC_DATE_UNKNOWN_YEAR,
    UTC_TIME_BITS, UTC_TIME_UNKNOWN,
    TIME_CONTROL_BASE_BITS, TIME_CONTROL_INC_BITS, TIME_CONTROL_UNKNOWN_BASE,
    SITE_PREFIX, SITE_ID_LEN, SITE_CHAR_BITS, SITE_IDX_TO_CHAR, SITE_UNKNOWN,
    RAW_STRING_LEN_BITS,
)


_EPOCH = _date(UTC_DATE_BASE_YEAR, 1, 1)
_UTC_DATE_DELTA_OFFSET = 63
_UTC_TIME_DELTA_OFFSET = 63

def _date_to_days(year: int, month: int, day: int) -> int:
    return (_date(year, month, day) - _EPOCH).days

def _days_to_ymd(days: int) -> tuple[int, int, int]:
    d = _EPOCH + _timedelta(days=days)
    return d.year, d.month, d.day


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


def _decode_abs_date(bits: bitLib.bitarray, pos: int) -> tuple[str, int, int | None]:
    """Read a 16-bit absolute date (the legacy format). Returns (value, pos, days)."""
    year_offset, pos = _read_int(bits, pos, UTC_DATE_YEAR_BITS)
    if year_offset == UTC_DATE_UNKNOWN_YEAR:
        value, pos = _read_raw_string(bits, pos)
        return value, pos, None
    month, pos = _read_int(bits, pos, UTC_DATE_MONTH_BITS)
    day, pos   = _read_int(bits, pos, UTC_DATE_DAY_BITS)
    year = year_offset + UTC_DATE_BASE_YEAR
    return f"{year:04d}.{month:02d}.{day:02d}", pos, _date_to_days(year, month, day)


def decode_utc_date(bits: bitLib.bitarray, pos: int, prev_days: int | None = None) -> tuple[str, int, int | None]:
    """Returns (value, new_pos, cur_days).

    When prev_days is supplied, interprets the 3-tier delta prefix written by
    encode_utc_date; otherwise reads the legacy 16-bit absolute encoding.
    """
    if prev_days is not None:
        first = bits[pos]; pos += 1
        if not first:                          # "0" — same day
            y, m, d = _days_to_ymd(prev_days)
            return f"{y:04d}.{m:02d}.{d:02d}", pos, prev_days
        second = bits[pos]; pos += 1
        if not second:                         # "10" — small delta
            delta_val, pos = _read_int(bits, pos, 7)
            cur_days = prev_days + delta_val - _UTC_DATE_DELTA_OFFSET
            y, m, d = _days_to_ymd(cur_days)
            return f"{y:04d}.{m:02d}.{d:02d}", pos, cur_days
        # "11" — absolute fallback
        return _decode_abs_date(bits, pos)

    return _decode_abs_date(bits, pos)


def decode_utc_time(bits: bitLib.bitarray, pos: int, prev_secs: int | None = None) -> tuple[str, int, int | None]:
    """Returns (value, new_pos, cur_secs).

    When prev_secs is supplied, interprets the 2-tier delta prefix written by
    encode_utc_time; otherwise reads the legacy 17-bit absolute encoding.
    """
    if prev_secs is not None:
        flag = bits[pos]; pos += 1
        if not flag:                           # "0" — small delta
            delta_val, pos = _read_int(bits, pos, 7)
            total = prev_secs + delta_val - _UTC_TIME_DELTA_OFFSET
            h, rem = divmod(total, 3600)
            m, s   = divmod(rem, 60)
            return f"{h:02d}:{m:02d}:{s:02d}", pos, total
        # "1" — absolute fallback

    total, pos = _read_int(bits, pos, UTC_TIME_BITS)
    if total == UTC_TIME_UNKNOWN:
        value, pos = _read_raw_string(bits, pos)
        return value, pos, None
    h, rem = divmod(total, 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}", pos, total


def decode_opening(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    value, pos = huffman_decode(bits, pos, bits_to_opening)
    if value == "UNKNOWN_TEXT":
        return _read_raw_string(bits, pos)
    return value, pos


def decode_event(bits: bitLib.bitarray, pos: int) -> tuple[str, int]:
    value, pos = huffman_decode(bits, pos, bits_to_event)
    if value == "UNKNOWN_TEXT":
        return _read_raw_string(bits, pos)
    return value, pos


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


def decode_player_name(bits: bitLib.bitarray, pos: int, name_list: list[str]) -> tuple[str, int]:
    """LZ78-style dict + character-Huffman decoder for White/Black player names.

    name_list is mutated in place: new names are appended as they are decoded.
    """
    flag = bits[pos]; pos += 1

    if flag:
        # Repeat: read adaptive-width index.
        width = index_width(len(name_list))
        idx, pos = _read_int(bits, pos, width)
        return name_list[idx], pos

    # New name: read 5-bit length then Huffman chars (length=0 → raw string).
    length, pos = _read_int(bits, pos, NAME_LENGTH_BITS)
    if length == 0:
        value, pos = _read_raw_string(bits, pos)
    else:
        chars = []
        for _ in range(length):
            char, pos = huffman_decode(bits, pos, bits_to_char)
            chars.append(char)
        value = "".join(chars)

    name_list.append(value)
    return value, pos


# UTCDate and UTCTime are handled separately in decode_headers (they carry inter-game state).
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


def decode_headers(
    bits: bitLib.bitarray,
    pos: int,
    name_list: list[str],
    prev_days: int | None = None,
    prev_secs: int | None = None,
) -> tuple[str, int, int | None, int | None]:
    """
    Decode a PGN header block from bits.

    name_list: shared mutable list of player names seen so far (index → name).
    Pass an empty list [] for the first game; it is mutated in place.

    prev_days / prev_secs: day-count / second-of-day from the previous game,
    used to read compact delta codes for UTCDate / UTCTime.  Pass None for
    the first game in a file (falls back to legacy absolute decoding).

    Returns (header_text, new_pos, cur_days, cur_secs).
    """
    lines = []
    cur_days: int | None = prev_days
    cur_secs: int | None = prev_secs

    while True:
        tag_key = bits[pos:pos + 5].to01()
        pos += 5
        tag = headers_bit_decoding[tag_key]
        if tag == "SEACABO":
            break
        if tag == "UNKNOWN_TAG":
            tag, pos   = _read_raw_string(bits, pos)
            value, pos = _read_raw_string(bits, pos)
        elif tag == "UTCDate":
            value, pos, cur_days = decode_utc_date(bits, pos, prev_days)
        elif tag == "UTCTime":
            value, pos, cur_secs = decode_utc_time(bits, pos, prev_secs)
        elif tag in ("White", "Black"):
            value, pos = decode_player_name(bits, pos, name_list)
        else:
            value, pos = decode_value(tag, bits, pos)
        lines.append(f'[{tag} "{value}"]')
    return "\n".join(lines), pos, cur_days, cur_secs
