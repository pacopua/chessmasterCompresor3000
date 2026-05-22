# chessmasterCompresor3000

Lossless PGN (chess game) compressor for Lichess-format game files.

---

## Team

| Member | Responsibility |
|--------|---------------|
| Dani   | Move encoding |
| Alex   | Tag-name encoding (ECO, Opening, TimeControl, Termination, WhiteTitle, BlackTitle, WhiteElo, BlackElo) |
| Adri   | Tag-name encoding (Event, Site, White, Black, Result, UTCDate, UTCTime, WhiteRatingDiff, BlackRatingDiff) + **tag-value encoding** |

---

## Header Encoding — `src/`

Headers are encoded as a flat bitstream. Each game's headers end with the **SEACABO** marker so the decoder knows when to stop.

### Tag-name encoding (5 bits)

Every known tag is assigned a fixed 5-bit code. `SEACABO` (`00000`) marks the end of a game's headers. `UNKNOWN_TAG` (`11111`) is a sentinel for tag names not in the table — the raw tag name and value follow as UTF-8 strings.

| Tag | Code |
|-----|------|
| `SEACABO` *(end marker)* | `00000` |
| `ECO` | `00001` |
| `Opening` | `00010` |
| `TimeControl` | `00011` |
| `Termination` | `00100` |
| `WhiteTitle` | `00101` |
| `BlackTitle` | `00110` |
| `WhiteElo` | `00111` |
| `BlackElo` | `01000` |
| `Event` | `01001` |
| `Site` | `01010` |
| `White` | `01011` |
| `Black` | `01100` |
| `Result` | `01101` |
| `UTCDate` | `01110` |
| `UTCTime` | `01111` |
| `WhiteRatingDiff` | `10000` |
| `BlackRatingDiff` | `10001` |
| `UNKNOWN_TAG` *(fallback)* | `11111` |

### Tag-value encoding

Each tag value is encoded compactly. Every encoding scheme reserves one **sentinel** bit pattern — when the decoder reads it, it knows a raw UTF-8 string follows instead of a compact value. The raw string is prefixed with an 8-bit byte-length field.

This means any unexpected value (new title, new result format, etc.) always survives a round-trip without a schema change.

#### `Result` — 3 bits

| Value | Bits |
|-------|------|
| `1-0` | `000` |
| `0-1` | `001` |
| `1/2-1/2` | `010` |
| `*` | `011` |
| *(unknown — raw UTF-8 follows)* | `100` |

#### `Termination` — 3 bits

| Value | Bits |
|-------|------|
| `Normal` | `000` |
| `Time forfeit` | `001` |
| `Abandoned` | `010` |
| `Rules infraction` | `011` |
| *(unknown — raw UTF-8 follows)* | `100` |

#### `WhiteTitle` / `BlackTitle` — 3 bits

| Value | Bits |
|-------|------|
| `GM` | `000` |
| `IM` | `001` |
| `FM` | `010` |
| `NM` | `011` |
| `CM` | `100` |
| `LM` | `101` |
| *(unknown — raw UTF-8 follows)* | `110` |

#### `ECO` — 10 bits (3-bit letter + 7-bit number)

The ECO code is split into its letter (`A`–`E`) and numeric part (`00`–`99`). Letter sentinel `101` signals an unknown value.

| Letter | Bits |
|--------|------|
| `A` | `000` |
| `B` | `001` |
| `C` | `010` |
| `D` | `011` |
| `E` | `100` |
| *(unknown — raw UTF-8 follows)* | `101` |

Number: 7 bits unsigned integer (`0`–`99`). Not emitted when letter is unknown.

#### `WhiteElo` / `BlackElo` — 12 bits

Unsigned integer, covers `0`–`4094`. Value `4095` (all 1s) is the sentinel — raw UTF-8 follows.

#### `WhiteRatingDiff` / `BlackRatingDiff` — 10 bits (1 sign + 9 magnitude)

Format: `+N` or `-N`.

- Bit 0: `0` = positive, `1` = negative.
- Bits 1–9: magnitude (`0`–`510`). Magnitude `511` (all 1s) is the sentinel.

#### `UTCDate` — 16 bits (7-bit year offset + 4-bit month + 5-bit day)

- Year: 7-bit offset from 1970 (covers 1970–2096). Offset `127` (all 1s) is the sentinel.
- Month: 4 bits (`1`–`12`).
- Day: 5 bits (`1`–`31`). Month and day are not emitted when year is the sentinel.

#### `UTCTime` — 17 bits

Seconds of the day (`0`–`86399`). Value `131071` (all 1s, > 86399) is the sentinel.

#### `TimeControl` — 21 bits (14-bit base + 7-bit increment)

Format: `base+increment` (both in seconds).

- Base: 14 bits (covers `0`–`16382` s ≈ 4.5 h). Base `16383` (all 1s) is the sentinel.
- Increment: 7 bits (covers `0`–`127` s). Not emitted when base is the sentinel.

#### `Site` — 48 bits (8 × 6-bit base62 characters)

Lichess game URLs always start with `https://lichess.org/`. Only the 8-character game ID is stored, with each character mapped to its index in the base62 alphabet `[0-9A-Za-z]` (6 bits each). Index `63` (all 1s, outside the 62-char range) is the sentinel — raw UTF-8 follows.

Saves ~200 bits per game compared to raw string encoding.

#### Tags without compact encoding (`White`, `Black`, `Opening`, `Event`)

These are stored directly as raw UTF-8 strings (8-bit length + bytes). Player names and opening names have too many unique values to encode with a fixed table.

---

## Bitstream format

```
<game 1 headers>  ::=  ( <5-bit tag code> <value bits> )*  <SEACABO>
<game 2 headers>  ::=  ( <5-bit tag code> <value bits> )*  <SEACABO>
...
```

Unknown tag: `11111` + raw_string(tag_name) + raw_string(value)  
Raw string: `8-bit byte-length` + `N × 8 bits UTF-8`

---

## Source files

| File | Description |
|------|-------------|
| `src/types.py` | All encoding tables, reverse-lookup dicts, and numeric constants |
| `src/encode_headers.py` | `encode_headers(text)` — parses a PGN header block and returns a `bitarray`; `strip_non_headers(text)` — strips move lines from PGN text |
| `src/decode_headers.py` | `decode_headers(bits, pos)` — decodes a game's headers from a bitstream, returns reconstructed `[Tag "Value"]` lines and new position |

---

## Compression results (SetPartides1.pgn)

| Stage | Size |
|-------|------|
| Original PGN (all content) | — |
| Headers-only text (`SetPartides1_headers.pgn`) | 653 KB |
| Encoded headers (`SetPartides1_headers.bin`) | **191 KB** |
| Compression ratio (headers only) | **3.42×** |

Output files are written to `data/output/`.
