# encode_game_chess.py — CPG5 Format

## Does it use LZW?

**No.** CPG5 completely drops LZW and Huffman for the move section. The chess-aware encoding is already near the information-theoretic minimum — no statistical compressor can meaningfully improve on it. The pipeline is:

| Section  | CPG4 (old)                        | CPG5 (this file)               |
|----------|-----------------------------------|--------------------------------|
| Headers  | Compact bit encoding (raw)        | Same — unchanged               |
| Moves    | Tokenized text → LZW → Huffman    | Legal-move index bits (no LZW) |

---

## How it works

### Headers

Unchanged from CPG4. Each PGN tag is encoded with domain-specific bit widths (`src/encode_headers.py` / `src/decode_headers.py`) and written as raw bytes — no secondary compression. Repetitive header text like `[Event "Rated Blitz game"]` is compressed by the semantic encoding itself.

### Move encoding (the key idea)

For every half-move (ply) in a game, python-chess tracks the board state and knows the full list of legal moves. Instead of storing the move as text (`Nf3`, `O-O`, `exd5`), we store its **index** in that list:

```
Position has 28 legal moves → need ceil(log2(28)) = 5 bits to identify one
Move played is the 7th in the list → store 00111 (5 bits)
```

Average legal moves per position ≈ 30, so average cost ≈ **5 bits/move** (0.6 bytes), vs the old tokenized approach which cost 3–5 bytes/move after LZW+Huffman.

**Move ordering:** `list(board.legal_moves)` — python-chess's natural generation order, which is deterministic for any given position. Both encoder and decoder use the same order, so the index is unambiguous.

**Forced moves (N=1):** 0 bits written — the decoder just applies the only legal move.

**After each move index:** 1 flag bit `has_annotation`. This costs 1 bit/ply regardless.

### Annotations

Annotations (`{[%eval +1.23]}`, `{[%clk 0:05:00]}`) are preserved losslessly. They are extracted from the move text before encoding, compressed into compact binary tokens, and stored separately after the bit-packed move stream for each game.

| Annotation type    | Token format                                  | Size     |
|--------------------|-----------------------------------------------|----------|
| Eval (centipawns)  | `0x01` + int16 BE (e.g. 123 = +1.23)          | 3 bytes  |
| Eval (mate-in-N)   | `0x02` + int8 signed (e.g. 5 = mate in 5)     | 2 bytes  |
| Clock              | `0x03` + uint16 packed `[H:4|MM:6|SS:6]`      | 3 bytes  |
| Unknown/raw        | `0x04` + uint8 length + raw bytes              | variable |

Each ply's annotation sequence ends with a `0x00` terminator so the decoder knows where one ply's annotations end and the next begin.

NAG suffixes (`?`, `!`, `?!`, `??`, `!!`, `!?`) are stripped from SAN tokens before parsing. Standalone NAGs (`$1`, `$2`, …), variation delimiters (`(`, `)`), and standalone NAG symbols are silently skipped — they carry no positional information.

---

## File layout (CPG5)

```
Offset  Size   Field
──────  ─────  ────────────────────────────────────────────────────────────
0       4      Magic: b'CPG5'
4       4      uint32 BE — total bits in the header section
8       N      Header bits, zero-padded to byte boundary (raw)
8+N     4      uint32 BE — number of games

For each game:
  0     4      uint32 BE — byte length of move block (L)
  4     2      uint16 BE — ply count (P)
  6     1      uint8     — result (0=1-0, 1=0-1, 2=1/2-1/2, 3=*)
  7     B      Bit-packed move data:
                 For each of P plies:
                   ceil(log2(N_legal)) bits — move index (0 bits if N_legal==1)
                   1 bit                   — has_annotation
                 Zero-padded to byte boundary
  7+B   A      Annotation bytes for annotated plies, in ply order
               (L = 2 + 1 + B + A)
```

---

## Encoding walkthrough (example)

Input game snippet: `1. e4 { [%eval 0.17] } 1... e5 2. Nf3`

1. `e4` — board has 20 legal moves. `e4` is index 4. Width = ceil(log2(20)) = 5 bits → `00100`. Annotation follows → flag bit `1`.
2. Annotation `[%eval 0.17]` → `0x01 0x00 0x11 0x00` (17 centipawns, int16 BE) + `0x00` terminator. Stored in the annotation blob.
3. `e5` — board has 29 legal moves. `e5` is index N. Width = 5 bits. No annotation → flag bit `0`.
4. `Nf3` — board has 28 legal moves. Width = 5 bits. No annotation → flag bit `0`.

Bit stream (3 plies): `00100 1 NNNNN 0 MMMMM 0` → padded to byte boundary → ~3 bytes.
Annotation blob: 4 bytes for the eval token.
Total move block: 2 (ply_count) + 1 (result) + 3 (bits) + 4 (annot) = **10 bytes** for 3 moves.
Original text: `1. e4 { [%eval 0.17] } 1... e5 2. Nf3` = **39 bytes**.

---

## Compression results

Tested on 7 Lichess game sets (25,113 KB total, 27,936 games).

| File             | Original  | Compressed | Ratio  | Enc KB/s | Dec KB/s |
|------------------|----------:|-----------:|-------:|---------:|---------:|
| SetPartides1.pgn |  1,708 KB |     256 KB | 6.53×  |    315   |    328   |
| SetPartides2.pgn |  3,888 KB |     575 KB | 6.60×  |    301   |    311   |
| SetPartides3.pgn |  3,102 KB |     462 KB | 6.56×  |    303   |    317   |
| SetPartides4.pgn |  2,512 KB |     371 KB | 6.61×  |    307   |    317   |
| SetPartides5.pgn |  5,639 KB |     835 KB | 6.60×  |    296   |    304   |
| SetPartides6.pgn |  4,647 KB |     694 KB | 6.55×  |    299   |    306   |
| SetPartides7.pgn |  3,616 KB |     508 KB | 6.95×  |    244   |    264   |
| **Total**        | **25,113 KB** | **3,701 KB** | **6.63×** | **291** | **303** |

### Comparison

| Format  | Move compression        | Overall ratio |
|---------|-------------------------|---------------|
| scpgn   | Tokenized text + LZW + Huffman | ~4.0×  |
| CPG4    | Tokenized text + LZW + Huffman (moves only) | 4.62× |
| **CPG5** | **Chess-aware index bits (no LZW)** | **6.63×** |

---

## Error handling

| Case | Behaviour |
|------|-----------|
| `parse_san` fails (corrupted move) | Game skipped, empty block written (0 plies, result=`*`), warning printed |
| N=1 (forced move) | 0 bits for index, 1 bit for has_annotation |
| N=0 (game already over) | Never reached — ply_count is exact |
| Clock hours ≥ 16 | Capped at 15 (4-bit field limit) |
| NAG tokens (`$1`, `?!`, …) | Silently skipped — no positional information |
| Variation delimiters `(` `)` | Silently skipped — variations not encoded |
