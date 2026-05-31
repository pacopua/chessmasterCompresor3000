#!/usr/bin/env python3
"""Build compress.cdi as a Python zipapp (no bundled interpreter — users install deps once)."""
import shutil
import stat
import tempfile
import zipapp
from pathlib import Path

# Requires Python ≥ 3.5 and the following packages installed in the active environment:
#   chess  bitarray  numpy
# Run:  python build_executable.py
# Or:   uv run python build_executable.py

def main():
    project = Path(__file__).parent.resolve()
    dist = project / 'dist'
    dist.mkdir(exist_ok=True)
    out = dist / 'compress.cdi'

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # __main__.py is the entry point inside the zip
        shutil.copy(project / 'compress.py', tmp / '__main__.py')

        # Bundle src/ excluding pycache and non-code files
        shutil.copytree(
            project / 'src', tmp / 'src',
            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.md'),
        )

        zipapp.create_archive(
            str(tmp),
            str(out),
            interpreter='/usr/bin/env python3',
        )

    # Make executable
    out.chmod(out.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    size_kb = out.stat().st_size // 1024
    print(f"Done! Executable at: dist/compress.cdi  ({size_kb} kB)")

if __name__ == '__main__':
    main()
