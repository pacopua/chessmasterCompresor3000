# Next improvement ideas

## Easy wins

### `Event` — 6-bit dictionary (50 known values)
All 50 unique event strings are known from the dataset. Encode as a 6-bit index.
Reserve index 63 (all 1s) as UNKNOWN_TEXT sentinel — raw UTF-8 follows.
Currently stored as raw UTF-8 (~30–80 bytes/game).
**Status: done**

### `Opening` — 11-bit lookup table (1608 known values)
1608 unique opening names. Encode as an 11-bit index.
Reserve index 2047 (all 1s) as UNKNOWN_TEXT sentinel.
Table is large (~15 KB) but should be stored once in the file header.
Every game saves 20–50 bytes.
**Status: done**

---

## Structural improvements

### Fixed tag order — remove tag labels for universal tags
Every game has the same 15 tags in the same order. We spend 5 bits × 15 = 75 bits/game
just labelling fields that are always present. A fixed-order schema encodes those 15 values
back-to-back with no tag codes, only using tag codes for optional tags (WhiteTitle, BlackTitle).

### `WhiteRatingDiff` / `BlackRatingDiff` — encode only one, delta for the other
Rating points are roughly zero-sum. Encode WhiteRatingDiff normally, then encode
BlackRatingDiff as a small signed delta from -WhiteRatingDiff (usually ≤ 2).
A signed 4-bit delta covers most cases, saving ~6 bits/game.

### `WhiteElo` / `BlackElo` — delta encoding
Elo values cluster tightly around 1500. Encode the first Elo in 12 bits, then encode
the second as a signed offset from the first (usually within ±300 → 9 bits).
Also possible: cross-game delta (each game's Elo relative to the previous game).

---

## Bigger gains

### Move encoding — legal move indexing
Headers are only ~20% of a PGN file. The moves section is untouched.
Encode each move as its rank in the sorted list of legal moves at that position.
~30 legal moves on average → ~5 bits/move vs ~6–10 bytes of SAN text.
Estimated 10–15× improvement on the moves section.

### Entropy coding layer
After all structural encoding, apply Huffman or arithmetic coding over the full bitstream
to exploit remaining statistical skew (low Elo values dominate, certain ECO codes dominate, etc.).
Free multiplier on top of everything else — estimated 1.2–1.5×.
