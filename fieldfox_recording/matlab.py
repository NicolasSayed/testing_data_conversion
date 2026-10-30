"""MATLAB-compatible section export, with SciPy as an optional dependency."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from .export import _destination
from .parser import RecordingError
from .timezones import convert_timestamps

if TYPE_CHECKING:
    from .parser import FieldFoxRecording
    from .spectrogram import SpectrogramSection


def save_section_mat(rec: FieldFoxRecording, section: SpectrogramSection,
                     path: str | Path, *, source_timezone: str | None = "EST",
                     dst_fold: int | None = None) -> None:
    """Save exactly the selected/thinned rows and frequency bins, not an image.

    Power is single precision, rows are sweeps, columns are frequency bins.
    All one-dimensional numeric arrays and timestamp cell arrays are columns.
    """
    try:
        from scipy.io import savemat
    except ImportError as error:
        raise RecordingError("MAT export requires SciPy: python -m pip install '.[mat]'") from error
    times = convert_timestamps(section.timestamp_ticks, source_timezone, dst_fold)
    payload = {"frequency_hz": section.frequency_hz, "elapsed_s": section.elapsed_s,
               "power_dbm": section.power_dbm, "sweep_indices": section.sweep_indices,
               "timestamp_ticks": section.timestamp_ticks,
               "trace_slot": section.trace_slot, "effective_step": section.effective_step,
               "metadata_json": json.dumps(rec.metadata), **times}
    for name, value in list(payload.items()):
        if isinstance(value, np.ndarray) and value.dtype.kind == "U":
            payload[name] = value.astype(object)  # MATLAB cell array of exact ISO strings
    with _destination(rec, path) as temporary:
        savemat(temporary, payload, appendmat=False, do_compression=True,
                long_field_names=True, oned_as="column")
