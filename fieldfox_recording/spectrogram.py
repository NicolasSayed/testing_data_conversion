"""Select and view recorded GPSA sweeps as a Matplotlib waterfall.

The recording already supplies power versus frequency. No FFT, STFT,
resampling or invented IQ/sample rate is applied to the stored values.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import argparse
import math
import sys

import numpy as np
from numpy.typing import NDArray

from .parser import FieldFoxRecording, RecordingError

MAX_PLOT_CELLS = 20_000_000  # Rendering/allocation guard, not an instrument limit


@dataclass(frozen=True)
class SpectrogramSection:
    """Selected rows with one common frequency axis and original power values."""

    frequency_hz: NDArray[np.float64]
    elapsed_s: NDArray[np.float64]
    power_dbm: NDArray[np.float32]
    sweep_indices: NDArray[np.int64]
    trace_slot: int
    first_timestamp: str
    effective_step: int


def load_section(
    rec: FieldFoxRecording, *, start_sweep: int = 0, stop_sweep: int | None = None,
    step: int = 1, max_sweeps: int = 2000, freq_min_hz: float | None = None,
    freq_max_hz: float | None = None, trace_slot: int = 0,
) -> SpectrogramSection:
    """Read just selected sweeps, sampling rows to the requested memory limit.

    Sweep indices are zero-based, start inclusive and stop exclusive. Frequency
    bounds are inclusive. Thinning selects original rows without averaging.
    A rectangular waterfall requires at least two sweeps and two frequency bins
    with an unchanged frequency axis and strictly increasing timestamps.
    """
    stop = len(rec) if stop_sweep is None else stop_sweep
    if not 0 <= start_sweep < stop <= len(rec):
        raise RecordingError(f"Require 0 <= start_sweep < stop_sweep <= {len(rec)}")
    if step < 1 or max_sweeps < 2:
        raise RecordingError("step must be >= 1 and max_sweeps must be >= 2")
    if not 0 <= trace_slot < rec.states[0].trace_count:
        raise RecordingError(f"Trace slot must be in 0..{rec.states[0].trace_count-1}")
    bounds = [v for v in (freq_min_hz, freq_max_hz) if v is not None]
    if not all(math.isfinite(v) for v in bounds):
        raise RecordingError("Frequency bounds must be finite")
    if freq_min_hz is not None and freq_max_hz is not None and freq_min_hz > freq_max_hz:
        raise RecordingError("freq_min_hz must be <= freq_max_hz")
    requested_rows = len(range(start_sweep, stop, step))
    effective_step = step * math.ceil(requested_rows / max_sweeps)
    indices = np.array(range(start_sweep, stop, effective_step), dtype=np.int64)
    if len(indices) < 2:
        raise RecordingError("Select at least two sweeps for a waterfall")
    axis = mask = power = ticks = None
    first_timestamp = ""
    for row, sweep in enumerate(rec.iter_sweeps(start_sweep, stop, effective_step)):
        current_axis = sweep.state.frequency_hz
        if row == 0:
            axis = current_axis
            mask = np.ones(axis.shape, dtype=bool)
            if freq_min_hz is not None:
                mask &= axis >= freq_min_hz
            if freq_max_hz is not None:
                mask &= axis <= freq_max_hz
            if np.count_nonzero(mask) < 2:
                raise RecordingError("Select at least two recorded frequency bins")
            if len(indices) * np.count_nonzero(mask) > MAX_PLOT_CELLS:
                raise RecordingError("Selected plot exceeds the rendering memory limit; narrow the frequency band, increase --step or lower --max-sweeps")
            power = np.empty((len(indices), np.count_nonzero(mask)), dtype=np.float32)
            ticks = np.empty(len(indices), dtype=np.int64)
            first_timestamp = sweep.timestamp
        elif not np.array_equal(axis, current_axis):
            raise RecordingError(f"Frequency axis changes at sweep {sweep.trace_id}; choose a shorter section")
        power[row] = sweep.power_dbm_traces[trace_slot, mask]
        ticks[row] = sweep.ticks
    if np.any(np.diff(ticks) <= 0):
        raise RecordingError("Selected sweep timestamps must be strictly increasing")
    if not np.isfinite(power).any():
        raise RecordingError("Selected section has no finite power values")
    # Subtract int64 ticks before conversion to preserve fine time differences.
    elapsed = (ticks - ticks[0]).astype(np.float64) / 10_000_000
    return SpectrogramSection(axis[mask], elapsed, power, indices,
                              trace_slot, first_timestamp, effective_step)


def plot_section(
    section: SpectrogramSection, *, title: str = "FieldFox recording section",
    vmin: float | None = None, vmax: float | None = None, cmap: str = "viridis",
) -> tuple[Any, Any]:
    """Return Matplotlib figure/axes with frequency in MHz and power in dBm."""
    try:
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise RecordingError("Plotting requires Matplotlib: python -m pip install '.[plot]'") from error
    if any(not math.isfinite(v) for v in (vmin, vmax) if v is not None):
        raise RecordingError("Color limits must be finite")
    if vmin is not None and vmax is not None and vmin >= vmax:
        raise RecordingError("vmin must be less than vmax")
    if cmap not in plt.colormaps():
        raise RecordingError(f"Unknown Matplotlib colormap: {cmap}")
    fig, ax = plt.subplots(figsize=(11, 6), layout="constrained")
    chart = ax.pcolormesh(section.frequency_hz / 1e6, section.elapsed_s,
                         np.ma.masked_invalid(section.power_dbm), shading="nearest",
                         cmap=cmap, vmin=vmin, vmax=vmax, rasterized=True)
    ax.set(xlabel="Frequency (MHz)", ylabel="Elapsed time from first selected sweep (s)",
           title=f"{title}\nSweeps {section.sweep_indices[0]}..{section.sweep_indices[-1]}, "
                 f"trace slot {section.trace_slot}, row step {section.effective_step}")
    ax.text(0, -0.14, f"First selected instrument timestamp: {section.first_timestamp} (timezone unspecified)",
            transform=ax.transAxes, fontsize=8)
    fig.colorbar(chart, ax=ax, label="Recorded power (dBm)")
    return fig, ax


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Shared options for the package CLI and standalone viewer script."""
    parser.add_argument("path", help="Complete GPSA recording session directory")
    parser.add_argument("--start-sweep", type=int, default=0, help="First sweep index, inclusive (default 0)")
    parser.add_argument("--stop-sweep", type=int, help="Last sweep index, exclusive (default session end)")
    parser.add_argument("--step", type=int, default=1, help="Read every Nth sweep (default 1)")
    parser.add_argument("--max-sweeps", type=int, default=2000, help="Maximum displayed rows; extra rows are sampled (default 2000)")
    parser.add_argument("--freq-min-hz", type=float, help="Inclusive lower frequency bound in Hz")
    parser.add_argument("--freq-max-hz", type=float, help="Inclusive upper frequency bound in Hz")
    parser.add_argument("--trace-slot", type=int, default=0, help="Zero-based stored trace slot (default 0)")
    parser.add_argument("--vmin", type=float, help="Lower color limit in dBm")
    parser.add_argument("--vmax", type=float, help="Upper color limit in dBm")
    parser.add_argument("--cmap", default="viridis", help="Matplotlib colormap")
    parser.add_argument("--output", help="Save to a new PNG, PDF or other Matplotlib image file")
    parser.add_argument("--show", action="store_true", help="Show interactive window even when saving an image")


def run(args: argparse.Namespace) -> int:
    """Select, plot and save or show a section without changing input files."""
    rec = FieldFoxRecording.open(args.path)
    section = load_section(rec, start_sweep=args.start_sweep, stop_sweep=args.stop_sweep,
                           step=args.step, max_sweeps=args.max_sweeps, freq_min_hz=args.freq_min_hz,
                           freq_max_hz=args.freq_max_hz, trace_slot=args.trace_slot)
    fig, _ = plot_section(section, title=rec.path.name, vmin=args.vmin, vmax=args.vmax, cmap=args.cmap)
    import matplotlib.pyplot as plt
    try:
        if args.output:
            from .export import _destination
            with _destination(rec, args.output) as temporary:
                fmt = Path(args.output).suffix.lstrip(".").lower() or "png"
                fig.savefig(temporary, format=fmt, dpi=160)
        print(f"Displayed {len(section.sweep_indices)} sweeps x {len(section.frequency_hz)} frequency bins; "
              f"sweeps {section.sweep_indices[0]}..{section.sweep_indices[-1]}, row step {section.effective_step}")
        if args.output:
            print(f"Saved {args.output}")
        if args.show or not args.output:
            plt.show()
        return 0
    finally:
        plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="View a section of GPSA power sweeps as a spectrogram/waterfall")
    add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (RecordingError, OSError, ValueError) as error:
        print(f"fieldfox-recording: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
