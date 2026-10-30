"""Streaming CSV and disk-backed NPZ exports, independent of Data Link."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory, NamedTemporaryFile
from typing import TYPE_CHECKING, Iterator
import csv
import json

import numpy as np

if TYPE_CHECKING:
    from .parser import FieldFoxRecording


@contextmanager
def _destination(rec: FieldFoxRecording, path: str | Path) -> Iterator[Path]:
    from .parser import RecordingError
    target = Path(path).resolve()
    if target.is_relative_to(rec.path.resolve()):
        raise RecordingError("Export destination must be outside the original session directory")
    if target.exists():
        raise RecordingError(f"Export destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, prefix=".fieldfox-", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        yield temporary
        # On Windows rename refuses an existing destination, preserving originals.
        # The existence check also covers the ordinary case on other platforms.
        if target.exists():
            raise RecordingError(f"Export destination already exists: {target}")
        temporary.rename(target)
    finally:
        temporary.unlink(missing_ok=True)


def to_csv(rec: FieldFoxRecording, path: str | Path) -> None:
    """Long-form, full-precision data CSV (not Data Link's presentation layout)."""
    with _destination(rec, path) as destination:
        with destination.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["trace_id", "state_id", "trace_slot", "trace_mask", "timestamp_local_unspecified",
                             "timestamp_ticks", "point_index", "frequency_hz", "time_s", "power_dbm"])
            for sweep in rec:
                state = sweep.state
                zero_span = state.span_hz == 0
                axis = state.time_axis_s if zero_span else state.frequency_hz
                for slot, trace in enumerate(sweep.power_dbm_traces):
                    for point, (x, power) in enumerate(zip(axis, trace)):
                        writer.writerow([sweep.trace_id, state.state_id, slot, sweep.trace_mask, sweep.timestamp,
                                         sweep.ticks, point, "" if zero_span else format(x, ".17g"),
                                         format(x, ".17g") if zero_span else "", format(power, ".9g")])


def to_npz(rec: FieldFoxRecording, path: str | Path) -> None:
    """Use disk-backed arrays so large power matrices need not fit in RAM.

    Read with numpy.load(..., allow_pickle=False). Axes are indexed by state_id;
    raw ticks retain 100 ns precision. Temporary disk use is roughly raw data size.
    """
    count, first = len(rec), rec.states[0]
    with _destination(rec, path) as destination, TemporaryDirectory(prefix="fieldfox-npz-") as temp:
        base = Path(temp)
        power = np.lib.format.open_memmap(base / "power.npy", mode="w+", dtype="<f4",
                                         shape=(count, first.trace_count, first.points))
        # Zero-sized memmaps are not portable.
        auxiliary = (np.lib.format.open_memmap(base / "aux.npy", mode="w+", dtype="<f4",
                     shape=(count, first.auxiliary_count)) if first.auxiliary_count else np.empty((count, 0), dtype="<f4"))
        ticks = np.empty(count, dtype="<i8")
        state_ids = np.empty(count, dtype="<u2")
        masks = np.empty(count, dtype="u1")
        headers = []
        try:
            for i, sweep in enumerate(rec):
                power[i], auxiliary[i] = sweep.power_dbm_traces, sweep.auxiliary_values
                ticks[i], state_ids[i], masks[i] = sweep.ticks, sweep.state.state_id, sweep.trace_mask
                headers.append(json.dumps(sweep.header, separators=(",", ":")))
            axis_kind = np.array(["time_s" if s.span_hz == 0 else "frequency_hz" for s in rec.states])
            axes = np.array([s.time_axis_s if s.span_hz == 0 else s.frequency_hz for s in rec.states])
            with destination.open("wb") as stream:
                np.savez_compressed(stream, power_dbm_traces=power, auxiliary_values=auxiliary,
                                    timestamp_ticks=ticks, state_ids=state_ids, trace_masks=masks,
                                    axes_by_state=axes, axis_kind_by_state=axis_kind,
                                    trace_headers_json=np.array(headers), metadata_json=np.array(json.dumps(rec.metadata)))
        finally:
            # Release mappings before TemporaryDirectory removes files on Windows.
            power._mmap.close()
            if isinstance(auxiliary, np.memmap):
                auxiliary._mmap.close()
