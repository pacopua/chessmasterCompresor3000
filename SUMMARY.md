# Old Vibecoded — Codebase Summary

**Project:** Lossless PGN (chess game) compression research  
**Dataset:** 7 PGN files (`SetPartides1–7.pgn`, ~24.5 MB total, Lichess format)  
**Goal:** Explore multiple codec approaches and compare their compression ratios and fidelity.

---

## Overall Description

This directory contains a full iterative exploration of PGN compression codecs, developed incrementally during a single session. The work starts from a baseline LZMA approach, passes through several hybrid text-preprocessing + entropy-coding codecs, and culminates in three production-quality codecs (Smart Chess, BWT, LMI) whose performance is benchmarked and documented. Accompanying scripts handle verification, analysis tooling, and one-off fixes applied mid-session.

All codecs operate encode/decode symmetrically and produce files that can be fully restored to the original PGN.

---

## File-by-File Descriptions

### Codec Implementations

#### `pgn_codec.py` — Baseline LZMA Codec (`.cpgn`)
The simplest codec. Applies two text-level optimizations before compression:
1. Replaces Lichess URLs (`https://lichess.org/`) with the short token `LICHESS:`.
2. Strips spaces after move numbers (`1. e4` → `1.e4`).

Compresses the result with Python's built-in `lzma` module. On decode, both substitutions are reversed. Output extension: `.cpgn`. No chess domain knowledge beyond the two substitution rules.

---

#### `custom_codec.py` — Custom Static Dictionary Codec (`.custom_cpgn`)
Uses a hand-crafted static dictionary encoded as high-byte tokens (`\x80`–`\xCC`):
- **Header keys** (17 entries): `[Event`, `[White`, `[BlackElo`, etc. → single bytes.
- **Common header values**: Lichess URL, game types (`Rated Bullet game`, …), time controls, results.
- **Common moves**: `O-O`, `O-O-O`, `e4`, `e5`, `d4`, `d5`, `Nf3`, `Nc6`, `c4`, `c5`.

Move numbers' spaces are stripped. On decode, moves are re-wrapped at 75 characters. No entropy coding layer — compression comes purely from the substitution dictionary. Output extension: `.custom_cpgn`.

---

#### `advanced_codec.py` — LZW + Huffman Codec (`.hcpgn`)
Two-stage entropy coder with no chess-specific preprocessing:
1. **LZW compression** (dictionary capped at 65 535 entries) over raw PGN bytes.
2. **Huffman coding** over the resulting LZW symbol stream.

The Huffman frequency table is stored in the file header so the decoder can rebuild the tree. Output extension: `.hcpgn`. This is the baseline entropy-only approach that the chess-aware codecs are compared against.

---

#### `smart_chess_codec.py` — Smart Chess Tokenizer + LZW + Huffman (`.scpgn`)
Adds a domain-aware preprocessing step before the LZW+Huffman pipeline:
- Board squares `a1`–`h8` → single bytes `\x80`–`\xBF` (saves 1 byte per square occurrence).
- Sequential move numbers (`1.`, `2.`, …) → `\xFD` (for `1.`) / `\xFE` (for all others).
- Game results (`1-0`, `0-1`, `1/2-1/2`) → `\xFB`, `\xFC`, `\xFA`.

Only applied to ASCII-only lines (headers with Unicode player names are passed through safely). Output extension: `.scpgn`. **Achieves 3.25× compression overall** and is fast (~5 s for all 7 files).

---

#### `ultimate_codec.py` — Binary Header Packing + Tokenization + LZW + Huffman (`.ucpgn`)
An extended version of the smart codec that additionally packs structured numeric header fields into compact binary representations before tokenization:
- `WhiteElo` / `BlackElo` → `\x80`/`\x81` + 2-byte big-endian uint16.
- `UTCDate` → `\x82` + 4-byte struct (year uint16, month uint8, day uint8).
- `UTCTime` → `\x83` + 3-byte struct (hour, minute, second uint8 each).

Also expands the string-replacement dictionary with more header tag prefixes and closing `"]` sequences. Square byte encoding is shifted to `\x90`–`\xCF` to avoid conflicts with the binary header markers. Output extension: `.ucpgn`.

---

#### `bwt_codec.py` — BWT + MTF + Huffman Codec (`.bpgn`)
A fundamentally different pipeline based on the Burrows-Wheeler Transform (used in bzip2):
1. **Chess tokenization** (same as `smart_chess_codec.py`).
2. **BWT** per 8 KB block: rearranges bytes so identical characters cluster into runs.
3. **MTF (Move-To-Front)**: converts runs from BWT into sequences of zeros and small numbers.
4. **Huffman coding** directly on the MTF byte values (0–255).

LZW was explicitly dropped here after testing revealed that MTF output is frequency-skewed (not substring-repeated), making Huffman the right final stage. Block indices needed for BWT inversion are stored in the file header. Output extension: `.bpgn`. **Also achieves 3.25× compression overall** but is slow (~2 min encode).

---

#### `lmi_codec.py` — Legal Move Indexing (LMI) Codec (`.lpgn`)
The most domain-specialized codec. Instead of storing move text, each move is encoded as its **rank in the sorted list of legal moves** at that position (~30 legal moves on average → ~5 bits/move vs ~10–15 bytes of text):

1. **PGN parsing**: extracts header lines and SAN token sequences per game.
2. **Board simulation**: a full chess engine (move generation, castling, en passant, promotion, check/checkmate, SAN disambiguation) replays every position.
3. **Bit packing**: move indices are bit-packed with variable width (`ceil(log2(n_legal_moves))` bits).
4. **Header Huffman**: a global Huffman table is built over all header bytes across all games and stored once in the file header (format v2, magic `LMI2`).

Handles non-standard "long SAN" (`Ne7c6`, `Re2e5`) via a regex fallback. **Achieves 2.32× compression** — lower than the other codecs because headers dominate file size and the per-game isolation prevents cross-game pattern reuse. Annotations (`{...}`, `!?`, variation lines) are stripped and lost. Output extension: `.lpgn`.

---

### Analysis & Utility Scripts

#### `analyze_headers.py` — PGN Header Tag Scanner
Single-purpose analysis script. Scans all `*.pgn` files in the current directory and collects every unique PGN header tag name (e.g. `Event`, `White`, `ECO`). Prints a sorted list. Used early in the session to inform which header keys were worth adding to static dictionaries.

---

#### `fix_tokens.py` — One-off Patch Script for `ultimate_codec.py`
A throwaway patch script written mid-session to fix a token collision bug in `ultimate_codec.py`. Reads the source of `ultimate_codec.py` as a string and applies targeted text substitutions:
- Reassigns the binary header marker bytes from conflicting high-byte ranges to `\x80`–`\x83`.
- Shifts the square encoding range from `\x80`–`\xBF` up to `\x85`–`\xC4` to avoid overlap.

This script modifies `ultimate_codec.py` in-place. It was a development aid, not part of the production pipeline.

---

### Verification Scripts

All three verification scripts follow the same pattern: glob for the original PGN files, pair each with its compressed/decompressed counterpart, report the compression ratio, and compare the decoded output byte-for-byte against the original.

#### `verify_compression.py` — Verify `custom_codec.py` (`.custom_cpgn`)
Reports the custom codec's compression ratio and runs a two-tier comparison:
1. Strict byte-for-byte equality check.
2. Semantic check (strips all whitespace) to distinguish true data loss from formatting differences — necessary because the custom decoder rewraps lines and normalizes spaces after move numbers.

#### `verify_advanced.py` — Verify `advanced_codec.py` (`.hcpgn`)
Strict byte-for-byte integrity check for the LZW+Huffman codec. Reports total original vs compressed sizes and prints SUCCESS/ERROR per file.

#### `verify_ultimate.py` — Verify `ultimate_codec.py` (`.ucpgn`)
Same structure as `verify_advanced.py` but targets `.ucpgn` files.

#### `verify_smart.py` — Verify `smart_chess_codec.py` (`.scpgn`)
Same structure, targets `.scpgn` files.

---

### Documentation

#### `CODEC_REVIEW.md` — Codec Benchmark Report
Detailed performance review comparing Smart Chess, BWT, and LMI codecs across all 7 dataset files. Includes a per-file compression ratio table, codec descriptions, encode/decode speed comparisons, a summary of trade-offs, and recommended next steps (e.g. swapping LZW for LZMA as a backend).

#### `session-ses_22ab.md` — Full Development Session Log
The complete chat transcript of the session in which all these scripts were written (using Gemini 3.1 Pro Preview via an agentic coding tool). Records every user prompt, model response, tool call, and code artifact produced during the session. Primarily useful as a development audit trail.

---

### Data Directories

| Directory | Contents |
|-----------|----------|
| `Matches/` | Original source PGN files (`SetPartides1–7.pgn`) |
| `Encoded/` | Sample encoded outputs (`SetPartides1.pgn.bpgn`, `SetPartides1.pgn.lpgn`) |
| `Decoded/` | Decoded/restored PGN outputs from BWT, custom, and LMI codecs for all 7 files |

---

## Codec Comparison Summary

| Codec | Extension | Approach | Ratio | Speed | Lossless? |
|-------|-----------|----------|-------|-------|-----------|
| `pgn_codec.py` | `.cpgn` | Text substitution + LZMA | ~best (LZMA) | Fast | Yes |
| `custom_codec.py` | `.custom_cpgn` | Static dictionary only | Moderate | Fast | Semantically (formatting differs) |
| `advanced_codec.py` | `.hcpgn` | LZW + Huffman | Moderate | Fast | Yes |
| `smart_chess_codec.py` | `.scpgn` | Chess tokens + LZW + Huffman | **3.25×** | ~5 s | Yes |
| `ultimate_codec.py` | `.ucpgn` | Binary headers + tokens + LZW + Huffman | ~3.25× | ~5 s | Yes |
| `bwt_codec.py` | `.bpgn` | Chess tokens + BWT + MTF + Huffman | **3.25×** | ~2 min | Yes |
| `lmi_codec.py` | `.lpgn` | Legal move indexing + Huffman headers | **2.32×** | 5–10 min | Moves only (loses annotations) |

**Key takeaway:** The chess-aware text tokenization (replacing board squares, move numbers, and results with single bytes) is the highest-leverage insight. Both the Smart Chess and BWT codecs reach 3.25× by building on it. LMI's theoretically elegant approach is hampered by header overhead and annotation loss. The recommended next step (noted in `CODEC_REVIEW.md`) is to replace the LZW backend with `lzma`, which would likely push the ratio to 4–5×.
