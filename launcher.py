"""Ponto de entrada do executável (PyInstaller)."""
import os
import sys

# No .exe sem console, stdout/stderr são None e qualquer print falharia.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from packlauncher.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
