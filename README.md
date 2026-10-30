# testing_data_conversion

Independent Python and MATLAB decoders for FieldFox SA/GPSA and RTSA recorded trace sessions,
targeting recordings from a **Keysight N9917B**. It reads session directories
directly, exports CSV or NumPy NPZ, and views selected sections as Matplotlib
spectrograms/waterfalls without installing or running Data Link.

**Status: initial decoder reconstructed by static analysis.** Before publication,
127 local synthetic tests passed and one real-recording integration test was
skipped. No N9917B recording or matching reference CSV was available, so actual
instrument compatibility and export equivalence are still unvalidated locally.
The user reports that the preceding Python build works with their recordings.

**Version 0.3.0 adds a Tkinter GUI, native MATLAB scripts, selected-data MAT
exports and UTC/EST/Eastern timestamps.** The original CLI remains available.
Version 0.3.1 also supports launching `fieldfox_recording/gui.py` directly
from an IDE or another working directory.

**Version 0.2.0 adds RTSA AutoSession trace decoding.** The original release
rejected RTSA. The added path recognizes application code 2 in recording
versions 8-18 and supports a single spectrum block with nonzero frequency span.
RTSA sample compatibility is still pending: no real N9917B AutoSession has been
tested. This reads recorded power-versus-frequency traces; raw IQ captures and
density frames are separate formats.

## Install

Requires Python 3.11 or newer.

```bash
git clone https://github.com/NicolasSayed/testing_data_conversion.git
cd testing_data_conversion
python -m pip install ".[plot]"
```

On Windows, `py -3.11` can be used instead of `python`. Decoding needs NumPy;
the optional `plot` extra adds Matplotlib, SciPy for MAT export, and time-zone
data. For decoding alone, install with `python -m pip install .`; MAT export
alone uses `.[mat]`. Viewing and decoding work offline after installation.
Update an existing checkout with `git pull`, then repeat the install command.

## Tkinter viewer

```bash
python -m fieldfox_recording gui
```

Or run `python scripts/fieldfox_gui.py`. Python must include Tkinter.
The installed `fieldfox-viewer` launcher opens it without a console on Windows.
Direct execution with `python fieldfox_recording/gui.py` or an IDE's Run File
button works too. Keep the entire repository together; `gui.py` uses the other
modules in `fieldfox_recording`. The direct launchers use the code beside them,
even if an older version of the package was installed previously.
Browse to the complete `RTAUTOsessionXX` folder, set the sweep range,
frequency limits in MHz, trace slot and color limits, then click
**Load / update plot**. The toolbar supports pan and zoom. Buttons export
the selected data to `.mat`, save the plot image, or export the entire session
as CSV/NPZ. Data reads and exports run in a worker thread.

The instrument clock setting defaults to **EST, fixed UTC-05:00**, as specified
by the user. It can be changed before MAT export. CSV and NPZ keep the original
instrument clock.

## Command line

Use the complete session directory, including every state, trace and index file
that belongs to it. The directory name is arbitrary.

For example, select `RTAUTOsession01`, containing
`dSTA00000/00000000.STA` and `dTRC00000/00000000.TRC`,
`dTRC00000/00000001.TRC`, etc. State files may increment too. Include all
numbered files, starting at zero. The `RTAUTOsession` prefix does not identify
the capture mode; the state header selects GPSA or RTSA.

```bash
python -m fieldfox_recording inspect /path/to/session
python -m fieldfox_recording export /path/to/session --format csv --output output/session.csv
python -m fieldfox_recording export /path/to/session --format npz --output output/session.npz
```

`inspect` prints JSON with metadata, file prefixes, raw headers and structural
checks. Exit code 0 means the session passed the implemented checks; code 2
means incomplete, unsupported or malformed input. Partial inspection is also
available for individual state and index files.

Exports refuse existing files and destinations inside the input session.
Original recordings are never opened for writing.

## View a spectrogram section

Open an interactive Matplotlib window, showing sweeps 100 through 499:

```bash
python scripts/view_spectrogram.py /path/to/session --start-sweep 100 --stop-sweep 500
```

Use the toolbar to pan, zoom and save. The plot shows frequency in MHz,
elapsed instrument time in seconds, and recorded power in dBm. Sweep indices
are zero-based; start is inclusive and stop is exclusive.

Select a frequency band and save an image without opening a window:

```bash
python -m fieldfox_recording plot /path/to/session --start-sweep 100 --stop-sweep 500 --freq-min-hz 902e6 --freq-max-hz 908e6 --vmin -110 --vmax -50 --output output/section.png
```

Add `--show` to both save and view. `--trace-slot 0` selects a stored trace;
`--cmap viridis` controls colors. `--step 5` selects every fifth sweep.
`--max-sweeps 2000` limits displayed rows by sampling original sweeps, without
averaging. The title reports the actual selected indices and row step.
For large plots, narrow the frequency band or lower `--max-sweeps`; the viewer
rejects matrices above its rendering memory limit before allocating them.

The viewer seeks directly to selected records and allocates only the selected
frequency bins and rows. Unselected records are not validated; run `inspect`
for full-session checks. A section needs at least two sweeps and two frequency
bins, a common frequency axis, and increasing timestamps. For a settings change,
select a shorter range on one side of the change. Zero-span traces have a time
axis within each sweep and are not supported by this frequency waterfall.

This displays the recorded spectrum sweeps directly. No FFT, STFT or assumed
IQ sample rate is applied. SciPy is used only when exporting MAT data.

## Export selected data to MATLAB

Save a section without opening a plot window:

```bash
python scripts/view_spectrogram.py /path/to/RTAUTOsession01 --start-sweep 100 --stop-sweep 500 --source-timezone EST --export-mat output/section.mat
```

`--output output/section.mat` is an alternative. To save an image and data
together, use `--output output/section.png --export-mat output/section.mat`.
Add `--show` to also open the interactive plot.

The MAT file contains exactly the selected frequency bins and sweep rows,
including any thinning from `--step` or `--max-sweeps`. Load it in MATLAB with
`data = load('output/section.mat')`:

| Variable | Meaning |
|---|---|
| `power_dbm` | Single matrix: rows are sweeps, columns are frequency bins |
| `frequency_hz`, `elapsed_s` | Frequency and elapsed-time column vectors |
| `sweep_indices`, `trace_slot`, `effective_step` | Original zero-based selection |
| `timestamp_ticks` | Original int64 ticks, preserving 100 ns precision |
| `timestamp_instrument` | Exact original clock strings without a time zone |
| `timestamp_utc`, `timestamp_est`, `timestamp_eastern` | ISO timestamp column cell arrays |
| `timestamp_ticks_utc` | Exact UTC ticks under the source-clock assumption |
| `source_timezone`, `timestamp_conversion` | Explicit conversion assumption |
| `metadata_json` | Recording metadata |

The file format stores no time zone. **EST is the user's assumption**, not a
recovered field. The default `--source-timezone EST` means fixed UTC-05:00.
`timestamp_eastern` instead follows `America/New_York` daylight saving, so
noon EST in summer becomes 17:00 UTC and 13:00 EDT. If the instrument followed
local daylight-saving time, choose `--source-timezone America/New_York`.
`UTC`, fixed `+HH:MM`/`-HH:MM` offsets and other IANA zones are accepted too.
Repeated local times require `--dst-fold 0` (earlier) or `1` (later);
nonexistent local times are rejected. Conversion preserves all seven fractional
digits and the original ticks.

## Simple MATLAB scripts

These read the session directly in base MATLAB; no Python or Signal Processing
Toolbox is needed. From this repository's root:

```matlab
addpath('matlab');
folder = 'D:\data\RTAUTOsession01';
data = read_fieldfox(folder, 'StartSweep', 100, 'StopSweep', 500);
data = view_spectrogram(folder, 'StartSweep', 100, 'StopSweep', 500, ...
    'SourceTimeZone', 'EST', 'OutputMat', 'section.mat');
```

Or edit the settings in `matlab/example_fieldfox.m` and run it. MATLAB sweep
indices stay zero-based to match Python. `StopSweep` is exclusive; `Inf` means
the session end. Reader options include `Step`, `MaxSweeps` (default 2000),
`TraceSlot`, `FreqMinHz`, `FreqMaxHz`, `SourceTimeZone` and `DSTFold`.
`ColorLimits`, such as `[-110 -50]`, and `Show` belong to the viewer.
Use `'Show',false` to export without a figure. `MaxSweeps=Inf` disables row
thinning, within the 20-million-selected-cell allocation limit.

The returned struct contains power, axes, timestamps, auxiliary values, masks,
state IDs and raw state headers. The simpler MATLAB reader validates physical
lengths and selected record links; use Python `inspect` for RPX index CRC checks.

## Python API

```python
from fieldfox_recording import FieldFoxRecording

rec = FieldFoxRecording.open('/path/to/session')
print(rec.metadata)
print(rec.frequency_hz)       # Common frequency axis, in Hz
print(rec.timestamps)         # ISO strings; instrument timezone is unknown
print(rec.power_dbm.shape)    # (sweeps, points), for a single trace
rec.to_csv('output/session.csv')
rec.to_npz('output/session.npz')

# Stream large sessions or handle changing settings one sweep at a time:
for sweep in rec:
    state = sweep.state
    axis = state.time_axis_s if state.span_hz == 0 else state.frequency_hz
    values = sweep.power_dbm_traces   # (trace_slots, points)
    extra = sweep.auxiliary_values   # Retained separately, meaning unassigned
```

The common-axis property raises if the axis changes during the session.
Zero-span sweeps expose a time axis in seconds. Convenience array properties
load their results into memory; iteration and CSV export use bounded record
reads. NPZ export uses temporary disk-backed power and auxiliary arrays;
timestamp and header metadata still use memory.

## Format summary

- Reconstructed GPSA versions 1–18 and single-block nonzero-span RTSA versions
  8–18; little-endian 104-byte state records. Metadata names GPSA or RTSA using
  the recording's application field.
- Trace records contain a 32-byte header before version 4, or a 44-byte header
  from version 4 onward, followed by float32 values. Dimensions come from the
  state header, including any auxiliary values.
- Supports nested stores such as `dSTA00000/00000000.STA` and
  `dTRC00000/00000000.TRC`, plus legacy flat `STA00000`/`TRC00000` stores.
- Recovers frequency axes, state changes, trace masks and exact .NET timestamps.
  Timestamps have 100 ns resolution and are local/unspecified, not established UTC.
- Uses the stored GPSA or supported RTSA spectrum values as dBm without an
  additional scaling factor, matching the recovered playback read path.
- Checks record sizes, IDs, state transitions and optional RPX index CRC-32
  checksums and record counts. Unknown fields are retained as raw data.

CSV is a long-form table with one row per point and trace slot, explicit units,
timestamps and state IDs. It differs from Data Link's presentation layout and
does not include auxiliary values or all raw header fields.

NPZ contains `power_dbm_traces`, `auxiliary_values`, `timestamp_ticks`,
`state_ids`, `trace_masks`, `axes_by_state`, `axis_kind_by_state`,
`trace_headers_json` and `metadata_json`. Load it with
`numpy.load(path, allow_pickle=False)`. Each sweep uses the axis selected by its
state ID. NPZ export needs temporary disk space near the uncompressed data size.

## Limits and validation

Multiple-block or zero-span RTSA, raw IQ/VITA-49 captures, saved RTSA XML traces,
density frames, DLS archives, unknown versions, incomplete
partition sequences and changing record dimensions are unsupported. GPS
coordinate scaling, auxiliary-value meanings and the mapping of trace slots to
physical trace numbers remain unassigned. There is no recovered checksum for
the trace samples, so sample corruption cannot always be detected.

The N9917B appears in the supplied software's recognized model lists, but the
decoder chooses layouts using recording headers. The model name does not prove
which recording version or capture mode a particular session uses.

Local tests covered version branches, endianness, timestamps, boundaries,
state changes, multiple trace slots, zero span, malformed inputs, index checks,
CSV/NPZ exports, section seeking, plot selection, PNG output and the shared
RTSA record layout. Further checks cover MAT round trips, exact UTC/EST clock
conversion, DST gaps/folds and an invisible Tkinter load/export workflow.
MATLAB tests compare the native reader and Python MAT files on the same
synthetic data. Tests and synthetic fixtures are not included in this
minimal publication. A complete finished N9917B GPSA or supported RTSA session
would enable local instrument validation; a matching CSV export would enable
independent numerical comparison.

This repository contains only the independent decoding scripts, package metadata
and this README. No Data Link binaries, decompiled code, recordings, sample
outputs or analysis artifacts are included.
