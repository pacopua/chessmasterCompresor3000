import bitarray as bitLib

headers_bit_encoding: dict[str, bitLib.bitarray] = {
    "ECO":             bitLib.bitarray("00001"),
    "Opening":         bitLib.bitarray("00010"),
    "TimeControl":     bitLib.bitarray("00011"),
    "Termination":     bitLib.bitarray("00100"),
    "WhiteTitle":      bitLib.bitarray("00101"),
    "BlackTitle":      bitLib.bitarray("00110"),
    "WhiteElo":        bitLib.bitarray("00111"),
    "BlackElo":        bitLib.bitarray("01000"),
    "Event":           bitLib.bitarray("01001"),
    "Site":            bitLib.bitarray("01010"),
    "White":           bitLib.bitarray("01011"),
    "Black":           bitLib.bitarray("01100"),
    "Result":          bitLib.bitarray("01101"),
    "UTCDate":         bitLib.bitarray("01110"),
    "UTCTime":         bitLib.bitarray("01111"),
    "WhiteRatingDiff": bitLib.bitarray("10000"),
    "BlackRatingDiff": bitLib.bitarray("10001"),
    "SEACABO":         bitLib.bitarray("00000"),
    "UNKNOWN_TAG":     bitLib.bitarray("11111"),  # raw tag name + raw value follow
}
# Reverse lookup: 5-bit pattern → tag name
headers_bit_decoding: dict[str, str] = {v.to01(): k for k, v in headers_bit_encoding.items()}

# ---------------------------------------------------------------------------
# Value encoding tables
#
# Convention: each tag has a fixed mapping from known values to compact bits.
# Every table includes an UNKNOWN_TEXT sentinel — a reserved bit pattern that
# signals "a raw UTF-8 string follows (8-bit byte-length + bytes)".
# Decoders that see the sentinel read the trailing string instead of looking
# up a value, so any unexpected input survives a round-trip without a schema
# change.
# ---------------------------------------------------------------------------

# Result: 3 bits — "100" = UNKNOWN_TEXT sentinel (raw UTF-8 follows)
result_to_bits: dict[str, bitLib.bitarray] = {
    "1-0":          bitLib.bitarray("000"),
    "0-1":          bitLib.bitarray("001"),
    "1/2-1/2":      bitLib.bitarray("010"),
    "*":            bitLib.bitarray("011"),
    "UNKNOWN_TEXT": bitLib.bitarray("100"),
}
bits_to_result: dict[str, str] = {v.to01(): k for k, v in result_to_bits.items()}

# Termination: 3 bits — "100" = UNKNOWN_TEXT sentinel (raw UTF-8 follows)
termination_to_bits: dict[str, bitLib.bitarray] = {
    "Normal":           bitLib.bitarray("000"),
    "Time forfeit":     bitLib.bitarray("001"),
    "Abandoned":        bitLib.bitarray("010"),
    "Rules infraction": bitLib.bitarray("011"),
    "UNKNOWN_TEXT":     bitLib.bitarray("100"),
}
bits_to_termination: dict[str, str] = {v.to01(): k for k, v in termination_to_bits.items()}

# WhiteTitle / BlackTitle: 3 bits — 110 reserved as UNKNOWN_TEXT sentinel
title_to_bits: dict[str, bitLib.bitarray] = {
    "GM":           bitLib.bitarray("000"),
    "IM":           bitLib.bitarray("001"),
    "FM":           bitLib.bitarray("010"),
    "NM":           bitLib.bitarray("011"),
    "CM":           bitLib.bitarray("100"),
    "LM":           bitLib.bitarray("101"),
    "UNKNOWN_TEXT": bitLib.bitarray("110"),   # raw UTF-8 string follows
}
bits_to_title: dict[str, str] = {v.to01(): k for k, v in title_to_bits.items()}

# ECO: 3 bits letter + 7 bits number = 10 bits total
# Letter sentinel 101 = UNKNOWN_TEXT (raw UTF-8 follows instead of 7 number bits)
eco_letter_to_bits: dict[str, bitLib.bitarray] = {
    "A":            bitLib.bitarray("000"),
    "B":            bitLib.bitarray("001"),
    "C":            bitLib.bitarray("010"),
    "D":            bitLib.bitarray("011"),
    "E":            bitLib.bitarray("100"),
    "UNKNOWN_TEXT": bitLib.bitarray("101"),   # raw UTF-8 string follows (no number bits)
}
bits_to_eco_letter: dict[str, str] = {v.to01(): k for k, v in eco_letter_to_bits.items()}

# WhiteElo / BlackElo: 12-bit unsigned int (0–4094)
# 4095 (all 1s) = UNKNOWN_TEXT sentinel
ELO_BITS        = 12
ELO_UNKNOWN     = (1 << ELO_BITS) - 1   # 4095  →  raw UTF-8 follows
ELO_MAX_VALID   = ELO_UNKNOWN - 1       # 4094

# WhiteRatingDiff / BlackRatingDiff: 1 sign bit + 9 magnitude bits
# Magnitude 511 (all 1s) = UNKNOWN_TEXT sentinel
RATING_DIFF_MAG_BITS    = 9
RATING_DIFF_UNKNOWN_MAG = (1 << RATING_DIFF_MAG_BITS) - 1   # 511  →  raw UTF-8 follows
RATING_DIFF_MAX_MAG     = RATING_DIFF_UNKNOWN_MAG - 1        # 510

# UTCDate: 7-bit year-offset-from-1970 + 4-bit month + 5-bit day = 16 bits
# Year-offset 127 (all 1s) = UNKNOWN_TEXT sentinel
UTC_DATE_BASE_YEAR      = 1970
UTC_DATE_YEAR_BITS      = 7
UTC_DATE_MONTH_BITS     = 4
UTC_DATE_DAY_BITS       = 5
UTC_DATE_UNKNOWN_YEAR   = (1 << UTC_DATE_YEAR_BITS) - 1   # 127  →  raw UTF-8 follows

# UTCTime: 17-bit seconds-of-day (0–86399)
# 131071 (all 1s, > 86399) = UNKNOWN_TEXT sentinel
UTC_TIME_BITS    = 17
UTC_TIME_UNKNOWN = (1 << UTC_TIME_BITS) - 1   # 131071  →  raw UTF-8 follows

# TimeControl: 14-bit base seconds + 7-bit increment = 21 bits
# Base 16383 (all 1s) = UNKNOWN_TEXT sentinel
TIME_CONTROL_BASE_BITS    = 14
TIME_CONTROL_INC_BITS     = 7
TIME_CONTROL_UNKNOWN_BASE = (1 << TIME_CONTROL_BASE_BITS) - 1   # 16383  →  raw UTF-8 follows

# Event: 6 bits — index 63 (all 1s) = UNKNOWN_TEXT sentinel
# Values ordered by frequency so the most common get the smallest indices,
# which helps if an entropy-coding layer is added later.
_EVENT_STRINGS = [
    "Rated Blitz game",
    "Rated Classical game",
    "Rated Bullet game",
    "Rated Correspondence game",
    "Rated Bullet tournament https://lichess.org/tournament/eJuOmDtR",
    "Rated Classical tournament https://lichess.org/tournament/riSmNP1H",
    "Rated Bullet tournament https://lichess.org/tournament/BFF1WBYs",
    "Rated Blitz tournament https://lichess.org/tournament/rPTa1eCG",
    "Rated Bullet tournament https://lichess.org/tournament/U2hkwBoK",
    "Rated Blitz tournament https://lichess.org/tournament/vPqL4MHt",
    "Rated Classical tournament https://lichess.org/tournament/apah3ohD",
    "Rated Blitz tournament https://lichess.org/tournament/9sxfYO8r",
    "Rated Blitz tournament https://lichess.org/tournament/UnmOkHnO",
    "Rated Blitz tournament https://lichess.org/tournament/2WQWjpVr",
    "Rated Blitz tournament https://lichess.org/tournament/lYCPRxNZ",
    "Rated Classical tournament https://lichess.org/tournament/nw02CTYi",
    "Rated Blitz tournament https://lichess.org/tournament/vRCsJQ8u",
    "Rated Blitz tournament https://lichess.org/tournament/3Ic7BIiC",
    "Rated Blitz tournament https://lichess.org/tournament/1TLHHMb1",
    "Rated Blitz tournament https://lichess.org/tournament/lOL4IauU",
    "Rated Blitz tournament https://lichess.org/tournament/RMWGlxes",
    "Rated Classical tournament https://lichess.org/tournament/mWvUjjXT",
    "Rated Bullet tournament https://lichess.org/tournament/lAGrIoiW",
    "Rated Blitz tournament https://lichess.org/tournament/0dbHoY88",
    "Rated Blitz tournament https://lichess.org/tournament/0EBP60tX",
    "Rated Blitz tournament https://lichess.org/tournament/uzgRZ9IA",
    "Rated Bullet tournament https://lichess.org/tournament/GtGzTF8O",
    "Rated Bullet tournament https://lichess.org/tournament/y5UqP1by",
    "Rated Blitz tournament https://lichess.org/tournament/27DAKVR1",
    "Rated Blitz tournament https://lichess.org/tournament/l1r0rZa9",
    "Rated Blitz tournament https://lichess.org/tournament/DoIGjlbp",
    "Rated Bullet tournament https://lichess.org/tournament/YToLeY1g",
    "Rated Bullet tournament https://lichess.org/tournament/xXcqfQgR",
    "Rated Blitz tournament https://lichess.org/tournament/ydvesvai",
    "Rated Blitz tournament https://lichess.org/tournament/MlbPnVjD",
    "Rated Bullet tournament https://lichess.org/tournament/if2eqc3O",
    "Rated Blitz tournament https://lichess.org/tournament/115UbdfR",
    "Rated Classical tournament https://lichess.org/tournament/HyT8DUrp",
    "Rated Blitz tournament https://lichess.org/tournament/02had06t",
    "Rated Bullet tournament https://lichess.org/tournament/68gjypew",
    "Rated Blitz tournament https://lichess.org/tournament/i1fiwlgk",
    "Rated Blitz tournament https://lichess.org/tournament/xpwue0nd",
    "Rated Blitz tournament https://lichess.org/tournament/hvPdb8ps",
    "Rated Blitz tournament https://lichess.org/tournament/9zgf350e",
    "Rated Blitz tournament https://lichess.org/tournament/wCoi5XXP",
    "Rated Bullet tournament https://lichess.org/tournament/THT5fc36",
    "Rated Blitz tournament https://lichess.org/tournament/wabLyQbF",
    "Rated Blitz tournament https://lichess.org/tournament/xF4zE8tl",
    "Rated Blitz tournament https://lichess.org/tournament/FrHTzWue",
    "Rated Classical tournament https://lichess.org/tournament/rIxo1iu2",
]
EVENT_BITS = 6
EVENT_UNKNOWN = (1 << EVENT_BITS) - 1   # 63 → raw UTF-8 follows
event_to_bits: dict[str, bitLib.bitarray] = {
    s: bitLib.bitarray(format(i, f"0{EVENT_BITS}b")) for i, s in enumerate(_EVENT_STRINGS)
}
event_to_bits["UNKNOWN_TEXT"] = bitLib.bitarray(format(EVENT_UNKNOWN, f"0{EVENT_BITS}b"))
bits_to_event: dict[str, str] = {v.to01(): k for k, v in event_to_bits.items()}

# Site: strip constant prefix, encode the 8-char base62 game ID
# Characters [0-9A-Za-z] map to indices 0–61 (6 bits each, covers 0–63)
# Index 63 (all 1s) = UNKNOWN_TEXT sentinel — raw UTF-8 follows
SITE_PREFIX     = "https://lichess.org/"
SITE_ID_LEN     = 8
SITE_CHAR_BITS  = 6
SITE_CHARS      = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
SITE_CHAR_TO_IDX: dict[str, int] = {c: i for i, c in enumerate(SITE_CHARS)}
SITE_IDX_TO_CHAR: dict[int, str] = {i: c for i, c in enumerate(SITE_CHARS)}
SITE_UNKNOWN    = (1 << SITE_CHAR_BITS) - 1   # 63 → raw UTF-8 follows

# Raw-string encoding used by all UNKNOWN_TEXT sentinels:
#   8-bit byte-length  +  N bytes UTF-8
RAW_STRING_LEN_BITS = 8
