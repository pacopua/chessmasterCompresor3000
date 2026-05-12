# chessmasterCompresor3000
## Dani: Codificación de partidas
## Alex: Codificación de categorías
b"ECO": b"\x8B" -> b00001
b"Opening": b"\x8C" -> b00010
b"TimeControl": b"\x8D" -> b00011
b"Termination": b"\x8E" -> b00100
b"WhiteTitle": b"\x8F" -> b00101
b"BlackTitle": b"\x90" -> b00110
b"WhiteElo": b"\x87" -> b00111
b"BlackElo": b"\x88" -> b01000
## Adri: Codificación de categorías
b"Event": b"\x80" -> b01001
b"Site": b"\x81" -> b01010
b"White": b"\x82" -> b01011
b"Black": b"\x83" -> b01100
b"Result": b"\x84" -> b01101
b"UTCDate": b"\x85" -> b01110
b"UTCTime": b"\x86" -> b01111
b"WhiteRatingDiff": b"\x89" -> b10000
b"BlackRatingDiff": b"\x8A" -> b10001
SEACABO : b00000
## Headers
HEADER_KEYS = {
    b"Event": b"\x80", b"Site": b"\x81", b"White": b"\x82", b"Black": b"\x83",
    b"Result": b"\x84", b"UTCDate": b"\x85", b"UTCTime": b"\x86", b"WhiteElo": b"\x87",
    b"BlackElo": b"\x88", b"WhiteRatingDiff": b"\x89", b"BlackRatingDiff": b"\x8A",
    b"ECO": b"\x8B", b"Opening": b"\x8C", b"TimeControl": b"\x8D", b"Termination": b"\x8E",
    b"WhiteTitle": b"\x8F", b"BlackTitle": b"\x90"
}