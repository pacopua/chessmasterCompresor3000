# chessmasterCompresor3000 — Current Implementation

Lossless PGN (chess game) compressor for Lichess-format game files.

---

## Team

| Member | Responsibility |
|--------|---------------|
| Dani   | Move encoding |
| Alex   | Tag-name encoding (ECO, Opening, TimeControl, Termination, WhiteTitle, BlackTitle, WhiteElo, BlackElo) |
| Adri   | Tag-name encoding (Event, Site, White, Black, Result, UTCDate, UTCTime, WhiteRatingDiff, BlackRatingDiff) + tag-value encoding + full-game encoder + annotation tokenization |

---

## Pipeline Overview

A PGN file is encoded in two conceptually independent sections that are then **combined and compressed together**:

```
PGN file
  ├─ Header lines  [Tag "Value"]  →  compact bitstream  (src/encode_headers.py)
  └─ Move lines                   →  tokenized bytes     (src/encode_game.py)
                                       ↓
                              LZW dictionary compression
                                       ↓
                           Huffman entropy coding
                                       ↓
                                 CPG3 file
```

---

## Header Encoding

Headers are encoded as a flat bitstream. Each game's headers end with the **SEACABO** marker so the decoder knows when to stop reading.

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

- Base: 14 bits (covers `0`–`16382` s). Base `16383` (all 1s) is the sentinel.
- Increment: 7 bits (covers `0`–`127` s). Not emitted when base is the sentinel.

#### `Site` — 48 bits (8 × 6-bit base62 characters)

Lichess game URLs always start with `https://lichess.org/`. Only the 8-character game ID is stored, with each character mapped to its index in the base62 alphabet `[0-9A-Za-z]` (6 bits each). Index `63` (all 1s) is the sentinel — raw UTF-8 follows.

#### `Event` — 6 bits

A lookup table of the 62 most common Lichess event strings (ordered by frequency). Index `63` (all 1s) is the sentinel — raw UTF-8 follows.

#### `Opening` — 11 bits

A lookup table of 1608 known opening names (ordered by frequency, in `src/openings.py`). Index `2047` (all 1s) is the sentinel — raw UTF-8 follows.

#### Tags stored as raw UTF-8 (`White`, `Black`)

Player names have too many unique values for a fixed table. Stored as: 8-bit byte-length + UTF-8 bytes.

---

## Header Bitstream Format

```
<game headers>  ::=  ( <5-bit tag code>  <value bits> )*  <SEACABO (00000)>
```

Unknown tag: `11111` + raw_string(tag_name) + raw_string(value)  
Raw string: `8-bit byte-length` + `N × 8-bit UTF-8 bytes`

All games are concatenated in a single bitstream. The decoder reads tag/value pairs until it hits `SEACABO`, then repeats for the next game.

---

## Move Encoding (Tokenization)

Before entropy coding, the move text is pre-processed in three passes to replace repetitive patterns with compact single-byte or multi-byte tokens.

### Pass 1 — Annotation extraction

`{ ... }` blocks are extracted and saved aside, replaced by a NUL placeholder (`\x00`). This prevents annotation content (e.g. the decimal point in `[%eval 12.34]`) from being corrupted by the subsequent regexes, and prevents the annotation token payloads (which can contain any byte value) from being corrupted by the result/square substitutions.

### Pass 2 — PGN text tokenization

Applied to the remaining move text (annotations already removed):

| Pattern | Token | Size before | Size after |
|---------|-------|-------------|------------|
| Board square `[a-h][1-8]` | `0x80`–`0xBF` (file×8+rank) | 2 bytes | 1 byte |
| Move number `1.` | `0xFD` | 2 bytes | 1 byte |
| Move numbers `2.`, `3.`, … | `0xFE` (decoder increments counter) | 2–4 bytes | 1 byte |
| `1-0` | `0xFB` | 3 bytes | 1 byte |
| `0-1` | `0xFC` | 3 bytes | 1 byte |
| `1/2-1/2` | `0xFA` | 7 bytes | 1 byte |
| `*` | `0xF9` | 1 byte | 1 byte |

### Pass 3 — Annotation token expansion

NUL placeholders are replaced with compact annotation tokens:

| Annotation | Token | Size before | Size after |
|------------|-------|-------------|------------|
| `{ [%eval X.XX] }` | `0x01` + int16 BE (centipawns) | ~16 bytes | 3 bytes |
| `{ [%eval #N] }` (mate-in-N) | `0x02` + int8 signed | ~14 bytes | 2 bytes |
| `{ [%clk H:MM:SS] }` | `0x03` + uint16 BE packed `[H:4\|MM:6\|SS:6]` | ~14 bytes | 3 bytes |
| Unknown annotation | `0x04` + uint8 length + raw bytes | original size | original size + 2 |

**Eval encoding detail**: centipawns = `round(pawn_eval × 100)`. On decode, `cp % 10 == 0` → 1 decimal place (e.g. `14.2`); otherwise → 2 decimal places (e.g. `0.19`). This matches the original Lichess/Stockfish formatting exactly.

### Game boundary encoding

Games are stored with **length-prefixed packing** (not a separator byte). This is necessary because annotation token payloads can contain any byte value.

```
all_tok  =  uint32_BE(n_games)
          + uint16_BE(len_game_1) + … + uint16_BE(len_game_N)
          + game_1_tokens + … + game_N_tokens
```

---

## Entropy Coding (LZW + Huffman)

The combined stream (encoded header bytes + tokenized move bytes) is compressed in two stages:

### LZW (Lempel-Ziv-Welch)

A dictionary-based compressor that replaces repeated byte sequences with integer codes. Dictionary capped at 65 535 entries to keep symbol values in uint16 range. Outputs a list of integer symbols.

### Huffman coding

A static Huffman tree is built from the LZW symbol frequencies. Each symbol is replaced with a variable-length bit code (shorter codes for more frequent symbols). The Huffman table is stored with the compressed data using **VLQ delta encoding**: symbols are sorted, and (delta, frequency) pairs are encoded with LEB128, saving ~20% table space vs. fixed-width entries.

---

## CPG3 File Format

```
Offset  Size  Field
------  ----  -----
0       4     Magic: b'CPG3'
4       4     uint32 BE — total bits in the header bitstream
8       4     uint32 BE — number of Huffman symbol table entries
12      4     uint32 BE — total number of LZW symbols
16      V     VLQ (delta, freq) pairs — Huffman symbol table
16+V    1     uint8 — padding bits at end of Huffman-coded data
17+V    M     LZW + Huffman compressed bytes
               (contains: header_bits_bytes + all_tok)
```

The decoder:
1. Reads the magic and header bit count.
2. Reads the Huffman table, decompresses the Huffman stream, decompresses LZW.
3. Splits the combined stream: first `ceil(n_bits/8)` bytes → header bitstream; rest → `all_tok`.
4. Decodes headers game by game (reads until SEACABO).
5. Decodes `all_tok` using `_unpack_game_tokens` to get per-game token slices.
6. Detokenizes each game's moves.
7. Reconstructs `[Tag "Value"]\n\n<moves>` for each game and joins with `\n\n`.

---

## Source Files

| File | Description |
|------|-------------|
| `src/types.py` | All encoding tables, reverse-lookup dicts, and numeric constants |
| `src/openings.py` | 1 608-entry opening name lookup table (11-bit encoding) |
| `src/encode_headers.py` | `encode_headers(text)` — parses a PGN header block and returns a `bitarray` |
| `src/decode_headers.py` | `decode_headers(bits, pos)` — decodes one game's headers from the bitstream |
| `src/encode_game.py` | `encode_pgn_file` / `decode_pgn_file` — full CPG3 pipeline |
| `src/arithmetic.py` | Arithmetic coder (CACM87 integer implementation) — not used in CPG3, available for experimentation |
| `src/encode_game_arithmetic.py` | CPG4 variant using LZW + arithmetic coding instead of Huffman |
| `main.py` | Entry point placeholder |
| `test_all.py` | Round-trip test against all files in `data/input/` |

---

## Compression Results

Tested on all 7 Lichess PGN datasets. All files pass a byte-exact round-trip check.

| File | Original | Compressed | Ratio |
|------|----------|------------|-------|
| SetPartides1.pgn | 1 708 094 B | 395 555 B | 4.32× |
| SetPartides2.pgn | 3 888 451 B | 1 058 646 B | 3.67× |
| SetPartides3.pgn | 3 101 892 B | 839 833 B | 3.69× |
| SetPartides4.pgn | 2 512 327 B | 678 317 B | 3.70× |
| SetPartides5.pgn | 5 638 618 B | 1 523 670 B | 3.70× |
| SetPartides6.pgn | 4 647 154 B | 1 264 512 B | 3.68× |
| SetPartides7.pgn | 3 616 474 B | 975 136 B | 3.71× |
| **TOTAL** | **25 113 010 B** | **6 735 669 B** | **3.73×** |

SetPartides1 compresses better (4.32×) because it is the only file with `%eval` annotations, which shrink from ~16 bytes to 3 bytes each.

---

## Possible Improvements

The current compression reaches **3.73× overall** (4.32× on annotation-heavy files). The target is **6×**. The following approaches are ordered by expected impact-to-effort ratio.

### 1. Castling tokenization — easy, ~0.05× gain

Replace `O-O` (3 bytes) and `O-O-O` (5 bytes) with single-byte tokens. Around 2 700 castling moves per dataset file. Negligible alone but trivial to implement.

### 2. Piece-move compaction — medium effort, ~0.3–0.5× gain

Currently a piece move like `Nc3` occupies 2 bytes after square tokenization (`N` + square token). A capture `Nxc3` occupies 3 bytes. We could combine piece letter + capture flag + check/mate flag + target square into a single 2-byte token, reducing most piece moves from 2–4 bytes to 2 bytes. 84 747 piece letters + 28 087 captures + 8 935 checks across the full dataset.

### 3. BWT + MTF preprocessing — medium effort, ~1–1.5× gain

The Burrows-Wheeler Transform rearranges bytes so that repeated substrings cluster into long runs of identical bytes. Move-to-Front (MTF) encoding then converts those runs into mostly small integers. LZW + Huffman then operates on a much more compressible stream. This is the same approach used by bzip2 and can realistically push the ratio to **5–5.5×** without any chess-domain knowledge.

### 4. Legal move indexing — high effort, ~3–4× gain on moves

The highest-impact approach. For each board position, compute all legal moves, sort them by a canonical ordering, and encode each move as its **rank index** (0 to N-1 where N ≈ 30–35 legal moves on average). This requires only `log2(30) ≈ 5 bits` per move vs. the current 10–25 bytes of SAN notation.

Estimated move-section size after indexing (1840 games × 80 moves × 5 bits): ~92 KB vs. the current ~824 KB. Combined with the already-compact header encoding, this would push the overall ratio to **7–8×**.

Requires implementing a complete chess move generator (piece movement rules, legality checking, castling, en passant, promotion) from scratch.

### 5. Context-based (PPM) arithmetic coding — high effort, ~1.5× gain

Prediction by Partial Matching builds an adaptive probability model based on the history of recent symbols. The arithmetic coder assigns fractional bit lengths according to these context-dependent probabilities. PPM consistently outperforms LZW + Huffman on structured text data and can realistically reach **5.5–6×** on its own, without chess-domain knowledge.

### 6. Player-name deduplication — low-medium effort, ~0.1× gain

Many games in a file share the same players. Currently each player name is stored as a raw UTF-8 string in the header bitstream. A simple dictionary (built on first pass, index stored in second pass) would deduplicate repeated names. Significant for tournament files where the same players appear hundreds of times.

### Summary table

| Approach | Estimated ratio | Effort |
|----------|-----------------|--------|
| Current (CPG3 + annotations) | 3.73× | done |
| + Castling tokens | ~3.80× | low |
| + Piece-move compaction | ~4.1–4.3× | medium |
| + BWT + MTF | ~5.0–5.5× | medium |
| + PPM coding | ~5.5–6.0× | high |
| + Legal move indexing | ~7.0–8.0× | very high |
