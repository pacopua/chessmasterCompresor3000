# Chess PGN Codec Review

**Date:** 2026-04-28  
**Dataset:** 7 PGN files (`SetPartides1–7.pgn`), 25 113 010 bytes total (~24.5 MB)

---

## Codecs Compared

| Codec | File | Extension | Lossless? | Chess logic? |
|---|---|---|---|---|
| Smart Chess | `smart_chess_codec.py` | `.scpgn` | Yes | No |
| BWT | `bwt_codec.py` | `.bpgn` | Yes | No |
| LMI | `lmi_codec.py` | `.lpgn` | Moves yes, annotations no | Yes |

---

## Compression Results

| File | Orig (KB) | Smart (KB) | Smart ratio | BWT (KB) | BWT ratio | LMI (KB) | LMI ratio |
|---|---:|---:|---:|---:|---:|---:|---:|
| SetPartides1.pgn | 1668 | 667 | **2.50x** | 515 | **3.24x** | 722 | 2.31x |
| SetPartides2.pgn | 3797 | 1144 | **3.32x** | 1171 | 3.24x | 1695 | 2.24x |
| SetPartides3.pgn | 3029 | 979 | 3.09x | 933 | **3.25x** | 1316 | 2.30x |
| SetPartides4.pgn | 2453 | 849 | 2.89x | 755 | **3.25x** | 1086 | 2.26x |
| SetPartides5.pgn | 5506 | 1527 | **3.61x** | 1700 | 3.24x | 2454 | 2.24x |
| SetPartides6.pgn | 4538 | 1308 | **3.47x** | 1400 | 3.24x | 1978 | 2.29x |
| SetPartides7.pgn | 3531 | 1065 | **3.32x** | 1068 | 3.31x | 1303 | **2.71x** ¹ |
| **TOTAL** | **24 524** | **7 540** | **3.25x** | **7 543** | **3.25x** | **10 554** | **2.32x** |

> ¹ SetPartides7 uses the updated LMI format with global Huffman coding on headers.
> Files 1–6 use the original LMI format (raw headers), hence the lower ratios.

---

## Codec Descriptions

### Smart Chess Codec (`smart_chess_codec.py` → `.scpgn`)

**Pipeline:** PGN text → Chess tokenization → LZW (max 65 535 entries) → Huffman → bitstream

**Tokenization replaces:**
- Board squares `a1`–`h8` → single bytes `\x80`–`\xBF` (64 values, saves 1 byte each)
- Sequential move numbers `1.`, `2.`, `3.` → `\xFD` (for `1.`) or `\xFE` (for all others)
- Game results `1-0`, `0-1`, `1/2-1/2` → `\xFB`, `\xFC`, `\xFA`

Headers are passed through unchanged but benefit from LZW's repeated-substring detection (tag names like `[Event "`, `[White "` repeat thousands of times).

**Strengths:**
- Fast encode and decode (pure Python, a few seconds per file)
- Byte-perfect round-trip
- No chess knowledge required — works at the text level
- Best ratio on files with many long games (SetPartides5 3.61x, SetPartides6 3.47x) where LZW has more dictionary reuse

**Weaknesses:**
- LZW dictionary cap (65 535 entries) limits gains on large files
- Headers are not explicitly compressed — relies entirely on LZW finding repeated substrings

---

### BWT Codec (`bwt_codec.py` → `.bpgn`)

**Pipeline:** PGN text → Chess tokenization → BWT (8 KB blocks) → MTF → Huffman → bitstream

Uses the same chess tokenization as the smart codec. The Burrows-Wheeler Transform rearranges bytes so identical characters cluster into runs, which MTF (Move-To-Front) then converts into sequences of zeros and small numbers — an ideal input for Huffman entropy coding.

**Key insight:** After testing, LZW was the wrong tool after MTF (MTF output is frequency-skewed, not substring-repeated). Replacing LZW with direct Huffman on the 0–255 MTF byte values raised the ratio from ~3.0x to 3.25x.

**Strengths:**
- Matches smart codec overall (3.25x tie)
- Outperforms smart on files with more uniform/shorter games (SetPartides1 3.24x vs 2.50x, SetPartides3–4 3.25x)
- No dictionary size limit — compresses each 8 KB block independently

**Weaknesses:**
- Slow: BWT sort is O(n²) in memory per block — encodes all 7 files in ~2 minutes vs seconds for smart codec
- Does not exploit cross-block repetition (e.g. the same opening appearing in many games across different blocks won't help)
- Same header weakness as smart codec

---

### LMI Codec (`lmi_codec.py` → `.lpgn`)

**Pipeline:** PGN → parse headers + SAN tokens → replay board → encode each move as its legal-move index → bit-pack → write

Instead of storing move text, each move is stored as its rank in the sorted list of legal moves at that position. With ~30 legal moves on average, this needs only ~5 bits per move vs ~10–15 bytes of text.

**Format (current, v2):**
```
[4B magic "LMI2"] [4B n_games]
[global Huffman table for headers]
per game: [4B n_header_bits] [compressed headers] [2B n_moves] [2B n_bytes] [move bits]
```

**Strengths:**
- Most principled compression of move data — exploits chess structure directly
- After adding global header Huffman, SetPartides7 reaches 2.71x (vs 1.93x without)
- Handles both standard minimal SAN and non-standard "long SAN" (`Ne7c6`, `Re2e5`) transparently

**Weaknesses:**
- Requires a full chess engine (legal move generation, SAN parsing, board state) — complex and brittle
- Slowest of all three codecs (must replay every position)
- Loses annotations (`{...}` comments, `!?` markers, variation lines `(...)`)
- Overall ratio (2.32x) is significantly below smart and BWT because headers dominate file size and the global Huffman only approximates what LZW achieves for free via substring repetition

---

## Speed Comparison (approximate, all 7 files)

| Codec | Encode time | Decode time |
|---|---|---|
| Smart Chess | ~5 s | ~5 s |
| BWT | ~2 min | ~10 s |
| LMI | ~5–10 min | ~3 min |

---

## Summary and Recommendations

Both **Smart Chess** and **BWT** achieve **3.25x** compression overall — effectively tied. Smart codec is strongly preferred in practice due to its encode speed (~24× faster).

BWT has an edge on files with short/uniform games where its block-level transform outperforms LZW's dictionary approach, but LZW recovers on larger files with more cross-game pattern repetition.

**LMI is not recommended** in its current form: it is the slowest codec, the most complex, lossy for annotations, and still ranks last on compression ratio. Its core idea (5 bits/move) is sound, but header overhead and the per-game isolation prevent it from beating a simple text-level approach.

### Potential next steps

1. **Replace LZW with zlib/LZMA in the smart codec.** The smart tokenization is the valuable insight; the backend compressor could be swapped for Python's built-in `lzma` (much larger sliding window, better entropy model) with ~5 lines of code change. Expected ratio: 4–5x.
2. **Tag-level header tokenization.** Encode standard PGN tag names (`[Event`, `[White`, `[Date`, etc.) as single-byte tokens before passing to the compressor — similar to how square names are already tokenized.
3. **Larger BWT block size.** Using 64 KB+ blocks would improve BWT ratio significantly but may be impractical in pure Python.
