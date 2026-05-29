#!/usr/bin/env python3
"""Build compress.cdi standalone executable from compress.py using PyInstaller."""
import subprocess
import sys
import os

# Este codigo es para crear el ejecutable a partir del script compress.py usando PyInstaller. Se ejecuta desde la terminal con:
# python build_executable.py

# IMPORTANTE: Antes de ejecutar este script, asegúrate de que tu entorno con python tenga todo instalado para que funcione la app, ya que el ejecutable se construirá con las dependencias del entorno actual.

# Para esto es muy util que utiliceis uv, que es el gestor de entornos que uso yo. Cualquiero otro gestor vale, lo digo para que no metais vuestros entornos de python globales enteros, que seguros que están llenos de paquetes innecesarios.
def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "compress.cdi",
        "compress.py",
    ]

    print("Building compress.cdi ...")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\nDone! Executable at: dist/compress.cdi")
    else:
        print("\nBuild failed.", file=sys.stderr)
        sys.exit(result.returncode)

if __name__ == "__main__":
    main()
