import os
import sys
import glob

# ── CPG5 (chess-aware) ───────────────────────────────────────────────────────
import time, io, contextlib

from src.encode_game_chess import encode_pgn_file_chess, decode_pgn_file_chess

#TEST
fileread = "data/input/SetPartides1.pgn"
filewrite = "data/output/encoded5/SetPartides1.bin"
encode_pgn_file_chess(fileread,filewrite)