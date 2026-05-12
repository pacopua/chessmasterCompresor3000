# chessmasterCompresor3000
## Dani: Codificación de partidas
## Alex: Codificación de categorías
b"ECO": b"\x8B"
b"Opening": b"\x8C"
b"TimeControl": b"\x8D"
b"Termination": b"\x8E"
b"WhiteTitle": b"\x8F"
b"BlackTitle": b"\x90"
b"WhiteElo": b"\x87",
b"BlackElo": b"\x88"
## Adri: Codificación de categorías
b"Event": b"\x80"
b"Site": b"\x81"
b"White": b"\x82"
b"Black": b"\x83",
b"Result": b"\x84"
b"UTCDate": b"\x85"
b"UTCTime": b"\x86"
b"WhiteRatingDiff": b"\x89"
b"BlackRatingDiff": b"\x8A"
## Headers
HEADER_KEYS = {
    b"Event": b"\x80", b"Site": b"\x81", b"White": b"\x82", b"Black": b"\x83",
    b"Result": b"\x84", b"UTCDate": b"\x85", b"UTCTime": b"\x86", b"WhiteElo": b"\x87",
    b"BlackElo": b"\x88", b"WhiteRatingDiff": b"\x89", b"BlackRatingDiff": b"\x8A",
    b"ECO": b"\x8B", b"Opening": b"\x8C", b"TimeControl": b"\x8D", b"Termination": b"\x8E",
    b"WhiteTitle": b"\x8F", b"BlackTitle": b"\x90"
}