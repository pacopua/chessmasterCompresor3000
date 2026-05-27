import re
from datetime import date as _date, timedelta as _timedelta
import bitarray as bitLib
from .openings import opening_to_bits
from .constant_types import (
    headers_bit_encoding,
    result_to_bits, termination_to_bits, title_to_bits, eco_letter_to_bits,
    event_to_bits,
    ELO_BITS, ELO_UNKNOWN, ELO_MAX_VALID,
    RATING_DIFF_MAG_BITS, RATING_DIFF_UNKNOWN_MAG, RATING_DIFF_MAX_MAG,
    UTC_DATE_BASE_YEAR, UTC_DATE_YEAR_BITS, UTC_DATE_MONTH_BITS, UTC_DATE_DAY_BITS,
    UTC_DATE_UNKNOWN_YEAR,
    UTC_TIME_BITS, UTC_TIME_UNKNOWN,
    TIME_CONTROL_BASE_BITS, TIME_CONTROL_INC_BITS, TIME_CONTROL_UNKNOWN_BASE,
    SITE_PREFIX, SITE_ID_LEN, SITE_CHAR_BITS, SITE_CHAR_TO_IDX, SITE_UNKNOWN,
    RAW_STRING_LEN_BITS,
)

_HEADER_RE = re.compile(r'\[(\w+)\s+"([^"]*)"\]')

_EPOCH = _date(UTC_DATE_BASE_YEAR, 1, 1)
_UTC_DATE_DELTA_OFFSET = 63   # 7-bit delta [-63,+63] stored as [0,126]; 127 unused (flag scheme has no sentinel)
_UTC_TIME_DELTA_OFFSET = 63   # same 7-bit scheme for time

def _date_to_days(year: int, month: int, day: int) -> int:
    return (_date(year, month, day) - _EPOCH).days

# This function is here for the sections that cannot be encoded. Or also for the values we don't take into account. Each tag from the header has a set of values accounted for, but if the value is not in that set, we encode it as UNKNOWN_TEXT and then the raw UTF-8 string, in that case the decoder will jus read the string as normal and that is that!
def _raw_string(value: str) -> bitLib.bitarray:
    """8-bit byte-length followed by the UTF-8 bytes."""
    raw = value.encode("utf-8")
    bits = bitLib.bitarray()
    bits.extend(format(len(raw), f"0{RAW_STRING_LEN_BITS}b"))
    bits.frombytes(raw)
    return bits


def _int_bits(value: int, width: int) -> bitLib.bitarray:
    return bitLib.bitarray(format(value, f"0{width}b"))


# --- Individual value encoders ---

def encode_result(value: str) -> bitLib.bitarray:
    if value in result_to_bits and value != "UNKNOWN_TEXT":
        return bitLib.bitarray(result_to_bits[value])
    return bitLib.bitarray(result_to_bits["UNKNOWN_TEXT"]) + _raw_string(value)


def encode_termination(value: str) -> bitLib.bitarray:
    if value in termination_to_bits and value != "UNKNOWN_TEXT":
        return bitLib.bitarray(termination_to_bits[value])
    return bitLib.bitarray(termination_to_bits["UNKNOWN_TEXT"]) + _raw_string(value)


def encode_title(value: str) -> bitLib.bitarray:
    if value in title_to_bits and value != "UNKNOWN_TEXT":
        return bitLib.bitarray(title_to_bits[value])
    return bitLib.bitarray(title_to_bits["UNKNOWN_TEXT"]) + _raw_string(value)


def encode_eco(value: str) -> bitLib.bitarray:
    try:
        letter, number = value[0], int(value[1:])
        if letter in eco_letter_to_bits and letter != "UNKNOWN_TEXT" and 0 <= number <= 99:
            return bitLib.bitarray(eco_letter_to_bits[letter]) + _int_bits(number, 7)
    except (ValueError, IndexError):
        pass
    return bitLib.bitarray(eco_letter_to_bits["UNKNOWN_TEXT"]) + _raw_string(value)


def encode_elo(value: str) -> bitLib.bitarray:
    try:
        elo = int(value)
        if 0 <= elo <= ELO_MAX_VALID:
            return _int_bits(elo, ELO_BITS)
    except ValueError:
        pass
    return _int_bits(ELO_UNKNOWN, ELO_BITS) + _raw_string(value)


def encode_rating_diff(value: str) -> bitLib.bitarray:
    try:
        negative = value.startswith("-")
        magnitude = abs(int(value))
        if magnitude <= RATING_DIFF_MAX_MAG:
            sign_bit = bitLib.bitarray("1" if negative else "0")
            return sign_bit + _int_bits(magnitude, RATING_DIFF_MAG_BITS)
    except ValueError:
        pass
    return bitLib.bitarray("0") + _int_bits(RATING_DIFF_UNKNOWN_MAG, RATING_DIFF_MAG_BITS) + _raw_string(value)


def _abs_date_bits(year_offset: int, m: int, d: int) -> bitLib.bitarray:
    return (
        _int_bits(year_offset, UTC_DATE_YEAR_BITS)
        + _int_bits(m, UTC_DATE_MONTH_BITS)
        + _int_bits(d, UTC_DATE_DAY_BITS)
    )


def encode_utc_date(value: str, prev_days: int | None = None) -> tuple[bitLib.bitarray, int | None]:
    """Returns (bits, current_day_count_or_None).

    When prev_days is supplied, uses a 3-tier delta prefix:
      "0"         — same day (1 bit)
      "10" + 7b   — delta in [-63,+63] (9 bits)
      "11" + 16b  — absolute fallback (18 bits)
    First game (prev_days=None) uses the legacy 16-bit absolute encoding.
    """
    try:
        y, m, d = (int(p) for p in value.split("."))
        year_offset = y - UTC_DATE_BASE_YEAR
        if 0 <= year_offset < UTC_DATE_UNKNOWN_YEAR and 1 <= m <= 12 and 1 <= d <= 31:
            cur_days = _date_to_days(y, m, d)
            if prev_days is not None:
                delta = cur_days - prev_days
                if delta == 0:
                    return bitLib.bitarray("0"), cur_days
                if -_UTC_DATE_DELTA_OFFSET <= delta <= _UTC_DATE_DELTA_OFFSET:
                    return bitLib.bitarray("10") + _int_bits(delta + _UTC_DATE_DELTA_OFFSET, 7), cur_days
                return bitLib.bitarray("11") + _abs_date_bits(year_offset, m, d), cur_days
            return _abs_date_bits(year_offset, m, d), cur_days
    except (ValueError, AttributeError):
        pass
    # Unknown date
    unknown_bits = _int_bits(UTC_DATE_UNKNOWN_YEAR, UTC_DATE_YEAR_BITS) + _raw_string(value)
    if prev_days is not None:
        return bitLib.bitarray("11") + unknown_bits, None
    return unknown_bits, None


def encode_utc_time(value: str, prev_secs: int | None = None) -> tuple[bitLib.bitarray, int | None]:
    """Returns (bits, current_seconds_or_None).

    When prev_secs is supplied, uses a 2-tier delta prefix:
      "0" + 7b   — delta in [-63,+63] (8 bits)
      "1" + 17b  — absolute fallback (18 bits)
    First game (prev_secs=None) uses the legacy 17-bit absolute encoding.
    """
    try:
        h, m, s = (int(p) for p in value.split(":"))
        total = h * 3600 + m * 60 + s
        if total < UTC_TIME_UNKNOWN:
            if prev_secs is not None:
                delta = total - prev_secs
                if -_UTC_TIME_DELTA_OFFSET <= delta <= _UTC_TIME_DELTA_OFFSET:
                    return bitLib.bitarray("0") + _int_bits(delta + _UTC_TIME_DELTA_OFFSET, 7), total
                return bitLib.bitarray("1") + _int_bits(total, UTC_TIME_BITS), total
            return _int_bits(total, UTC_TIME_BITS), total
    except (ValueError, AttributeError):
        pass
    # Unknown time
    unknown_bits = _int_bits(UTC_TIME_UNKNOWN, UTC_TIME_BITS) + _raw_string(value)
    if prev_secs is not None:
        return bitLib.bitarray("1") + unknown_bits, None
    return unknown_bits, None


def encode_opening(value: str) -> bitLib.bitarray:
    if value in opening_to_bits and value != "UNKNOWN_TEXT":
        return bitLib.bitarray(opening_to_bits[value])
    return bitLib.bitarray(opening_to_bits["UNKNOWN_TEXT"]) + _raw_string(value)


def encode_event(value: str) -> bitLib.bitarray:
    if value in event_to_bits and value != "UNKNOWN_TEXT":
        return bitLib.bitarray(event_to_bits[value])
    return bitLib.bitarray(event_to_bits["UNKNOWN_TEXT"]) + _raw_string(value)


def encode_site(value: str) -> bitLib.bitarray:
    if value.startswith(SITE_PREFIX):
        game_id = value[len(SITE_PREFIX):]
        if len(game_id) == SITE_ID_LEN and all(c in SITE_CHAR_TO_IDX for c in game_id):
            bits = bitLib.bitarray()
            for c in game_id:
                bits.extend(_int_bits(SITE_CHAR_TO_IDX[c], SITE_CHAR_BITS))
            return bits
    return _int_bits(SITE_UNKNOWN, SITE_CHAR_BITS) + _raw_string(value)


def encode_time_control(value: str) -> bitLib.bitarray:
    try:
        base_str, inc_str = value.split("+")
        base, inc = int(base_str), int(inc_str)
        if base < TIME_CONTROL_UNKNOWN_BASE and inc < (1 << TIME_CONTROL_INC_BITS):
            return _int_bits(base, TIME_CONTROL_BASE_BITS) + _int_bits(inc, TIME_CONTROL_INC_BITS)
    except (ValueError, AttributeError):
        pass
    return _int_bits(TIME_CONTROL_UNKNOWN_BASE, TIME_CONTROL_BASE_BITS) + _raw_string(value)

# just a bit of itty bitty of functional programming!
# UTCDate and UTCTime are handled separately in encode_headers (they carry inter-game state).
VALUE_ENCODERS = {
    "Result":          encode_result,
    "Termination":     encode_termination,
    "WhiteTitle":      encode_title,
    "BlackTitle":      encode_title,
    "ECO":             encode_eco,
    "WhiteElo":        encode_elo,
    "BlackElo":        encode_elo,
    "WhiteRatingDiff": encode_rating_diff,
    "BlackRatingDiff": encode_rating_diff,
    "TimeControl":     encode_time_control,
    "Site":            encode_site,
    "Event":           encode_event,
    "Opening":         encode_opening,
}


def encode_value(tag: str, value: str) -> bitLib.bitarray:
    """Encode a single tag value. Tags without compact encoding use raw UTF-8."""
    encoder = VALUE_ENCODERS.get(tag)
    if encoder:
        return encoder(value)
    return _raw_string(value)


def encode_headers(
    text: str,
    prev_days: int | None = None,
    prev_secs: int | None = None,
) -> tuple[bitLib.bitarray, int | None, int | None]:
    """
    Encode a PGN header block to bits.

    prev_days / prev_secs: day-count / second-of-day from the previous game,
    used to write compact delta codes for UTCDate / UTCTime.  Pass None for
    the first game in a file (falls back to legacy absolute encoding).

    Returns (bits, cur_days, cur_secs) — the current game's date/time values
    to be forwarded as prev_* when encoding the next game.
    """
    bits = bitLib.bitarray()
    cur_days: int | None = prev_days
    cur_secs: int | None = prev_secs

    for line in text.splitlines():
        if not line.strip():
            break
        m = _HEADER_RE.match(line.strip())
        if not m:
            continue
        tag, value = m.group(1), m.group(2)
        if tag in headers_bit_encoding and tag not in ("SEACABO", "UNKNOWN_TAG"):
            bits.extend(headers_bit_encoding[tag])
            if tag == "UTCDate":
                tag_bits, cur_days = encode_utc_date(value, prev_days)
                bits.extend(tag_bits)
            elif tag == "UTCTime":
                tag_bits, cur_secs = encode_utc_time(value, prev_secs)
                bits.extend(tag_bits)
            else:
                bits.extend(encode_value(tag, value))
        else:
            bits.extend(headers_bit_encoding["UNKNOWN_TAG"])
            bits.extend(_raw_string(tag))
            bits.extend(_raw_string(value))
    bits.extend(headers_bit_encoding["SEACABO"])
    return bits, cur_days, cur_secs

def strip_non_headers(text: str) -> str:
    """
    Return only the header lines from a PGN string (supports multiple games).

    State machine:
      - Starts in header mode.
      - A [ line always means we're in headers (new game or continuing).
      - A blank line after headers flips to moves mode.
      - Move lines are dropped.
    Each game's header block is separated by a blank line in the output.
    """
    result = []
    in_headers = True

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            if not in_headers:
                result.append("")   # blank line between game blocks
            in_headers = True
            result.append(line)
        elif not stripped:
            if in_headers:
                in_headers = False  # blank line ends this game's headers
        # move lines are silently dropped

    return "\n".join(result)


def strip_non_headers_from_file(path: str) -> str:
    """Read a PGN file and return only its header lines."""
    with open(path, "r", encoding="utf-8") as f:
        return strip_non_headers(f.read())


def main():
    print("yowasup")

if __name__ == "__main__":
    main()

    