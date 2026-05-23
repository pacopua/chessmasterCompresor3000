# SmartCodec + Header Encoding: CPG4 Format

## Overview

CPG4 is a chess PGN compressor that combines two complementary strategies:

1. **Semantic header encoding** — each PGN tag is compressed individually using domain knowledge (known event names, ELO ranges, ECO codes, dates, etc.) into a compact bitstream.
2. **Move compression** — move tokens (squares, move numbers, results, clock annotations) are substituted with compact byte tokens, then the token stream is compressed with LZW followed by Huffman coding.

The key design insight is that these two strategies are kept **separate in the file**. Headers are stored as raw bits (already at their information-theoretic floor for known fields), and LZW+Huffman runs only on the move stream where it can fully exploit cross-game repetition.

---

## How It Works

### Header Encoding (`src/encode_headers.py`)

Each PGN tag gets a 5-bit tag identifier. Known tags have purpose-built value encoders:

| Tag              | Encoding                                                       |
|------------------|----------------------------------------------------------------|
| `Event`          | Index into a table of ~30 known Lichess event types           |
| `Site`           | `https://lichess.org/` prefix stripped; 8-char ID encoded at 6 bits/char |
| `WhiteElo`/`BlackElo` | 13-bit integer (0–8191); sentinel for unknown              |
| `WhiteRatingDiff`/`BlackRatingDiff` | 1 sign bit + 9-bit magnitude               |
| `UTCDate`        | Year offset from 2012 (8 bits) + month (4 bits) + day (5 bits)|
| `UTCTime`        | Total seconds since midnight (17 bits)                        |
| `TimeControl`    | Base seconds + increment, each in compact fixed-width fields  |
| `ECO`            | Letter (3 bits) + number 0–99 (7 bits)                        |
| `Opening`        | Index into a table of ~500 known opening names                |
| `Result`         | 3-bit enum (1-0, 0-1, 1/2-1/2, *, unknown)                   |
| `Termination`    | 3-bit enum (Normal, Time forfeit, Abandoned, …)               |
| Unknown tags/values | Raw UTF-8 with an 8-bit length prefix                      |

A `SEACABO` marker (5-bit sentinel) terminates each game's header block.

The entire header bitstream for all games is written **raw** to the file — no further compression. It is already close to the information-theoretic minimum for structured data with known vocabularies.

### Move Tokenization (`src/encode_game.py`)

Before LZW, the move text is pre-processed to replace predictable patterns:

| Pattern              | Token                    |
|----------------------|--------------------------|
| Board squares `a1`–`h8` | Single byte `0x80`–`0xBF` (64 values) |
| First move number `1.` | `0xFD`                 |
| Subsequent move numbers `2.`, `3.`, … | `0xFE` (decoder increments a counter) |
| `1-0`                | `0xFB`                   |
| `0-1`                | `0xFC`                   |
| `1/2-1/2`            | `0xFA`                   |
| `*`                  | `0xF9`                   |
| `{[%eval +1.23]}`    | `0x01` + int16 centipawns |
| `{[%eval #5]}`       | `0x02` + int8 mate-in-N  |
| `{[%clk 0:05:00]}`   | `0x03` + uint16 packed H:MM:SS |
| Other annotations    | `0x04` + uint8 length + raw bytes |

Each game's token stream is length-prefixed (uint16), and all games are packed with a uint32 game count header. This combined move blob is then LZW-compressed (dictionary up to 65535 entries) and Huffman-coded.

### File Layout (CPG4)

```
Offset  Size   Field
──────  ─────  ─────────────────────────────────────────────────
0       4      Magic: b'CPG4'
4       4      uint32 BE — total bits in the header section
8       N      Header bits, zero-padded to byte boundary (RAW)
8+N     4      uint32 BE — number of Huffman symbol table entries
12+N    4      uint32 BE — total LZW symbol count
16+N    V      VLQ-encoded (delta, frequency) pairs for Huffman table
16+N+V  1      uint8 — padding bits at end of move data
17+N+V  M      LZW + Huffman compressed move tokens
```

---

## Why Not Combine Headers and Moves Under LZW?

The previous format (CPG3) ran LZW over `header_bits.tobytes() + move_tokens`. This was counterproductive:

- LZW excels at **byte-level repetition of long strings**. Raw PGN headers like `[Event "Rated Blitz game"]\n` repeated thousands of times are ideal LZW input.
- The semantic header encoding converts those strings into compact bits that are already non-repetitive at the byte level. LZW sees no patterns to exploit.
- Worse, the header blob fills up LZW's 65535-entry dictionary with header byte patterns before it even processes the move stream, reducing move compression quality.

Storing headers raw and compressing moves independently gives each section the treatment it needs.

---

## Compression Results

Tested on 7 Lichess game sets (25,113 KB total, 27,936 games).

| File             | Original  | Compressed | Ratio  |
|------------------|----------:|-----------:|-------:|
| SetPartides1.pgn | 1,708 KB  |   398 KB   | 4.19×  |
| SetPartides2.pgn | 3,888 KB  |   817 KB   | 4.65×  |
| SetPartides3.pgn | 3,102 KB  |   663 KB   | 4.57×  |
| SetPartides4.pgn | 2,512 KB  |   558 KB   | 4.40×  |
| SetPartides5.pgn | 5,639 KB  | 1,149 KB   | 4.79×  |
| SetPartides6.pgn | 4,647 KB  |   957 KB   | 4.74×  |
| SetPartides7.pgn | 3,616 KB  |   771 KB   | 4.58×  |
| **Total**        | **25,113 KB** | **5,313 KB** | **4.62×** |

### Comparison Against Previous Formats

| Format        | Approach                                | Avg ratio |
|---------------|-----------------------------------------|----------:|
| CPG3          | Combined LZW on headers + moves         | ~3.8×     |
| smart_chess_codec (.scpgn) | Tokenized moves, LZW+Huffman on raw PGN | ~4.0× |
| **CPG4**      | Raw header bits + LZW+Huffman on moves  | **4.62×** |

---

## Encode / Decode Speed

Measured on all 7 files (WSL2, Python, no native extensions).

| File             | Size (KB) | Encode (KB/s) | Decode (KB/s) |
|------------------|----------:|--------------:|--------------:|
| SetPartides1.pgn |    1,668  |       3,074   |       4,385   |
| SetPartides2.pgn |    3,797  |       3,456   |       4,958   |
| SetPartides3.pgn |    3,029  |       3,390   |       4,783   |
| SetPartides4.pgn |    2,453  |       3,350   |       4,687   |
| SetPartides5.pgn |    5,507  |       3,620   |       4,953   |
| SetPartides6.pgn |    4,538  |       3,535   |       4,883   |
| SetPartides7.pgn |    3,532  |       3,482   |       4,849   |
| **Average**      | **3,503** |   **3,461**   |   **4,835**   |

Decoding is ~40% faster than encoding because LZW decompression avoids the dictionary-building overhead of compression, and Huffman decoding is a single tree traversal rather than a frequency-count + tree-build pass.
