"""View or save a selected FieldFox GPSA/RTSA trace recording section.

Install from the repository root with: python -m pip install '.[plot]'
Then run: python scripts/view_spectrogram.py SESSION --start-sweep 100 --stop-sweep 500
"""
from fieldfox_recording.spectrogram import main

if __name__ == "__main__":
    raise SystemExit(main())
