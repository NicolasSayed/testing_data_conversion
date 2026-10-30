"""Launch the Tkinter viewer from this checkout; install dependencies with .[plot]."""
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fieldfox_recording.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
